"""Modus "alle Kameras immer bereit" (Issue #19, Anregung von Bittersweet1987): Zubringer und Auswahl der Kameras.

Die Sendekette hat in diesem Modus je Kamera-Platz (0 bis 3) zwei Eingänge, die nie ausfallen: udpsrc auf Loopback (Bild: H.264 über RTP, Ton: PCM). Ein
Zubringer-Prozess je Platz holt den Stream der Kamera aus dem RTMP-Server der Box und reicht ihn dorthin weiter. Sendet die Kamera nicht (noch nicht, nicht
mehr), endet der Zubringer sofort ("Failed to read any data from stream") und wird nach einer Sekunde neu gestartet. Die Kette bekommt davon nichts mit; der
Baustein pbpipsel hält den Ausgang mit schwarzen Bildern und Stille am Leben, bis wieder echte Daten kommen.

Dieses Modul enthält nur Logik ohne Zugriff auf die Sendekette: den Befehl des Zubringers, die Zuordnung der Kamera-Schlüssel zu den Plätzen, die Wahl
von Hauptbild und kleinen Bildern bei Ausfall und Rückkehr (Auswahl) und die Verwaltung der Prozesse (Zubringer). pipbox_send.py ruft es auf.
"""
import os
import re
import signal
import subprocess
import threading
import time

FEED_PORT = 9410            # wie server.FEED_PORT (Bild: FEED_PORT + 2*Platz, Ton: +1)
SLOTS = 4
RESTART_S = 1.0             # so lange wartet ein Zubringer nach seinem Ende, bevor er den Stream neu holt
BACK_S = 3.0                # so lange muss die eigentliche Hauptkamera wieder Bilder liefern, bevor sie die Ersatz-Hauptkamera ablöst
KEY_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


PRIV_PORT = 9440            # Jetson: private Eingänge der Weiche (pipbox_relay.py) je Platz: PRIV_PORT + 3*Platz Bild der Kamera, +1 Ton der Kamera, +2 Füllbild
FEED_CPUS = (1, 2, 3)       # Kern je Platz (Platz mod 3) für Zubringer und Füllbild: nur ein Sender mit festem Kern hält auf Loopback die Reihenfolge (siehe pipbox_relay)


def pipbox_relay_pin(cpu):
    import pipbox_relay
    pipbox_relay.pin_cpu(cpu)


def priv_ports(slot):
    return PRIV_PORT + 3 * slot, PRIV_PORT + 3 * slot + 1, PRIV_PORT + 3 * slot + 2


def feeder_cmd(key, slot, rtmp_port=1935, rtmp_app="publish", gst="gst-launch-1.0", ports=None):
    """Befehl (Liste) eines Zubringers. Der Schlüssel muss geprüft sein (a-z, 0-9, -, _); er geht nie über eine Shell.

    Bild: Stream unverändert (kein Umkodieren), SPS/PPS jede Sekunde mitgeschickt, damit eine neu startende Kette sofort einsteigt.
    Ton: AAC wird hier zu PCM 48 kHz Stereo gewandelt, weil die AAC-Einstellungen je Kamera und Neuverbindung wechseln können; die RTP-Kopfdaten der Sendekette
    wären dann falsch ("not-negotiated", gemessen). Die Zeitstempel setzt die Kette selbst beim Eintreffen (udpsrc do-timestamp)."""
    if not KEY_RE.match(key or "") or not 0 <= slot < SLOTS:
        raise ValueError("Schlüssel oder Platz ungültig")
    vp, ap = ports if ports else (FEED_PORT + 2 * slot, FEED_PORT + 2 * slot + 1)
    chain = (f"rtmpsrc location=rtmp://127.0.0.1:{int(rtmp_port)}/{rtmp_app}/{key} do-timestamp=true ! flvdemux name=d "
             f"d.video ! queue max-size-time=2000000000 max-size-buffers=0 max-size-bytes=0 ! h264parse config-interval=-1 ! "
             f"rtph264pay config-interval=1 pt=96 ! udpsink host=127.0.0.1 port={vp} sync=false "
             f"d.audio ! queue max-size-time=2000000000 max-size-buffers=0 max-size-bytes=0 ! aacparse ! avdec_aac ! audioconvert ! audioresample ! "
             f"audio/x-raw,format=S16LE,rate=48000,channels=2,layout=interleaved ! audiobuffersplit output-buffer-duration=1024/48000 ! "
             f"udpsink host=127.0.0.1 port={ap} sync=false")
    return [gst, "-q"] + chain.split()


