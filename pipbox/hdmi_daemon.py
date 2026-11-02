#!/usr/bin/env python3
"""USB-Kamera-Dienst (pipbox-hdmi.service): speist eine USB-Kamera (UVC-Webcam, zum Beispiel eine DJI Osmo Action im USB-Modus oder ein HDMI-USB-Grabber) als Kamera in den RTMP-Eingang der Box ein.

Die USB-Kamera wird dadurch zu einer ganz normalen Kamera ("rtmp://127.0.0.1/publish/<Schlüssel>", wie eine RTMP- oder DJI-Kamera): Sie steht in der Kameraliste, im Status
und im Bildaufbau, kann Hauptbild oder kleines Bild sein und springt bei Ausfall des Hauptbildes ein. Die Sendekette bleibt unverändert. Der Name "hdmi" (Dienst, Schlüssel, Dateien
hdmi.json und hdmi-token) stammt aus der Anfangszeit und bleibt, damit gespeicherte Einstellungen und Kameralisten weiter passen; der Jetson hat keinen HDMI-Eingang.

Der Dienst sucht die erste angeschlossene USB-Kamera, die sich als UVC-Webcam meldet (Treiber uvcvideo, Videoknoten mit Nummer 0 der Kamera), probiert der Reihe nach Bildformate
durch (MJPEG 1080p30, MJPEG 720p30, H.264 1080p30, RAW 720p30, RAW 480p30; jeweils mit einem kurzen Probelauf gegen fakesink), nimmt das erste, das geht, und startet einen
gst-launch-Prozess: MJPEG wird in der Video-Hardware dekodiert und mit nvv4l2h264enc neu kodiert, H.264 geht unverändert durch. Der Ton kommt vom USB-Mikrofon derselben Kamera
(ALSA-Karte mit gleicher USB-Adresse), sonst Stille. Endet der Prozess oder wechselt das Gerät, startet er neu; ohne Kamera läuft nichts.

Läuft als root (die Hardware-Kodierer und /dev/snd sind nur für root zugänglich), getrennt von der Weboberfläche.
Schnittstelle: nur 127.0.0.1, JSON-Zeilen über TCP. Jede Anfrage braucht das Token aus <state>/hdmi-token (nur der Benutzer pipbox
kann es lesen). Der Dienst nimmt nur geprüfte Zahlen und feste Auswahlen entgegen und baut den Befehl selbst (keine Shell).
"""
import argparse
import asyncio
import collections
import hmac
import json
import logging
import os
import pwd
import re
import secrets
import signal
import subprocess
import time
import urllib.request

LISTEN_HOST, LISTEN_PORT = "127.0.0.1", 9102
RTMP_PORT = 1935
RTMP_APP = "publish"
STAT_URL = "http://127.0.0.1:1936/"                      # nginx-rtmp-Statistik
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")       # wie in der Weboberfläche
DEFAULTS = {"enabled": False, "key": "hdmi", "bitrate": 8000, "fps": 30, "audio": "hdmi", "source": "usb", "usb_format": "auto"}      # audio "hdmi" = Ton der Kamera (der Wert bleibt, weil er in gespeicherten Einstellungen steht)
SOURCE_CHOICES = ("usb", "test")                         # Quelle der Einspeisung: die USB-Kamera oder das eingebaute Testbild (läuft ohne Kamera, prüft die ganze Kette bis zum Server)
TEST_SIZE = (1280, 720)
TEST_TONES = ((440, "0x1"), (660, "0x2"))                # Testton: links 440 Hz, rechts 660 Hz (Kanalmaske des Interleavers)
USB_FORMAT_CHOICES = ("auto", "mjpeg", "h264")           # Bildformat der USB-Webcam: Automatisch (MJPEG zuerst), MJPEG oder H.264 zuerst; das andere bleibt als Rückfall
SYS_V4L = "/sys/class/video4linux"
PROC_ASOUND = "/proc/asound"
SYS_USB = "/sys/bus/usb/devices"
DJI_VENDOR = "2ca3"                                      # USB-Hersteller-ID von DJI
POWER_WINDOW = 180.0                                     # Sekunden, in denen wiederholtes Auftauchen ohne Webcam-Bild als Stromproblem zählt
POWER_STAY = 10.0                                        # Sekunden, die eine DJI-Kamera ohne Webcam-Bild am USB hängen darf
USB_POWER_TEXT = "Die Kamera meldet sich nur kurz am USB und trennt sich wieder, meist fehlt ihr Strom. Bitte einen USB-Hub mit eigenem Netzteil verwenden."
PROBE_TIMEOUT = 8.0                                      # Sekunden je Probelauf eines Bildformats
# Bildformate einer USB-Webcam in der Reihenfolge, in der sie probiert werden: (Art, Breite, Höhe, Bildrate)
USB_CANDIDATES = (("mjpeg", 1920, 1080, 30), ("mjpeg", 1280, 720, 30), ("h264", 1920, 1080, 30), ("h264", 1280, 720, 30), ("rawhd", 1920, 1080, 30), ("raw", 1280, 720, 30), ("raw", 640, 480, 30))      # MJPEG zuerst: Es kodiert die Box mit der eingestellten Bitrate (Action 5 Pro: H.264 aus der Kamera nur 1,3 Mbit/s in 1080p, MJPEG-Bild 52 Mbit/s, nach dem Kodierer der Box ~8 Mbit/s)
USB_BAD_AFTER = 3                                        # so oft hintereinander schnell gescheitert: dieses Format wird nicht mehr genommen, das nächste kommt dran
PROBE_RETRY_PAUSE = 1.0                                  # Sekunden vor dem zweiten Probelauf (die Kamera ist direkt nach dem Stoppen der Einspeisung manchmal kurz belegt)
BITRATE_RANGE = (1000, 20000)                            # kbit/s
FPS_CHOICES = (25, 30)
AUDIO_CHOICES = ("hdmi", "none")                              # "hdmi": Ton der USB-Kamera, "none": ohne Ton
MUX_LATENCY_NS = 300000000                              # Wartezeit des Muxers (flvmux) der USB-Einspeisung: ohne sie wirft er Bilder weg, die gegenüber dem Ton zu spät sind (gemessen mit der Action 4: nur 21 bis 24 statt 30 Bilder je Sekunde im RTMP-Strom, Lücken bis 1,1 s). Mit 200 bis 300 ms genau 30,0 fps, Abstand 33,3 ms
NICE = 0                                                 # Die Einspeisung der USB-Kamera läuft mit normaler Priorität: mit nice 10 wurde sie bei hoher Last der Box ausgebremst und lieferte im RTMP-Strom nur 23 bis 30 statt 30 Bilder je Sekunde (gemessen bei laufender Sendung, 4 von 4 Läufen mit nice 0: genau 30,0 fps)
GRACE = 15.0                                             # so lange darf der Stream brauchen, bis nginx ihn zeigt
STALL = 12.0                                             # so lange darf er danach fehlen, bevor neu gestartet wird
BACKOFF = (2.0, 4.0, 8.0, 15.0, 30.0)                    # Wartezeit nach einem Ende des Prozesses
STABLE = 30.0                                            # danach zählt der Lauf als stabil (Zähler der Fehlstarts wird gelöscht)
TICK = 1.0

