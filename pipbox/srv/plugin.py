"""Bildbaustein der Sendekette: Funktionen und Dateien der Engine (Ecken, Tausch, Ansicht, Stil)."""

import os
import shutil


PIP_CORNERS = ("oben links", "oben rechts", "unten links", "unten rechts", "unten Mitte", "frei (verschiebbar)")


FREE = 5                      # Nummer von "frei": Position aus x/y (Promille)


PLUGIN_SO = "/opt/pipbox/gst/libgstpbpip.so"


SEND_STATUS = "/run/pipbox-send/status.json"


VIEW_FILE = "main-view"                 # Datei im Zustandsordner: "ausgeblendet Tonquelle stumm" (liest der Baustein pbctl, siehe gst/gstpbpip.c)


VIEW_STATE = "/run/pipbox-send/view-state"   # hier meldet pbctl zurück, was wirklich gilt


SWAP_SELECT = "main-select"            # Datei im Zustandsordner: welche Kamera ist Hauptbild (liest der Baustein pbctl)


SWAP_STATE = "/run/pipbox-send/swap-state"   # hier meldet pbctl zurück, was er eingestellt hat


_CENTER = {"mtime": None, "ok": True, "free": True}


def jetson():
    """Läuft das hier auf einem Jetson (L4T)? Dort gibt es keinen Rockchip-Baustein: Mischen, Tausch, Füllbild und Ansicht im Betrieb macht die Nvidia-Kette
    (nvcompositor mit Steuerdatei, pipbox_always.SlotController). Die Prüfungen unten fragen deshalb nicht nach der Datei des Bausteins."""
    return os.path.exists("/etc/nv_tegra_release")


def pip_corners():
    """Wählbare Positionen. "unten Mitte" und "frei" nur, wenn der installierte Baustein sie kennt (sonst landet das Bild oben links). Jetson: alle (pipeline_jetson.place)."""
    if jetson():
        return PIP_CORNERS
    try:
        mt = os.stat(PLUGIN_SO).st_mtime
        if _CENTER["mtime"] != mt:
            with open(PLUGIN_SO, "rb") as f:
                data = f.read()
            _CENTER.update(mtime=mt, ok=b"4 unten Mitte" in data, free=b"5 frei" in data)
    except OSError:
        return PIP_CORNERS          # kein Baustein (Entwicklungsrechner, Demo): alle anzeigen
    if not _CENTER["ok"]:
        return PIP_CORNERS[:4]
    return PIP_CORNERS if _CENTER["free"] else PIP_CORNERS[:5]


_MULTI = {"mtime": None, "ok": True}


def plugin_multi():
    """Kennt der installierte Baustein den gemeinsamen Mischer für bis zu drei kleine Bilder (Eigenschaft "slot3")?
    Ein alter Baustein (z. B. wenn der Neubau beim Update scheiterte) bekommt die alte Form mit zwei Mischern. Jetson: ja (nvcompositor, ein Pad je Platz)."""
    if jetson():
        return True
    try:
        mt = os.stat(PLUGIN_SO).st_mtime
        if _MULTI["mtime"] != mt:
            with open(PLUGIN_SO, "rb") as f:
                _MULTI.update(mtime=mt, ok=b"slot3" in f.read())
    except OSError:
        return True
    return _MULTI["ok"]


_SWAP = {"mtime": None, "ok": True}


def plugin_swap():
    """Kennt der installierte Baustein den Umschalter für den Tausch ohne Unterbrechung (pbpipsel)? Ohne Baustein (Entwicklungsrechner) ja.
    Jetson: ja (Tausch über Rollen in der Steuerdatei, jede Kamera behält ihren Decoder)."""
    if jetson():
        return True
    try:
        mt = os.stat(PLUGIN_SO).st_mtime
        if _SWAP["mtime"] != mt:
            with open(PLUGIN_SO, "rb") as f:
                data = f.read()
            _SWAP.update(mtime=mt, ok=b"pbpipsel" in data and b"follow-tag" in data)
    except OSError:
        return True
    return _SWAP["ok"]


