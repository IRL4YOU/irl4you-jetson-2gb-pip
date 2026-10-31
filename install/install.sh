#!/bin/sh
# Jetson 2GB PIP: Installation auf dem Jetson (Version siehe Datei VERSION).
# Aufruf: sudo sh install/install.sh [install|uninstall]
# Aendert nichts an BELABOX (belaUI, belacoder, nginx). Rueckweg: install.sh uninstall
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/jetson-pip
APP=/opt/pipbox
STATE=/var/lib/pipbox
UNIT=/etc/systemd/system/pipbox.service
# Root-Helfer: je einer mit .path (Ausloeser), .service und .py; die Oberflaeche legt nur eine Anforderungsdatei mit einem festen Stichwort ab
HELPERS="ssh update wifi power logs logmode netaddr remote swupdate"

case "${1:-install}" in
  uninstall)
    systemctl disable --now pipbox.service >/dev/null 2>&1 || true
    rm -f "$UNIT"
    for h in $HELPERS; do
      systemctl disable --now "pipbox-$h.path" >/dev/null 2>&1 || true
      rm -f "/etc/systemd/system/pipbox-$h.path" "/etc/systemd/system/pipbox-$h.service"
    done
    systemctl daemon-reload >/dev/null 2>&1 || true
    rm -rf "$APP" "$DEST"
    echo "Jetson 2GB PIP entfernt. Zustand in $STATE, Benutzer pipbox und nachinstallierte Pakete bleiben."
    exit 0 ;;
  install) ;;
  *) echo "Aufruf: install.sh [install|uninstall]"; exit 2 ;;
esac

[ "$(id -u)" = 0 ] || { echo "FEHLER: Bitte mit sudo ausfuehren."; exit 1; }

echo "JPIP-STEP pakete"
need=""
for p in gstreamer1.0-tools git curl ca-certificates bluez usbutils rfkill; do
  dpkg -s "$p" >/dev/null 2>&1 || need="$need $p"
done
if [ -n "$need" ]; then
  export DEBIAN_FRONTEND=noninteractive
  # shellcheck disable=SC2086
  apt-get install -y --no-install-recommends $need || echo "WARNUNG: Pakete liessen sich nicht installieren:$need"
fi

echo "JPIP-STEP dienst"
getent group bluetooth >/dev/null || groupadd --system bluetooth
getent group input >/dev/null || groupadd --system input
# Fester, rechteloser Benutzer; in /etc/passwd pruefen, damit ein noch laufender temporaerer Benutzer nicht taeuscht
if ! grep -q '^pipbox:' /etc/passwd; then
  useradd --system --no-create-home --home-dir "$STATE" --shell /usr/sbin/nologin --groups bluetooth pipbox
fi
mkdir -p "$STATE"
chown -R pipbox:pipbox "$STATE"
chmod 700 "$STATE"

echo "JPIP-STEP dateien"
systemctl stop pipbox.service >/dev/null 2>&1 || true
mkdir -p "$DEST" "$APP"
cp "$HERE/VERSION" "$DEST/VERSION"
# Altes, das nicht mehr gebraucht wird, entfaellt: Ordner der Oberflaeche ersetzen, dann vorbereiten
rm -rf "$APP/srv" "$APP/tw" "$APP/web" "$APP/__pycache__"
cp -a "$HERE/pipbox/." "$APP/"
cp "$HERE/VERSION" "$APP/VERSION"
chown -R root:root "$APP"
chmod -R u=rwX,go=rX "$APP"
python3 -m compileall -q "$APP" >/dev/null 2>&1 || true
install -m 644 "$HERE/install/pipbox.service" "$UNIT"
for h in $HELPERS; do
  install -m 755 "$HERE/install/pipbox-$h.py" "$APP/pipbox-$h.py"
  install -m 644 "$HERE/install/pipbox-$h.service" "/etc/systemd/system/pipbox-$h.service"
  install -m 644 "$HERE/install/pipbox-$h.path" "/etc/systemd/system/pipbox-$h.path"
done

echo "JPIP-STEP start"
systemctl daemon-reload
systemctl enable pipbox.service >/dev/null 2>&1 || echo "WARNUNG: Der Dienst pipbox liess sich nicht fuer den Autostart eintragen."
for h in $HELPERS; do
  systemctl enable --now "pipbox-$h.path" >/dev/null 2>&1 || echo "WARNUNG: Der Helfer pipbox-$h.path liess sich nicht einschalten."
done
systemctl restart pipbox.service || echo "WARNUNG: Der Dienst pipbox liess sich nicht starten (journalctl -u pipbox)."
i=0
while [ "$i" -lt 20 ]; do
  wget -q -O /dev/null --timeout=2 http://127.0.0.1:8780/api/auth 2>/dev/null && break
  i=$((i + 1)); sleep 1
done
if [ "$i" -ge 20 ]; then
  echo "WARNUNG: Die Oberflaeche antwortet nicht auf Port 8780 (journalctl -u pipbox)."
else
  echo "Die Oberflaeche antwortet auf Port 8780."
fi