log = logging.getLogger("pipbox-hdmi")


# ---------------------------------------------------------------- reine Funktionen (ohne Hardware, gut testbar)
def no_signal():
    """Zustand "keine Kamera": das Bild der USB-Kamera heißt im Dienst "Signal" (Breite, Höhe, Bildrate, Gerät)."""
    return {"plugged": False, "locked": False, "width": 0, "height": 0, "fps": 0.0, "interlaced": False, "format": "", "depth": 0}


def signal_id(sig):
    """Was sich ändern darf, ohne dass die Einspeisung neu starten muss: nichts. Wechselt das Bildformat (oder bei USB das Gerät), startet sie neu."""
    return (sig.get("width"), sig.get("height"), round(float(sig.get("fps") or 0)), bool(sig.get("interlaced")), sig.get("device"))


def clean_settings(d, current=None):
    """Geprüfte Einstellungen. Unbekannte Schlüssel werden ignoriert, falsche Werte gemeldet (ValueError mit kurzem deutschem Text)."""
    cur = dict(DEFAULTS)
    cur.update(current or {})
    if not isinstance(d, dict):
        raise ValueError("Ungültige Anfrage")
    out = dict(cur)
    if "enabled" in d:
        if not isinstance(d["enabled"], bool):
            raise ValueError("Einschalten: ja oder nein")
        out["enabled"] = d["enabled"]
    if "key" in d:
        k = d["key"]
        if not isinstance(k, str) or not KEY_RE.match(k) or k.startswith("test-"):
            raise ValueError("Schlüssel: nur a-z, 0-9, - und _, höchstens 32 Zeichen, nicht mit test- beginnen")
        out["key"] = k
    if "bitrate" in d:
        b = d["bitrate"]
        if isinstance(b, bool) or not isinstance(b, int) or not BITRATE_RANGE[0] <= b <= BITRATE_RANGE[1]:
            raise ValueError("Bitrate: %d bis %d kbit/s" % BITRATE_RANGE)
        out["bitrate"] = b
    if "fps" in d:
        if isinstance(d["fps"], bool) or d["fps"] not in FPS_CHOICES:
            raise ValueError("Bildrate: 25 oder 30")
        out["fps"] = d["fps"]
    if "audio" in d:
        if d["audio"] not in AUDIO_CHOICES:
            raise ValueError("Ton: Ton der Kamera oder ohne Ton")
        out["audio"] = d["audio"]
    if "source" in d:
        if d["source"] not in SOURCE_CHOICES:
            raise ValueError("Quelle: USB-Kamera oder Testbild")
        out["source"] = d["source"]
    if "usb_format" in d:
        if d["usb_format"] not in USB_FORMAT_CHOICES:
            raise ValueError("Bildformat: Automatisch, MJPEG oder H.264")
        out["usb_format"] = d["usb_format"]
    return out


