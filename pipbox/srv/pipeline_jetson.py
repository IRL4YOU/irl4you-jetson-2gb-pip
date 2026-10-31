"""Pipeline-Text für belacoder auf dem Jetson Nano (Nvidia-Hardware statt Rockchip).

Aufbau wie die Jetson-Pipelines des BELABOX-Pakets (belacoder-pipelines-tegra): RTMP von nginx, Hardware-Decoder nvv4l2decoder, H.265 mit
nvv4l2h265enc, MPEG-TS an den appsink. Bild-in-Bild macht nvcompositor (Mischen in der Videohardware, ohne dass die CPU die Bilder liest).
belacoder findet die Elemente über ihre Namen: v_delay, a_delay, venc_bps und appsink.
"""

import os

from srv.plugin import FEED_AUDIO_CAPS, FEED_PORT, FEED_VIDEO_CAPS
from srv.style import CROP_KEEP, CROP_REF_H, CROP_REF_W, STYLE_COLOR_RE, STYLE_DEFAULT, pip_size

FRAME_PAD0 = 4              # Pads sink_4 bis sink_6 des Compositors: Rahmen (Farbfläche) hinter dem kleinen Bild an Stelle 1 bis 3
FRAME_SRC = "video/x-raw,format=I420,width=64,height=36,framerate=10/1"     # winzige Farbfläche, der Compositor zieht sie auf die Rahmengröße


def place(corner, mw, mh, pw, ph, margin, fx, fy):
    """Position des kleinen Bildes auf der Leinwand mw x mh: 0 oben links, 1 oben rechts, 2 unten links, 3 unten rechts, 4 unten Mitte,
    5 frei (fx, fy in Promille des freien Wegs). Dieselbe Rechnung wie in der Oberfläche (Vorschau des Bildaufbaus)."""
    if corner == 5:
        fx, fy = max(0, min(1000, fx)), max(0, min(1000, fy))
        x, y = (mw - pw) * fx // 1000, (mh - ph) * fy // 1000
        return max(0, x), max(0, y)
    if corner == 4:
        x, y = (mw - pw) // 2, mh - ph - margin
    else:
        x = mw - pw - margin if corner & 1 else margin
        y = mh - ph - margin if corner & 2 else margin
    return max(0, min(x, mw - pw)), max(0, min(y, mh - ph))

CANVAS_W, CANVAS_H = 1920, 1080
Q_BIG = "queue max-size-time=3000000000 max-size-buffers=0 max-size-bytes=0 leaky=downstream"
Q_MUX = "queue max-size-time=10000000000 max-size-buffers=1000 max-size-bytes=41943040"
RGBA = "video/x-raw(memory:NVMM),format=RGBA"      # ohne Hochkommas: belacoder gibt den Text direkt an gst_parse_launch (Hochkommas gelten nur in der Shell)
NV12 = "video/x-raw(memory:NVMM),format=NV12"
ENCODER = ('nvv4l2h265enc control-rate=1 qp-range="28,50:0,38:0,50" iframeinterval=60 idrinterval=60 preset-level=4 maxperf-enable=true '
           "EnableTwopassCBR=true insert-sps-pps=true name=venc_bps")


# Bildgrößen der sendenden Kameras {Schlüssel: (Breite, Höhe)}, vom Sende-Dienst aus der nginx-Statistik gefüllt (pipbox_send.live_keys); leer, wenn unbekannt
STREAM_SIZES = {}
FULL_W, FULL_H = CANVAS_W, CANVAS_H


