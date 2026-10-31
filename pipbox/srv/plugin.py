"""Namen, Wege und Konstanten der Sendekette, die Oberfläche, Sendedienst und Pipeline gemeinsam nutzen."""


PIP_CORNERS = ("oben links", "oben rechts", "unten links", "unten rechts", "unten Mitte", "frei (verschiebbar)")


FREE = 5                      # Nummer von "frei": Position aus x/y (Promille)


SEND_STATUS = "/run/pipbox-send/status.json"


VIEW_FILE = "main-view"                 # Datei im Zustandsordner: "ausgeblendet Tonquelle stumm" (schreibt die Oberfläche, liest der SlotController, pipbox_always.py)


VIEW_STATE = "/run/pipbox-send/view-state"   # hier meldet der SlotController zurück, was gilt (die Oberfläche wartet darauf)


FEED_PORT = 9410            # "alle Kameras immer bereit": die Weiche je Platz (0 bis 3) gibt Bild an Port FEED_PORT + 2*Platz und Ton an +1 weiter (nur Loopback)


FEED_VIDEO_CAPS = "application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000"


FEED_AUDIO_CAPS = "audio/x-raw,format=S16LE,rate=48000,channels=2,layout=interleaved"