# Die Tonquelle der USB-Kamera darf nicht der Takt der ganzen Sendekette sein: alsasrc liefert sonst standardmäßig den Takt (provide-clock=true),
# und der Takt der Kamera läuft gegenüber dem der Box (gemessen 12./13. Oktober 2026: etwa 0,44 ms je Sekunde). Die Zeitstempel des Bildes folgen dann diesem Takt, belacoder
# vergleicht sie mit seiner Uhr, und der Versatz der Kamera wuchs gleichmäßig von -0,1 auf +1,5 s in etwa einer Stunde, bis der Verzugs-Schutz den Zweig herausnahm.
# Mit provide-clock=false gilt der Systemtakt; der Ton wird per Neuberechnung (resample) an ihn angepasst.
ALSA_CLOCK = ["provide-clock=false", "slave-method=resample"]


def _read(path, limit=200):
    try:
        with open(path, errors="replace") as f:
            return f.read(limit).strip()
    except OSError:
        return ""


def find_uvc_cameras(sysfs=SYS_V4L):
    """USB-Webcams am Kernel: Videoknoten mit Treiber uvcvideo und Nummer 0 der Kamera (die zweite, "Metadaten", wird übergangen). Ergebnis, nach Knoten sortiert:
    [{"node": "/dev/video2", "name": "...", "bus": "1", "dev": "4", "id": "2ca3:0021"}]."""
    out = []
    try:
        names = sorted(os.listdir(sysfs), key=lambda n: (len(n), n))
    except OSError:
        return out
    for n in names:
        if not re.match(r"^video\d{1,3}$", n):
            continue
        base = os.path.join(sysfs, n)
        if _read(os.path.join(base, "index")) not in ("", "0"):
            continue
        iface = os.path.realpath(os.path.join(base, "device"))
        if os.path.basename(os.path.realpath(os.path.join(iface, "driver"))) != "uvcvideo":
            continue
        usb = os.path.dirname(iface)
        out.append({"node": "/dev/" + n, "name": _read(os.path.join(base, "name"), 80) or "USB-Kamera", "bus": _read(os.path.join(usb, "busnum"), 8),
                    "dev": _read(os.path.join(usb, "devnum"), 8),
                    "id": (_read(os.path.join(usb, "idVendor"), 8) + ":" + _read(os.path.join(usb, "idProduct"), 8)).lower()})
    return out


def find_dji_devices(sysusb=SYS_USB):
    """DJI-Geräte am USB, auch solche ohne Webcam-Bild (Zustand 2ca3:0025, DJI-eigener Modus). Ergebnis: [{"dev": "5-1.3.2", "num": "19", "id": "2ca3:0025"}]."""
    out = []
    try:
        names = sorted(os.listdir(sysusb))
    except OSError:
        return out
    for n in names:
        base = os.path.join(sysusb, n)
        if _read(os.path.join(base, "idVendor"), 8).lower() != DJI_VENDOR:
            continue
        out.append({"dev": n, "num": _read(os.path.join(base, "devnum"), 8), "id": (DJI_VENDOR + ":" + _read(os.path.join(base, "idProduct"), 8)).lower()})
    return out


def find_usb_audio(cam, asound=PROC_ASOUND):
    """ALSA-Karte desselben USB-Geräts wie die Kamera (gleiche Bus- und Gerätenummer, "usbbus" der Karte). Ergebnis: "plughw:CARD=<id>" oder None."""
    if not (cam and cam.get("bus") and cam.get("dev")):
        return None
    try:
        cards = sorted(os.listdir(asound))
    except OSError:
        return None
    want = "%03d/%03d" % (int(cam["bus"]), int(cam["dev"])) if str(cam["bus"]).isdigit() and str(cam["dev"]).isdigit() else None
    for c in cards:
        if not re.match(r"^card\d{1,2}$", c):
            continue
        if want and _read(os.path.join(asound, c, "usbbus"), 16) == want:
            cid = _read(os.path.join(asound, c, "id"), 40)
            if re.match(r"^[A-Za-z0-9_]{1,40}$", cid):
                return "plughw:CARD=" + cid
    return None


def usb_candidates(fmt):
    """Reihenfolge der Bildformate: "mjpeg" und "h264" ziehen ihre Art vor, die anderen bleiben als Rückfall; sonst (Automatisch) die Standardreihenfolge."""
    if fmt in ("mjpeg", "h264"):
        return tuple(sorted(USB_CANDIDATES, key=lambda c: c[0] != fmt))        # stabil: innerhalb gleicher Art bleibt die Reihenfolge (1080p vor 720p)
    return USB_CANDIDATES


def usb_caps(cand):
    """Beschreibung eines Bildformats für Anzeige und gst: (Text, Caps-Zeichenkette)."""
    kind, w, h, f = cand
    media = {"mjpeg": "image/jpeg", "h264": "video/x-h264", "raw": "video/x-raw", "rawhd": "video/x-raw"}[kind]
    label = {"mjpeg": "MJPEG", "h264": "H.264", "raw": "RAW", "rawhd": "RAW"}[kind]
    if kind == "rawhd":                     # HDMI-USB-Grabber (zum Beispiel Elgato Cam Link 4K): die Bildrate bestimmt die HDMI-Quelle (25, 30, 50, 60), die Box rechnet sie in _usb_decode auf f herunter
        return "%s %dx%d@%d" % (label, w, h, f), "%s,width=%d,height=%d" % (media, w, h)
    return "%s %dx%d@%d" % (label, w, h, f), "%s,width=%d,height=%d,framerate=%d/1" % (media, w, h, f)