def crop_edges(key, crop=(0, 0, 0, 0)):
    """Ausschnitt für den nvvidconv eines Platzes: (left, top, right, bottom) als Kanten im Quellbild der Kamera key. crop ist der Beschnitt der Einstellung in Bezugspixeln
    eines Bildes von 1920x1080 (links, rechts, oben, unten); er wird auf die Bildgröße der Kamera umgerechnet (STREAM_SIZES aus der nginx-Statistik; unbekannt: 1920x1080).
    1920x1088 gilt als 1080: Die Osmo Action 6 kodiert bei 1080p 1088 Zeilen ohne Vermerk im Strom, die unteren 8 sind schwarze Füllzeilen (der Compositor würde sie
    mitzeigen und das Bild stauchen; gemessen). Der nvvidconv liefert immer 1920x1080 (feste Caps), so ändert ein Beschnitt im Betrieb nie das Format."""
    w, h = STREAM_SIZES.get(key) or (FULL_W, FULL_H)
    if (w, h) == (FULL_W, FULL_H + 8):
        h = FULL_H
    l, r, t, b = (max(0, int(v)) for v in crop)
    left, right = (l * w // CROP_REF_W) & ~1, (r * w // CROP_REF_W) & ~1
    top, bottom = (t * h // CROP_REF_H) & ~1, (b * h // CROP_REF_H) & ~1
    if w - left - right < CROP_KEEP or h - top - bottom < CROP_KEEP:
        left = right = top = bottom = 0
    return left, top, w - right, h - bottom


def role_layout(c, pip, pip2, pip3):
    """Alles je Rolle aus der Einstellung (0 Hauptbild, 1 bis 3 kleines Bild an dieser Stelle, nur die, die es gibt):
    {"pic": (x, y, Breite, Höhe) auf der Leinwand nach Beschnitt, "crop": (l, r, t, b) in Bezugspixeln 1920x1080, "frame": (x, y, Breite, Höhe) der Farbfläche oder None,
    "frame_pad": Pad des Rahmens im Compositor, "frame_name": Name seiner Quelle, "color": Farbe als ARGB, "frame_alpha": Deckkraft des Rahmens 0..1}.
    Der Beschnitt verkleinert das Bild im selben Maßstab (wie im anderen Paket), er vergrößert nicht. Werte gerade (nvcompositor verlangt gerade Werte)."""
    out = {0: {"pic": (0, 0, CANVAS_W, CANVAS_H), "crop": (0, 0, 0, 0), "frame": None, "frame_pad": None, "frame_name": None, "color": 0, "frame_alpha": 0.0}}
    margin = (CANVAS_W // 60) & ~1
    present = {1: pip, 2: pip2, 3: pip3}
    styles = c.get("styles") if isinstance(c.get("styles"), dict) else {}
    for n, size_key, sfx in ((1, "size_pct", ""), (2, "size_pct2", "2"), (3, "size_pct3", "3")):
        if not present[n]:
            continue
        st = styles.get(str(n)) if isinstance(styles.get(str(n)), dict) else {}
        cr = st.get("crop") if isinstance(st.get("crop"), dict) else {}
        try:
            l, r, t, b = (max(0, int(cr.get(k, 0))) for k in ("l", "r", "t", "b"))
        except (TypeError, ValueError):
            l = r = t = b = 0
        if CROP_REF_W - l - r < CROP_KEEP or CROP_REF_H - t - b < CROP_KEEP:
            l = r = t = b = 0
        pw, ph = pip_size(c[size_key])
        cw, ch = ((CROP_REF_W - l - r) * pw // CROP_REF_W) & ~1, ((CROP_REF_H - t - b) * ph // CROP_REF_H) & ~1
        x, y = place(c["corner" + sfx], CANVAS_W, CANVAS_H, cw, ch, margin, c["x" + sfx], c["y" + sfx])
        x, y = x & ~1, y & ~1
        bd = st.get("border") if isinstance(st.get("border"), dict) else {}
        enabled = bool(bd.get("enabled"))
        try:
            bw = max(2, (int(bd.get("width", STYLE_DEFAULT["border"]["width"])) + 1) & ~1)
            fo = max(0, min(100, int(bd.get("opacity", 100))))
        except (TypeError, ValueError):
            bw, fo = STYLE_DEFAULT["border"]["width"], 100
        color = bd.get("color") if isinstance(bd.get("color"), str) and STYLE_COLOR_RE.match(bd.get("color")) else "#ffffff"
        frame = None
        if enabled:
            fx, fy = max(0, x - bw) & ~1, max(0, y - bw) & ~1
            fw, fh = min(CANVAS_W - fx, cw + 2 * bw) & ~1, min(CANVAS_H - fy, ch + 2 * bw) & ~1
            frame = (fx, fy, fw, fh)
        out[n] = {"pic": (x, y, cw, ch), "crop": (l, r, t, b), "frame": frame, "frame_pad": FRAME_PAD0 + n - 1, "frame_name": f"frame{n}",
                  "color": 0xFF000000 | int(color[1:], 16), "frame_alpha": fo / 100.0 if enabled else 0.0}
    return out


def is_jetson():
    """Läuft das hier auf einem Jetson (L4T)? Dann baut PipelineStore.build() diese Kette statt der Rockchip-Kette."""
    return os.path.exists("/etc/nv_tegra_release")


def _audio_main(demux):
    return (f"{demux}.audio ! aacparse ! avdec_aac ! identity name=a_delay signal-handoffs=TRUE ! volume volume=1.0 ! "
            f"audioconvert ! voaacenc bitrate=128000 ! aacparse ! {Q_MUX} ! mux.")


def _audio_other(demux, take):
    """Ton einer zweiten Kamera: entweder in die Sendung (wenn gewählt) oder verwerfen, damit flvdemux nicht aufstaut."""
    if take:
        return (f"{demux}.audio ! aacparse ! avdec_aac ! identity name=a_delay signal-handoffs=TRUE ! volume volume=1.0 ! audioconvert ! "
                f"voaacenc bitrate=128000 ! aacparse ! {Q_MUX} ! mux.")
    return f"{demux}.audio ! queue max-size-buffers=4 leaky=downstream ! fakesink sync=false async=false"


def slot_geometry(c, pip, pip2, pip3):
    """Lage der Plätze auf der Leinwand: {Platz: (x, y, Breite, Höhe)}; Platz 0 ist das Hauptbild, 1 bis 3 sind die kleinen Bilder (nur die, die es gibt)."""
    return {n: lay["pic"] for n, lay in role_layout(c, pip, pip2, pip3).items()}


def build_always(c, pip, pip2, pip3):
    """"Alle Kameras immer bereit": jeder Platz (Hauptbild, kleine Bilder) liest von udpsrc auf Loopback, wohin ein Zubringer (pipbox_always.py) den Stream der Kamera
    reicht. udpsrc fällt nie aus; fehlt eine Kamera, speist ein schwarzes Füllbild den Platz (pipbox_always.fill_cmd), so hat der Compositor immer an jedem Platz Bilder und der
    Ausgang läuft auch ohne Kamera. Welche Kamera wo zu sehen ist (kleine Bilder ausblenden, Ersatz für die Hauptkamera) und welcher Ton läuft, ändert die Steuerdatei von
    belacoder (belacoder-padctl.patch) im Betrieb: Lage und Ebene der Compositor-Pads (sink_N = Platz N) und Lautstärke der Ton-Pads des audiomixer (sink_N+1 = Platz N,
    sink_0 ist die Stille)."""
    sel = c.get("audio", "main") if pip else "main"
    if sel == "pip2" and not pip2 or sel == "pip3" and not pip3 or sel not in ("main", "pip", "pip2", "pip3"):
        sel = "main"
    geo = role_layout(c, pip, pip2, pip3)
    out = []
    props = []
    for n in sorted(geo):                                 # beim Bau hat Platz n die Rolle n (pipbox_always.SlotController.rebind)
        x, y, w, h = geo[n]["pic"]
        props.append(f"sink_{n}::xpos={x} sink_{n}::ypos={y} sink_{n}::width={w} sink_{n}::height={h} sink_{n}::zorder={2 * n + 1 if n else 0}")
        v_delay = "identity name=v_delay signal-handoffs=TRUE ! " if n == 0 else ""
        cam = c.get(("main", "pip", "pip2", "pip3")[n], "")
        left, top, right, bottom = crop_edges(cam, geo[n]["crop"])
        # nvvidconv je Platz mit Namen (Beschnitt im Betrieb über die Steuerdatei: "vcN left …") und fester Ausgabegröße: so ändert kein Beschnitt und keine
        # Kamera (4K, 1088 Zeilen) die Caps zum Compositor; der skaliert auf die Pad-Größe
        conv = f"nvvidconv name=vc{n} left={left} top={top} right={right} bottom={bottom} ! {RGBA},width={FULL_W},height={FULL_H}"
        out.append(f"udpsrc port={FEED_PORT + 2 * n} address=127.0.0.1 buffer-size=8388608 do-timestamp=true caps=\"{FEED_VIDEO_CAPS}\" !\n"
                   f"rtph264depay ! h264parse ! {v_delay}{Q_BIG} ! nvv4l2decoder ! {conv} ! comp.sink_{n}\n")
    for n in sorted(geo):                                 # Rahmen: eine Farbfläche hinter dem kleinen Bild (Ebene zwischen Hauptbild und Bild), ohne Rahmen unsichtbar
        lay = geo[n]
        if lay["frame_pad"] is None:
            continue
        fx, fy, fw, fh = lay["frame"] or lay["pic"]
        p = lay["frame_pad"]
        props.append(f"sink_{p}::xpos={fx} sink_{p}::ypos={fy} sink_{p}::width={fw} sink_{p}::height={fh} sink_{p}::zorder={2 * n} sink_{p}::alpha={lay['frame_alpha']:.2f}")
        out.append(f"videotestsrc name={lay['frame_name']} is-live=true pattern=solid-color foreground-color={lay['color']} ! {FRAME_SRC} ! nvvidconv ! {RGBA} ! comp.sink_{p}\n")
    # Ausgabegröße fest: ohne sie folgt der Compositor der Größe der Pads (gemessen: ein Pad mit 1088 Zeilen machte die Ausgabe 1088 groß)
    out.append("nvcompositor name=comp " + " ".join(props) + f" !\n{RGBA},width={FULL_W},height={FULL_H} ! nvvidconv ! {NV12} !\n"
               f"{ENCODER} !\nh265parse config-interval=-1 ! {Q_MUX} ! mux.\n")
    slot_sel = {"main": 0, "pip": 1, "pip2": 2, "pip3": 3}[sel]
    out.append(f"audiotestsrc is-live=true wave=silence ! {FEED_AUDIO_CAPS} ! amix.sink_0\n")
    apads = []
    for n in sorted(geo):
        apads.append(f"sink_{n + 1}::volume={1.0 if n == slot_sel else 0.0}")
        out.append(f"udpsrc port={FEED_PORT + 2 * n + 1} address=127.0.0.1 buffer-size=1048576 do-timestamp=true caps=\"{FEED_AUDIO_CAPS}\" !\n"
                   f"queue max-size-time=2000000000 max-size-buffers=0 max-size-bytes=0 leaky=downstream ! amix.sink_{n + 1}\n")
    out.append("audiomixer name=amix " + " ".join(apads) + " ! audioconvert ! identity name=a_delay signal-handoffs=TRUE ! volume volume=1.0 ! "
               f"voaacenc bitrate=128000 ! aacparse ! {Q_MUX} ! mux.\n")
    out.append("mpegtsmux name=mux !\nappsink name=appsink")
    return "\n".join(out)


def build(c, base, pip, pip2, pip3, always=False):
    """c: geprüfte Einstellung (PipelineStore._safe_cfg), base: rtmp://127.0.0.1:<Port>/<Anwendung>, pip/pip2/pip3: welche kleinen Bilder es gibt.
    always: Modus "alle Kameras immer bereit" (build_always)."""
    if always:
        return build_always(c, pip, pip2, pip3)
    sel = c.get("audio", "main") if pip else "main"
    if sel == "pip2" and not pip2 or sel == "pip3" and not pip3 or sel not in ("main", "pip", "pip2", "pip3"):
        sel = "main"
    out = []

    # Hauptbild
    out.append(f"rtmpsrc location={base}/{c['main']} do-timestamp=true !\nflvdemux name=demux\n")
    if pip:
        out.append(f"demux.video ! identity name=v_delay signal-handoffs=TRUE ! {Q_BIG} ! h264parse ! nvv4l2decoder ! nvvidconv ! {RGBA} ! comp.sink_0\n")
    else:
        out.append(f"demux.video ! identity name=v_delay signal-handoffs=TRUE ! {Q_BIG} ! h264parse ! nvv4l2decoder ! nvvidconv ! {NV12} !\n"
                   f"{ENCODER} !\nh265parse config-interval=-1 ! {Q_MUX} ! mux.\n")

    # Kleine Bilder: jedes Bild bekommt seine Größe und Ecke; nvcompositor verkleinert und legt es über das Hauptbild
    if pip:
        props = [f"sink_0::xpos=0 sink_0::ypos=0 sink_0::width={CANVAS_W} sink_0::height={CANVAS_H} sink_0::zorder=0"]
        margin = (CANVAS_W // 60) & ~1
        slots = [(1, "pip", ""), (2, "pip2", "2"), (3, "pip3", "3")]
        present = {"pip": pip, "pip2": pip2, "pip3": pip3}
        size_keys = {"pip": "size_pct", "pip2": "size_pct2", "pip3": "size_pct3"}
        for n, key, sfx in slots:
            if not present[key]:
                continue
            w, h = pip_size(c[size_keys[key]])
            x, y = place(c["corner" + sfx], CANVAS_W, CANVAS_H, w, h, margin, c["x" + sfx], c["y" + sfx])
            x, y, w, h = x & ~1, y & ~1, w & ~1, h & ~1                  # nvcompositor verlangt gerade Werte (sonst eine Meldung je Bild)
            props.append(f"sink_{n}::xpos={x} sink_{n}::ypos={y} sink_{n}::width={w} sink_{n}::height={h} sink_{n}::zorder={n}")
            out.append(f"rtmpsrc location={base}/{c[key]} do-timestamp=true !\nflvdemux name=d{n}\n")
            out.append(f"d{n}.video ! {Q_BIG} ! h264parse ! nvv4l2decoder ! nvvidconv ! {RGBA} ! comp.sink_{n}\n")
        out.append("nvcompositor name=comp " + " ".join(props) + f" !\n{RGBA},width={CANVAS_W},height={CANVAS_H} ! nvvidconv ! {NV12} !\n"
                   f"{ENCODER} !\nh265parse config-interval=-1 ! {Q_MUX} ! mux.\n")

    # Ton: genau eine Quelle geht in die Sendung, die übrigen werden verworfen
    out.append(_audio_main("demux") + "\n" if sel == "main" else
               "demux.audio ! queue max-size-buffers=4 leaky=downstream ! fakesink sync=false async=false\n")
    if pip:
        out.append(_audio_other("d1", sel == "pip") + "\n")
        if pip2:
            out.append(_audio_other("d2", sel == "pip2") + "\n")
        if pip3:
            out.append(_audio_other("d3", sel == "pip3") + "\n")
    out.append("mpegtsmux name=mux !\nappsink name=appsink")
    return "\n".join(out)
