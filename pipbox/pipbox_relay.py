"""Jetson: Weiche je Platz für "alle Kameras immer bereit".

Der Hardware-Decoder des Jetson (nvv4l2decoder) wirft Bilder eines neuen Streams weg ("Stream format not found"), bis ein vollständiger Keyframe (IDR) mit SPS/PPS
ankommt, und der Compositor liefert in dieser Zeit keinen Ausgang (gemessen: bis zur Länge eines Keyframe-Abstands, bei 8 Sekunden Abstand also 8 bis 13 Sekunden Stillstand
der ganzen Sendung). Deshalb liest die Kette nicht direkt vom Zubringer der Kamera, sondern von dieser Weiche:

  Füllbild (schwarz, nur am Anfang) ─┐
  Kamera-Zubringer (Bild, Ton) ──────┴─> Weiche ─> udpsrc der Sendekette (Bild und Ton)

Die Weiche gibt das Füllbild weiter, bis der erste IDR der Kamera ankommt, und schaltet genau dort auf die Kamera um (mit den zuletzt gesehenen SPS/PPS davor), sodass der
Decoder nie ein Bild ohne seinen Keyframe sieht. Bleiben die Bilder der Kamera länger als ACTIVE_GAP aus, schließt das Tor: es geht nichts mehr durch (der Platz ist dann in der
Kette ausgeblendet, der Compositor liefert weiter, gemessen), und beim Zurückkehren öffnet es wieder erst an einem IDR. Der Ton läuft nur bei offenem Tor von der Kamera, sonst
schickt die Weiche Stille, damit der audiomixer der Kette nie auf einen Platz wartet. Folgenummer und Quelle der RTP-Pakete werden neu gesetzt, damit der Strom für den
Depayloader lückenlos aussieht.
"""
import collections
import select
import socket
import threading
import time

ACTIVE_GAP = 0.7                  # so lange dürfen Bilder der Kamera ausbleiben, bevor das Tor schließt
SHOW_AFTER = 0.3                  # so lange muss das Tor offen sein, bevor die Kamera zu sehen sein darf
SILENCE_STEP = 1024 / 48000.0     # Dauer eines Tonpakets (1024 Abtastwerte bei 48 kHz)
SILENCE = bytes(1024 * 4)         # 1024 Abtastwerte, 2 Kanäle, 16 Bit
SSRC = b"\x4a\x50\x49\x50"


def classify(pkt):
    """RTP-Paket mit H.264: "param" (nur SPS/PPS), "idr" (Anfang eines IDR-Bildes oder aggregiert mit einem) oder "other"."""
    if len(pkt) < 14 or pkt[0] >> 6 != 2:
        return "other"
    off = 12 + 4 * (pkt[0] & 0x0F)
    if pkt[0] & 0x10:
        if len(pkt) < off + 4:
            return "other"
        off += 4 + 4 * int.from_bytes(pkt[off + 2:off + 4], "big")
    if len(pkt) <= off:
        return "other"
    t = pkt[off] & 0x1F
    if t in (7, 8):
        return "param"
    if t == 5:
        return "idr"
    if t == 24:                                   # STAP-A: mehrere kleine NAL-Einheiten in einem Paket
        i, kinds = off + 1, set()
        while i + 3 <= len(pkt):
            n = int.from_bytes(pkt[i:i + 2], "big")
            if n == 0 or i + 2 >= len(pkt):
                break
            kinds.add(pkt[i + 2] & 0x1F)
            i += 2 + n
        if 5 in kinds:
            return "idr"
        return "param" if kinds and kinds <= {7, 8} else "other"
    if t == 28 and len(pkt) > off + 1:            # FU-A: Bild in Teilen; nur das erste Teil (Startbit) eines IDR zählt
        fu = pkt[off + 1]
        if fu & 0x80 and fu & 0x1F == 5:
            return "idr"
    return "other"