class Binder:
    """Ordnet Kamera-Schlüsseln Plätze zu. Ein Schlüssel behält seinen Platz, solange er gewünscht ist; neue Schlüssel bekommen einen freien Platz.
    So bleibt beim Tausch oder Entfernen einer Kamera der Zubringer der übrigen unverändert."""

    def __init__(self, n=SLOTS):
        self.slot_key = [""] * n

    def update(self, wanted):
        """wanted: gewünschte Schlüssel (ohne Leere). Gibt True zurück, wenn sich etwas geändert hat."""
        want = []
        for k in wanted:
            if k and k not in want:
                want.append(k)
        before = list(self.slot_key)
        for i, k in enumerate(self.slot_key):
            if k and k not in want:
                self.slot_key[i] = ""
        for k in want:
            if k not in self.slot_key:
                free = next((i for i, v in enumerate(self.slot_key) if not v), None)
                if free is None:
                    break                                    # mehr Kameras als Plätze: die übrigen bleiben ohne Platz
                self.slot_key[free] = k
        return before != self.slot_key

    def slot_of(self, key):
        return self.slot_key.index(key) if key in self.slot_key else None


class Chooser:
    """Wählt aus der Einstellung (wer soll Hauptbild und kleine Bilder sein) und den Kameras mit Bild die Belegung der Sendekette.

    Ist die eingestellte Hauptkamera nicht da, wird die erste vorhandene Kamera der kleinen Bilder (in der Reihenfolge der Einstellung) Hauptbild; deaktivierte
    Kameras springen nicht ein (Issue #19). Deren eigener Platz bleibt dann leer, damit sie nicht doppelt zu sehen ist. Kommt die eingestellte Hauptkamera zurück,
    übernimmt sie nach BACK_S wieder. Kleine Bilder werden immer an ihrem Platz gezeigt: die Kamera erscheint, sobald ihre Bilder ankommen (der Mischer blendet
    ein Bild ohne frische Bilder aus), es braucht dafür keinen Befehl."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.alive_since = {}                # Schlüssel -> seit wann er ununterbrochen Bilder liefert
        self.main_key = None                 # wer zuletzt als Hauptbild gewählt war
        self.desired_main = None             # und wer es laut Einstellung sein sollte

    def line(self, desired, slot_of, alive, inactive=(), now=None):
        """desired: Schlüssel an Hauptbild, kleines Bild 1 bis 3 ("" = keiner). slot_of: Schlüssel -> Platz. alive: Schlüssel mit Bild.
        Gibt (Zeile "H K1 K2 K3" mit Plätzen, 15 = keine, Schlüssel des Hauptbildes) zurück."""
        now = self.clock() if now is None else now
        for k in list(self.alive_since):
            if k not in alive:
                del self.alive_since[k]
        for k in alive:
            self.alive_since.setdefault(k, now)
        want = list(desired) + [""] * (4 - len(desired))
        main = want[0]
        if main and main not in alive:
            sub = next((k for k in want[1:] if k and k in alive and k not in set(inactive)), None)
            main = sub or main
        elif (main and main == self.desired_main and self.main_key not in (None, main) and self.main_key in alive
              and now - self.alive_since.get(main, now) < BACK_S):
            main = self.main_key                          # die eigentliche Hauptkamera ist erst kurz zurück: die Ersatzkamera bleibt noch
        self.desired_main = want[0]                       # (wurde die Hauptkamera in der Einstellung gewechselt, gilt der Wunsch sofort)
        self.main_key = main
        vals = [slot_of.get(main, 0) if main in slot_of else 0]
        for k in want[1:]:
            vals.append(15 if (not k or k == main or k not in slot_of) else slot_of[k])
        return " ".join(str(v) for v in vals), main


def alive_from_file(path, slot_key):
    """Schlüssel der Kameras mit Bild aus der Datei von pbctl ("1 0 1 0", ein Wert je Platz). None, wenn die Datei fehlt oder nicht lesbar ist."""
    try:
        with open(path) as f:
            flags = f.read().split()
    except OSError:
        return None
    if len(flags) != SLOTS or any(x not in ("0", "1") for x in flags):
        return None
    return {slot_key[i] for i, x in enumerate(flags) if x == "1" and slot_key[i]}


class Feeders:
    """Ein Zubringer je belegtem Platz. Jeder läuft in einem eigenen Faden, startet bei Ende neu und wird mit dem Platz beendet."""

    def __init__(self, rtmp_port=1935, rtmp_app="publish", log=print, popen=subprocess.Popen, clock=time.monotonic, killpg=os.killpg):
        self.rtmp_port, self.rtmp_app, self.log, self.popen, self.clock, self.killpg = rtmp_port, rtmp_app, log, popen, clock, killpg
        self.lock = threading.Lock()
        self.running = {}                    # Platz -> {"key", "stop", "thread", "proc"}
        self.starts = {i: 0 for i in range(SLOTS)}

    def set_keys(self, slot_key):
        """Zubringer an die Belegung anpassen: neue Schlüssel starten, geänderte neu starten, nicht mehr belegte beenden."""
        with self.lock:
            for slot in range(SLOTS):
                key = slot_key[slot] if slot < len(slot_key) else ""
                cur = self.running.get(slot)
                if cur and cur["key"] == key:
                    continue
                if cur:
                    self._stop_locked(slot)
                if key:
                    self._start_locked(slot, key)

    def _start_locked(self, slot, key):
        st = {"key": key, "stop": threading.Event(), "proc": None}
        st["thread"] = threading.Thread(target=self._loop, args=(slot, st), daemon=True, name=f"feeder{slot}")
        self.running[slot] = st
        st["thread"].start()

    def _stop_locked(self, slot):
        st = self.running.pop(slot, None)
        if not st:
            return
        st["stop"].set()
        self._kill(st.get("proc"))

    def _kill(self, p):
        if p is None or p.poll() is not None:
            return
        try:
            self.killpg(p.pid, signal.SIGTERM)                  # die ganze Gruppe (der Zubringer startet eigene Fäden, kein Kindprozess bleibt zurück)
        except OSError:
            try:
                p.terminate()
            except OSError:
                pass

    def _loop(self, slot, st):
        key = st["key"]
        while not st["stop"].is_set():
            try:
                cmd = feeder_cmd(key, slot, self.rtmp_port, self.rtmp_app)
                p = self.popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except (OSError, ValueError) as e:
                if st.get("warned") != type(e).__name__:          # einmal melden statt alle 5 s
                    st["warned"] = type(e).__name__
                    self.log(f"send: Zubringer {slot} nicht startbar ({type(e).__name__}"
                             + (": gst-launch-1.0 fehlt, Paket gstreamer1.0-tools)" if isinstance(e, FileNotFoundError) else ")"))
                if st["stop"].wait(5):
                    return
                continue
            st["proc"] = p
            self.starts[slot] += 1
            while p.poll() is None and not st["stop"].is_set():
                time.sleep(0.2)
            if st["stop"].is_set():
                self._kill(p)
                return
            st["stop"].wait(RESTART_S)                      # beendet (kein Stream da oder er ist zu Ende): in einer Sekunde neu holen

    def stop_all(self):
        with self.lock:
            for slot in list(self.running):
                self._stop_locked(slot)


FILL_SIZE = (1920, 1080)    # Größe des Füllbildes: gleich der üblichen Kamera, damit der Decoder beim Umschalten nicht die Größe wechseln muss


def fill_cmd(slot, gst="gst-launch-1.0", size=None):
    """Jetson: Füllbild für einen Platz, solange seine Kamera noch nicht da war. Ein schwarzer H.264-Stream (30 Bilder/s, alle halbe Sekunde ein IDR mit SPS/PPS: ohne idrinterval sendet der Encoder nur alle 256 Bilder einen, ein später einsteigender Decoder wartete bis zu 8,5 s; wenig Datenrate) geht an den
    Füll-Eingang der Weiche. So hat der Compositor an jedem Platz von Anfang an Bilder (ohne sie liefert nvcompositor beim Start keinen Ausgang, gemessen)."""
    if not 0 <= slot < SLOTS:
        raise ValueError("Platz ungültig")
    w, h = size or FILL_SIZE
    fp = priv_ports(slot)[2]
    chain = (f"videotestsrc is-live=true pattern=black ! video/x-raw,width={int(w)},height={int(h)},framerate=30/1 ! nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! "
             "nvv4l2h264enc bitrate=300000 iframeinterval=15 idrinterval=15 insert-sps-pps=true ! h264parse config-interval=-1 ! "
             f"rtph264pay config-interval=1 pt=96 ! udpsink host=127.0.0.1 port={fp} sync=false")
    return [gst, "-q"] + chain.split()


class JetsonFeeders:
    """Zubringer für den Jetson. Je Platz: eine Weiche (pipbox_relay.SlotRelay), die den Eingang der Kette speist, ein Zubringer der Kamera (läuft, solange sie am RTMP-Server
    sendet) und das Füllbild (läuft, bis die Kamera zum ersten Mal einen Keyframe geliefert hat). live_fn liefert die Schlüssel der sendenden Kameras (oder None, wenn unbekannt:
    dann wird die Kamera einfach versucht)."""

    def __init__(self, live_fn=lambda: None, rtmp_port=1935, rtmp_app="publish", log=print, popen=subprocess.Popen, clock=time.monotonic, killpg=os.killpg,
                 relay_factory=None):
        self.live_fn, self.rtmp_port, self.rtmp_app, self.log = live_fn, rtmp_port, rtmp_app, log
        self.popen, self.clock, self.killpg = popen, clock, killpg
        self.relay_factory = relay_factory or self._default_relay
        self.lock = threading.Lock()
        self.relays = {}
        self.running = {}                    # Platz -> {"key", "stop", "threads", "procs"}
        self.starts = {i: 0 for i in range(SLOTS)}

    @staticmethod
    def _default_relay(slot):
        import pipbox_relay
        pv, pa, pf = priv_ports(slot)
        return pipbox_relay.SlotRelay(slot, FEED_PORT + 2 * slot, FEED_PORT + 2 * slot + 1, pv, pa, pf)

    # --- Zustand für Anzeige und Steuerung ------------------------------------------------------------------------------------------------
    def shown(self, slot):
        r = self.relays.get(slot)
        return bool(r and r.shown())

    @property
    def modes(self):
        return {s: ("kamera" if r.gate else "fuell") for s, r in self.relays.items()}

    # --- Verwaltung ------------------------------------------------------------------------------------------------------------------------
    def set_keys(self, slot_key):
        with self.lock:
            for slot in range(SLOTS):
                key = slot_key[slot] if slot < len(slot_key) else ""
                cur = self.running.get(slot)
                if cur and cur["key"] == key:
                    continue
                if cur:
                    self._stop_locked(slot)
                if key:
                    self._start_locked(slot, key)

    def _start_locked(self, slot, key):
        relay = self.relays.get(slot)
        if relay is None:
            relay = self.relays[slot] = self.relay_factory(slot)
            relay.start()
        else:
            relay.reset()                    # andere Kamera: ihr erster Keyframe öffnet das Tor
        st = {"key": key, "stop": threading.Event(), "procs": {}}
        st["threads"] = [threading.Thread(target=self._cam_loop, args=(slot, st, relay), daemon=True, name=f"cam{slot}"),
                         threading.Thread(target=self._fill_loop, args=(slot, st, relay), daemon=True, name=f"fill{slot}")]
        self.running[slot] = st
        for t in st["threads"]:
            t.start()

    def _stop_locked(self, slot):
        st = self.running.pop(slot, None)
        if not st:
            return
        st["stop"].set()
        for p in list(st["procs"].values()):
            self._kill(p)

    def _kill(self, p):
        if p is None or p.poll() is not None:
            return
        try:
            self.killpg(p.pid, signal.SIGTERM)
        except OSError:
            try:
                p.terminate()
            except OSError:
                pass

    def _spawn(self, st, name, cmd, cpu=None):
        """Zubringer oder Füllbild starten, auf Wunsch an einen Kern gebunden (cpu): UDP über Loopback hält die Reihenfolge nur bei festem Kern des Senders (siehe pipbox_relay)."""
        kw = {}
        if cpu is not None and hasattr(os, "sched_setaffinity"):
            kw["preexec_fn"] = lambda: pipbox_relay_pin(cpu)
        try:
            p = self.popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, **kw)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            if st.get("warned") != type(e).__name__:
                st["warned"] = type(e).__name__
                self.log(f"send: Zubringer nicht startbar ({type(e).__name__})")
            return None
        st["procs"][name] = p
        return p

    def _cam_loop(self, slot, st, relay):
        key = st["key"]
        while not st["stop"].is_set():
            live = self.live_fn()
            if live is not None and key not in live:
                st["stop"].wait(0.5)         # die Kamera sendet nicht: nichts zu holen
                continue
            pv, pa, _pf = priv_ports(slot)
            p = self._spawn(st, "cam", feeder_cmd(key, slot, self.rtmp_port, self.rtmp_app, ports=(pv, pa)), cpu=FEED_CPUS[slot % len(FEED_CPUS)])
            if p is None:
                if st["stop"].wait(5):
                    return
                continue
            self.starts[slot] += 1
            gone = None
            while p.poll() is None and not st["stop"].is_set():
                time.sleep(0.2)
                now = self.live_fn()
                if now is not None and key not in now:
                    gone = gone or self.clock()
                    if self.clock() - gone > 1.0:
                        self._kill(p)        # die Kamera ist weg, der Zubringer endet sonst erst später
                else:
                    gone = None
            if st["stop"].is_set():
                self._kill(p)
                return
            st["stop"].wait(0.5)

    def _fill_loop(self, slot, st, relay):
        while not st["stop"].is_set() and not relay.fill_done:
            p = self._spawn(st, "fill", fill_cmd(slot), cpu=FEED_CPUS[slot % len(FEED_CPUS)])
            if p is None:
                if st["stop"].wait(5):
                    return
                continue
            while p.poll() is None and not st["stop"].is_set() and not relay.fill_done:
                time.sleep(0.2)
            self._kill(p)
            if st["stop"].wait(0.3):
                return

    def wait_ready(self, timeout=12.0):
        """Wartet, bis an jedem Platz Füllbild (oder die Kamera) ankommt. belacoder verbindet sich zum Server und wird dort nach wenigen Sekunden ohne Mediendaten
        hinausgeworfen (der Empfänger meldet "never_received_data, first_data_timeout=14000ms"); startet er erst, wenn die Plätze Bilder liefern, kommen sie gleich nach dem Verbinden."""
        end = self.clock() + timeout
        while self.clock() < end:
            with self.lock:
                pending = [s for s, r in self.relays.items() if s in self.running and not (r.fill_seen or r.gate)]
            if not pending:
                return True
            time.sleep(0.1)
        return False

    def set_delays(self, ms_by_slot):
        """Verzögerung je Platz (Millisekunden, Liste in der Reihenfolge der Plätze) an die Weichen geben; sie gilt der Kamera, die gerade an dem Platz hängt."""
        with self.lock:
            for slot, r in self.relays.items():
                r.set_delay(ms_by_slot[slot] if slot < len(ms_by_slot) else 0)

    def relay_report(self):
        """Zustand und Ereignisse der Weichen für den Bericht bei einem unerwarteten Ende von belacoder: je Platz Tor, Füllbild und die letzten Ereignisse (nur Plätze und Uhrzeiten)."""
        out = []
        for slot, r in sorted(self.relays.items()):
            out.append("Platz %d: Tor %s, Füllbild %s, Verzögerung %d ms, Lücken vor der Weiche %d Pakete, davon Nachzügler %d, Zubringer-Starts %d" % (
                slot, "offen" if r.gate else "zu", "beendet" if r.fill_done else "läuft", round(r.delay_s * 1000), r.lost_in, r.late_in, self.starts.get(slot, 0)))
            out += ["    " + e for e in list(r.events)[-8:]]
        return out

    def rearm(self):
        """belacoder startet neu: Weichen zurücksetzen und das Füllbild wieder starten, damit der neue Abnehmer sofort Bilder samt Keyframe bekommt."""
        with self.lock:
            for slot, st in self.running.items():
                relay = self.relays.get(slot)
                if relay is None:
                    continue
                relay.reset()
                if not st["threads"][1].is_alive():          # das Füllbild war beendet: wieder starten (die Zubringer der Kameras laufen weiter)
                    t = threading.Thread(target=self._fill_loop, args=(slot, st, relay), daemon=True, name=f"fill{slot}")
                    st["threads"][1] = t
                    t.start()

    def stop_all(self):
        with self.lock:
            for slot in list(self.running):
                self._stop_locked(slot)
            for r in self.relays.values():
                r.stop()
            self.relays = {}


class Controller:
    """Hält die Zubringer und die Belegung der Sendekette im Betrieb auf dem Stand der Einstellung und der Kameras mit Bild.

    tick() wird etwa alle 0,5 s gerufen: liest pipeline.json (bei Änderung), ordnet Kameras den Plätzen zu (Zubringer anpassen, Verzögerungsdatei schreiben),
    liest die Datei von pbctl (welche Plätze liefern Bilder), wählt die Belegung (Chooser) und schreibt bei Änderung die Umschaltzeile (select-file)."""

    def __init__(self, load_json, put_state_file, delay_values, cam_live_path, select_name, delay_name, feeders, log=print, clock=time.monotonic):
        self.load_json, self.put, self.delay_values = load_json, put_state_file, delay_values
        self.cam_live_path, self.select_name, self.delay_name = cam_live_path, select_name, delay_name
        self.feeders, self.log, self.clock = feeders, log, clock
        self.binder = Binder()
        self.chooser = Chooser(clock)
        self.cfg = {}
        self.desired = ["", "", "", ""]
        self.inactive = []
        self.last_line = None
        self.main_key = None
        self.alive = set()
        self.live_known = False
        self.last_cfg_sig = None

    @staticmethod
    def keys_of(cfg):
        out = []
        for k in ("main", "pip", "pip2", "pip3"):
            v = cfg.get(k, "") if cfg.get("type") == "pip" or k == "main" else ""
            out.append(v if isinstance(v, str) and KEY_RE.match(v) else "")
        return out

    def reload(self, cfg=None):
        """Einstellung lesen (oder übernehmen) und Plätze zuordnen. Gibt True zurück, wenn sich die Belegung der Plätze geändert hat."""
        cfg = cfg if cfg is not None else self.load_json("pipeline.json")
        sig = repr(sorted((k, repr(v)) for k, v in cfg.items()))
        if sig == self.last_cfg_sig:
            return False
        self.last_cfg_sig = sig
        self.cfg = cfg
        self.desired = self.keys_of(cfg)
        ina = cfg.get("inactive")
        self.inactive = [k for k in ina if isinstance(k, str)] if isinstance(ina, list) else []
        changed = self.binder.update([k for k in self.desired if k])
        if changed:
            self.feeders.set_keys(self.binder.slot_key)
        vals = self.delay_values(cfg, [k or None for k in self.binder.slot_key])
        try:
            self.put(self.delay_name, " ".join(map(str, vals)) + "\n")
        except OSError:
            pass
        return changed

    def start(self):
        self.reload()
        self.feeders.set_keys(self.binder.slot_key)

    def tick(self):
        """Ein Durchgang. Gibt den Zustand für die Anzeige zurück: {"slots", "alive", "main", "line"}."""
        self.reload()
        alive = alive_from_file(self.cam_live_path, self.binder.slot_key)
        if alive is not None:
            self.alive, self.live_known = alive, True
        if self.live_known:
            slot_of = {k: i for i, k in enumerate(self.binder.slot_key) if k}
            line, main = self.chooser.line(self.desired, slot_of, self.alive, self.inactive)
            if line != self.last_line:
                if main != self.main_key and self.main_key is not None:
                    self.log(f"send: Hauptbild jetzt {main} (eingestellt: {self.desired[0]})")
                self.main_key = main
                try:
                    self.put(self.select_name, line + "\n")
                    self.last_line = line
                except OSError:
                    pass
        return {"slots": list(self.binder.slot_key), "alive": sorted(self.alive), "main": self.main_key, "line": self.last_line}

    def stop(self):
        self.feeders.stop_all()


class SlotController:
    """Jetson: "alle Kameras immer bereit". Die Kette (srv/pipeline_jetson.py build_always) hat je Platz (Pad des Compositors, Decoder) einen Eingang von udpsrc, der Strom kommt
    über die Weiche (pipbox_relay.py) von einem Zubringer. WICHTIG: Ein Decoder, der schon läuft, verkraftet den Strom einer anderen Kamera nicht (gemessen: "reference in DPB was
    never decoded", dann steht der Ausgang und belacoder startet neu, auch bei gleicher Auflösung). Darum behält jede Kamera ihren Platz, und ein Tausch ändert nur, WO ihr
    Bild zu sehen ist: Lage, Größe und Ebene der Pads und die Lautstärke der Tonquellen über die Steuerdatei von belacoder (belacoder-padctl.patch). Nur eine Kamera, die neu
    dazukommt (ein Platz bekommt eine andere Kamera), braucht einen Neustart von belacoder (Anzeige "restart" in tick(), der Sende-Dienst startet dann neu).

    Rollen (Hauptbild, kleine Bilder 1 bis 3) kommen aus der Einstellung. Wer in welcher Rolle zu sehen ist, entscheidet wie beim anderen Projekt der Chooser: Fällt die Hauptkamera
    aus, wird die erste vorhandene Kamera der kleinen Bilder Hauptbild (nicht deaktivierte, in der Reihenfolge der Einstellung), ihr kleiner Platz bleibt leer; die Hauptkamera
    übernimmt nach BACK_S wieder. Kleine Bilder ohne Kamera sind unsichtbar (kein schwarzes Viereck), das Hauptbild ist ohne Kamera schwarz. Der Ton folgt dem Hauptbild, wenn
    "Ton von: Hauptbild" gewählt ist."""

    GRACE = 15.0                              # so lange gilt eine sendende Kamera, die noch auf ihren Keyframe wartet, als vorhanden (kein Hauptbild-Wechsel beim Start)
    CANVAS = (0, 0, 1920, 1080)

    def __init__(self, load_json, live_keys, feeders, log=print, padctl_path=None, clock=time.monotonic, geometry_fn=None,
                 view_file=None, view_state=None, view_values=None, crop_fn=None, delay_fn=None):
        self.load_json, self.live_keys, self.feeders, self.log = load_json, live_keys, feeders, log
        self.padctl_path, self.clock, self.geometry_fn = padctl_path, clock, geometry_fn
        self.delay_fn = delay_fn              # (Einstellung, Schlüssel je Platz) -> Verzögerung in ms je Platz; sie gehört zur Kamera, nicht zur Rolle (PipelineStore.delay_values)
        self.crop_fn = crop_fn                # (Schlüssel, Beschnitt) -> Kanten für den nvvidconv des Platzes (pipeline_jetson.crop_edges); None: kein Beschnitt
        self.padctl_last = None
        # Ansicht im Betrieb wie beim Rockchip-Baustein: die Oberfläche schreibt "ausgeblendet Tonquelle stumm" in view_file und wartet, bis dieselbe Zeile in
        # view_state zurückgemeldet ist; sonst startet sie die Sendung neu. Hier gehen alle drei über die Steuerdatei (alpha und volume der Pads).
        self.view_file, self.view_state, self.view_values = view_file, view_state, view_values
        self.view = None                      # (ausgeblendet: Bits für kleines Bild 1..3, Tonquelle: -1 Hauptbild oder 0..2, stumm) aus view_file
        self.view_line_last = None
        self.binder = Binder()                # slot_key: welche Kamera an welchem Platz (Decoder) hängt
        self.chooser = Chooser(clock)
        self.cfg = {}
        self.roles = ["", "", "", ""]         # Hauptbild und kleine Bilder laut Einstellung
        self.last_cfg_sig = None
        self.alive = set()
        self.shown = set()                    # Kameras, deren Bilder durch die Weiche laufen und die zu sehen sein dürfen
        self._wait = {}                       # Schlüssel -> seit wann die Kamera sendet, aber noch nicht zu sehen ist
        self.main_key = None
        self.restart_needed = False
        self.live_set = None                  # Schlüssel aller Kameras am RTMP-Server (None = unbekannt); die Zubringer lesen es
        if isinstance(feeders, JetsonFeeders):
            feeders.live_fn = lambda: self.live_set

    def _pads(self):
        """{Rolle: Lage} aus der Einstellung (pipeline_jetson.role_layout): "pic" (x, y, Breite, Höhe), "crop", "frame", "frame_pad", "frame_name", "color", "frame_alpha".
        Eine alte Form mit (x, y, Breite, Höhe) je Rolle wird angenommen (Tests)."""
        geo = self.geometry_fn(self.cfg) if self.geometry_fn else {}
        return {r: (v if isinstance(v, dict) else {"pic": tuple(v), "crop": (0, 0, 0, 0), "frame": None, "frame_pad": None, "frame_name": None, "color": 0, "frame_alpha": 0.0})
                for r, v in geo.items()}

    def reload(self):
        cfg = self.load_json("pipeline.json")
        sig = repr(sorted((k, repr(v)) for k, v in cfg.items()))
        if sig == self.last_cfg_sig:
            return False
        self.last_cfg_sig = sig
        self.cfg = cfg
        self.roles = Controller.keys_of(cfg)
        npads = len(self._pads()) or 4
        wanted = []
        for k in self.roles[:npads]:
            if k and k not in wanted:
                wanted.append(k)
        cur = list(self.binder.slot_key)
        new = [""] * 4
        for s in range(min(npads, 4)):
            if cur[s] in wanted:
                new[s] = cur[s]                                    # bleibt: derselbe Decoder, nur die Rolle ändert sich
        free = [s for s in range(min(npads, 4)) if not new[s]]
        replaced = False
        for k in wanted:
            if k not in new and free:
                s = free.pop(0)
                new[s] = k
                replaced = replaced or bool(cur[s])                # der Platz hatte schon eine andere Kamera: sein Decoder müsste den Strom wechseln
        if new != cur:
            self.binder.slot_key = new
            self.feeders.set_keys(new)
            if replaced:
                self.restart_needed = True
            return True
        return False

    def _shown_slots(self):
        """Plätze, deren Kamera sendet und deren Bilder durch die Weiche laufen: erst dann ist ihr Bild echt (vorher läuft noch das Füllbild)."""
        return {s for s, k in enumerate(self.binder.slot_key) if k and self.feeders.shown(s)}

    def plan(self):
        """(Zeilen für die Steuerdatei, Schlüssel des Hauptbildes). Platz s = Pad sink_s des Compositors; Ton-Pad des audiomixer: sink_(s+1)."""
        slots = list(self.binder.slot_key)
        shown_slots = self._shown_slots()
        self.shown = {slots[s] for s in shown_slots}
        now = self.clock()
        live = self.live_set or set()
        pending = set()
        for s, k in enumerate(slots):
            if not k or s in shown_slots or k not in live:
                self._wait.pop(k, None)
                continue
            if now - self._wait.setdefault(k, now) < self.GRACE:
                pending.add(k)
        slot_of = {k: s for s, k in reversed(list(enumerate(slots))) if k}
        ina = self.cfg.get("inactive")
        inactive = [k for k in ina if isinstance(k, str)] if isinstance(ina, list) else []
        line, main = self.chooser.line(self.roles, slot_of, self.shown | pending, inactive)
        nums = [int(x) for x in line.split()]          # Platz, der in der Rolle Hauptbild/kleines Bild 1..3 zu sehen ist (15 = keiner)
        geo = self._pads()
        pad_role = {}
        for r, s in enumerate(nums):
            if s != 15 and s < 4 and slots[s] and r in geo and s not in pad_role:
                pad_role[s] = r
        lines = []
        hide, apos, mute = self._view_now()
        visible_role = {}                                          # Rolle -> ihr Bild ist gerade zu sehen (für den Rahmen)
        for s in sorted(set(range(len(geo))) | set(pad_role)):
            role = pad_role.get(s)
            if role is None or role not in geo:
                lines.append(f"comp.sink_{s} alpha 0")             # keine Rolle: unsichtbar (Lage bleibt wie sie war)
                continue
            lay = geo[role]
            x, y, w, h = lay["pic"]
            z = 0 if role == 0 else 2 * role + 1                   # Ebenen: Hauptbild 0, Rahmen der Stelle n 2n, ihr Bild 2n+1
            hidden = role >= 1 and bool(hide >> (role - 1) & 1)   # kleines Bild in der Ansicht ausgeblendet
            visible_role[role] = s in shown_slots and not hidden
            lines.append(f"comp.sink_{s} xpos {x}\ncomp.sink_{s} ypos {y}\ncomp.sink_{s} width {w}\ncomp.sink_{s} height {h}\ncomp.sink_{s} zorder {z}\n"
                         f"comp.sink_{s} alpha {1 if visible_role[role] else 0}")
            if self.crop_fn:                                       # Beschnitt der Rolle am nvvidconv des Platzes, der sie gerade zeigt (Kanten im Quellbild der Kamera)
                left, top, right, bottom = self.crop_fn(slots[s], lay["crop"])
                lines.append(f"vc{s} left {left}\nvc{s} top {top}\nvc{s} right {right}\nvc{s} bottom {bottom}")
        for role in sorted(geo):                                   # Rahmen: Farbfläche hinter dem kleinen Bild, nur sichtbar, wenn das Bild zu sehen ist
            lay = geo[role]
            if lay.get("frame_pad") is None:
                continue
            fx, fy, fw, fh = lay["frame"] or lay["pic"]
            p = lay["frame_pad"]
            alpha = lay["frame_alpha"] if lay["frame"] and visible_role.get(role) else 0
            lines.append(f"comp.sink_{p} xpos {fx}\ncomp.sink_{p} ypos {fy}\ncomp.sink_{p} width {fw}\ncomp.sink_{p} height {fh}\ncomp.sink_{p} zorder {2 * role}\n"
                         f"comp.sink_{p} alpha {alpha:g}\n{lay['frame_name']} foreground-color {lay['color']}")
        arole = apos + 1 if apos >= 0 else 0                       # Tonquelle: -1 Hauptbild, 0..2 kleines Bild an dieser Stelle
        a_slot = nums[arole] if arole < len(nums) and nums[arole] != 15 else None
        for s in sorted(set(range(len(geo))) | set(pad_role)):
            lines.append(f"amix.sink_{s + 1} volume {1 if s == a_slot and not mute else 0}")
        return "\n".join(lines) + "\n", main

    def _view_now(self):
        """(ausgeblendet, Tonquelle, stumm): aus der Datei der Oberfläche, sonst aus der Einstellung (stumm nur aus der Datei)."""
        if self.view is not None:
            return self.view
        if self.view_values:
            hide, apos = self.view_values(self.cfg)
            return int(hide), int(apos), 0
        return 0, {"main": -1, "pip": 0, "pip2": 1, "pip3": 2}.get(self.cfg.get("audio", "main"), -1), 0

    def apply_delays(self):
        """Verzögerung je Kamera (Einstellung "Verzögerung" im Bildaufbau) an die Weichen der Plätze geben, an denen die Kameras gerade hängen."""
        if not self.delay_fn or not hasattr(self.feeders, "set_delays"):
            return
        try:
            vals = self.delay_fn(self.cfg, list(self.binder.slot_key))
        except (KeyError, TypeError, ValueError):
            return
        self.feeders.set_delays(vals)

    def read_view(self):
        """Die Zeile der Oberfläche lesen ("ausgeblendet Tonquelle stumm"); None, wenn es sie nicht gibt oder sie nicht passt."""
        if not self.view_file:
            return None
        try:
            with open(self.view_file) as f:
                p = f.read().split()
            hide, apos, mute = int(p[0]), int(p[1]), int(p[2]) if len(p) >= 3 else 0
            if 0 <= hide <= 7 and -1 <= apos <= 2:
                return hide, apos, 1 if mute else 0
        except (OSError, ValueError, IndexError):
            pass
        return None

    def report_view(self):
        """Zurückmelden, was gilt (die Oberfläche wartet darauf): dieselbe Zeile wie gelesen. Nach jedem Start von belacoder ist die Datei weg und wird neu geschrieben."""
        if not self.view_state:
            return
        hide, apos, mute = self._view_now()
        line = f"{hide} {apos} {mute}\n"
        if line == self.view_line_last and os.path.exists(self.view_state):
            return
        try:
            tmp = self.view_state + ".tmp"
            with open(tmp, "w") as f:
                f.write(line)
            os.chmod(tmp, 0o644)
            os.replace(tmp, self.view_state)
            self.view_line_last = line
        except OSError:
            pass

    def write_padctl(self):
        if not self.padctl_path or not self.geometry_fn:
            return None
        text, main = self.plan()
        if text != self.padctl_last:
            try:
                tmp = self.padctl_path + ".tmp"
                with open(tmp, "w") as f:
                    f.write(text)
                os.chmod(tmp, 0o644)
                os.replace(tmp, self.padctl_path)
                self.padctl_last = text
            except OSError:
                pass
        return main

    def rebind(self):
        """Plätze wieder in der Reihenfolge der Rollen belegen (vor einem Neuaufbau der Kette: dort gehört Platz n zur Rolle n, auch für den Zuschnitt)."""
        self.last_cfg_sig = None
        self.binder.slot_key = [""] * 4
        self.reload()
        self.restart_needed = False
        self.feeders.set_keys(self.binder.slot_key)

    def rearm(self):
        """belacoder wird (neu) gestartet: die Plätze zeigen wieder das Füllbild (kleine Bilder unsichtbar), bis die Kameras ihren nächsten Keyframe liefern."""
        self.feeders.rearm()
        self.padctl_last = None
        self.write_padctl()
        if not self.feeders.wait_ready():
            self.log("send: Füllbild kam nicht rechtzeitig an, belacoder startet trotzdem")

    def start(self):
        self.last_cfg_sig = None
        self.live_set = self.live_keys()
        self.reload()
        self.restart_needed = False
        self.padctl_last = None
        self.write_padctl()                   # Anfangszustand: kleine Bilder unsichtbar, bis ihre Kamera da ist
        self.feeders.set_keys(self.binder.slot_key)

    def tick(self):
        self.reload()
        self.view = self.read_view()
        self.apply_delays()
        live = self.live_keys()
        self.live_set = live
        if live is not None:
            self.alive = {k for k in self.binder.slot_key if k and k in live}
        slots = list(self.binder.slot_key)
        main = self.write_padctl()
        self.report_view()
        if main is not None and main != self.main_key:
            if self.main_key is not None:
                self.log(f"send: Hauptbild jetzt {main or '(keine Kamera)'} (eingestellt: {self.roles[0]})")
            self.main_key = main
        restart, self.restart_needed = self.restart_needed, False
        return {"slots": slots, "alive": sorted(self.alive), "main": self.main_key or self.roles[0] or None, "line": "", "restart": restart}

    def stop(self):
        self.feeders.stop_all()
