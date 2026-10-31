#!/bin/sh
# Baut belacoder (BELABOX/belacoder, Commit ccce9ca, GPL-3.0) mit den Patches aus diesem Ordner:
#   jitter-tolerant  toleranterer Bitraten-Regler
#   stall-output     Wächter, der einen hängenden Encoder erkennt
#   stats            Kennzahlen-Datei (BELACODER_STATS_FILE) für die Anzeige "Live" in der Oberfläche
#   padctl           Steuerdatei (BELACODER_PADCTL_FILE): kleine Bilder des Compositors im Betrieb aus- und einblenden
# Installiert nach /opt/pipbox/bin/belacoder; das Original aus dem BELABOX-Paket bleibt unter /usr/bin und dient als Rückfall.
# Braucht gcc, git, patch und Internet. Die Header für GStreamer und GLib lädt das Skript in ein temporäres Verzeichnis (apt-get download und
# dpkg -x, ohne die Entwicklerpakete zu installieren); die Header für SRT bringt das BELABOX-Paket libsrt mit. Als root ausführen.
# BELACODER_OUT=/anderer/Ordner installiert dorthin (zum Testen).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${BELACODER_OUT:-/opt/pipbox/bin}
COMMIT=ccce9ca33c8e425b33353500b95795101e847964
B=/var/tmp/pbbuild
R=$B/root
mkdir -p "$B/debs" "$R" "$OUT"
if [ ! -f "$R/usr/include/gstreamer-1.0/gst/gst.h" ] || [ ! -f "$R/usr/include/gstreamer-1.0/gst/app/gstappsink.h" ]; then
  (cd "$B/debs" && apt-get -o APT::Sandbox::User=root download libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libglib2.0-dev \
    && for d in *.deb; do dpkg -x "$d" "$R"; done)
fi
[ -f /usr/include/srt/srt.h ] || { echo "FEHLER: /usr/include/srt/srt.h fehlt (Paket belabox-libsrt1)"; exit 1; }
D=$(mktemp -d)
trap 'rm -rf "$D"' EXIT
git clone --quiet https://github.com/BELABOX/belacoder "$D/belacoder"
cd "$D/belacoder"
git checkout --quiet "$COMMIT"
for p in jitter-tolerant stall-output stats padctl; do
  patch -p1 --quiet < "$HERE/belacoder-$p.patch"
done
gcc -O2 -Wall -DVERSION=\"${COMMIT%${COMMIT#???????}}-jt-so-st-pc\" belacoder.c -o belacoder.new \
  -I"$R/usr/include/gstreamer-1.0" -I"$R/usr/lib/aarch64-linux-gnu/gstreamer-1.0/include" \
  -I"$R/usr/include/glib-2.0" -I"$R/usr/lib/aarch64-linux-gnu/glib-2.0/include" -I/usr/include/srt \
  -l:libgstapp-1.0.so.0 -l:libgstbase-1.0.so.0 -l:libgstreamer-1.0.so.0 -l:libgobject-2.0.so.0 -l:libglib-2.0.so.0 -lsrt -ldl
install -m 755 belacoder.new "$OUT/belacoder.new"
mv -f "$OUT/belacoder.new" "$OUT/belacoder"      # ersetzen statt überschreiben: ein laufender Encoder bleibt heil
echo "belacoder gebaut: $OUT/belacoder"