def _usb_decode(kind, fps=30):
    """Teil der Pipeline hinter der Quelle bis zum rohen Bild (für den Probelauf und die Einspeisung). Jetson: MJPEG dekodiert der Hardware-Dekoder (nvv4l2decoder mjpeg=1, Bild in NVMM). nvjpegdec
    schaffte mit einer echten Kamera (Osmo Action 4, 1080p30 über USB 2.0) nur etwa 5 Bilder je Sekunde bei fast 100 % Systemzeit im Aufnahme-Thread, der Hardware-Dekoder über 28 (gemessen: 120 Bilder
    in 24 s gegen 4,4 s). Rohbilder wandelt videoconvert in I420; H.264 bleibt vorerst ein Strom (Dekoder und Kodierer folgen in der Einspeisung).
    "rawhd" (HDMI-USB-Grabber, 1080p unkomprimiert, zum Beispiel YUY2): videorate rechnet die Bildrate der Quelle auf fps herunter, die Umwandlung der Farbformate macht danach nvvidconv in der
    Video-Hardware (gemessen am Cam Link 4K: 30 Bilder je Sekunde bei einer Quelle mit 50 Hz, rund 13 % eines Kerns)."""
    if kind == "mjpeg":
        return ["jpegparse", "!", "nvv4l2decoder", "mjpeg=1"]
    if kind == "h264":
        return ["h264parse", "config-interval=-1"]
    if kind == "rawhd":
        return ["videorate", "!", "video/x-raw,framerate=%d/1" % fps]
    return ["videoconvert", "!", "video/x-raw,format=I420"]


NVMM_NV12 = "video/x-raw(memory:NVMM),format=NV12"


def _nv_encode(cfg, fps):
    """Hardware-Kodierer der Einspeisung (Jetson): Bild kommt als rohes Bild im Systemspeicher oder in NVMM (MJPEG: vom Hardware-Dekoder), nvvidconv bringt es nach NVMM/NV12. Alle Sekunde ein IDR-Bild
    (idrinterval; der Standard wäre alle 256 Bilder, ein Empfänger wartete dann bis zu 8,5 s auf sein erstes Bild)."""
    return ["nvvidconv", "!", NVMM_NV12, "!", "nvv4l2h264enc", "bitrate=%d" % (cfg["bitrate"] * 1000), "iframeinterval=%d" % fps, "idrinterval=%d" % fps,
            "insert-sps-pps=true", "!", "h264parse", "config-interval=-1"]


def usb_probe_argv(device, cand):
    """Probelauf: drei Bilder aus der Kamera holen und bis zum Dekoder durchreichen (der Hardware-Kodierer der Sendung bleibt unberührt)."""
    if not re.match(r"^/dev/video\d{1,3}$", device or ""):
        raise ValueError("Gerät ungültig")
    return ["gst-launch-1.0", "-q", "v4l2src", "device=" + device, "num-buffers=3", "!", usb_caps(cand)[1], "!"] + _usb_decode(cand[0], cand[3]) + ["!", "fakesink"]


def usb_feeder_argv(cfg, device, cand, audio_device=None, rtmp_port=RTMP_PORT, rtmp_app=RTMP_APP):
    """Befehl der Einspeisung einer USB-Webcam als Liste (keine Shell). MJPEG, Rohbild und H.264 mit Füllzeilen (Action 6, 1080p) werden mit dem Hardware-Kodierer neu kodiert, übriges H.264 geht unverändert durch.
    audio_device: "plughw:CARD=<id>" oder None (dann Stille, auch bei cfg["audio"] == "none")."""
    cfg = clean_settings(cfg)
    if not re.match(r"^/dev/video\d{1,3}$", device or ""):
        raise ValueError("Gerät ungültig")
    if audio_device is not None and not re.match(r"^plughw:CARD=[A-Za-z0-9_]{1,40}$", audio_device):
        raise ValueError("Tongerät ungültig")
    if not (isinstance(rtmp_app, str) and re.match(r"^[a-z0-9_]{1,20}$", rtmp_app)) or not isinstance(rtmp_port, int):
        raise ValueError("RTMP-Ziel ungültig")
    kind = cand[0]
    fps = cand[3]
    v = ["v4l2src", "device=" + device, "!", usb_caps(cand)[1], "!"] + _usb_decode(kind, fps) + ["!"]
    if kind == "h264":                                  # H.264 geht unverändert durch (kein Neukodieren, keine Last auf der Video-Hardware)
        v += ["queue", "!", "mux."]
    else:
        v += ["queue", "!"] + _nv_encode(cfg, fps) + ["!", "queue", "!", "mux."]
    if cfg["audio"] == "hdmi" and audio_device:
        a = ["alsasrc", "device=" + audio_device] + ALSA_CLOCK + ["!", "audioconvert", "!", "audioresample", "!", "audio/x-raw,rate=48000,channels=2", "!",
             "voaacenc", "bitrate=128000", "!", "aacparse", "!", "queue", "!", "mux."]
    else:
        a = ["audiotestsrc", "wave=silence", "is-live=true", "!", "audio/x-raw,rate=48000,channels=2", "!",
             "voaacenc", "bitrate=128000", "!", "aacparse", "!", "queue", "!", "mux."]
    sink = ["flvmux", "name=mux", "streamable=true", "latency=%d" % MUX_LATENCY_NS, "!", "rtmpsink", "location=rtmp://127.0.0.1:%d/%s/%s" % (rtmp_port, rtmp_app, cfg["key"])]
    return ["gst-launch-1.0", "-q"] + v + a + sink


