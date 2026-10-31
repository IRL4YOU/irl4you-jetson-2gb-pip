"""Bildaufbau (Bild in Bild): Sendekette bauen, Pläne für Tausch und Ansicht, Wartezeiten."""

import json
import os
import threading

from srv import pipeline_jetson
from srv.cameras import KEY_RE
from srv.datenschutz import datenschutz_aktiv
from srv.plugin import FREE, PIP_CORNERS
from srv.style import SIZE_MAX, SIZE_MIN, STYLE_SLOTS, clean_styles


DEFAULT_MAIN_DELAY_MS = 0     # Ausgangswert der Verzögerung des Hauptbildes (per Regler anpassbar). Jetson: 0, alle Bilder gehen denselben Weg; das andere Paket braucht 450 ms, weil dort die kleinen Bilder später fertig sind


DEFAULT_PIP_DELAY_MS = 0      # kleine Bilder: zusätzliche Wartezeit je Bild (Feinabgleich, wenn eine Kamera mehr hinterherhinkt)


DELAY_KEYS = ("main_delay_ms", "pip_delay_ms", "pip2_delay_ms", "pip3_delay_ms")


FRAME_MS = 33                 # eine Warteschlange gibt erst nach der Schwelle frei: beim Bild ein Bild zugeben


class PipelineStore:
    """Welche Pipeline gesendet wird und welche Kameras sie nutzt.

    Typ "single": eine Kamera. Typ "pip": Hauptbild plus kleines Bild. Die Pipeline
    ist ein Text für belacoder, abgeleitet von BELABOX' Standard-Pipeline für RTMP
    (h265_rtmp_localhost_publish_live_30fps). Das kleine Bild verkleinert der
    Hardware-Decoder selbst; unser Baustein schreibt es nur in das Hauptbild
    (lesen wäre auf diesem Chip zu langsam).
    """
    DEFAULT = {"type": "single", "main": "", "pip": "", "corner": 3, "size_pct": 25, "size_pct2": 25, "size_pct3": 25, "audio": "main",
               "pip2": "", "corner2": 2, "pip3": "", "corner3": 0, "x": 500, "y": 500, "x2": 500, "y2": 500, "x3": 500, "y3": 500, "main_delay_ms": DEFAULT_MAIN_DELAY_MS,
               "pip_delay_ms": DEFAULT_PIP_DELAY_MS, "pip2_delay_ms": DEFAULT_PIP_DELAY_MS,
               "pip3_delay_ms": DEFAULT_PIP_DELAY_MS, "auto_failover": True, "swap_cams": 0, "always_ready": False, "facecam": ""}
    SLOTS = ("main", "pip", "pip2", "pip3")
    Q = "queue max-size-time=10000000000 max-size-buffers=1000 max-size-bytes=41943040"
    DATENSCHUTZ_PFAD = None                 # Tests: Pfad der Einstellung (sonst DATENSCHUTZ_DATEI); DATENSCHUTZ_FEST = dict/None übersteuert die Datei
    DATENSCHUTZ_FEST = "datei"

    @classmethod
    def datenschutz(cls):
        """{"delay_ms": ...} wenn die Sendekette die Hauptkamera verpixeln soll, sonst None (siehe datenschutz_aktiv)."""
        if cls.DATENSCHUTZ_FEST != "datei":
            return cls.DATENSCHUTZ_FEST
        return datenschutz_aktiv(cls.DATENSCHUTZ_PFAD)

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.cfg = dict(self.DEFAULT)
        try:
            with open(path) as f:
                self.cfg.update(json.load(f))
        except FileNotFoundError:
            self.cfg["always_ready"] = True   # neue Installation: "Alle Kameras immer bereit" ist Standard (auch auf dem Jetson: Weichen, Füllbild, Tausch, Ansicht, Verzögerung und Aussehen gibt es nur dort); wer schon gespeichert hat, behält seine Wahl
        except (OSError, ValueError):
            pass
        self.cfg["styles"] = clean_styles(self.cfg.get("styles"))        # ältere Dateien kennen sie noch nicht

    def save(self):
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        with os.fdopen(fd, "w") as f:
            json.dump(self.cfg, f, indent=1)
        os.replace(tmp, self.path)

    SLOT_DELAY = {"pip": "pip_delay_ms", "pip2": "pip2_delay_ms", "pip3": "pip3_delay_ms"}

    @classmethod
    def facecam_slot(cls, c):
        """Platz der Facecam-Kamera in dieser Einstellung ("main", "pip", "pip2", "pip3") oder None (keine Facecam oder nicht im Bild)."""
        k = c.get("facecam")
        if not k or c.get("type") != "pip":
            return None
        return next((s for s in cls.SLOTS if c.get(s) == k), None)

    @classmethod
    def _facecam_keeps_the_sound(cls, c):
        """Mit einer Facecam bleibt der Ton bei ihrer Kamera, auch wenn sie durch einen Tausch an einen anderen Platz wandert (Hauptbild oder ein anderes
        kleines Bild). Eine manuell gewählte Tonquelle gilt bis zum nächsten Tausch. Ohne Facecam ändert sich nichts: der Ton bleibt am Platz, bei
        "Hauptbild" folgt er dem wechselnden Hauptbild. Eine deaktivierte Kamera ist nie die Tonquelle."""
        if not c.get("facecam"):
            return
        slot = cls.facecam_slot(c)
        if slot is None:
            c["facecam"] = ""                                                                  # die Kamera ist nicht mehr im Bild
        elif slot != "main" and c.get(slot) in (c.get("inactive") or []):
            c["audio"] = "main"
        else:
            c["audio"] = slot

    def set_facecam(self, slot):
        """Das Bild wählen, dessen Kamera die Facecam ist ("main", "pip", "pip2", "pip3" oder "" = keine). Gespeichert wird die Kamera, nicht der Platz: Sie behält den Ton auch nach einem
        Tausch, egal ob ihr Bild gerade groß oder klein ist. Gibt die Tonquelle zurück, die jetzt gilt ("main" ohne Facecam, sonst der Platz der Kamera)."""
        if slot not in ("", "main", "pip", "pip2", "pip3"):
            raise ValueError("Facecam: eines der Bilder oder keine")
        with self.lock:
            c = self.cfg
            if c.get("type") != "pip":
                raise ValueError("Das gibt es nur bei der Art Bild-in-Bild")
            if slot:
                key = c.get(slot)
                if not key:
                    raise ValueError("Dieses Bild ist nicht belegt")
                if slot != "main" and key in (c.get("inactive") or []):
                    raise ValueError("Diese Kamera ist deaktiviert und kann nicht die Facecam sein")
                c["facecam"] = key
            else:
                c["facecam"] = ""
            self.save()
            return slot or "main"

    def _carry_facecam(self, new):
        """Die Facecam einer neu gespeicherten Einstellung: Sie folgt ihrem Platz (wer das kleine Bild mit einer anderen Kamera belegt, bekommt dort die neue
        Facecam); steht ihre Kamera gerade im Hauptbild (nach einem Tausch), bleibt sie, solange sie im Bild ist."""
        old = self.cfg.get("facecam")
        if not old or new.get("type") != "pip":
            return ""
        slot = self.facecam_slot(self.cfg)
        here = {new.get(s) for s in self.SLOTS} - {""}
        if slot in ("pip", "pip2", "pip3"):
            return new.get(slot) or (old if old in here else "")
        return old if slot == "main" and old in here else ""

    def swap_main_pip(self, with_key=None):
        """Hauptbild gegen eine Kamera tauschen, die gerade als kleines Bild im Bild ist (Szenenwechsel, Stufe 1). Ohne Angabe
        das erste kleine Bild. Kamera und Verzögerung bleiben beisammen (die Verzögerung gehört zur Kamera); Ecke, Größe,
        Position und die Wahl des Tons (Hauptbild oder kleines Bild) bleiben am Platz. Wahr, wenn dabei ein ausgeblendetes
        kleines Bild eingeblendet wurde."""
        with self.lock:
            c = self.cfg
            if c.get("type") != "pip" or not c.get("pip") or not c.get("main"):
                raise ValueError("Zum Tauschen braucht es ein Hauptbild und ein kleines Bild")
            slot = "pip"
            if with_key:
                slot = next((k for k in self.SLOT_DELAY if c.get(k) == with_key), None)
                if slot is None:
                    raise ValueError("Diese Kamera ist gerade nicht als kleines Bild im Bild")
            dk = self.SLOT_DELAY[slot]
            c["main"], c[slot] = c[slot], c["main"]
            c["main_delay_ms"], c[dk] = c.get(dk, 0), c.get("main_delay_ms", 0)
            if c.get("inactive"):                                                    # die Hauptkamera ist nie deaktiviert
                rest = [k for k in c["inactive"] if k != c["main"]]
                if rest:
                    c["inactive"] = rest
                else:
                    c.pop("inactive")
            self._facecam_keeps_the_sound(c)
            # "Ausgeblendet" gehört zur Kamera: die bisherige Hauptkamera war sichtbar, also ist ihr kleines Bild nach dem Tausch sichtbar
            styles = clean_styles(c.get("styles"))
            idx = STYLE_SLOTS[list(self.SLOT_DELAY).index(slot)]
            shown = not styles[idx]["visible"]
            if shown:
                styles[idx]["visible"] = True
                c["styles"] = styles
            self.save()
            return shown

    def set(self, req, camera_keys):
        t = req.get("type")
        if t not in ("single", "pip"):
            raise ValueError("Art des Bildaufbaus unbekannt")
        main = str(req.get("main", ""))
        if main not in camera_keys:
            raise ValueError("Hauptkamera: bitte eine vorhandene Kamera wählen")
        cfg = {"type": t, "main": main, "pip": "", "corner": 3, "size_pct": 25, "size_pct2": 25, "size_pct3": 25, "audio": "main",
               "pip2": "", "corner2": 2, "pip3": "", "corner3": 0, "x": 500, "y": 500, "x2": 500, "y2": 500, "x3": 500, "y3": 500, "main_delay_ms": DEFAULT_MAIN_DELAY_MS,
               "pip_delay_ms": DEFAULT_PIP_DELAY_MS, "pip2_delay_ms": DEFAULT_PIP_DELAY_MS,
               "pip3_delay_ms": DEFAULT_PIP_DELAY_MS, "auto_failover": req.get("auto_failover", True) is not False, "swap_cams": 0,
               "always_ready": req.get("always_ready") is True}
        cfg["styles"] = clean_styles(req.get("styles"), self.cfg.get("styles"), strict=True)       # Deckkraft, Beschnitt, Rahmen je kleinem Bild
        if t == "pip":
            try:
                swap = int(req.get("swap_cams", 0) or 0)
            except (TypeError, ValueError):
                raise ValueError("Tausch: aus, 2 oder 4 Kameras")
            if swap not in (0, 2, 4):
                raise ValueError("Tausch: aus, 2 oder 4 Kameras")
            cfg["swap_cams"] = swap
            pipk = str(req.get("pip", ""))
            if pipk not in camera_keys or pipk == main:
                raise ValueError("Kleines Bild: eine andere vorhandene Kamera wählen")
            try:
                corner, pct = int(req.get("corner", 3)), int(req.get("size_pct", 25))
                # Größe je kleinem Bild; eine Anfrage ohne die Werte für Bild 2 und 3 (älterer Client) gibt allen die Größe von Bild 1
                pct2, pct3 = int(req.get("size_pct2", pct)), int(req.get("size_pct3", pct))
            except (TypeError, ValueError):
                raise ValueError("Ecke und Größe müssen Zahlen sein")
            if corner not in range(len(PIP_CORNERS)) or not all(SIZE_MIN <= v <= SIZE_MAX for v in (pct, pct2, pct3)):
                raise ValueError("Position aus der Liste wählen, Skalierung jedes kleinen Bildes %d bis %d Prozent" % (SIZE_MIN, SIZE_MAX))
            audio = req.get("audio", "main")
            if audio not in ("main", "pip", "pip2", "pip3"):
                raise ValueError("Ton: Hauptbild oder eines der kleinen Bilder")
            cfg.update(pip=pipk, corner=corner, size_pct=pct, size_pct2=pct2, size_pct3=pct3, audio=audio)
            for key in ("x", "y", "x2", "y2", "x3", "y3"):
                try:
                    val = int(req.get(key, 500))
                except (TypeError, ValueError):
                    raise ValueError("Position muss eine Zahl sein")
                cfg[key] = max(0, min(1000, val))
            for key, dflt in (("main_delay_ms", DEFAULT_MAIN_DELAY_MS), ("pip_delay_ms", DEFAULT_PIP_DELAY_MS),
                              ("pip2_delay_ms", DEFAULT_PIP_DELAY_MS), ("pip3_delay_ms", DEFAULT_PIP_DELAY_MS)):
                try:
                    delay = int(req.get(key, dflt)) if req.get(key) != "" else 0
                except (TypeError, ValueError):
                    raise ValueError("Verzögerung muss eine Zahl sein (Millisekunden)")
                if not 0 <= delay <= 3000:
                    raise ValueError("Verzögerung: 0 bis 3000 ms")
                cfg[key] = delay
            pip2 = str(req.get("pip2", "") or "")
            if pip2:
                try:
                    corner2 = int(req.get("corner2", 2))
                except (TypeError, ValueError):
                    raise ValueError("Ecke muss eine Zahl sein")
                if pip2 not in camera_keys or pip2 in (main, pipk):
                    raise ValueError("Zweites kleines Bild: eine weitere vorhandene Kamera wählen")
                if corner2 not in range(len(PIP_CORNERS)) or (corner2 == corner and corner != FREE):
                    raise ValueError("Zweites kleines Bild: eine andere Position als das erste wählen")
                cfg.update(pip2=pip2, corner2=corner2)
            else:
                cfg["pip2_delay_ms"] = 0
            pip3 = str(req.get("pip3", "") or "")
            if pip3 and pip2:
                try:
                    corner3 = int(req.get("corner3", 0))
                except (TypeError, ValueError):
                    raise ValueError("Ecke muss eine Zahl sein")
                if pip3 not in camera_keys or pip3 in (main, pipk, pip2):
                    raise ValueError("Drittes kleines Bild: eine weitere vorhandene Kamera wählen")
                if corner3 not in range(len(PIP_CORNERS)) or (corner3 != FREE and corner3 in (corner, cfg["corner2"])):
                    raise ValueError("Drittes kleines Bild: eine andere Position als die ersten beiden wählen")
                cfg.update(pip3=pip3, corner3=corner3)
            else:
                cfg["pip3_delay_ms"] = 0
            if cfg["audio"] == "pip2" and not cfg["pip2"] or cfg["audio"] == "pip3" and not cfg["pip3"]:
                raise ValueError("Ton: dieses kleine Bild ist nicht gewählt")
        pips = {cfg.get(k) for k in ("pip", "pip2", "pip3")} - {""}
        old = req.get("inactive") if "inactive" in req else self.cfg.get("inactive", [])
        inactive = list(dict.fromkeys(k for k in (old if isinstance(old, list) else []) if isinstance(k, str) and k in pips))[:3]
        if t == "pip" and inactive:                                                 # deaktivierte Kameras (Issue #19); ohne sie fehlt der Schlüssel
            cfg["inactive"] = inactive
        fc = self._carry_facecam(cfg)
        if fc:
            cfg["facecam"] = fc
        with self.lock:
            self.cfg = cfg
            self.save()

    def set_active(self, key, active):
        """Eine Kamera deaktivieren (sie springt bei Ausfall des Hauptbildes nicht als Ersatz ein) oder wieder aktivieren. Nur kleine Bilder."""
        if not isinstance(active, bool) or not isinstance(key, str) or not KEY_RE.match(key):
            raise ValueError("Kamera oder Zustand ungültig")
        with self.lock:
            c = self.cfg
            if c.get("type") != "pip":
                raise ValueError("Das gibt es nur bei der Art Bild-in-Bild")
            if key == c.get("main"):
                raise ValueError("Das Hauptbild lässt sich nicht deaktivieren")
            if key not in (c.get("pip"), c.get("pip2"), c.get("pip3")):
                raise ValueError("Diese Kamera ist nicht im Bild")
            cur = [k for k in (c.get("inactive") or []) if k != key]
            if not active:
                cur.append(key)
            if cur:
                c["inactive"] = cur
            else:
                c.pop("inactive", None)
            self.save()

    @classmethod
    def _safe_cfg(cls, c):
        """Zahlenfelder zu Zahlen in festen Bereichen zwingen. build() läuft über pipbox_send auch als root, und die
        Datei pipeline.json gehört dem Benutzer pipbox: ein eingeschleuster Text darf nie in den Pipeline-Text gelangen."""
        out = dict(c)

        def num(k, lo, hi):
            try:
                v = int(out.get(k, cls.DEFAULT[k]))
            except (TypeError, ValueError):
                v = cls.DEFAULT[k]
            out[k] = max(lo, min(hi, v))
        for k in ("corner", "corner2", "corner3"):
            num(k, 0, len(PIP_CORNERS) - 1)
        num("size_pct", SIZE_MIN, SIZE_MAX)
        for k in ("size_pct2", "size_pct3"):                  # ältere Dateien kennen sie nicht: dann gilt die Größe von Bild 1
            if k not in out:
                out[k] = out["size_pct"]
            num(k, SIZE_MIN, SIZE_MAX)
        for k in ("x", "y", "x2", "y2", "x3", "y3"):
            num(k, 0, 1000)
        for k in ("main_delay_ms", "pip_delay_ms", "pip2_delay_ms", "pip3_delay_ms"):
            num(k, 0, 3000)
        num("swap_cams", 0, 4)
        if out["swap_cams"] not in (2, 4):
            out["swap_cams"] = 0
        out["always_ready"] = out.get("always_ready") is True
        out["type"] = "pip" if out.get("type") == "pip" else "single"
        fc = out.get("facecam")
        out["facecam"] = fc if (out["type"] == "pip" and isinstance(fc, str) and KEY_RE.match(fc) and fc in [out.get(s) for s in cls.SLOTS]) else ""
        out["styles"] = clean_styles(out.get("styles"))
        if "inactive" in out:
            ina = out["inactive"]
            out["inactive"] = [k for k in ina if isinstance(k, str) and KEY_RE.match(k)][:3] if isinstance(ina, list) else []
        return out

    @classmethod
    def _layout(cls, c):
        """Welche kleinen Bilder wirklich dabei sind: (pip, pip2, pip3, multi). c ist eine geprüfte Einstellung (_safe_cfg)."""
        pip = c["type"] == "pip" and bool(KEY_RE.match(c.get("pip", "")))
        pip2 = bool(pip and c.get("pip2") and KEY_RE.match(c["pip2"]) and c.get("corner2") in range(len(PIP_CORNERS))
                    and (c["corner2"] != c["corner"] or c["corner"] == FREE))
        multi = True                                  # nvcompositor: ein Pad je Platz, bis zu drei kleine Bilder
        pip3 = bool(multi and pip2 and c.get("pip3") and KEY_RE.match(c["pip3"])
                    and c.get("corner3") in range(len(PIP_CORNERS)) and (c["corner3"] == FREE or c["corner3"] not in (c["corner"], c["corner2"])))
        return pip, pip2, pip3, multi

    @classmethod
    def swap_plan(cls, cfg):
        """Tausch über einen Umschalter in der Kette: Den gibt es auf dem Jetson nicht. Hauptbild und kleine Bilder tauschen dort über die Steuerdatei (Rollen, siehe
        pipbox_always.SlotController), jede Kamera behält ihren Decoder. Bleibt als Schnittstelle erhalten (Aufrufer fragen nach einem Plan) und liefert immer None."""
        return None

    @classmethod
    def always_plan(cls, cfg):
        """Plan für "alle Kameras immer bereit" oder None. Feste Plätze (0 = Hauptbild beim Aufbau, 1 bis 3 = kleine Bilder), je Platz ein Zubringer (pipbox_always.py)
        mit Weiche, der den Stream der Kamera aus dem RTMP-Server weiterreicht; im Compositor liegt ein schwarzer Untergrund, die Sendekette selbst hat nie eine Quelle,
        die ausfällt. Ein Kamerawechsel an einem Platz braucht nur einen gezielten Neustart (der Decoder kann den Strom nicht wechseln)."""
        c = cls._safe_cfg(cfg)
        if c["type"] not in ("pip", "single") or c.get("always_ready") is not True or not KEY_RE.match(c.get("main", "")):
            return None
        pip, pip2, pip3, multi = cls._layout(c)
        if c["type"] == "pip" and not pip:
            return None
        cams = [c["main"]] + ([c["pip"]] if pip else []) + ([c["pip2"]] if pip2 else []) + ([c["pip3"]] if pip3 else [])
        return {"cams": cams, "group": len(cams), "audio_pos": -1, "asel": False, "always": True, "live": True, "state": 0, "line": ""}

    @classmethod
    def always_blocker(cls, cfg):
        """Warum "alle Kameras immer bereit" trotz Schalter nicht gilt (Text für die Anzeige), sonst None. Die Sendung läuft dann im normalen Modus weiter."""
        c = cls._safe_cfg(cfg)
        if c.get("always_ready") is not True or cls.always_plan(cfg):
            return None
        return "Alle Kameras immer bereit ist nicht aktiv: Der Bildaufbau passt nicht dazu (Hauptbild fehlt oder Art unbekannt). Die Sendung läuft im normalen Modus."

    AUDIO_POS = {"main": -1, "pip": 0, "pip2": 1, "pip3": 2}

    @classmethod
    def view_values(cls, cfg):
        """Ansicht im Betrieb aus der Einstellung: (ausgeblendet, Tonquelle). ausgeblendet: Bit 0 bis 2 = kleines Bild an Stelle 1 bis 3 ist
        ausgeblendet; Tonquelle: -1 Hauptbild, 0 bis 2 das kleine Bild an dieser Stelle (so, wie der Baustein es versteht)."""
        c = cls._safe_cfg(cfg)
        hide = 0
        for i, k in enumerate(STYLE_SLOTS):
            if not c["styles"][k]["visible"]:
                hide |= 1 << i
        plan = cls.swap_plan(c)
        audio = plan["audio_pos"] if plan else cls.AUDIO_POS.get(c.get("audio", "main"), -1)
        return hide, audio

    @classmethod
    def view_line(cls, cfg, mute=0):
        hide, audio = cls.view_values(cfg)
        return f"{hide} {audio} {1 if mute else 0}"

    def set_view(self, visible=None, audio=None):
        """Sichtbarkeit der kleinen Bilder (visible: {"1": bool, ...}) und Tonquelle (audio: main, pip, pip2, pip3) ändern und speichern.
        Gibt (ausgeblendet, Tonquelle) der neuen Einstellung zurück. Nur bei Bild-in-Bild."""
        with self.lock:
            c = self.cfg
            if c.get("type") != "pip":
                raise ValueError("Das gibt es nur bei der Art Bild-in-Bild")
            if visible is not None:
                if not isinstance(visible, dict) or any(k not in STYLE_SLOTS or not isinstance(v, bool) for k, v in visible.items()):
                    raise ValueError("Bild einblenden: Stelle 1 bis 3, ja oder nein")
                for k, v in visible.items():
                    if k == "2" and not c.get("pip2") or k == "3" and not c.get("pip3") or k == "1" and not c.get("pip"):
                        raise ValueError("Dieses kleine Bild gibt es nicht")
            if audio is not None:
                if not isinstance(audio, str) or audio not in self.AUDIO_POS:
                    raise ValueError("Ton: Hauptbild oder eines der kleinen Bilder")
                if audio == "pip" and not c.get("pip") or audio == "pip2" and not c.get("pip2") or audio == "pip3" and not c.get("pip3"):
                    raise ValueError("Ton: dieses kleine Bild gibt es nicht")
                if audio != "main" and c.get(audio) in (c.get("inactive") or []):
                    raise ValueError("Ton: eine deaktivierte Kamera kann nicht die Tonquelle sein")
            styles = clean_styles(c.get("styles"))
            for k, v in (visible or {}).items():
                styles[k]["visible"] = v
            c["styles"] = styles
            if audio is not None:
                c["audio"] = audio
            self.save()
            return self.view_values(c)

    @staticmethod
    def swap_line(slots, cams, group):
        """Umschaltzeile für die laufende Sendekette aus der Belegung (Hauptbild, kleine Bilder 1 bis 3; "" = leer) und den Kameras
        beim Aufbau. Der Tausch geht nur innerhalb der Gruppe; alles andere bleibt am Platz. None, wenn das nicht passt."""
        slots = [(s or "") for s in slots] + [""] * (4 - len(slots))
        if len(cams) < 2 or group < 2 or group > len(cams) or slots[len(cams):] != [""] * (4 - len(cams)):
            return None
        if sorted(slots[:group]) != sorted(cams[:group]):
            return None
        if any(slots[i] != cams[i] for i in range(group, len(cams))):
            return None
        return " ".join([str(cams.index(slots[0]))] + [str(cams.index(s)) if s else "15" for s in slots[1:]])

    @staticmethod
    def delay_values(cfg, base=None):
        """Verzögerungen in ms je Platz (die Weiche des Platzes hält die Pakete der Kamera zurück, höchstens 750 ms), in der Reihenfolge der Kameras (base: ihre Schlüssel je Platz;
        sonst die Reihenfolge der Einstellung). Die Verzögerung gehört zur Kamera, nicht zum Platz."""
        if cfg.get("type") != "pip":
            return [0, 0, 0, 0]
        slots = ("main", "pip", "pip2", "pip3")
        by_key = {cfg[s]: cfg.get(d, 0) for s, d in zip(slots, DELAY_KEYS) if cfg.get(s)}
        order = list(base) if base else [cfg.get(s) for s in slots]
        vals = []
        for k in (order + [None] * 4)[:4]:
            try:
                vals.append(max(0, min(3000, int(by_key.get(k, 0) or 0))) if k else 0)
            except (TypeError, ValueError):
                vals.append(0)
        return vals

    def build(self, cfg=None, rtmp_port=1935, rtmp_app="publish"):
        """Pipeline-Text für belacoder (Nvidia-Kette mit nvcompositor, siehe pipeline_jetson). Die Schlüssel sind geprüft (a-z, 0-9, -, _)."""
        c = self._safe_cfg(cfg or self.cfg)
        if not KEY_RE.match(c.get("main", "")):
            return ""
        base = f"rtmp://127.0.0.1:{rtmp_port}/{rtmp_app}"
        pip, pip2, pip3, multi = self._layout(c)
        return pipeline_jetson.build(c, base, pip, pip2, pip3, always=bool(self.always_plan(c)))

    def status(self, cams):
        keys = [c["key"] for c in cams]
        return {"config": dict(self.cfg, styles=clean_styles(self.cfg.get("styles"))), "plugin_style": True,
                "style_radius": False,                                      # Eckenrundung gibt es nicht (nvcompositor kennt keine Rundung); die Oberfläche blendet sie aus
                "cameras": [{"key": c["key"], "name": c["name"], "state": c.get("state", "unknown"), "w": c.get("w", 0), "h": c.get("h", 0)} for c in cams],
                "corners": list(PIP_CORNERS), "preview": self.build() if self.cfg.get("main") in keys else "",
                "needs_plugin": self.cfg.get("type") == "pip", "plugin_present": True}


