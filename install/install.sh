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
    systemctl stop pipbox-send.service >/dev/null 2>&1 || true
    systemctl disable --now pipbox-send-ctl.path >/dev/null 2>&1 || true
    systemctl disable --now pipbox-dji.service pipbox-hdmi.service >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/pipbox-dji.service /etc/systemd/system/pipbox-hdmi.service
    systemctl disable --now pipbox-preview.socket pipbox-preview.service >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/pipbox-preview.socket /etc/systemd/system/pipbox-preview.service
    rm -f "$UNIT" /etc/systemd/system/pipbox-send.service /etc/systemd/system/pipbox-send-ctl.service /etc/systemd/system/pipbox-send-ctl.path
    for h in $HELPERS; do
      systemctl disable --now "pipbox-$h.path" >/dev/null 2>&1 || true
      rm -f "/etc/systemd/system/pipbox-$h.path" "/etc/systemd/system/pipbox-$h.service"
    done
    systemctl daemon-reload >/dev/null 2>&1 || true
    rm -rf "$APP" "$DEST"
    rm -f /usr/local/bin/srtla_send /usr/local/bin/srtla_send.sig
    echo "Jetson 2GB PIP entfernt. Zustand in $STATE, Benutzer pipbox und nachinstallierte Pakete bleiben."
    exit 0 ;;
  install) ;;
  *) echo "Aufruf: install.sh [install|uninstall]"; exit 2 ;;
esac

[ "$(id -u)" = 0 ] || { echo "FEHLER: Bitte mit sudo ausfuehren."; exit 1; }

echo "JPIP-STEP pakete"
need=""
for p in gstreamer1.0-tools git curl ca-certificates bluez usbutils rfkill python3.8 python3.8-venv python3-venv python-pip-whl python3-distutils; do
  dpkg -s "$p" >/dev/null 2>&1 || need="$need $p"
done
if [ -n "$need" ]; then
  export DEBIAN_FRONTEND=noninteractive
  # shellcheck disable=SC2086
  apt-get install -y --no-install-recommends $need || echo "WARNUNG: Pakete liessen sich nicht installieren:$need"
fi

# DJI-Dienst: Die Bluetooth-Bibliothek bleak braucht ab Version 0.22 Python 3.8 (das System hat 3.6), also eine eigene Umgebung mit Python 3.8 (braucht Internet).
# Schlägt das fehl, läuft alles andere; nur die DJI-Kameras gehen dann nicht.
if ! /opt/pipbox/venv-dji/bin/python -c "import bleak" 2>/dev/null; then
  echo "Richte die Bluetooth-Umgebung für die DJI-Kameras ein (Python 3.8, bleak)"
  mkdir -p "$APP"
  if rm -rf "$APP/venv-dji" && python3.8 -m venv "$APP/venv-dji" > /var/tmp/venv-dji.log 2>&1 \
     && "$APP/venv-dji/bin/python" -m pip install --disable-pip-version-check -q --upgrade pip setuptools wheel >> /var/tmp/venv-dji.log 2>&1 \
     && "$APP/venv-dji/bin/python" -m pip install --disable-pip-version-check "bleak>=0.22,<1.0" >> /var/tmp/venv-dji.log 2>&1; then
    echo "bleak eingerichtet."
  else
    echo "WARNUNG: Die Bluetooth-Umgebung für die DJI-Kameras liess sich nicht einrichten (Internet? Protokoll: /var/tmp/venv-dji.log). Die DJI-Kameras gehen erst nach einer erneuten Installation."
  fi
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
# Dateien, die frühere Versionen mitbrachten und die es nicht mehr gibt (Rockchip-Reste), einzeln entfernen: cp -a ersetzt nur, was im Paket steht
rm -f "$APP/pipbox_live.py" "$APP/pipbox_live.pyc"
rm -rf "$APP/gst" "$APP/gst-src"
cp -a "$HERE/pipbox/." "$APP/"
cp "$HERE/VERSION" "$APP/VERSION"
chown -R root:root "$APP"
chmod -R u=rwX,go=rX "$APP"
python3 -m compileall -q -x 'venv-dji' "$APP" >/dev/null 2>&1 || true
install -m 644 "$HERE/install/pipbox.service" "$UNIT"
for h in $HELPERS; do
  install -m 755 "$HERE/install/pipbox-$h.py" "$APP/pipbox-$h.py"
  install -m 644 "$HERE/install/pipbox-$h.service" "/etc/systemd/system/pipbox-$h.service"
  install -m 644 "$HERE/install/pipbox-$h.path" "/etc/systemd/system/pipbox-$h.path"