def test_feeder_argv(cfg, rtmp_port=RTMP_PORT, rtmp_app=RTMP_APP):
    """Befehl der Einspeisung des Testbilds als Liste (keine Shell): bewegter Ball mit Text und Laufzeit (Systemspeicher), dann der Hardware-Kodierer wie bei der USB-Kamera. Ton: Stereo-Testton
    (links 440 Hz, rechts 660 Hz, zwei Mono-Quellen über interleave), bei "ohne Ton" Stille. Gleiche Form wie in der BOX, nur der Kodierer ist hier nvv4l2h264enc."""
    cfg = clean_settings(cfg)
    if not (isinstance(rtmp_app, str) and re.match(r"^[a-z0-9_]{1,20}$", rtmp_app)) or not isinstance(rtmp_port, int):
        raise ValueError("RTMP-Ziel ungültig")
    w, h = TEST_SIZE
    fps = cfg["fps"]
    v = ["videotestsrc", "is-live=true", "pattern=ball", "!", "video/x-raw,format=NV12,width=%d,height=%d,framerate=%d/1" % (w, h, fps), "!",
         "textoverlay", "text=IRL4YOU BOX Testbild", "valignment=top", "halignment=left", "font-desc=Monospace 28", "!",
         "timeoverlay", "valignment=bottom", "halignment=left", "font-desc=Monospace 28", "!"] + _nv_encode(cfg, fps) + ["!", "queue", "!", "mux."]
    if cfg["audio"] == "hdmi":
        a = []
        for pad, (freq, mask) in enumerate(TEST_TONES):
            a += ["audiotestsrc", "is-live=true", "wave=sine", "freq=%d" % freq, "volume=0.1", "!", "audio/x-raw,rate=48000,channels=1,channel-mask=(bitmask)%s" % mask, "!",
                  "queue", "!", "il.sink_%d" % pad]
        a += ["interleave", "name=il", "!", "audio/x-raw,rate=48000,channels=2", "!"]
    else:
        a = ["audiotestsrc", "is-live=true", "wave=silence", "!", "audio/x-raw,rate=48000,channels=2", "!"]
    a += ["voaacenc", "bitrate=128000", "!", "aacparse", "!", "queue", "!", "mux."]
    sink = ["flvmux", "name=mux", "streamable=true", "latency=%d" % MUX_LATENCY_NS, "!", "rtmpsink", "location=rtmp://127.0.0.1:%d/%s/%s" % (rtmp_port, rtmp_app, cfg["key"])]
    return ["gst-launch-1.0", "-q"] + v + a + sink


def rtmp_publishing(key, stat_url=None):
    """True, wenn gerade jemand zu rtmp://<Box>/publish/<key> sendet (nginx-rtmp-Statistik). None, wenn sie nicht lesbar ist."""
    try:
        with urllib.request.urlopen(stat_url or STAT_URL, timeout=2) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r"<stream>\s*<name>\s*%s\s*</name>[\s\S]*?</stream>" % re.escape(key), body)
    return bool(m and "<publishing/>" in m.group(0))


def friendly_error(lines):
    """Kurzer deutscher Text aus den letzten Zeilen von gst-launch."""
    text = " ".join(lines)[-600:]
    low = text.lower()
    if "no such device" in low or "cannot identify device" in low or "could not open" in low or "device busy" in low or "streamon" in low:
        return "Die USB-Kamera ist nicht erreichbar oder wird schon benutzt"
    if "busy" in low and ("alsa" in low or "audio" in low or "snd" in low):
        return "Das Tongerät ist belegt"
    if "rtmp" in low and ("connect" in low or "could not" in low or "failed" in low):
        return "Keine Verbindung zum RTMP-Eingang der Box"
    if ("nvv4l2" in low or "nvjpeg" in low or "nvvidconv" in low) and ("fail" in low or "error" in low):
        return "Der Hardware-Kodierer meldet einen Fehler"
    return "Die Einspeisung wurde beendet" + (": " + re.sub(r"\s+", " ", lines[-1])[:120] if lines else "")


