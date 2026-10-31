"""Messwerte der Box: Prozessor, Temperatur, Speicher, Netzverkehr, USB- und Ausfallüberwachung."""

import glob
import json
import math
import os
import random
import re
import subprocess
import threading
import time
try:
    import pipbox_preview
except ImportError:
    pipbox_preview = None

from srv.cameras import HDMI_KEY
from srv.netinfo import NET_PREFIXES, NET_SKIP
from srv.util import read


LIMITS = {"temp_warn": 70.0, "temp_crit": 80.0, "cpu_warn": 85.0, "core_warn": 90.0, "core_hold_s": 10.0, "mem_warn": 85.0}


BC_STATS_FILE = "/run/pipbox-send/belacoder-stats.json"        # vom Sender (belacoder-stats.patch), einmal je Sekunde


THERMAL_NAMES = {"soc-thermal": "SoC", "bigcore0-thermal": "Große Kerne 4–5", "bigcore1-thermal": "Große Kerne 6–7",
                 "littlecore-thermal": "Kleine Kerne 0–3", "center-thermal": "Mitte", "gpu-thermal": "GPU", "npu-thermal": "NPU",
                 # Jetson (Tegra)
                 "CPU-therm": "CPU", "GPU-therm": "GPU", "AO-therm": "Dauerbetrieb (AO)", "PLL-therm": "Taktgeber (PLL)",
                 "PMIC-Die": "Spannungsregler (PMIC)", "thermal-fan-est": "Lüfter-Schätzung"}
# Zonen, die nicht in die Gesamttemperatur eingehen: der PMIC meldet beim Jetson Nano einen festen Wert, die Lüfter-Schätzung ist abgeleitet
THERMAL_NO_MAX = ("PMIC-Die", "thermal-fan-est")


NPU_FILE = "/run/pipbox-npu"


def npu_load():
    """Echte NPU-Auslastung je Kern. Der Frequenzregler der NPU meldet immer 100 %; die richtige Zahl steht nur in debugfs (root).
    Der Dienst pipbox-npu liest sie und legt sie in /run/pipbox-npu ab. Gibt {"load_pct": höchster Kern, "cores": [...]} oder None (fehlt/zu alt)."""
    try:
        d = json.loads(read(NPU_FILE, "") or "")
        cores = [max(0, min(100, int(c))) for c in d["cores"]][:8]
        if cores and abs(time.time() - float(d["t"])) < 15:
            return {"load_pct": max(cores), "cores": cores}
    except (ValueError, KeyError, TypeError):
        pass
    return None


