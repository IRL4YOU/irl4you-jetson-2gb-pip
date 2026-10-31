"""Pipeline-Text für belacoder auf dem Jetson Nano (Nvidia-Hardware statt Rockchip).

Aufbau wie die Jetson-Pipelines des BELABOX-Pakets (belacoder-pipelines-tegra): RTMP von nginx, Hardware-Decoder nvv4l2decoder, H.265 mit
nvv4l2h265enc, MPEG-TS an den appsink. Bild-in-Bild macht nvcompositor (Mischen in der Videohardware, ohne dass die CPU die Bilder liest).
belacoder findet die Elemente über ihre Namen: v_delay, a_delay, venc_bps und appsink.
"""

import os

from pipbox_live import place
from srv.plugin import FEED_AUDIO_CAPS, FEED_PORT, FEED_VIDEO_CAPS
from srv.style import pip_size

CANVAS_W, CANVAS_H = 1920, 1080
Q_BIG = "queue max-size-time=3000000000 max-size-buffers=0 max-size-bytes=0 leaky=downstream"
Q_MUX = "queue max-size-time=10000000000 max-size-buffers=1000 max-size-bytes=41943040"
RGBA = "video/x-raw(memory:NVMM),format=RGBA"      # ohne Hochkommas: belacoder gibt den Text direkt an gst_parse_launch (Hochkommas gelten nur in der Shell)
NV12 = "video/x-raw(memory:NVMM),format=NV12"
ENCODER = ('nvv4l2h265enc control-rate=1 qp-range="28,50:0,38:0,50" iframeinterval=60 idrinterval=60 preset-level=4 maxperf-enable=true '
           "EnableTwopassCBR=true insert-sps-pps=true name=venc_bps")


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
    geo = {0: (0, 0, CANVAS_W, CANVAS_H)}
    margin = (CANVAS_W // 60) & ~1
    present = {1: pip, 2: pip2, 3: pip3}
    for n, size_key, sfx in ((1, "size_pct", ""), (2, "size_pct2", "2"), (3, "size_pct3", "3")):
        if not present[n]:
            continue
        w, h = pip_size(c[size_key])
        x, y = place(c["corner" + sfx], CANVAS_W, CANVAS_H, w, h, margin, c["x" + sfx], c["y" + sfx])
        geo[n] = (x & ~1, y & ~1, w & ~1, h & ~1)         # nvcompositor verlangt gerade Werte (sonst eine Meldung je Bild)
    return geo


def build_always(c, pip, pip2, pip3):
    """"Alle Kameras immer bereit": jeder Platz (Hauptbild, kleine Bilder) liest von udpsrc auf Loopback, wohin ein Zubringer (pipbox_always.py) den Stream der Kamera
    reicht. udpsrc fällt nie aus; fehlt eine Kamera, speist ein schwarzes Füllbild den Platz (pipbox_always.fill_cmd), so hat der Compositor immer an jedem Platz Bilder und der
    Ausgang läuft auch ohne Kamera. Welche Kamera wo zu sehen ist (kleine Bilder ausblenden, Ersatz für die Hauptkamera) und welcher Ton läuft, ändert die Steuerdatei von
    belacoder (belacoder-padctl.patch) im Betrieb: Lage und Ebene der Compositor-Pads (sink_N = Platz N) und Lautstärke der Ton-Pads des audiomixer (sink_N+1 = Platz N,
    sink_0 ist die Stille)."""
    sel = c.get("audio", "main") if pip else "main"
    if sel == "pip2" and not pip2 or sel == "pip3" and not pip3 or sel not in ("main", "pip", "pip2", "pip3"):
        sel = "main"
    geo = slot_geometry(c, pip, pip2, pip3)
    out = []
    props = []
    for n in sorted(geo):
        x, y, w, h = geo[n]
        props.append(f"sink_{n}::xpos={x} sink_{n}::ypos={y} sink_{n}::width={w} sink_{n}::height={h} sink_{n}::zorder={n + (1 if n else 0)}")
        v_delay = "identity name=v_delay signal-handoffs=TRUE ! " if n == 0 else ""
        out.append(f"udpsrc port={FEED_PORT + 2 * n} address=127.0.0.1 buffer-size=8388608 do-timestamp=true caps=\"{FEED_VIDEO_CAPS}\" !\n"
                   f"rtph264depay ! h264parse ! {v_delay}{Q_BIG} ! nvv4l2decoder ! nvvidconv ! {RGBA} ! comp.sink_{n}\n")
    out.append("nvcompositor name=comp " + " ".join(props) + f" !\n{RGBA} ! nvvidconv ! {NV12} !\n"
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
        out.append("nvcompositor name=comp " + " ".join(props) + f" !\n{RGBA} ! nvvidconv ! {NV12} !\n"
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