# ---------------------------------------------------------------- Dienst
class Daemon:
    def __init__(self, state_dir, rtmp_port=RTMP_PORT, rtmp_app=RTMP_APP, stat_url=STAT_URL,
                 spawn=None, publishing=None, clock=time.monotonic,
                 sysfs=SYS_V4L, asound=PROC_ASOUND, probe=None, sysusb=SYS_USB):
        self.state_dir = state_dir
        self.config_file = os.path.join(state_dir, "hdmi.json")
        self.token_path = os.path.join(state_dir, "hdmi-token")
        self.rtmp_port, self.rtmp_app, self.stat_url = rtmp_port, rtmp_app, stat_url
        self._spawn = spawn or self._spawn_process
        self._publishing = publishing or (lambda key: rtmp_publishing(key, self.stat_url))
        self.clock = clock
        self.sysfs, self.asound, self.sysusb = sysfs, asound, sysusb
        self.dji_seen = {}                                                                      # Gerätenummer -> (erstmals, zuletzt gesehen) einer DJI-Kamera ohne Webcam-Bild
        self._probe_run = probe or self._probe_process
        self.usb = {"present": False, "name": "", "node": "", "format": "", "audio": "", "power": False}      # Zustand der USB-Webcam (die USB-Kamera)
        self.usb_choice = None                                                                  # (Knoten, Bildformat) des letzten gelungenen Probelaufs
        self.usb_bad = set()                                                                    # (Knoten, Bildformat), die in der Einspeisung wiederholt schnell scheiterten
        self.usb_cur = None                                                                     # (Knoten, Bildformat) der laufenden Einspeisung
        self.usb_quick_fails = 0
        self.token = self._load_token()
        self.cfg = self.load()
        self.state, self.message = "off", ""
        self.signal = no_signal()
        self.signal_known = False
        self.proc = None
        self.tail = collections.deque(maxlen=12)
        self.started = 0.0
        self.sig_at_start = None
        self.fails = 0
        self.next_try = 0.0
        self.published = None
        self.missing_since = None
        self.restarts = 0
        self.closing = False
        self._reader = None

    # -- Dateien
    def _load_token(self):
        try:
            with open(self.token_path) as f:
                t = f.read().strip()
            if len(t) >= 32:
                return t
        except OSError:
            pass
        t = secrets.token_urlsafe(32)
        fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(t + "\n")
        try:                                    # die Weboberfläche (Benutzer pipbox) muss es lesen können
            pw = pwd.getpwnam("pipbox")
            os.chown(self.token_path, pw.pw_uid, pw.pw_gid)
        except (KeyError, PermissionError):
            pass
        return t

    def load(self):
        try:
            with open(self.config_file) as f:
                saved = json.load(f)
            return clean_settings(saved)
        except (OSError, ValueError):
            return dict(DEFAULTS)

    def save(self):
        tmp = self.config_file + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.cfg, f, indent=1)
        os.replace(tmp, self.config_file)

    # -- Hardware
    @staticmethod
    def _probe_process(argv):
        """Probelauf einer Bildquelle: True, wenn gst-launch ohne Fehler endet."""
        try:
            return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=PROBE_TIMEOUT).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _usb_pick(self):
        """Die erste USB-Webcam (oder None) und ihr Ton."""
        cams = find_uvc_cameras(self.sysfs)
        return cams[0] if cams else None

    def _usb_power_problem(self, cam):
        """True, wenn eine DJI-Kamera am USB hängt, sich aber nicht als Webcam meldet: entweder immer wieder kurz auftaucht oder lange so stehen bleibt (meist Strommangel)."""
        now = self.clock()
        if cam:
            self.dji_seen.clear()
            return False
        here = set()
        for d in find_dji_devices(self.sysusb):
            here.add(d["num"])
            first, _ = self.dji_seen.get(d["num"], (now, now))
            self.dji_seen[d["num"]] = (first, now)
        for num in [n for n, (_, last) in self.dji_seen.items() if now - last > POWER_WINDOW]:
            del self.dji_seen[num]
        stays = any(now - first >= POWER_STAY for num, (first, _) in self.dji_seen.items() if num in here)
        return len(self.dji_seen) >= 2 or stays

    def _usb_waiting_message(self):
        return USB_POWER_TEXT if self.usb.get("power") else "Keine USB-Kamera angeschlossen"

    def _usb_choose_format(self, cam):
        """Erstes Bildformat, das die Kamera liefert (Probelauf, blockiert bis zu einigen Sekunden). Ein früheres Ergebnis für denselben Knoten gilt weiter."""
        if self.usb_choice and self.usb_choice[0] == cam["node"]:
            return self.usb_choice[1]
        for cand in usb_candidates(self.cfg.get("usb_format")):
            if (cam["node"], cand) in self.usb_bad:
                continue
            argv = usb_probe_argv(cam["node"], cand)
            if self._probe_run(argv) or (self._pause(PROBE_RETRY_PAUSE) or self._probe_run(argv)):      # ein zweiter Versuch, bevor auf ein schlechteres Format zurückgegriffen wird
                self.usb_choice = (cam["node"], cand)
                return cand
            log.info("Das Bildformat %s lässt sich von dieser Kamera nicht abholen, die Box nimmt das nächste", usb_caps(cand)[0])
        self.usb_choice = None
        return None

    @staticmethod
    def _pause(seconds):
        time.sleep(seconds)

    def _usb_note_failure(self):
        """Die Einspeisung ist schnell gescheitert: nach USB_BAD_AFTER Fehlern hintereinander wird dieses Bildformat übergangen (das nächste kommt dran)."""
        if not self.usb_cur or self.clock() - self.started >= STABLE:
            self.usb_quick_fails = 0
            return
        self.usb_quick_fails += 1
        if self.usb_quick_fails >= USB_BAD_AFTER:
            self.usb_bad.add(self.usb_cur)
            if self.usb_choice == self.usb_cur:
                self.usb_choice = None
            self.usb_quick_fails = 0
            log.warning("Das Bildformat %s läuft nicht stabil, die Box nimmt das nächste", usb_caps(self.usb_cur[1])[0])

    async def read_signal(self):
        """Die erste USB-Kamera und, wenn ihr Bildformat schon feststeht, dessen Größe und Bildrate als "Signal". Beim Testbild: immer ein Signal (feste Größe, Bildrate aus den Einstellungen), ohne Kamera."""
        if self.cfg.get("source") == "test":
            self.signal_known = True
            sig = no_signal()
            sig.update(plugged=True, locked=True, width=TEST_SIZE[0], height=TEST_SIZE[1], fps=float(self.cfg["fps"]), device="test")
            self.usb = dict(self.usb, power=False, present=False, name="", node="", format="", audio="")
            return sig
        cam = self._usb_pick()
        self.signal_known = True
        sig = no_signal()
        if cam:
            f = self.usb_choice[1] if self.usb_choice and self.usb_choice[0] == cam["node"] else None
            sig.update(plugged=True, locked=True, width=f[1] if f else 0, height=f[2] if f else 0, fps=float(f[3]) if f else 0.0, device=cam["node"])
        self.usb = dict(self.usb, power=self._usb_power_problem(cam), present=bool(cam), name=cam["name"] if cam else "", node=cam["node"] if cam else "",
                        format=usb_caps(self.usb_choice[1])[0] if cam and self.usb_choice and self.usb_choice[0] == cam["node"] else "")
        return sig

    async def _spawn_process(self, argv):
        return await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            preexec_fn=lambda: os.nice(NICE))

    async def _drain(self, proc):
        """Die letzten Zeilen von stderr merken (für die Fehlermeldung)."""
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                self.tail.append(line.decode("utf-8", "replace").strip())
        except Exception:
            pass

    async def _usb_argv(self):
        """Befehl der Einspeisung für die USB-Webcam und das gewählte Bildformat, oder (None, None) (der Fehler ist dann gemeldet)."""
        cam = self._usb_pick()
        if cam is None:
            return None, None
        loop = asyncio.get_event_loop()
        cand = await loop.run_in_executor(None, self._usb_choose_format, cam)
        if cand is None:
            self._failed("Die Kamera liefert kein Bild. Sie muss eingeschaltet und im Webcam-Modus sein (an der Kamera: USB-Modus „Webcam“). Bei einem HDMI-USB-Grabber muss die HDMI-Quelle ein Bild senden.")
            return None, None
        audio = find_usb_audio(cam, self.asound) if self.cfg["audio"] == "hdmi" else None
        self.usb = dict(self.usb, present=True, name=cam["name"], node=cam["node"], format=usb_caps(cand)[0], audio=(audio or ""))
        return usb_feeder_argv(self.cfg, cam["node"], cand, audio, self.rtmp_port, self.rtmp_app), cand

    async def _start(self, sig):
        test = self.cfg.get("source") == "test"
        if test:
            argv, self.usb_cur = test_feeder_argv(self.cfg, self.rtmp_port, self.rtmp_app), None
        else:
            argv, cand = await self._usb_argv()
            if argv is None:
                return
            self.usb_cur = (self.usb["node"], cand)
            sig = dict(sig, width=cand[1], height=cand[2], fps=float(cand[3]), device=self.usb["node"])     # das gewählte Format ist ab jetzt "das Signal" (sonst Neustart beim nächsten Durchgang)
        self.tail.clear()
        try:
            self.proc = await self._spawn(argv)
        except Exception as e:
            self.proc = None
            self._failed("Start nicht möglich: %s" % (str(e) or e.__class__.__name__))
            return
        self.started = self.clock()
        self.sig_at_start = signal_id(sig)
        self.published, self.missing_since = None, None
        self.state, self.message = "starting", ""
        if getattr(self.proc, "stderr", None) is not None:
            self._reader = asyncio.ensure_future(self._drain(self.proc))
        log.info("Einspeisung gestartet (%s, %dx%d@%s, %d kbit/s, Schlüssel %s)", "Testbild" if test else "USB-Kamera", sig.get("width") or 0, sig.get("height") or 0,
                 sig.get("fps") or "?", self.cfg["bitrate"], self.cfg["key"])

    async def _stop(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), 3)
                except Exception:
                    pass
            except ProcessLookupError:
                pass
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        log.info("Einspeisung beendet")

    def _failed(self, message):
        self.fails += 1
        wait = BACKOFF[min(self.fails - 1, len(BACKOFF) - 1)]
        self.next_try = self.clock() + wait
        self.state, self.message = "error", message
        log.warning("%s (nächster Versuch in %d s)", message, wait)

    # -- ein Durchgang der Überwachung
    async def tick(self):
        if self.closing:
            return
        sig = await self.read_signal()
        self.signal = sig
        running = self.proc is not None and self.proc.returncode is None
        if self.proc is not None and not running:             # der Prozess ist von selbst zu Ende gegangen
            rc = self.proc.returncode
            if self._reader is not None:
                try:
                    await asyncio.wait_for(self._reader, 1)
                except Exception:
                    pass
            self.proc, self._reader = None, None
            if self.clock() - self.started >= STABLE:
                self.fails = 0
            self._usb_note_failure()
            self._failed(friendly_error(list(self.tail)) if rc else "Die Einspeisung wurde beendet")
            self.restarts += 1
            return
        if not self.cfg["enabled"]:
            if running:
                await self._stop()
            self.state, self.message, self.fails = "off", "", 0
            return
        if self.signal_known and not sig["locked"]:
            if running:
                await self._stop()
            self.state, self.message, self.fails = "waiting", self._usb_waiting_message(), 0
            return
        if running:
            if self.signal_known and signal_id(sig) != self.sig_at_start:
                log.info("Bildformat hat gewechselt, die Einspeisung startet neu")
                await self._stop()
                self.next_try = self.clock()
                self.state = "starting"
                return
            await self._watch_stream()
            return
        if self.clock() < self.next_try:
            return                                            # Wartezeit nach einem Fehler: Zustand "error" bleibt stehen
        await self._start(sig)

    async def _watch_stream(self):
        now = self.clock()
        loop = asyncio.get_event_loop()
        pub = await loop.run_in_executor(None, self._publishing, self.cfg["key"])
        self.published = pub
        age = now - self.started
        if pub is None:                                       # Statistik nicht lesbar: dem Prozess vertrauen
            if age >= 5:
                self.state, self.message = "streaming", ""
            return
        if pub:
            self.missing_since = None
            self.state, self.message = "streaming", ""
            if age >= STABLE:
                self.fails = 0
            return
        if age < GRACE:
            self.state = "starting"
            return
        if self.missing_since is None:
            self.missing_since = now
        if now - self.missing_since >= STALL:
            log.warning("Der Stream erscheint nicht im RTMP-Eingang, die Einspeisung startet neu")
            await self._stop()
            self.restarts += 1
            self._failed("Der Stream kommt nicht in der Box an")

    # -- Schnittstelle
    def status(self):
        s = {"ok": True, "state": self.state, "message": self.message, "settings": dict(self.cfg), "usb": dict(self.usb),
             "signal": {k: self.signal[k] for k in ("plugged", "locked", "width", "height", "fps", "interlaced", "format", "depth")},
             "signal_known": self.signal_known, "publishing": self.published, "restarts": self.restarts}
        return s

    async def handle(self, req):
        cmd = req.get("cmd")
        if cmd == "status":
            return self.status()
        if cmd == "set":
            new = clean_settings(req.get("settings"), self.cfg)
            changed = new != self.cfg
            if new.get("usb_format") != self.cfg.get("usb_format"):
                self.usb_choice, self.usb_bad, self.usb_quick_fails = None, set(), 0       # neues Bildformat: neu probieren
            self.cfg = new
            self.save()
            if changed and self.proc is not None:             # neue Werte gelten sofort: Einspeisung neu starten
                await self._stop()
                self.next_try = self.clock()
            if changed:
                self.fails = 0
            return self.status()
        if cmd == "restart":
            await self._stop()
            self.fails, self.next_try = 0, self.clock()
            return self.status()
        return {"error": "Unbekannter Befehl"}

    async def client(self, reader, writer):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                req = None
                try:
                    req = json.loads(line)
                    if not isinstance(req, dict):
                        raise ValueError("Ungültige Anfrage")
                    if not hmac.compare_digest(str(req.get("token", "")), self.token):
                        resp = {"error": "kein Zugriff"}
                    else:
                        resp = await self.handle(req)
                except Exception as e:
                    resp = {"error": str(e) or "Ungültige Anfrage"}
                resp["reply_to"] = req.get("id") if isinstance(req, dict) else None
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    async def supervise(self):
        while not self.closing:
            try:
                await self.tick()
            except Exception:
                log.exception("Fehler in der Überwachung")
            await asyncio.sleep(TICK)

    async def shutdown(self):
        self.closing = True
        await self._stop()

    async def main(self, host=LISTEN_HOST, port=LISTEN_PORT):
        server = await asyncio.start_server(self.client, host, port)
        log.info("bereit auf %s:%d", host, port)
        asyncio.ensure_future(self.supervise())
        async with server:
            await server.serve_forever()


async def amain(args):
    daemon = Daemon(args.state, args.rtmp_port, args.rtmp_app, args.stat_url)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass
    main_task = asyncio.ensure_future(daemon.main(LISTEN_HOST, args.port))
    stopper = asyncio.ensure_future(stop.wait())
    await asyncio.wait({main_task, stopper}, return_when=asyncio.FIRST_COMPLETED)
    if stop.is_set():
        log.info("wird beendet")
        try:
            await asyncio.wait_for(daemon.shutdown(), 10)
        except Exception as e:
            log.info("Beenden unvollständig: %s", e)
        logging.shutdown()
        os._exit(0)
    stopper.cancel()
    main_task.cancel()
    if not main_task.cancelled() and main_task.done() and main_task.exception():
        raise main_task.exception()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="/var/lib/pipbox")
    ap.add_argument("--port", type=int, default=LISTEN_PORT)
    ap.add_argument("--rtmp-port", type=int, default=RTMP_PORT)
    ap.add_argument("--rtmp-app", default=RTMP_APP)
    ap.add_argument("--stat-url", default=STAT_URL)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.get_event_loop().run_until_complete(amain(args))


if __name__ == "__main__":
    main()
