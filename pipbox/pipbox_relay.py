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

Fester Kern: UDP über Loopback hält die Reihenfolge nur, solange der sendende Thread auf demselben Kern bleibt (der Kernel reiht Pakete je Kern ein; wechselt der
Sender den Kern mitten in einem Bild, überholen spätere Pakete frühere). Gemessen am Jetson: Lücken in der Folgenummer von 1 bis 91 Paketen an allen Plätzen,
immer in fallenden Serien (49, 44, 40, 34 …), ohne dass der Kernel ein Paket verworfen hätte; danach "reference in DPB was never decoded" und ein Stillstand der
Kette. Deshalb laufen jede Weiche (hier) und jeder Zubringer (pipbox_always) auf einem festen Kern.

Verzögerung je Kamera: Der Benutzer kann jeder Kamera eine Wartezeit geben (Bild und Ton zusammen, zum Beispiel für eine Kamera mit längerer eigener Laufzeit). Die Weiche hält
dazu die Pakete der Kamera um diese Zeit zurück (set_delay) und gibt sie in derselben Reihenfolge frei; die Kette stempelt die Pakete beim Eintreffen (udpsrc do-timestamp),
so kommt die Kamera um die Wartezeit später im Bild an. Bis das erste verzögerte Bild ankommt, läuft das Füllbild weiter (der Platz ist nie leer).
"""
import collections
import os
import select
import socket
import threading
import time

ACTIVE_GAP = 0.7                  # so lange dürfen Bilder der Kamera ausbleiben, bevor das Tor schließt
SHOW_AFTER = 0.3                  # so lange muss das Tor offen sein, bevor die Kamera zu sehen sein darf
SILENCE_STEP = 1024 / 48000.0     # Dauer eines Tonpakets (1024 Abtastwerte bei 48 kHz)
SILENCE = bytes(1024 * 4)         # 1024 Abtastwerte, 2 Kanäle, 16 Bit
MAX_DELAY_S = 0.75                # größte Verzögerung je Kamera (wie im anderen Paket: pipbox_live.MAX_DELAY_MS)
SSRC = b"\x4a\x50\x49\x50"
RELAY_CPUS = (1, 2, 3)            # Kern je Platz (Platz mod 3); Kern 0 bleibt für Unterbrechungen und den Rest frei


def pin_cpu(cpu):
    """Den aufrufenden Thread (oder, in preexec_fn, den neuen Prozess) an einen Kern binden; still, wenn es den Kern nicht gibt."""
    try:
        os.sched_setaffinity(0, {int(cpu)})
    except (AttributeError, OSError, ValueError):
        pass


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
        self.started = False                  # das erste Bild der Kamera ist (nach einer Verzögerung) tatsächlich an der Kette angekommen
        self.delay_s = 0.0                    # Verzögerung dieser Kamera (Bild und Ton)
        self.q = collections.deque()          # zurückgehaltene Pakete: (Freigabezeit, Art "v"/"a", Daten)
        self.fill_seen = False                # seit dem letzten Zurücksetzen ist Füllbild angekommen (der Platz kann sofort Bilder liefern)
        self.params = []                      # zuletzt gesehene SPS/PPS-Pakete der Kamera
        self.last_cam = 0.0
        self.last_sil = clock()
        self.events = collections.deque(maxlen=40)    # (Uhrzeit, Text): Tor auf/zu, Füllbild, Zähler; für den Bericht bei einem unerwarteten Ende von belacoder
        self.pkts_v = self.pkts_fill = 0
        self.last_in = None                   # höchste Folgenummer des Zubringers bisher
        self.lost_in = 0                      # Pakete, die laut Folgenummer zwischen Zubringer und Weiche fehlen (Lücke nach vorn)
        self.late_in = 0                      # Pakete, die nach einer Lücke doch noch kamen (Reihenfolge vertauscht): so viele davon waren kein Verlust
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
        return self.gate and self.started and self.clock() - self.opened_at >= SHOW_AFTER

    def set_delay(self, ms):
        """Verzögerung der Kamera an diesem Platz in Millisekunden (0 bis 750). Eine Änderung hält den Strom um den Unterschied an (größer) oder gibt aufgestaute Pakete auf einmal frei (kleiner)."""
        try:
            d = max(0.0, min(MAX_DELAY_S, float(ms) / 1000.0))
        except (TypeError, ValueError):
            d = 0.0
        if abs(d - self.delay_s) > 0.0005:
            self.note("Verzögerung %d ms (vorher %d ms)" % (round(d * 1000), round(self.delay_s * 1000)))
            self.delay_s = d

    def reset(self):
        """Andere Kamera auf diesem Platz oder neuer Abnehmer (belacoder startet neu): das Tor schließt und das Füllbild läuft wieder, bis der nächste IDR der Kamera kommt.
        Ein neuer Abnehmer steigt sonst mitten im Keyframe-Abstand ein und sähe bis zum nächsten IDR nichts (gemessen: der Ausgang steht dann bis zu einem Keyframe-Abstand)."""
        self.gate = False
        self.params = []
        self.fill_done = False
        self.fill_seen = False
        self.started = False
        self.q.clear()
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

    def emit_v(self, pkt, now):
        self._emit("v", pkt, now)

    def emit_a(self, data, now):
        self._emit("a", data, now)

    def _emit(self, kind, data, now):
        """Paket der Kamera an die Kette: sofort, oder (Verzögerung) in die Warteschlange. Die Reihenfolge bleibt immer erhalten."""
        if self.delay_s <= 0 and not self.q:
            self._out(kind, data, now)
        else:
            due = now + self.delay_s
            if self.q and self.q[-1][0] > due:
                due = self.q[-1][0]               # eine kleinere Verzögerung überholt nie schon Wartende
            self.q.append((due, kind, data))

    def _out(self, kind, data, now):
        if kind == "v":
            if not self.started:                  # das erste Bild der Kamera erreicht die Kette: ab hier kein Füllbild mehr, und die Kamera gilt als zu sehen
                self.started, self.fill_done, self.opened_at = True, True, now
                self.note("Kamera an der Kette (Verzögerung %d ms)" % round(self.delay_s * 1000))
            self.send_v(data)
        else:
            self.send_a(data)

    def flush(self, now):
        while self.q and self.q[0][0] <= now:
            _, kind, data = self.q.popleft()
            self._out(kind, data, now)

    def on_video(self, pkt, now):
        self.last_cam = now
        if len(pkt) >= 4:                     # Folgenummer vom Zubringer: Lücke nach vorn = Pakete fehlen (oder kommen später), Nachzügler = Reihenfolge vertauscht
            seq = int.from_bytes(pkt[2:4], "big")
            if self.last_in is None:
                self.last_in = seq
            else:
                gap = (seq - self.last_in - 1) & 0xFFFF
                if gap == 0 or gap >= 1000 and gap < 0xFFFF - 1000:        # das nächste Paket, oder ein neuer Zubringer (eigene Nummern)
                    self.last_in = seq
                elif gap < 1000:
                    self.lost_in += gap
                    self.last_in = seq
                    if self.gate:
                        self.note("Lücke im Strom der Kamera: %d Pakete fehlen (Tor offen)" % gap)
                elif gap != 0xFFFF:                                        # älter als das letzte: ein Nachzügler (last_in bleibt die höchste Nummer)
                    self.late_in += 1
                    if self.gate:
                        self.note("Nachzügler: Paket %d Plätze zu spät (Tor offen)" % (0xFFFF - gap))
        kind = classify(pkt)
        if self.gate:
            self.emit_v(pkt, now)
        elif kind == "param":
            self.params = (self.params + [pkt])[-4:]
        elif kind == "idr":
            self.note("Tor offen (Keyframe der Kamera, %d SPS/PPS davor)" % len(self.params))
            self.gate, self.opened_at = True, now
            for p in self.params:
                self.emit_v(p, now)
            self.params = []
            self.emit_v(pkt, now)
        # sonst: Bild ohne seinen Keyframe, verwerfen

    def on_audio(self, data):
        if self.gate:
            self.emit_a(data, self.clock())

    def on_fill(self, pkt):
        if not self.fill_done:                # das Füllbild läuft, bis das erste Bild der Kamera (auch nach einer Verzögerung) an der Kette ankommt
            self.fill_seen = True
            self.send_v(pkt)

    def tick(self, now):
        self.flush(now)
        if self.gate and now - self.last_cam > ACTIVE_GAP:
            self.note("Tor zu (seit %.1f s keine Bilder der Kamera)" % (now - self.last_cam))
            self.gate = False                 # die Kamera liefert nichts mehr
            self.params = []
            self.last_in = None
            self.started = False              # kommt die Kamera zurück, zählt erst ihr erstes (verzögertes) Bild wieder als "zu sehen"
            self.q.clear()                    # Zurückgehaltenes einer Kamera, die weg ist, gibt es nicht mehr frei
        if not self.gate or not self.started:    # Stille im Takt eines Tonpakets, damit der audiomixer nie auf diesen Platz wartet (auch bis das erste verzögerte Bild da ist)
            if now - self.last_sil > 0.25:
                self.last_sil = now
            while now - self.last_sil >= SILENCE_STEP:
                self.send_a(SILENCE)
                self.last_sil += SILENCE_STEP
        else:
            self.last_sil = now

    def run(self):
        pin_cpu(RELAY_CPUS[self.slot % len(RELAY_CPUS)])
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