def devfreq_loads():
    """Auslastung der GPU aus /sys/class/devfreq/*/load ("12@300000000Hz"): {"gpu": {...}}; dazu die NPU (echte Last aus npu_load, Takt aus devfreq)."""
    out = {}
    try:
        names = sorted(os.listdir("/sys/class/devfreq"))
    except OSError:
        names = []
    for n in names:
        if "gpu" not in n and "npu" not in n:
            continue
        raw = (read(f"/sys/class/devfreq/{n}/load", "") or "").strip()
        m = re.match(r"^(\d+)@(\d+)Hz$", raw)
        if not m:
            continue
        if "gpu" in n:
            out["gpu"] = {"load_pct": int(m.group(1)), "mhz": int(m.group(2)) // 1000000}
        else:                                                    # NPU: die Prozentzahl von devfreq ist wertlos (immer 100), nur der Takt zählt
            real = npu_load()
            if real:
                out["npu"] = {"load_pct": real["load_pct"], "mhz": int(m.group(2)) // 1000000, "cores": real["cores"]}
    if "gpu" not in out:                  # Jetson (Tegra): Last in Promille unter /sys/devices/gpu.0/load, Takt als cur_freq (Hz) in devfreq
        raw = (read("/sys/devices/gpu.0/load", "") or "").strip()
        if raw.isdigit():
            mhz = 0
            for n in names:
                if "gpu" in n:
                    f = (read(f"/sys/class/devfreq/{n}/cur_freq", "") or "").strip()
                    mhz = int(f) // 1000000 if f.isdigit() else 0
            out["gpu"] = {"load_pct": max(0, min(100, int(round(int(raw) / 10.0)))), "mhz": mhz}
    out.update(tegra_video_loads(names))
    return out


TEGRA_VIDEO = (("vic", "vic"), ("nvdec", "nvdec"), ("nvenc", "nvenc"))     # (Schlüssel, Namensteil unter /sys/devices/platform/host1x)
TEGRA_HOST1X = "/sys/devices/platform/host1x"
_TEGRA = {"units": None, "hist": {}, "thread": None, "lock": threading.Lock()}


def _tegra_units():
    """{Schlüssel: Verzeichnisname} der Video-Einheiten des Jetson, einmal ermittelt; {} ohne Jetson."""
    if _TEGRA["units"] is None:
        found = {}
        try:
            for u in os.listdir(TEGRA_HOST1X):
                for key, part in TEGRA_VIDEO:
                    if u.endswith("." + part) and os.path.exists(f"{TEGRA_HOST1X}/{u}/load"):
                        found[key] = u
        except OSError:
            pass
        _TEGRA["units"] = found
    return _TEGRA["units"]


def _tegra_sampler():
    """Liest die Lastdateien alle 100 ms: ein einzelner Wert ist eine Momentaufnahme (gemessen: 0 bis 854 Promille innerhalb von Sekunden bei gleichmäßiger Last),
    erst der Mittelwert über 2 s ist aussagekräftig (so rechnet auch tegrastats)."""
    units = _tegra_units()
    while True:
        now = time.monotonic()
        for key, u in units.items():
            raw = (read(f"{TEGRA_HOST1X}/{u}/load", "") or "").strip()
            if raw.isdigit():
                with _TEGRA["lock"]:
                    h = _TEGRA["hist"].setdefault(key, [])
                    h.append((now, int(raw)))
                    del h[:-40]
        time.sleep(0.1)


def tegra_video_loads(devfreq_names=()):
    """Jetson: Auslastung der Video-Hardware aus /sys/devices/platform/host1x/<Adresse>.<Einheit>/load (Promille, 2 s gemittelt): Bildwandler VIC (Skalieren,
    Mischen, Farbwandlung), Decoder NVDEC, Encoder NVENC. Takt nur für Einheiten mit devfreq-Eintrag (VIC); die anderen Takte stehen nur in debugfs (root).
    {"vic": {"load_pct", "mhz"}, ...}; leer, wenn es die Dateien nicht gibt (kein Jetson)."""
    units = _tegra_units()
    if not units:
        return {}
    if _TEGRA["thread"] is None:
        _TEGRA["thread"] = threading.Thread(target=_tegra_sampler, daemon=True, name="tegra-last")
        _TEGRA["thread"].start()
    out = {}
    now = time.monotonic()
    with _TEGRA["lock"]:
        for key, u in units.items():
            vals = [v for t, v in _TEGRA["hist"].get(key, []) if now - t <= 2.0]
            if not vals:
                continue
            mhz = None
            if u in devfreq_names:
                f = (read(f"/sys/class/devfreq/{u}/cur_freq", "") or "").strip()
                mhz = int(f) // 1000000 if f.isdigit() else None
            out[key] = {"load_pct": max(0, min(100, int(round(sum(vals) / len(vals) / 10.0)))), "mhz": mhz}
    return out


def disk_usage(path="/"):
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    return {"total_gb": round(total / 1e9, 1), "free_gb": round(free / 1e9, 1), "used_gb": round((total - st.f_bfree * st.f_frsize) / 1e9, 1),
            "used_pct": round(100.0 * (1 - free / total), 1) if total else None}


def send_stats():
    """Kennzahlen der Sendung aus der Datei von belacoder (Bitrate, Laufzeit, Sendepuffer, Verlust, Encoder-Bilder je Sekunde; Neuübertragungen nur für die Nutzdatenrate).
    None, wenn keine frische Datei da ist (Sendung aus oder ältere belacoder-Fassung)."""
    try:
        mtime = os.stat(BC_STATS_FILE).st_mtime
        if time.time() - mtime > 6:
            return None
        d = json.loads(read(BC_STATS_FILE, "") or "{}")
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d:
        return None
    sent = d.get("sent_total")
    out = {k: d.get(k) for k in ("fps", "bitrate_kbps", "rtt_ms", "send_mbps", "snd_buf_pkts", "snd_buf_ms", "retrans_total", "loss_total", "drop_total", "sent_total")}
    out["mtime"] = mtime                    # Zeit der Datei in Sekunden mit Bruchteil (belacoders eigenes Feld "time" ist auf ganze Sekunden abgeschnitten)
    t = d.get("loss_total")
    out["loss_pct"] = round(100.0 * t / sent, 2) if isinstance(t, (int, float)) and isinstance(sent, (int, float)) and sent > 0 and t >= 0 else None
    return out


class UsbWatch:
    """Merkt sich, wenn ein USB-Gerät ausfällt oder abgezogen wird (zum Beispiel der USB-WLAN-Adapter als Sendeweg, ein Router, ein Bluetooth-Stick).
    Quelle ist das Kernel-Protokoll (dmesg, ohne Rechte lesbar): "usb 2-1: USB disconnect", "usb usb2-port1: disabled by hub (EMI?)" und "over-current".
    Die Ereignisse stehen mit Zeit in <state>/usb-events.json (überstehen einen Neustart des Dienstes; ein Ausfall, bei dem die ganze Box stehen bleibt, ist
    für den Kernel nicht zu sehen). Die Oberfläche zeigt sie als Meldung: Art des Geräts (aus dem Produktnamen) und Uhrzeit. Kommt das Gerät wieder (der Kernel
    erkennt am selben Anschluss ein neues Gerät), steht „wieder da“ dabei und die Meldung verschwindet nach BACK_SHOW (5 Minuten ohne neue Trennung); kommt es nicht
    wieder, bleibt sie bis WINDOW (24 Stunden) oder bis der Nutzer sie mit dem × schließt (dismiss).
    Issue #58: In den ersten GRACE Sekunden nach dem Start der Box zählen Trennungen nicht (manche Sticks melden sich beim Hochfahren mehrmals neu an, zum
    Beispiel beim Wechsel des Betriebsmodus); Meldungen aus der Zeit vor dem Neustart erscheinen danach nicht mehr. Die Meldung nennt Namen und Anschluss."""
    WINDOW = 24 * 3600.0
    BACK_SHOW = 300.0
    GRACE = 120.0
    EVERY = 20.0
    KEEP = 20
    RE_LINE = re.compile(r"^(\d{4}-\d\d-\d\dT[\d:.,]+[+-]\d\d:?\d\d) (.*)$")      # Zeitzone mit oder ohne Doppelpunkt (util-linux 2.31 auf dem Jetson schreibt +0000)
    RE_OC = re.compile(r"(?i)(?:soctherm.*OC ALARM|OC ALARM 0x|throttled due to over-?current|system throttled)")      # Überlast der Stromversorgung am Prozessor (Jetson)
    OC_GAP = 60.0                                                              # Meldungen einer Überlast-Serie zählen als ein Ereignis
    RE_PROD = re.compile(r"^usb (\d+-[\d.]+): Product: (.{1,80})$")
    RE_NEW = re.compile(r"^usb (\d+-[\d.]+): new .*USB device number \d+")
    RE_ID = re.compile(r"^usb (\d+-[\d.]+): New USB device found, idVendor=([0-9a-fA-F]{4}), idProduct=([0-9a-fA-F]{4})")
    RE_GONE = re.compile(r"^usb (\d+-[\d.]+): USB disconnect, device number \d+$")
    RE_HUB = re.compile(r"^usb usb(\d+)-port(\d+): (disabled by hub|over-current condition)")
    CATS = (("wlan", re.compile(r"(?i)802\.11|wlan|wireless|wi-?fi|\bnic\b|rtl88|rtl81|ralink|mediatek.*wlan")),
            ("bt", re.compile(r"(?i)bluetooth|\bbt\d|usb-bt")),
            ("net", re.compile(r"(?i)rndis|ethernet|\bcdc\b|router|modem|lte|\b4g\b|\b5g\b|mudi|gl-?inet|tether|android|hotspot|gadget")),
            ("cam", re.compile(r"(?i)camera|uvc|capture|hdmi|video|osmo|action|dji|webcam")))

    def __init__(self, path, runner=None, clock=time.time, demo=False, uptime=None):
        self.path, self.runner, self.clock, self.demo = path, runner or self._dmesg, clock, demo
        self.uptime = uptime or (self._uptime if clock is time.time else (lambda: None))              # mit eigener Uhr (Tests) gibt es keine Startzeit
        self.lock = threading.Lock()
        self.events, self.last = [], 0.0
        self.demo_t, self.demo_closed = clock() - 2100, False              # Vorschau: eine feste Beispielmeldung, die sich schließen lässt
        try:
            with open(path) as f:
                saved = json.load(f)
            if isinstance(saved, list):
                self.events = [e for e in saved if isinstance(e, dict) and isinstance(e.get("t"), (int, float)) and isinstance(e.get("cat"), str)][-self.KEEP:]
        except (OSError, ValueError):
            pass
        boot = self._boot()
        if boot is not None:
            self.events = [e for e in self.events if e["t"] >= boot]                                 # aus der Zeit vor dem Neustart: das Gerät kam mit dem Neustart neu

    @staticmethod
    def _uptime():
        try:
            return float(read("/proc/uptime", "").split()[0])
        except (OSError, ValueError, IndexError):
            return None

    def _boot(self):
        """Zeitpunkt des Starts der Box (Uhr minus Betriebszeit) oder None."""
        up = self.uptime()
        return self.clock() - up if isinstance(up, (int, float)) and up >= 0 else None

    @staticmethod
    def _dmesg():
        try:
            return subprocess.run(["dmesg", "--time-format", "iso"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    @classmethod
    def category(cls, name):
        for cat, rx in cls.CATS:
            if rx.search(name or ""):
                return cat
        return "other"

    def _parse(self, text):
        import datetime
        import compat36
        prod, ids, out, backs = {}, {}, [], []
        boot = self._boot()
        for raw in text.splitlines()[-6000:]:
            m = self.RE_LINE.match(raw)
            if not m:
                continue
            try:
                t = compat36.fromiso(m.group(1)).timestamp()
            except ValueError:
                continue
            msg = m.group(2)
            a = self.RE_PROD.match(msg)
            if a:
                prod[a.group(1)] = a.group(2).strip()
                continue
            n = self.RE_NEW.match(msg)
            if n:
                backs.append((t, n.group(1)))
                continue
            i = self.RE_ID.match(msg)
            if i:
                ids[i.group(1)] = "%s:%s" % (i.group(2).lower(), i.group(3).lower())
                continue
            g = self.RE_GONE.match(msg)
            if g:
                if boot is None or t >= boot + self.GRACE:                                  # in den ersten Sekunden nach dem Start melden sich Geräte oft mehrmals neu an
                    out.append({"t": round(t, 1), "port": g.group(1), "cat": self.category(prod.get(g.group(1), "")), "why": "gone",
                                "name": prod.get(g.group(1), ""), "ids": ids.get(g.group(1), "")})
                continue
            if self.RE_OC.search(msg):
                if boot is None or t >= boot + self.GRACE:
                    last = max((e["t"] for e in out if e["port"] == "soc"), default=None)
                    if last is None or t - last >= self.OC_GAP:
                        out.append({"t": round(t, 1), "port": "soc", "cat": "power", "why": "oc", "name": "", "ids": ""})
                continue
            h = self.RE_HUB.match(msg)
            if h:
                port = "%s-%s" % (h.group(1), h.group(2))
                if boot is None or t >= boot + self.GRACE:
                    out.append({"t": round(t, 1), "port": port, "cat": self.category(prod.get(port, "")), "why": "emi" if h.group(3).startswith("disabled") else "over",
                                "name": prod.get(port, ""), "ids": ids.get(port, "")})
        merged = []
        for e in sorted(out, key=lambda x: x["t"]):                       # Trennung und abgeschalteter Anschluss kurz hintereinander am selben Anschluss: ein Ereignis
            if merged and merged[-1]["port"] == e["port"] and e["t"] - merged[-1]["t"] < 5:
                if e["why"] != "gone":
                    merged[-1]["why"] = e["why"]
                continue
            merged.append(e)
        for e in merged:                                                    # am selben Anschluss wurde danach ein Gerät neu erkannt: wieder da
            for bt, bport in backs:
                if bport == e["port"] and 0 < bt - e["t"] < 3600:
                    e["back"] = round(bt, 1)
                    break
        return merged

    def scan(self):
        """Kernel-Protokoll lesen und neue Ereignisse aufnehmen (höchstens alle EVERY Sekunden)."""
        with self.lock:
            now = self.clock()
            if now - self.last < self.EVERY:
                return
            self.last = now
        try:
            found = self._parse(self.runner())
        except Exception:
            return
        with self.lock:
            have = {(round(e["t"]), e.get("port")): e for e in self.events}
            new = [e for e in found if (round(e["t"]), e["port"]) not in have]
            changed = False
            for f in found:                                                 # ein schon gemerktes Ereignis bekommt nachträglich "wieder da"
                old = have.get((round(f["t"]), f["port"]))
                if old is not None and f.get("back") and not old.get("back"):
                    old["back"] = f["back"]
                    changed = True
            if not new and not changed:
                return
            self.events = (self.events + new)[-self.KEEP:]
            data = list(self.events)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def alerts(self):
        """Meldungen für die Oberfläche: die jüngsten Ereignisse der letzten 24 Stunden (höchstens zwei), je ein Eintrag mit Art und Zeit. Weg sind Meldungen,
        die der Nutzer geschlossen hat, und solche, deren Gerät seit mehr als BACK_SHOW Sekunden wieder da ist."""
        if self.demo:
            return [] if self.demo_closed else [{"level": "warn", "kind": "usb", "cat": "wlan", "why": "emi", "t": int(self.demo_t), "back": False}]
        self.scan()
        now = self.clock()
        with self.lock:
            fresh = [e for e in self.events if now - e["t"] <= self.WINDOW and not e.get("ack") and not (e.get("back") and now - e["back"] > self.BACK_SHOW)]
        return [{"level": "warn", "kind": "usb", "cat": e["cat"], "why": e.get("why", "gone"), "t": int(e["t"]), "back": bool(e.get("back")),
                 "name": str(e.get("name") or "")[:80], "port": str(e.get("port") or "")[:12], "ids": str(e.get("ids") or "")[:9]}
                for e in sorted(fresh, key=lambda x: -x["t"])[:2]]

    def dismiss(self, t):
        """Die Meldung mit dieser Zeit (ganze Sekunden, wie in alerts()) schließen. Gibt zurück, ob eine gefunden wurde."""
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            raise ValueError("Ungültige Anfrage")
        if self.demo:
            self.demo_closed = True
            return True
        found = False
        with self.lock:
            for e in self.events:
                if int(e["t"]) == int(t) and not e.get("ack"):
                    e["ack"] = True
                    found = True
            data = list(self.events)
        if found and not self.demo:
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f)
                os.replace(tmp, self.path)
            except OSError:
                pass
        return found


class OutageWatch:
    """Merkt sich, wenn eine Kamera ausfällt (sie hat gesendet und sendet nicht mehr) oder der HDMI-Eingang kein Signal hat, und liefert kurze Meldungen für die
    Oberfläche: {"kind": "cam"|"hdmi", ...}. Eine Kamera gilt als ausgefallen, wenn sie seit dem Start des Dienstes einmal gesendet hat und jetzt länger als DOWN
    Sekunden nicht mehr; die Meldung verschwindet, sobald sie wieder sendet (oder nach MAX Stunden). Ohne Zustand auf der Platte: nach einem Neustart des Dienstes
    beginnt die Beobachtung neu."""
    DOWN = 20.0
    MAX = 6 * 3600.0

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.seen = {}                 # Kamera-Schlüssel -> hat gesendet
        self.since = {}                # Kamera-Schlüssel -> seit wann nicht mehr (Zeit) oder fehlt
        self.hdmi_since = None
        self.closed = set()            # vom Nutzer mit dem × geschlossene Meldungen: (Art, Zeit des Ausfalls); kommt die Kamera wieder, gilt ein neuer Ausfall wieder

    def dismiss(self, kind, t):
        """Eine Meldung "Kamera ausgefallen" oder "HDMI: kein Signal" schließen (zum Beispiel nach einem bewussten Abziehen). Gibt zurück, ob die Art bekannt ist."""
        if kind not in ("cam", "hdmi") or isinstance(t, bool) or not isinstance(t, (int, float)):
            raise ValueError("Ungültige Anfrage")
        with self.lock:
            self.closed.add((kind, int(t)))
        return True

    def alerts(self, cameras, hdmi=None, parked=()):
        """parked: Schlüssel von Kameras, die der Nutzer bewusst ausgeschaltet hat (im Bildaufbau deaktiviert, DJI getrennt oder ohne automatisches Verbinden): keine Ausfall-Meldung."""
        now = self.clock()
        out = []
        with self.lock:
            self.closed = {c for c in self.closed if now - c[1] <= self.MAX}                 # alte Einträge fallen weg
            keys = set()
            for c in cameras or []:
                key = c.get("key")
                if not isinstance(key, str):
                    continue
                keys.add(key)
                state = c.get("state")
                if key in parked:
                    self.since.pop(key, None)                       # gewollt aus: kein Ausfall; kommt sie zurück und fällt später aus, beginnt die Zeit neu
                    continue
                if state == "live":
                    self.seen[key] = True
                    self.since.pop(key, None)
                elif state == "offline" and self.seen.get(key):
                    self.since.setdefault(key, now)
                    t = self.since[key]
                    if key != HDMI_KEY and now - t >= self.DOWN and now - t <= self.MAX and ("cam", int(t)) not in self.closed:
                        kind = "dji" if str(key).startswith("dji-") else "cam"
                        out.append({"level": "warn", "kind": "cam", "cam": kind, "name": str(c.get("name") or "")[:40], "t": int(t)})
            for k in list(self.seen):
                if k not in keys:
                    self.seen.pop(k, None)
                    self.since.pop(k, None)
            # HDMI-Eingang: Dienst meldet einen Fehler oder (eingeschaltet) kein Signal
            bad = False
            if isinstance(hdmi, dict) and hdmi.get("service") is not False and hdmi.get("available") is not False:
                en = bool((hdmi.get("settings") or {}).get("enabled"))
                sig = hdmi.get("signal") or {}
                bad = hdmi.get("state") == "error" or (en and hdmi.get("signal_known") and sig.get("plugged") is False)
            if bad:
                if self.hdmi_since is None:
                    self.hdmi_since = now
                if self.DOWN <= now - self.hdmi_since <= self.MAX and ("hdmi", int(self.hdmi_since)) not in self.closed:
                    out.append({"level": "warn", "kind": "hdmi", "src": (hdmi.get("settings") or {}).get("source", "hdmi"), "t": int(self.hdmi_since)})
            else:
                self.hdmi_since = None
        return out


class Sampler:
    """Berechnet Raten aus Zählerdifferenzen zwischen zwei Abfragen."""

    # Meldung "n Prozess(e) blockiert (D-State)" (Issue #51): Gezählt wird nicht jede kurze Wartezeit. Beim Start schreibt die Box viel auf die Speicherkarte
    # (apt-get, Journal), dann warten kurz Threads des Dateisystems; das hat mit der Sendung nichts zu tun. Darum: (1) erst GRACE Sekunden nach dem Start, (2) erst
    # wenn SUSTAIN Sekunden am Stück etwas blockiert ist (Messungen mit mehr als GAP Sekunden Abstand zählen nicht als am Stück), (3) ohne Threads, die auf die
    # Speicherkarte oder den CPU-Regler warten. Unbekanntes (zum Beispiel usb-storage, ein Decoder-Treiber) meldet weiter; das Zustandsprotokoll behält alle Namen.
    D_GRACE, D_SUSTAIN, D_GAP = 120.0, 15.0, 6.0
    D_BENIGN_NAME = re.compile(r"^(kworker|jbd2|sugov|apt-get|apt|dpkg|mmcqd|kswapd\d*|flush-|ext4|systemd-journal)")
    D_BENIGN_WCHAN = re.compile(r"(__wait_on_buffer|wait_on_page|io_schedule|mmc_blk|jbd2|generic_file_buffered_read|bit_wait|blk_)")

    def __init__(self, demo):
        self.demo = demo
        self.prev_cpu = None
        self.prev_net = None
        self.prev_t = None
        self.sm_net, self.sm_zero = {}, {}     # geglättete Raten je Netzkarte und Zähler der Messungen ohne Verkehr (smooth_rates)
        self.pay_prev, self.pay_sm, self.pay_zero = None, None, 0   # Nutzdatenrate der Sendung: letzter Stand (Zeit der Datei, Pakete), geglätteter Wert, Messungen ohne Verkehr (payload_rate)
        self._lock = threading.Lock()
        self._d_since, self._d_last = None, 0.0
        self._core_hot_t0 = None       # seit wann ein Kern durchgehend über der Warngrenze liegt (finish)

    # Angezeigte Raten der Netzkarten: gleitender Mittelwert statt Rohwert. Der Sender schickt Bilder in Schüben (SRT-Pacing, WLAN), darum schwankt jede einzelne Messung stark.
    NET_SMOOTH_S = 4.0          # Zeitkonstante: nach einem Sprung der Rate ist die Anzeige nach 4 s noch bei 37 % des Unterschieds, nach 8 s bei 14 %
    NET_SMOOTH_GAP_S = 15.0     # war die letzte Messung länger her (Seite nicht geöffnet), beginnt die Glättung neu mit dem Rohwert
    NET_ZERO_MBIT, NET_ZERO_N = 0.1, 2   # Kommt zweimal hintereinander (rund 3 s) fast nichts, ist es ein Ausfall: die Anzeige springt sofort auf den Rohwert, statt 10 bis 20 s auszulaufen

    def smooth_rates(self, raw, dt_s):
        """Rohe Raten (je Netzkarte rx_mbit/tx_mbit über die Zeit dt_s seit der letzten Messung) glätten; Zeitkonstante NET_SMOOTH_S, unabhängig davon, wie oft abgefragt wird. Ein Ausfall (NET_ZERO_N
        Messungen hintereinander unter NET_ZERO_MBIT) wird nicht geglättet."""
        fresh = dt_s is None or dt_s > self.NET_SMOOTH_GAP_S
        a = 1.0 - math.exp(-max(dt_s or 0.0, 0.0) / self.NET_SMOOTH_S)
        out, new, zeros = {}, {}, {}
        for n, r in raw.items():
            p = None if fresh else self.sm_net.get(n)
            cur = {}
            for k in ("rx_mbit", "tx_mbit"):
                z = (self.sm_zero.get((n, k), 0) + 1) if r[k] < self.NET_ZERO_MBIT else 0
                zeros[(n, k)] = z
                cur[k] = r[k] if (p is None or z >= self.NET_ZERO_N) else p[k] + (r[k] - p[k]) * a
            new[n] = cur
            out[n] = {k: round(v, 2) for k, v in cur.items()}
        self.sm_net, self.sm_zero = new, zeros
        return out

    SRT_PAYLOAD_BYTES = 1316    # Nutzdaten je SRT-Paket (7 TS-Pakete zu 188 Byte; belacoder ohne Option -r)

    def payload_rate(self, send):
        """Nutzdatenrate der Sendung in Mbit/s (Video und Ton, ohne Kopfdaten (IP, UDP, SRT, SRTLA) und ohne Neuübertragungen): Zuwachs von sent_total - retrans_total aus der Kennzahlen-Datei von belacoder
        (SRT zählt in sent_total auch die Neuübertragungen, pktSentTotal), mal 1316 Byte je Paket, geteilt durch die Zeit zwischen zwei Ständen der Datei (mtime mit Bruchteil; belacoder schreibt einmal je
        Sekunde, die Zeit der Abfrage wäre ungenau), danach wie die Netzraten geglättet. Das ist, was belacoder an srtla_send übergibt; die Anzeige nimmt nie mehr als auf der Leitung gesendet wird. None ohne laufende Sendung und bis zum zweiten Stand."""
        def num(k):
            v = send.get(k) if isinstance(send, dict) else None
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        t, sent, retr = num("mtime"), num("sent_total"), num("retrans_total")
        if t is None or sent is None or sent < 0:
            self.pay_prev, self.pay_sm, self.pay_zero = None, None, 0
            return None
        unique = sent - (retr if retr is not None and 0 <= retr <= sent else 0.0)
        cur, prev = (t, unique), self.pay_prev
        if prev is not None and t <= prev[0]:
            return None if self.pay_sm is None else round(self.pay_sm, 2)              # Datei noch nicht erneuert (oder Uhr zurück): der letzte Wert gilt weiter
        self.pay_prev = cur
        dt = None if prev is None else t - prev[0]
        if dt is None or dt > self.NET_SMOOTH_GAP_S or unique < prev[1]:               # erster Wert, lange Pause (Uhrsprung, Sendung lange aus) oder Zähler zurückgesetzt (belacoder neu gestartet)
            self.pay_sm, self.pay_zero = None, 0
            return None
        raw = (unique - prev[1]) * self.SRT_PAYLOAD_BYTES * 8 / dt / 1e6
        if self.pay_sm is None:
            self.pay_sm = raw
        elif raw < self.NET_ZERO_MBIT and self.pay_zero + 1 >= self.NET_ZERO_N:       # zweimal fast nichts: Ausfall, nicht glätten
            self.pay_sm = raw
        else:
            self.pay_sm += (raw - self.pay_sm) * (1.0 - math.exp(-dt / self.NET_SMOOTH_S))
        self.pay_zero = self.pay_zero + 1 if raw < self.NET_ZERO_MBIT else 0
        return round(self.pay_sm, 2)

    @classmethod
    def d_relevant(cls, names):
        """Aus den Namen blockierter Threads ("Name@Wartestelle") die, die nicht nur auf Speicherkarte oder CPU-Regler warten."""
        return [n for n in (names or []) if not (cls.D_BENIGN_NAME.match(n) or cls.D_BENIGN_WCHAN.search(n.partition("@")[2]))]

    def _d_alert(self, rel, now, uptime):
        """Anzahl der Threads für die Meldung: 0 in der Schonzeit nach dem Start und solange nichts lange genug am Stück blockiert war."""
        if not rel:
            self._d_since = None
            return 0
        if self._d_since is None or now - self._d_last > self.D_GAP:
            self._d_since = now
        self._d_last = now
        if uptime is not None and uptime < self.D_GRACE:
            return 0
        return len(rel) if now - self._d_since >= self.D_SUSTAIN else 0

    def cpu_times(self):
        out = []
        for line in (read("/proc/stat", "") or "").splitlines():
            if line.startswith("cpu") and line[3:4].isdigit():
                v = list(map(int, line.split()[1:]))
                idle = v[3] + (v[4] if len(v) > 4 else 0)
                out.append((sum(v), idle))
        return out

    @staticmethod
    def fan_pwm():
        """Ansteuerung des Lüfters (PWM 0..255) oder None. Das ist der Sollwert, keine gemessene Drehzahl:
        die Box hat keinen Drehzahlanschluss am Lüfter."""
        try:
            for d in sorted(os.listdir("/sys/class/hwmon")):
                base = f"/sys/class/hwmon/{d}"
                if "pwmfan" in (read(base + "/name", "") or "").strip():          # "pwmfan" (Rockchip) oder "tegra_pwmfan" (Jetson)
                    for fn in ("pwm1", "cur_pwm"):
                        v = read(base + "/" + fn)
                        if v is not None and 0 <= int(v) <= 255:
                            return int(v)
                    return None
        except (OSError, ValueError):
            pass
        return None

    _fan_driven = False
    FAN_FILE = None                         # Datei mit der Wahl "Lüfter am Anschluss der Box" (setzt server.py: <Zustandsordner>/fan.json)
    FAN_MODES = ("auto", "yes", "no")

    @classmethod
    def fan_mode(cls):
        """Wahl des Benutzers: "auto" (Zeile nur, wenn der Ausgang angesteuert wird), "yes" (Lüfter steckt am Anschluss: Zeile immer) oder "no" (Lüfter extern, zum
        Beispiel über USB gespeist: Zeile nie). Ohne Datei "auto"."""
        try:
            with open(cls.FAN_FILE) as f:
                m = json.load(f).get("mode")
            return m if m in cls.FAN_MODES else "auto"
        except (OSError, ValueError, TypeError, AttributeError):
            return "auto"

    @classmethod
    def set_fan_mode(cls, mode):
        if mode not in cls.FAN_MODES:
            raise ValueError("Lüfter am Anschluss: automatisch, ja oder nein")
        if not cls.FAN_FILE:
            raise ValueError("Nicht verfügbar")
        tmp = cls.FAN_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        with os.fdopen(fd, "w") as f:
            json.dump({"mode": mode}, f)
        os.replace(tmp, cls.FAN_FILE)
        return mode

    def fan_shown(self, pwm):
        """Jetson: Die Lüfterzeile erscheint nur, wenn die Box den Lüfter wirklich ansteuert. Der Jetson Nano meldet den PWM-Ausgang auch dann, wenn gar kein Lüfter
        am Anschluss steckt oder ein externer Lüfter den Kühlkörper bläst; es gibt weder eine Drehzahl noch eine Steckererkennung. Bleibt der Ausgang auf 0 (die
        automatische Regelung des Kernels schaltet erst bei höheren Temperaturen ein), ist die Zeile unnötig und verwirrt. Sobald er einmal größer als 0 war, bleibt
        sie bis zum Neustart des Dienstes sichtbar. Rockchip: unverändert."""
        if pwm is None or not os.path.exists("/etc/nv_tegra_release"):
            return pwm
        mode = self.fan_mode()
        if mode == "no":
            return None                     # Lüfter extern (zum Beispiel USB): die Box steuert ihn nicht, die Zeile wäre irreführend
        if mode == "yes":
            return pwm
        if pwm > 0:
            self._fan_driven = True
        return pwm if self._fan_driven else None

    @staticmethod
    def blocked_threads(proc="/proc", limit=20):
        """Threads im Kernel-Zustand D (nicht unterbrechbar) mit Wartestelle im Kernel: ["usb-storage@usb_sg_wait", ...]. Zeigt, WER hinter der Meldung
        "n Prozess(e) blockiert" steckt (oft ein USB-Modem, das sich zusätzlich als CD-Laufwerk meldet, oder der Treiber eines Geräts)."""
        out = []
        for d in sorted(glob.glob(proc + "/[0-9]*/task/[0-9]*")):
            t = read(d + "/stat", "") or ""
            i = t.rfind(")")
            if i < 0 or t[i + 2:i + 3] != "D":
                continue
            name = t[t.find("(") + 1:i].replace(" ", "_")
            wchan = (read(d + "/wchan", "") or "").strip()
            out.append("%s@%s" % (name, wchan if wchan and wchan != "0" else "?"))
            if len(out) >= limit:
                break
        return out

    def net_bytes(self):
        res = {}
        for line in (read("/proc/net/dev", "") or "").splitlines()[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            if name.startswith(NET_PREFIXES) and not name.startswith(NET_SKIP) and \
                    (read(f"/sys/class/net/{name}/operstate", "") or "").strip() in ("up", "unknown"):
                f = rest.split()
                res[name] = (int(f[0]), int(f[8]))
        if pipbox_preview:
            res = pipbox_preview.TRAFFIC.adjust(res)            # der Verkehr der Vorschau zum Browser zählt nicht zum Upload der Sendung
        return res

    def sample(self):
        """Messwerte. Liegt die letzte Messung keine 1,5 s zurück (zweiter Tab, mehrere Abfragen), gilt sie weiter:
        sonst würden die Raten über sehr kurze Zeiträume berechnet und die Arbeit doppelt gemacht."""
        if self.demo:
            return self.sample_demo()
        with self._lock:
            hit = getattr(self, "_last", None)
            if hit is not None and time.monotonic() - hit[0] < 1.5:
                return dict(hit[1])                      # flache Kopie: der Abrufer ergänzt Schlüssel und Meldungen, das darf den Zwischenspeicher nicht verändern (zweiter Tab: Meldungen doppelt)
            val = self.sample_real()
            self._last = (time.monotonic(), val)
            return dict(val)

    def sample_real(self):
        now = time.time()
        cpu, net = self.cpu_times(), self.net_bytes()
        cores, rates = [], {}
        if self.prev_cpu and len(self.prev_cpu) == len(cpu):
            for (t1, i1), (t0, i0) in zip(cpu, self.prev_cpu):
                dt = max(t1 - t0, 1)
                cores.append(round(100.0 * (1 - (i1 - i0) / dt), 1))
        dt_s = (now - self.prev_t) if self.prev_t else None
        if self.prev_net and dt_s:
            for n, (rx, tx) in net.items():
                p = self.prev_net.get(n)
                if p:
                    rates[n] = {"rx_mbit": max(0.0, round((rx - p[0]) * 8 / dt_s / 1e6, 2)),
                                "tx_mbit": max(0.0, round((tx - p[1]) * 8 / dt_s / 1e6, 2))}
        rates = self.smooth_rates(rates, dt_s)
        self.prev_cpu, self.prev_net, self.prev_t = cpu, net, now

        freqs = []
        i = 0
        while True:
            v = read(f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq")
            if v is None:
                break
            freqs.append(int(v) // 1000)
            i += 1
        temps = []
        z = 0
        while True:
            v = read(f"/sys/class/thermal/thermal_zone{z}/temp")
            if v is None:
                break
            temps.append(int(v) / 1000.0)
            z += 1
        mem = {}
        for line in (read("/proc/meminfo", "") or "").splitlines():
            k, _, v = line.partition(":")
            mem[k] = int(v.split()[0]) if v.split() else 0
        total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
        blocked = 0
        for line in (read("/proc/stat", "") or "").splitlines():
            if line.startswith("procs_blocked"):
                blocked = int(line.split()[1])
        zones, counted = [], []
        for zi in range(len(temps)):
            zt = (read(f"/sys/class/thermal/thermal_zone{zi}/type", "") or "").strip()
            zones.append({"name": THERMAL_NAMES.get(zt, zt or f"Zone {zi}"), "c": round(temps[zi], 1)})
            if zt not in THERMAL_NO_MAX:
                counted.append(temps[zi])
        hottest = max(counted) if counted else (max(temps) if temps else None)
        out = self.finish(cores, freqs, hottest,
                          total, avail, rates, blocked, self.fan_shown(self.fan_pwm()), self.blocked_threads() if blocked > 0 else None)
        send = send_stats()
        out["details"] = {"temps": zones, "accel": devfreq_loads(), "disk": disk_usage("/"), "send": send}
        out["payload_mbit"] = self.payload_rate(send)
        return out

    def sample_demo(self):
        t = time.time()
        cores = [round(max(2, min(99, 45 + 35 * math.sin(t / 7 + k) +
                                  random.uniform(-6, 6))), 1) for k in range(8)]
        freqs = [1800 if k >= 4 else 1416 for k in range(8)]
        temp = 52 + 8 * math.sin(t / 30) + random.uniform(-0.5, 0.5)
        rates = {"eth0": {"rx_mbit": 0.4, "tx_mbit": round(6 + random.uniform(-1, 1), 2)},
                 "eth1": {"rx_mbit": round(13 + random.uniform(-1, 1), 2),
                          "tx_mbit": round(5 + random.uniform(-1, 1), 2)}}
        out = self.finish(cores, freqs, temp, 16 * 1024 * 1024,
                          int(7.4 * 1024 * 1024), rates, 0, int(110 + 40 * math.sin(t / 30)))
        out["details"] = {
            "temps": [{"name": n, "c": round(temp + d + random.uniform(-0.4, 0.4), 1)} for n, d in
                      (("SoC", 0), ("Große Kerne 4–5", 2), ("Große Kerne 6–7", 1.5), ("Kleine Kerne 0–3", -3), ("Mitte", 0), ("GPU", -5), ("NPU", -6))],
            "accel": {"gpu": {"load_pct": int(12 + 8 * math.sin(t / 5)), "mhz": 600},
                      "npu": {"load_pct": int(30 + 20 * math.sin(t / 7)), "mhz": 1000, "cores": [int(30 + 20 * math.sin(t / 7)), int(10 + 8 * math.sin(t / 4)), 0]}},
            "disk": {"total_gb": 62.8, "free_gb": 55.5, "used_gb": 4.6, "used_pct": 8.7},
            "send": {"fps": 29.9, "bitrate_kbps": 9800, "rtt_ms": round(38 + 6 * math.sin(t / 9), 1), "send_mbps": round(9.7 + random.uniform(-0.5, 0.5), 2),
                     "snd_buf_pkts": int(30 + 20 * random.random()), "snd_buf_ms": int(25 + 15 * random.random()), "loss_total": 37,
                     "drop_total": 0, "sent_total": 90210, "loss_pct": 0.04}}
        return out

    def _core_sustained(self, cpu_max, now):
        """Ein einzelner Kern darf kurz voll sein (die Verfolgung der Köpfe rechnet nach jedem Durchgang einen Schub): gemeldet wird erst, wenn er
        LIMITS["core_hold_s"] Sekunden am Stück über der Grenze liegt. Fällt der Wert darunter, beginnt die Zählung neu."""
        if cpu_max is None or cpu_max < LIMITS["core_warn"]:
            self._core_hot_t0 = None
            return False
        if self._core_hot_t0 is None:
            self._core_hot_t0 = now
        return now - self._core_hot_t0 >= LIMITS["core_hold_s"]

    def finish(self, cores, freqs, temp, total_kb, avail_kb, rates, blocked, fan_pwm=None, blocked_names=None, now=None, uptime=None):
        cpu_avg = round(sum(cores) / len(cores), 1) if cores else None
        cpu_max = max(cores) if cores else None
        mem_used = round(100.0 * (1 - avail_kb / total_kb), 1) if total_kb else None
        alerts = []
        if temp is not None and temp >= LIMITS["temp_crit"]:
            alerts.append({"level": "crit", "text": f"Temperatur {temp:.0f} °C"})
        elif temp is not None and temp >= LIMITS["temp_warn"]:
            alerts.append({"level": "warn", "text": f"Temperatur {temp:.0f} °C"})
        core_hot = self._core_sustained(cpu_max, time.monotonic() if now is None else now)    # immer aufrufen, damit die Zählung auch bei hoher Gesamtlast mitläuft
        if cpu_avg is not None and cpu_avg >= LIMITS["cpu_warn"]:
            alerts.append({"level": "warn", "text": f"CPU-Last {cpu_avg:.0f} %"})
        elif core_hot:
            alerts.append({"level": "warn", "text": f"Ein CPU-Kern ist fast voll ({cpu_max:.0f} %)"})
        if mem_used is not None and mem_used >= LIMITS["mem_warn"]:
            alerts.append({"level": "warn", "text": f"RAM {mem_used:.0f} % belegt"})
        rel = self.d_relevant(blocked_names) if blocked > 0 else []
        up = uptime
        if up is None and not self.demo:
            try:
                up = float((read("/proc/uptime", "") or "").split()[0])
            except (ValueError, IndexError):
                up = None
        n = self._d_alert(rel, time.monotonic() if now is None else now, up)
        if n > 0:
            alerts.append({"level": "warn", "text": f"{n} Prozess(e) blockiert (D-State)", "kind": "dstate", "names": rel[:6]})
        return {"time": int(time.time()), "demo": self.demo,
                "cpu": {"cores": cores, "avg": cpu_avg, "max": cpu_max, "freq_mhz": freqs},
                "temp_c": None if temp is None else round(temp, 1),
                "fan_pct": None if fan_pwm is None else round(100.0 * fan_pwm / 255),   # Ansteuerung, keine Drehzahl
                "mem": {"used_pct": mem_used, "avail_mb": avail_kb // 1024,
                        "total_mb": total_kb // 1024},
                "net": rates, "procs_blocked": blocked, "alerts": alerts,
                # Platzhalter bis die Pipeline echte Werte liefert
                "encoder": {"fps": 29.9, "bitrate_mbit": 9.8, "max_mbit": 12}
                if self.demo else None}
