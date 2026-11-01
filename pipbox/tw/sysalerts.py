"""Systemwarnungen und Chat-Befehle der Box (Temperatur, Bilder pro Sekunde, Akku)."""

import json
import math
import os
import re
import threading
import time

from tw.notifier import TwitchNotifier
from tw.store import TwitchStore


class SysAlerts:
    """Systemwarnungen im Twitch-Chat (Wunsch aus Issue #67, 12. Oktober 2026): meldet über denselben Bot wie die Akku-Warnung, wenn die Temperatur, die CPU-Last oder
    der Arbeitsspeicher der Box eine Grenze erreicht, und optional, wenn der Wert wieder normal ist. Einstellungen: <state>/sysalerts.json (atomar geschrieben, ohne
    Geheimnisse; Konto, Kanal und Token gehören zur Twitch-Karte und werden von dort genommen).

    Standard: aus. Alle 10 s werden die Messwerte der Box gelesen (dieselben wie in der Karte "Status", kein zusätzlicher Aufwand). Eine Warnung folgt, wenn der Wert in
    3 Messungen hintereinander (etwa 30 s) die Grenze erreicht oder überschreitet und die Pause (Cooldown) seit der letzten Meldung dieses Werts vorbei ist; bleibt er darüber,
    kommt nach jeder Pause eine Erinnerung. "Wieder normal" kommt, wenn er die Grenze um 3 Grad (Temperatur) oder 5 Punkte (CPU, RAM) unterschreitet, nur einmal je Warnung.
    Höchstens eine Nachricht je 3 s insgesamt (wie bei der Akku-Warnung, über denselben Sendeweg); schlägt das Senden fehl, folgt ein neuer Versuch nach 60 s, dann nach
    der Pause. Es wird nur gesendet, wenn die Twitch-Angaben vollständig sind (und bei "Nur während der Sendung" gesendet wird). Ein Fehler hier stört nie die Sendung."""
    METRICS = (("temp", "CPU-Temperatur", "°C", 3, (40, 100), 65), ("cpu", "CPU-Auslastung", "%", 5, (20, 100), 75), ("ram", "RAM-Auslastung", "%", 5, (20, 100), 75))
    DEFAULT_ALERT = "Warnung: {Name} bei {Wert} (Grenze {Grenze})"
    DEFAULT_OK = "{Name} wieder normal ({Wert})"
    DEFAULT_TEMP = "Box-Temperatur: {Wert}"
    DEFAULT_FPS = "Warnung: {Name} liefert nur {Wert}"
    FPS_LOW = 20.0                                # unter so vielen Bildern je Sekunde wird gewarnt
    FPS_HOLD_S = 15.0                             # so lange am Stück, bevor gemeldet wird (Anlaufen und kurze Aussetzer sind normal)
    FPS_REARM = 3.0                               # "wieder normal" erst, wenn die Bildrate so viel über der Grenze liegt
    DEFAULT_STATUS = {"ok": "🟢 Alles okay", "warn": "🟡 Es gibt eine Warnung", "crit": "🔴 Es gibt ein Problem"}
    DEFAULTS = {"enabled": False, "cooldown": 10, "recover": True, "only_live": True, "msg_alert": DEFAULT_ALERT, "msg_ok": DEFAULT_OK, "msg_temp": DEFAULT_TEMP, "msg_fps": DEFAULT_FPS, "msg_st_ok": DEFAULT_STATUS["ok"],
                "msg_st_warn": DEFAULT_STATUS["warn"], "msg_st_crit": DEFAULT_STATUS["crit"], "fps_on": True, "cmd_temp": False, "cmd_status": False, "cmd_vip": False,
                **{k: {"on": True, "limit": dflt} for k, _n, _u, _h, _r, dflt in METRICS}}
    POLL_S = 10
    SUSTAIN = 3                                   # Messungen hintereinander über der Grenze (etwa 30 s)
    RETRY_S = 60
    COOLDOWN = (1, 120)                           # Minuten
    CMDS = ("!temp", "!status")                   # Chat-Befehle: Moderatoren und der Streamer (auf Wunsch auch VIPs) fragen Temperatur und Ampel der Box ab
    CMD_FLAG = {"!temp": "cmd_temp", "!status": "cmd_status"}
    CMD_POLL_S = 2
    CMD_GAP_S = 30                                # höchstens eine Antwort je Befehl und 30 s, egal von wem (!temp und !status sperren sich nicht gegenseitig)
    CMD_MAX_AGE_S = 60                            # ältere Nachrichten (nach einem Verbindungsabbruch nachgeliefert) werden nicht mehr beantwortet

    def __init__(self, path, notifier, sampler, demo=False, mono=time.monotonic, wall=time.time):
        self.path, self.notifier, self.sampler, self.demo = path, notifier, sampler, demo
        self.mono, self.wall = mono, wall
        self.lock = threading.Lock()
        self.data = json.loads(json.dumps(self.DEFAULTS))
        self.state = {k: {"over": 0, "alerting": False, "last": None, "retry": None, "pending_ok": False} for k, *_ in self.METRICS}
        self.last = None                          # {"ok", "time", "text"}
        self.stop_ev = threading.Event()
        self.reader = None                        # TwitchReader (für den Chat-Befehl), vom Server gesetzt
        self.fps_fn = None                        # liefert {Schlüssel: {"name", "rates": [geliefert, dekodiert]}} der Kameras (Bildraten-Warnung), vom Server gesetzt
        self.fps_state = {}                       # Schlüssel -> {"since", "alerting", "last", "retry", "pending_ok", "name"}
        self.light_fn = None                      # liefert die Ampel der Box {"level", "live", "reasons"} (für !status), vom Server gesetzt
        self.cmd_since = None                     # Nummer der letzten gesehenen Chat-Nachricht (None: noch nichts gesehen, Altes wird nie beantwortet)
        self.cmd_last = {}                        # Befehl -> monotone Zeit der letzten Antwort
        try:
            with open(path) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, dict):
            if saved.get("cmd_on") is True and "cmd_temp" not in saved and "cmd_status" not in saved:
                saved = dict(saved, cmd_temp=True, cmd_status=True)          # Datei aus 1.0.88/1.0.89 (ein Haken für beide Befehle)
            try:
                self.data = self._merge(self.data, saved, strict=False)
            except ValueError:
                pass

    # ---- Prüfung
    @classmethod
    def _int(cls, v, lo, hi, error):
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(error)
        return v

    @classmethod
    def _merge(cls, base, req, strict=True):
        """Neue Werte in die Einstellungen übernehmen. strict: ungültige Angaben werfen ValueError; sonst (gespeicherte Datei) bleibt der Standard."""
        new = json.loads(json.dumps(base))

        def take(fn):
            try:
                fn()
            except ValueError:
                if strict:
                    raise
        for key in ("enabled", "recover", "only_live", "cmd_temp", "cmd_status", "cmd_vip", "fps_on"):
            if key in req:
                if isinstance(req[key], bool):
                    new[key] = req[key]
                elif strict:
                    raise ValueError("ja oder nein")
        if "cooldown" in req:
            def f():
                new["cooldown"] = cls._int(req["cooldown"], cls.COOLDOWN[0], cls.COOLDOWN[1], "Pause: Zahl von %d bis %d Minuten" % cls.COOLDOWN)
            take(f)
        for key, name, unit, _h, (lo, hi), _d in cls.METRICS:
            sub = req.get(key)
            if isinstance(sub, dict):
                if "on" in sub:
                    if isinstance(sub["on"], bool):
                        new[key]["on"] = sub["on"]
                    elif strict:
                        raise ValueError("ja oder nein")
                if "limit" in sub:
                    def g(key=key, sub=sub, name=name, unit=unit, lo=lo, hi=hi):
                        new[key]["limit"] = cls._int(sub["limit"], lo, hi, "%s: Zahl von %d bis %d" % (name, lo, hi))
                    take(g)
            elif sub is not None and strict:
                raise ValueError("Ungültige Anfrage")
        for key in ("msg_alert", "msg_ok", "msg_temp", "msg_fps", "msg_st_ok", "msg_st_warn", "msg_st_crit"):
            if key in req:
                def h(key=key):
                    new[key] = TwitchStore._message(req[key])
                take(h)
        return new

    def _write(self, data):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def save(self, req):
        if not isinstance(req, dict):
            raise ValueError("Ungültige Anfrage")
        with self.lock:
            new = self._merge(self.data, req, strict=True)
            try:
                self._write(new)
            except OSError:
                raise RuntimeError("Die Einstellungen konnten nicht gespeichert werden")
            self.data = new
            for st in self.state.values():
                st.update(over=0, retry=None)
        return self.status()

    # ---- Bausteine
    @staticmethod
    def render(template, name, value, limit):
        """{Name}, {Wert} und {Grenze} ersetzen (in einem Durchgang)."""
        vals = {"Name": name, "Wert": value, "Grenze": limit}
        return re.sub(r"\{(Name|Wert|Grenze)\}", lambda m: vals[m.group(1)], template)

    @staticmethod
    def fmt(v, unit):
        return "%d %s" % (round(v), unit)

    def values(self):
        """Aktuelle Messwerte {temp, cpu, ram} (None, wenn nicht messbar)."""
        try:
            s = self.sampler.sample() or {}
        except Exception:
            return {"temp": None, "cpu": None, "ram": None}

        def num(v):
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
        return {"temp": num(s.get("temp_c")), "cpu": num((s.get("cpu") or {}).get("avg")), "ram": num((s.get("mem") or {}).get("used_pct"))}

    def _creds(self):
        cfg = self.notifier.store.notify_settings()
        return cfg if (cfg.get("login") and cfg.get("channel") and cfg.get("token")) else None

    def _live(self):
        return self.notifier._live()

    def _send(self, cfg, text):
        ok, msg = self.notifier._deliver(cfg, text, wait=True)
        with self.lock:
            self.last = {"ok": ok, "time": int(self.wall()), "text": text if ok else msg}
        return ok

    # ---- Dienst
    def tick(self):
        with self.lock:
            data = json.loads(json.dumps(self.data))
        if not data["enabled"]:
            self._reset()
            return
        cfg = self._creds()
        if cfg is None:
            self._reset()
            return
        if data["only_live"] and not self._live():
            self._reset(keep_alert=True)               # ohne Sendung nichts melden; eine laufende Warnung bleibt vermerkt
            return
        vals = self.values()
        now = self.mono()
        pause = data["cooldown"] * 60
        for key, name, unit, hyst, _r, _d in self.METRICS:
            m, v = data[key], vals[key]
            st = self.state[key]
            if not m["on"] or v is None:
                st.update(over=0)
                continue
            limit = m["limit"]
            st["over"] = st["over"] + 1 if v >= limit else 0
            if st["retry"] is not None and now < st["retry"]:
                continue                                  # wartet auf den nächsten Versuch
            if st["over"] >= self.SUSTAIN and (st["last"] is None or now - st["last"] >= pause):
                text = self.render(data["msg_alert"], name, self.fmt(v, unit), self.fmt(limit, unit))
                if self._send(cfg, text):
                    st.update(alerting=True, last=now, retry=None, pending_ok=data["recover"])
                else:
                    st["retry"] = now + self.RETRY_S
            elif st["alerting"] and v < limit - hyst:
                st["alerting"] = False
                if st["pending_ok"] and data["recover"]:
                    text = self.render(data["msg_ok"], name, self.fmt(v, unit), self.fmt(limit, unit))
                    if not self._send(cfg, text):
                        st["alerting"], st["retry"] = True, now + self.RETRY_S      # nicht gesendet: beim nächsten Versuch noch einmal
                        continue
                st["pending_ok"] = False
        self.fps_tick(data, cfg, now, pause)

    def fps_tick(self, data, cfg, now, pause):
        """Kameras mit zu wenigen Bildern je Sekunde: Meldung nach FPS_HOLD_S am Stück, Erinnerung nach der Pause, "wieder normal" mit Abstand zur Grenze."""
        try:
            cams = (self.fps_fn() if (self.fps_fn and data.get("fps_on", True)) else None) or {}
        except Exception:
            cams = {}
        for key in [k for k in self.fps_state if k not in cams]:          # Kamera weg: Zustand vergessen, nichts melden
            del self.fps_state[key]
        for key, c in cams.items():
            try:
                dmx, dec = float(c["rates"][0]), float(c["rates"][1])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if 0 < dmx < self.FPS_LOW:                    # 0 = kein Bild: das ist "Kamera ohne Signal", keine Bildratenwarnung
                kind, fps = "camera", dmx
            elif dmx > 0 and 0 < dec < self.FPS_LOW:
                kind, fps = "box", dec
            else:
                kind, fps = None, min(dmx, dec) if dec > 0 else dmx
            st = self.fps_state.setdefault(key, {"since": None, "alerting": False, "last": None, "retry": None, "pending_ok": False, "kind": None})
            name = str(c.get("name") or key)
            label = name                                      # beide Fälle gleich benannt: schlechtes Netz der Kamera zeigt sich oft als "Dekoder zählt weniger", die Box ist dann nicht schuld
            limit = self.fmt(self.FPS_LOW, "fps")
            if kind is not None:
                if st["since"] is None or st["kind"] != kind:
                    st["since"], st["kind"] = now, kind
                if st["retry"] is not None and now < st["retry"]:
                    continue
                if now - st["since"] >= self.FPS_HOLD_S and (st["last"] is None or now - st["last"] >= pause):
                    text = self.render(data["msg_fps"], label, self.fmt(fps, "fps"), limit)
                    if self._send(cfg, text):
                        st.update(alerting=True, last=now, retry=None, pending_ok=data["recover"], name=label)
                    else:
                        st["retry"] = now + self.RETRY_S
            else:
                st["since"], st["kind"] = None, None
                if st["alerting"] and fps >= self.FPS_LOW + self.FPS_REARM:
                    st["alerting"] = False
                    if st["pending_ok"] and data["recover"]:
                        text = self.render(data["msg_ok"], st.get("name") or name, self.fmt(fps, "fps"), limit)
                        if not self._send(cfg, text):
                            st["alerting"], st["retry"] = True, now + self.RETRY_S
                            continue
                    st["pending_ok"] = False

    # ---- Chat-Befehl !temp
    def _allowed(self, item, vip):
        """Darf der Absender den Befehl nutzen? Nach dem Abzeichen aus der Twitch-Nachricht: Streamer und Moderatoren, auf Wunsch auch VIPs."""
        badges = item.get("badges") or []
        return "broadcaster" in badges or "moderator" in badges or (vip and "vip" in badges)

    def _is_cmd(self, item):
        """Der Befehl in der Nachricht ("!temp" oder "!status") oder None."""
        if item.get("type") != "msg":
            return None
        parts = str(item.get("text") or "").split()
        return parts[0].lower() if parts and parts[0].lower() in self.CMDS else None

    def _light_text(self, data):
        """Antwort auf !status: die Farbe (Text vom Streamer einstellbar) und, wenn eine Kamera zu wenige Bilder liefert, diese Kameras; die übrigen Gründe sieht er in der Oberfläche."""
        try:
            light = self.light_fn() if self.light_fn else None
        except Exception:
            light = None
        level = (light or {}).get("level")
        if level not in ("ok", "warn", "crit"):
            return "⚪ Status nicht verfügbar"
        text = data["msg_st_" + level] + (" (keine Sendung)" if level == "ok" and not light.get("live") else "")
        why = [r["text"] for r in (light.get("reasons") or []) if isinstance(r, dict) and r.get("kind") == "fps" and r.get("text")][:2]
        return text + (": " + " · ".join(why) if why else "")

    def _reply(self, cfg, item, cmd="!temp", data=None):
        data = data or self.data
        who = TwitchNotifier.camera_text(item.get("name"))
        if cmd == "!status":
            text = ("@%s " % who if who else "") + self._light_text(data)
        else:
            v = self.values()["temp"]
            text = ("@%s " % who if who else "") + data["msg_temp"].replace("{Wert}", "%d °C" % round(v) if v is not None else "nicht messbar")
        if self.demo:
            self.reader._add({"type": "msg", "name": "Box", "color": "#9146FF", "text": text, "emotes": []})
            return True
        return self._send(cfg, text)

    def cmd_tick(self):
        """Ein Durchlauf: neue Chat-Nachrichten lesen und "!temp" von Berechtigten mit der Temperatur der Box beantworten. Das Lesen hält die Chat-Verbindung offen."""
        with self.lock:
            data = json.loads(json.dumps(self.data))
        cfg = self._creds()
        if not (data["cmd_temp"] or data["cmd_status"]) or self.reader is None or (cfg is None and not self.demo):
            self.cmd_since = None
            return
        r = self.reader.poll(self.cmd_since or 0)
        last = r.get("last", 0)
        if self.cmd_since is None:
            self.cmd_since = last                 # beim Einschalten zählt nur, was ab jetzt kommt
            return
        self.cmd_since = last
        now = self.wall()
        for it in r.get("items", []):
            cmd = self._is_cmd(it)
            if not cmd or not data[self.CMD_FLAG[cmd]] or now - it.get("t", now) > self.CMD_MAX_AGE_S:
                continue
            if not self._allowed(it, data["cmd_vip"]):
                continue
            last = self.cmd_last.get(cmd)
            if last is not None and self.mono() - last < self.CMD_GAP_S:
                continue
            self.cmd_last[cmd] = self.mono()
            self._reply(cfg, it, cmd, data)

    def run_cmd(self):
        while not self.stop_ev.is_set():
            try:
                self.cmd_tick()
            except Exception as e:
                print("sysalerts-cmd:", type(e).__name__)
            self.stop_ev.wait(self.CMD_POLL_S)

    def _reset(self, keep_alert=False):
        for st in self.state.values():
            st.update(over=0, retry=None)
            if not keep_alert:
                st.update(alerting=False, pending_ok=False)
        for st in self.fps_state.values():
            st.update(since=None, retry=None)
            if not keep_alert:
                st.update(alerting=False, pending_ok=False)

    def run(self):
        while not self.stop_ev.is_set():
            try:
                self.tick()
            except Exception as e:                  # nie den Dienst beenden; vom Text der Ausnahme nur den Typ ausgeben
                print("sysalerts:", type(e).__name__)
            self.stop_ev.wait(self.POLL_S)

    # ---- für die Oberfläche
    def status(self):
        with self.lock:
            d = json.loads(json.dumps(self.data))
            last = dict(self.last) if self.last else None
        vals = self.values()
        return dict(d, ready=self._creds() is not None,
                    values={k: (None if vals[k] is None else round(vals[k], 1)) for k in vals},
                    alerting=[k for k, st in self.state.items() if st["alerting"]] + (["fps"] if any(st["alerting"] for st in self.fps_state.values()) else []), last=last)
