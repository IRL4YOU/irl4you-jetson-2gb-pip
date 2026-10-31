"""Meldungen der Box an den Chat (Akku, Ausfall, Sendestart)."""

import re
import threading
import time

from tw.irc import TwitchChat
from tw.store import TwitchStore
from tw.util import belacoder_running


class TwitchNotifier:
    """Hintergrunddienst: schreibt eine Warnung in den Twitch-Chat, wenn der Akku einer DJI-Kamera die Schwelle erreicht (Auftrag des Nutzers).

    Alle 10 s wird je Kamera geprüft: Warnung, wenn der Akkustand bekannt ist, höchstens die Schwelle beträgt, die Kamera nicht lädt, der Messwert höchstens
    5 Minuten alt ist, für sie noch nicht gewarnt wurde und (bei "Nur während der Sendung") gesendet wird. Danach merkt sich der Speicher die Warnung, auch über einen
    Neustart des Dienstes hinweg. Wieder scharf wird eine Kamera, wenn sie lädt oder ihr Akku mindestens 10 Prozentpunkte über der Schwelle liegt (Akku gewechselt).
    Höchstens eine Nachricht je 3 s insgesamt. Schlägt das Senden fehl, folgen Wiederholungen nach 30, 60 und 120 s (dann weiter alle 120 s), höchstens 5 Versuche je
    Warnung; der letzte Fehler steht im Status. Neue Einstellungen starten die Versuche neu. Im Demo-Modus läuft der Dienst nicht und der Test sendet nichts."""
    POLL_S = 10
    GAP_S = 3
    FRESH_S = 300
    BACKOFF_S = (30, 60, 120, 120)         # Wartezeit nach dem 1., 2., 3. und 4. Fehlversuch; nach dem 5. wird aufgegeben
    TEST_EVERY_S = 10
    TEST_TEXT = "Test: IRL4YOU BOX"

    def __init__(self, store, djisvc, cams, send, chat=None, demo=False, mono=time.monotonic, wall=time.time, sleep=time.sleep):
        self.store, self.djisvc, self.cams, self.send = store, djisvc, cams, send
        self.chat, self.demo = chat or TwitchChat(), demo
        self.mono, self.wall, self.sleep = mono, wall, sleep
        self.lock = threading.Lock()           # Zustand (Versuche, letzte Meldung)
        self.net_lock = threading.Lock()       # immer nur eine Verbindung zu Twitch
        self.tries = {}                        # Schlüssel -> {"n": Versuche, "at": nächster Versuch (monotone Zeit) oder None = aufgegeben}
        self.last = None                       # {"ok", "time", "text"}: Ergebnis des letzten Sendens
        self.last_send = None                  # monotone Zeit der letzten Nachricht
        self.test_at = None
        self.stop_ev = threading.Event()

    # ---- Bausteine
    @staticmethod
    def camera_text(name):
        """Kameraname für die Nachricht: ohne Steuerzeichen und Zeilenumbrüche, höchstens 40 Zeichen, nicht mit / oder . am Anfang (ein Chat-Befehl)."""
        t = " ".join(str(name or "").split())
        t = "".join(ch for ch in t if ch.isprintable()).lstrip("/. ")
        return t[:40].strip()

    @staticmethod
    def render(template, name, percent):
        """{Kamera} und {Prozent} in der Nachricht ersetzen (in einem Durchgang: ein Kameraname wird nicht noch einmal durchsucht)."""
        return re.sub(r"\{(Kamera|Prozent)\}", lambda m: name if m.group(1) == "Kamera" else str(percent), template)

    @staticmethod
    def _percent(e):
        v = e.get("battery") if isinstance(e, dict) else None
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100 else None

    def _fresh(self, e):
        age = e.get("battery_age")
        return isinstance(age, (int, float)) and not isinstance(age, bool) and 0 <= age <= self.FRESH_S

    def _live(self):
        """Wird gerade gesendet (eigene Sendekette oder ein belacoder der BELABOX-Oberfläche)?"""
        return bool(self.send._active() or belacoder_running())

    def _camera_name(self, key):
        cam = next((c for c in list(self.cams.cams) if c.get("key") == key), None)
        return self.camera_text(cam.get("name") if cam else "") or key

    def _deliver(self, cfg, text, wait=False):
        """Eine Nachricht senden (nie zwei Verbindungen zugleich). wait: den Abstand zur letzten Nachricht abwarten."""
        with self.net_lock:
            if wait and self.last_send is not None:
                left = self.GAP_S - (self.mono() - self.last_send)
                if left > 0:
                    self.sleep(left)
            ok, msg = self.chat.send(cfg["login"], cfg["token"], cfg["channel"], text)
            self.last_send = self.mono()
        return ok, msg

    # ---- Dienst
    def tick(self):
        """Ein Durchlauf: Kameras wieder scharf stellen, deren Akku gewechselt wurde oder die laden, und fällige Warnungen senden."""
        cfg = self.store.notify_settings()
        if not (cfg["enabled"] and cfg["login"] and cfg["channel"] and cfg["token"]):
            with self.lock:
                self.tries.clear()
            return
        extras = self.djisvc.camera_extras() or {}
        thr = cfg["threshold"]
        for key in self.store.warned_keys():
            e = extras.get(key)
            pct = self._percent(e)
            if e and (e.get("charging") is True or (pct is not None and pct >= thr + 10)):
                self.store.unwarn(key)
        live, due = None, []
        for key in sorted(extras):
            e = extras[key]
            pct = self._percent(e)
            if pct is None or pct > thr or e.get("charging") is True or not self._fresh(e) or self.store.is_warned(key):
                continue
            if cfg["only_live"]:
                live = self._live() if live is None else live
                if not live:
                    continue
            due.append((key, pct))
        keys = {d[0] for d in due}
        with self.lock:
            self.tries = {k: v for k, v in self.tries.items() if k in keys}      # was nicht mehr fällig ist, wird nicht wiederholt
        for key, pct in due:
            now = self.mono()
            t = self.tries.get(key)
            if t is not None and (t["at"] is None or now < t["at"]):
                continue                                                  # wartet auf den nächsten Versuch oder ist aufgegeben
            if self.last_send is not None and now - self.last_send < self.GAP_S:
                break                                                     # höchstens eine Nachricht je 3 s: der Rest folgt beim nächsten Durchlauf
            self._warn(cfg, key, pct)

    def _warn(self, cfg, key, pct):
        text = self.render(cfg["message"], self._camera_name(key), pct)
        ok, msg = self._deliver(cfg, text)
        with self.lock:
            if ok:
                self.tries.pop(key, None)
                self.last = {"ok": True, "time": int(self.wall()), "text": text}
            else:
                n = self.tries.get(key, {}).get("n", 0) + 1
                self.tries[key] = {"n": n, "at": self.mono() + self.BACKOFF_S[n - 1] if n <= len(self.BACKOFF_S) else None}
                self.last = {"ok": False, "time": int(self.wall()), "text": msg}
        if ok:
            self.store.mark_warned(key, self.wall())

    def run(self):
        """Läuft im Hintergrund, solange die Oberfläche läuft."""
        while not self.stop_ev.is_set():
            try:
                self.tick()
            except Exception as e:                  # nie den Dienst beenden; vom Text der Ausnahme nur den Typ ausgeben (er könnte Angaben enthalten)
                print("twitch:", type(e).__name__)
            self.stop_ev.wait(self.POLL_S)

    # ---- für die Oberfläche
    def status(self):
        out = self.store.public()
        with self.lock:
            last = dict(self.last) if self.last else None
            waits = [t["at"] for t in self.tries.values() if t["at"] is not None]
            gave_up = any(t["at"] is None for t in self.tries.values())
        st = {"ok": None, "time": None, "text": "", "retry_at": None, "gave_up": gave_up}
        if last:
            st.update(ok=last["ok"], time=last["time"], text=last["text"])
            if not last["ok"] and waits:
                st["retry_at"] = int(self.wall() + max(0.0, min(waits) - self.mono()))
        out["status"] = st
        return out

    def save(self, req):
        self.store.set(req)
        with self.lock:
            self.tries.clear()                       # neue Angaben: neue Versuche
        return self.status()

    def test(self):
        """Eine Testnachricht mit den gespeicherten Angaben senden: {"ok": bool, "message": Meldung auf Deutsch}."""
        cfg = self.store.notify_settings()
        if not (cfg["channel"] and cfg["login"] and cfg["token"]):
            raise ValueError(TwitchStore.ERR_MISSING)
        with self.lock:
            now = self.mono()
            if self.test_at is not None and now - self.test_at < self.TEST_EVERY_S:
                raise PermissionError("Bitte kurz warten")
            self.test_at = now
        ok, msg = (True, "Demo: gesendet.") if self.demo else self._deliver(cfg, self.TEST_TEXT, wait=True)
        with self.lock:
            self.last = {"ok": ok, "time": int(self.wall()), "text": self.TEST_TEXT if ok else msg}
        return {"ok": ok, "message": msg}