def view_only_change(a, b):
    """Unterscheiden sich zwei Bildaufbau-Einstellungen nur in "Bild einblenden" (je Stelle) und der Tonquelle? Nur das lässt sich in der laufenden
    Sendekette ohne Neustart umschalten."""
    def norm(c):
        c = dict(c)
        c.pop("facecam", None)
        c["audio"] = "main"
        c["styles"] = clean_styles(c.get("styles"))
        for k in STYLE_SLOTS:
            c["styles"][k] = dict(c["styles"][k], visible=True)
        return c
    return a.get("type") == "pip" and norm(a) == norm(b)


def always_compatible(a, b):
    """Gilt eine Änderung der Bildaufbau-Einstellung im Modus "alle Kameras immer bereit" ohne Neustart der Sendekette? Lage, Größe, Ecke, Beschnitt, Rahmen,
    Verzögerung, Ton, Ansicht und welche Kamera an welchem Platz ist, gehen über die Steuerdatei und die Weichen. Nur die Art (eine Kamera, Bild-in-Bild) und die Zahl
    der kleinen Bildern (Pads des Compositors) ändern den Aufbau; eine neue Kamera an einem Platz startet der Sende-Dienst selbst gezielt neu (SlotController.reload).
    Ohne den Schalter bei beiden Einstellungen gilt die Regel nicht."""
    both = a.get("type") in ("pip", "single") and b.get("type") in ("pip", "single") and a.get("always_ready") is True and b.get("always_ready") is True
    return bool(both and a.get("type") == b.get("type") and all(bool(a.get(k)) == bool(b.get(k)) for k in ("pip", "pip2", "pip3")))
