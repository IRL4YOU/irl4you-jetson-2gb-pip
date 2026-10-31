#!/bin/sh
# Jetson 2GB PIP: Installation auf dem Jetson (Version siehe Datei VERSION).
# Aufruf: sudo sh install/install.sh [install|uninstall]
# Ändert nichts an BELABOX (belaUI, belacoder, nginx). Rückweg: install.sh uninstall
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/jetson-pip

case "${1:-install}" in
  uninstall)
    rm -rf "$DEST"
    echo "Jetson 2GB PIP entfernt (nachinstallierte Pakete bleiben)."
    exit 0 ;;
  install) ;;
  *) echo "Aufruf: install.sh [install|uninstall]"; exit 2 ;;
esac

[ "$(id -u)" = 0 ] || { echo "FEHLER: Bitte mit sudo ausführen."; exit 1; }

echo "JPIP-STEP pakete"
need=""
for p in gstreamer1.0-tools git curl ca-certificates; do
  dpkg -s "$p" >/dev/null 2>&1 || need="$need $p"
done
if [ -n "$need" ]; then
  export DEBIAN_FRONTEND=noninteractive
  # shellcheck disable=SC2086
  apt-get install -y --no-install-recommends $need || echo "WARNUNG: Pakete ließen sich nicht installieren:$need"
fi

echo "JPIP-STEP dateien"
mkdir -p "$DEST"
cp "$HERE/VERSION" "$DEST/VERSION"