done
# Sendekette (srtla_send und belacoder): der Dienst pipbox-send startet nur auf Anforderung der Oberflaeche (pipbox-send-ctl.path), nie von selbst
install -m 644 "$HERE/install/pipbox-send.service" /etc/systemd/system/pipbox-send.service
install -m 644 "$HERE/install/pipbox-send-ctl.service" /etc/systemd/system/pipbox-send-ctl.service
install -m 644 "$HERE/install/pipbox-send-ctl.path" /etc/systemd/system/pipbox-send-ctl.path
# DJI-Kameras per Bluetooth (Dienst mit Python 3.8 aus /opt/pipbox/venv-dji)
install -m 644 "$HERE/install/pipbox-dji.service" /etc/systemd/system/pipbox-dji.service
# USB-Kamera als Kamera (Webcam, HDMI-USB-Grabber): speist sie in den RTMP-Eingang ein, solange sie steckt
install -m 644 "$HERE/install/pipbox-hdmi.service" /etc/systemd/system/pipbox-hdmi.service
# Vorschau des gesendeten Bildes: Socket, der Dienst startet erst bei Bedarf (liest den lokalen SRT-Strom mit und dekodiert ihn mit der Video-Hardware)
install -m 644 "$HERE/install/pipbox-preview.socket" /etc/systemd/system/pipbox-preview.socket
install -m 644 "$HERE/install/pipbox-preview.service" /etc/systemd/system/pipbox-preview.service

# belacoder mit den Patches aus belacoder/ (Regler, Wächter, Kennzahlen für die Anzeige Live). Gebaut wird nur, wenn sich Skript oder Patches geändert haben;
# schlägt der Bau fehl, bleibt das Original aus dem BELABOX-Paket (/usr/bin/belacoder) im Einsatz, nur die Kennzahlen fehlen dann.
echo "JPIP-STEP encoder"
SIG=$(cat "$HERE/belacoder/build.sh" "$HERE"/belacoder/belacoder-*.patch | sha1sum | cut -d' ' -f1)
if [ -x "$APP/bin/belacoder" ] && [ "$(cat "$APP/bin/belacoder.sig" 2>/dev/null)" = "$SIG" ]; then
  echo "belacoder ist schon in der gebauten Fassung vorhanden."
elif sh "$HERE/belacoder/build.sh" > /var/tmp/belacoder-build.log 2>&1; then
  echo "$SIG" > "$APP/bin/belacoder.sig"
  echo "belacoder gebaut."
else
  echo "WARNUNG: belacoder liess sich nicht bauen, es bleibt das Original ohne Kennzahlen (Protokoll: /var/tmp/belacoder-build.log)."
  tail -3 /var/tmp/belacoder-build.log | sed 's/^/  /'
fi

# srtla_send mit den Patches aus srtla/ (Wegewahl nach Laufzeit, Mindestanteil, Zustandszeilen für die Anzeige Live): gleiches Vorgehen wie beim Encoder;
# schlägt der Bau fehl, bleibt das Original aus dem BELABOX-Paket im Einsatz, nur die Anzeige Live kennt dann den Zustand der Wege nicht.
echo "JPIP-STEP srtla"
SIG=$(cat "$HERE/srtla/build.sh" "$HERE"/srtla/srtla_send-*.patch | sha1sum | cut -d' ' -f1)
if [ -x /usr/local/bin/srtla_send ] && [ "$(cat /usr/local/bin/srtla_send.sig 2>/dev/null)" = "$SIG" ]; then
  echo "srtla_send ist schon in der gebauten Fassung vorhanden."
elif sh "$HERE/srtla/build.sh" > /var/tmp/srtla-build.log 2>&1; then
  echo "$SIG" > /usr/local/bin/srtla_send.sig
  echo "srtla_send gebaut."
else
  echo "WARNUNG: srtla_send liess sich nicht bauen, es bleibt das Original ohne Zustandszeilen (Protokoll: /var/tmp/srtla-build.log)."
  tail -3 /var/tmp/srtla-build.log | sed 's/^/  /'
fi

echo "JPIP-STEP start"
systemctl daemon-reload
systemctl enable pipbox.service >/dev/null 2>&1 || echo "WARNUNG: Der Dienst pipbox liess sich nicht fuer den Autostart eintragen."
for h in $HELPERS send-ctl; do
  systemctl enable --now "pipbox-$h.path" >/dev/null 2>&1 || echo "WARNUNG: Der Helfer pipbox-$h.path liess sich nicht einschalten."
done
systemctl enable pipbox-dji.service >/dev/null 2>&1 || echo "WARNUNG: Der DJI-Dienst liess sich nicht fuer den Autostart eintragen."
systemctl enable pipbox-hdmi.service >/dev/null 2>&1 || echo "WARNUNG: Der USB-Kamera-Dienst liess sich nicht fuer den Autostart eintragen."
systemctl restart pipbox-hdmi.service >/dev/null 2>&1 || echo "WARNUNG: Der USB-Kamera-Dienst liess sich nicht starten (journalctl -u pipbox-hdmi)."
systemctl restart pipbox-dji.service >/dev/null 2>&1 || echo "WARNUNG: Der DJI-Dienst liess sich nicht starten (journalctl -u pipbox-dji)."
systemctl enable --now pipbox-preview.socket >/dev/null 2>&1 || echo "WARNUNG: Der Anschluss der Vorschau liess sich nicht einschalten (pipbox-preview.socket)."
systemctl try-restart pipbox-preview.service >/dev/null 2>&1 || true       # neuer Programmstand (der Dienst endet sonst nach einer Minute ohne Zuschauer von selbst)
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