_FILL = {"mtime": None, "ok": True}


FEED_PORT = 9410            # "alle Kameras immer bereit": Zubringer je Platz (0 bis 3) geben Bild an Port FEED_PORT + 2*Platz und Ton an +1 weiter (nur Loopback)


FEED_VIDEO_CAPS = "application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000"


FEED_AUDIO_CAPS = "audio/x-raw,format=S16LE,rate=48000,channels=2,layout=interleaved"


FEED_FILL_VIDEO = "video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1"


CAM_LIVE = "/run/pipbox-send/cam-live"       # pbctl meldet hier, welche Plätze gerade Bilder liefern ("1 0 1 0")


def plugin_fill():
    """Kann der installierte Baustein den Ausgang bei fehlendem Eingang füllen (Eigenschaft fill-caps von pbpipsel)? Ohne Baustein (Entwicklungsrechner) ja.
    Jetson: ja (Füllbild und Stille je Platz über die Weiche, pipbox_relay)."""
    if jetson():
        return True
    try:
        mt = os.stat(PLUGIN_SO).st_mtime
        if _FILL["mtime"] != mt:
            with open(PLUGIN_SO, "rb") as f:
                data = f.read()
            _FILL.update(mtime=mt, ok=b"fill-caps" in data and b"live-file" in data)
    except OSError:
        return True
    return _FILL["ok"]


def feeder_tool():
    """Pfad von gst-launch-1.0 (Paket gstreamer1.0-tools) oder None: Die Zubringer von "alle Kameras immer bereit" brauchen es. Ein frisches BELABOX-Image bringt es nicht mit."""
    return shutil.which("gst-launch-1.0")


_VIEW = {"mtime": None, "ok": True}


VIEW_ENABLED = True          # Ansicht im Betrieb (Issue #19): Fußleiste am Handy; ohne passenden Baustein (plugin_view) bleibt es beim Neustart


def plugin_view():
    """Kennt der installierte Baustein die Ansicht im Betrieb (Eigenschaften "view-file" und "view-state-file" von pbctl: kleine Bilder
    ein-/ausblenden, Tonquelle, stumm ohne Neustart), und ist sie eingeschaltet (VIEW_ENABLED)? Ohne Baustein (Entwicklungsrechner) ja.
    Jetson: ja (der SlotController setzt alpha und volume der Pads über die Steuerdatei und meldet in view-state zurück)."""
    if not VIEW_ENABLED:
        return False
    if jetson():
        return True
    try:
        mt = os.stat(PLUGIN_SO).st_mtime
        if _VIEW["mtime"] != mt:
            with open(PLUGIN_SO, "rb") as f:
                data = f.read()
            _VIEW.update(mtime=mt, ok=b"view-file" in data and b"view-state-file" in data)
    except OSError:
        return True
    return _VIEW["ok"]


_STYLE = {"mtime": None, "ok": True}


def plugin_style():
    """Kennt der installierte Baustein Beschnitt, Deckkraft und Rahmen je kleinem Bild (Eigenschaften "style1" bis "style3")?
    Ein alter Baustein (z. B. wenn der Neubau beim Update scheiterte) würde die Eigenschaft nicht kennen und die Sendekette
    nicht starten: dann bleibt sie aus dem Pipeline-Text weg. Ohne Baustein (Entwicklungsrechner) ja. Jetson: ja (Beschnitt über den nvvidconv des Platzes,
    Rahmen als Farbfläche im Compositor, beides im Betrieb über die Steuerdatei; nur die Eckenrundung gibt es dort nicht)."""
    if jetson():
        return True
    try:
        mt = os.stat(PLUGIN_SO).st_mtime
        if _STYLE["mtime"] != mt:
            with open(PLUGIN_SO, "rb") as f:
                data = f.read()
            _STYLE.update(mtime=mt, ok=b"style1" in data and b"style3" in data)
    except OSError:
        return True
    return _STYLE["ok"]