class SlotRelay(threading.Thread):
    def __init__(self, slot, out_v, out_a, in_v, in_a, in_f, clock=time.monotonic):
        super().__init__(daemon=True, name=f"relay{slot}")
        self.slot, self.out_v, self.out_a, self.clock = slot, out_v, out_a, clock
        self.stop_ev = threading.Event()
        self.gate = False
        self.opened_at = 0.0
        self.fill_done = False                # die Kamera war schon einmal zu sehen: das Füllbild wird nicht mehr gebraucht
        self.fill_seen = False                # seit dem letzten Zurücksetzen ist Füllbild angekommen (der Platz kann sofort Bilder liefern)
        self.params = []                      # zuletzt gesehene SPS/PPS-Pakete der Kamera
        self.last_cam = 0.0
        self.last_sil = clock()
        self.events = collections.deque(maxlen=40)    # (Uhrzeit, Text): Tor auf/zu, Füllbild, Zähler; für den Bericht bei einem unerwarteten Ende von belacoder
        self.pkts_v = self.pkts_fill = 0
        self.last_in = None                   # letzte Folgenummer des Zubringers
        self.lost_in = 0                      # Pakete, die laut Folgenummer zwischen Zubringer und Weiche fehlen
        self.seq = 0
        self.socks = {}
        for name, port in (("v", in_v), ("a", in_a), ("f", in_f)):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            s.bind(("127.0.0.1", port))
            self.socks[name] = s
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # --- Zustand ---------------------------------------------------------------------------------------------------------------------------
    def shown(self):
        return self.gate and self.clock() - self.opened_at >= SHOW_AFTER

    def reset(self):
        """Andere Kamera auf diesem Platz oder neuer Abnehmer (belacoder startet neu): das Tor schließt und das Füllbild läuft wieder, bis der nächste IDR der Kamera kommt.
        Ein neuer Abnehmer steigt sonst mitten im Keyframe-Abstand ein und sähe bis zum nächsten IDR nichts (gemessen: der Ausgang steht dann bis zu einem Keyframe-Abstand)."""
        self.gate = False
        self.params = []
        self.fill_done = False
        self.fill_seen = False
        self.note("zurückgesetzt (Tor zu, Füllbild wieder an)")

    def stop(self):
        self.stop_ev.set()

    def note(self, text):
        self.events.append("%s %s" % (time.strftime("%H:%M:%S", time.gmtime()), text))

    # --- Weitergabe ------------------------------------------------------------------------------------------------------------------------
    def send_v(self, pkt):
        self.seq = (self.seq + 1) & 0xFFFF
        try:
            self.out.sendto(pkt[:2] + self.seq.to_bytes(2, "big") + pkt[4:8] + SSRC + pkt[12:], ("127.0.0.1", self.out_v))
        except OSError:
            pass

    def send_a(self, data):
        try:
            self.out.sendto(data, ("127.0.0.1", self.out_a))
        except OSError:
            pass

    def on_video(self, pkt, now):
        self.last_cam = now
        if len(pkt) >= 4:                     # Lücken in der Folgenummer vom Zubringer: Pakete, die vor der Weiche verloren gingen
            seq = int.from_bytes(pkt[2:4], "big")
            if self.last_in is not None:
                gap = (seq - self.last_in - 1) & 0xFFFF
                if 0 < gap < 1000:
                    self.lost_in += gap
                    if self.gate:
                        self.note("Lücke im Strom der Kamera: %d Pakete fehlen (Tor offen)" % gap)
            self.last_in = seq
        kind = classify(pkt)
        if self.gate:
            self.send_v(pkt)
        elif kind == "param":
            self.params = (self.params + [pkt])[-4:]
        elif kind == "idr":
            self.note("Tor offen (Keyframe der Kamera, %d SPS/PPS davor)" % len(self.params))
            self.gate, self.opened_at, self.fill_done = True, now, True
            for p in self.params:
                self.send_v(p)
            self.params = []
            self.send_v(pkt)
        # sonst: Bild ohne seinen Keyframe, verwerfen

    def on_audio(self, data):
        if self.gate:
            self.send_a(data)

    def on_fill(self, pkt):
        if not self.fill_done and not self.gate:
            self.fill_seen = True
            self.send_v(pkt)

    def tick(self, now):
        if self.gate and now - self.last_cam > ACTIVE_GAP:
            self.note("Tor zu (seit %.1f s keine Bilder der Kamera)" % (now - self.last_cam))
            self.gate = False                 # die Kamera liefert nichts mehr
            self.params = []
            self.last_in = None
        if not self.gate:                     # Stille im Takt eines Tonpakets, damit der audiomixer nie auf diesen Platz wartet
            if now - self.last_sil > 0.25:
                self.last_sil = now
            while now - self.last_sil >= SILENCE_STEP:
                self.send_a(SILENCE)
                self.last_sil += SILENCE_STEP
        else:
            self.last_sil = now

    def run(self):
        socks = list(self.socks.values())
        while not self.stop_ev.is_set():
            try:
                ready, _, _ = select.select(socks, [], [], 0.01)
            except (OSError, ValueError):
                break
            now = self.clock()
            for s in ready:
                try:
                    data = s.recv(65536)
                except OSError:
                    continue
                if s is self.socks["v"]:
                    self.on_video(data, now)
                elif s is self.socks["a"]:
                    self.on_audio(data)
                else:
                    self.on_fill(data)
            self.tick(now)
        for s in list(self.socks.values()) + [self.out]:
            try:
                s.close()
            except OSError:
                pass
