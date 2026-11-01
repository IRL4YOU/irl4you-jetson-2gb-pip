# Jetson 2GB PIP (Beta)

Bild-in-Bild für den **Jetson Nano 2GB** (BELABOX-Image, JetPack 4.6.4 / L4T 32.7.4): mehrere Kameras zu einem Bild mischen und über SRT/SRTLA senden. Eigenständiges Projekt, die Jetson-Ausgabe von [IRL4YOU PIP](https://github.com/IRL4YOU/irl4you-pip).

**Webseite:** [irl4you.de](https://irl4you.de) · **Schwesterprojekt (Orange Pi / ROCK):** [IRL4YOU/irl4you-pip](https://github.com/IRL4YOU/irl4you-pip) · **Fehler und Wünsche:** [Issues](https://github.com/IRL4YOU/irl4you-jetson-2gb-pip/issues)

> **Beta:** Testversion, Änderungen sind jederzeit möglich. Die Versionsnummer steht in `VERSION`, die Änderungen in [CHANGELOG.md](CHANGELOG.md). Getestet auf dem Jetson Nano 2GB (JetPack 4.6.4); das 4-GB-Modell ist noch nicht getestet.

## Was die Box kann

- **Bild-in-Bild mit bis zu vier Kameras** (ein Hauptbild, bis zu drei kleine Bilder), gemischt in der Video-Hardware des Jetson (Decoder, Bildwandler, Compositor, H.265-Encoder). Die CPU bleibt dabei frei: im Dauertest über eine Stunde mit mehreren Kameras und laufender Sendung im Mittel 34 % frei, nie unter 15 %.
- **Alle Kameras immer bereit:** Tausch von Haupt- und kleinem Bild ohne Unterbrechung, Verzögerung je Kamera bis 750 ms. Fällt die Hauptkamera aus (Kabel gezogen, Akku leer), übernimmt nach etwa 2 Sekunden die erste vorhandene Kamera der kleinen Bilder das Hauptbild, bei der Rückkehr nach 3 Sekunden wieder die eigentliche Hauptkamera. Eine ausgefallene kleine Kamera verschwindet aus dem Bild. Die Sendung läuft in jedem Fall weiter; nur wenn gar keine Kamera mehr liefert, bleibt das Hauptbild schwarz.
- **Senden über SRT und SRTLA** (Bündelung mehrerer Leitungen, zum Beispiel LAN, WLAN und Handy-Hotspot) mit angepasstem `belacoder` und `srtla_send` (Bitratenregler, Wegewahl, Kennzahlen).
- **Kameras:**
  - **USB-Kamera** (zum Beispiel DJI Osmo Action 4 im USB-Modus, Webcam oder HDMI-USB-Grabber): 1080p mit 30 Bildern je Sekunde und 8000 kbit/s, gemessen genau 30,0 fps. MJPEG der Kamera wird in der Video-Hardware dekodiert und neu kodiert.
  - **DJI-Kameras per Bluetooth** (Kopplung, Steuerung, Akkustand), bewährter Stick: ASUS USB-BT500.
  - **RTMP-Kameras** (zum Beispiel Handy-Apps oder Action-Cams), die an die Box senden.
- **Weboberfläche** (Port 8780, 14 Sprachen): Live, Vorschau, Status, Bildaufbau (Positionen, Rahmen, Beschnitt, Facecam), Verbindungen (WLAN, Bluetooth, Upload-Leitungen), SRTLA-Einstellungen, Streamer.bot-Deck, Chat und Systemwarnungen im Twitch-Chat, öffentliche Statistik für OBS und Homepage, Einstellungen sichern, Protokolle.
- **Update über die Oberfläche** (Karte Software-Update, mit Fortschritt) und **Fernzugriff über Tailscale**.

## Bekannte Grenzen

- **Kein Verpixeln** (Köpfe, Kennzeichen) und **kein HDMI-Eingang**: Der Jetson Nano hat keinen. Kameras kommen über USB (Webcam oder HDMI-USB-Grabber), RTMP oder DJI-Bluetooth.
- **Keine abgerundeten Ecken** bei den kleinen Bildern: Der Compositor der Video-Hardware (`nvcompositor`) kennt keine Rundung, die Einstellung ist in der Oberfläche ausgeblendet. Rahmen, Beschnitt, Deckkraft und alle sechs Positionen gibt es.
- **Höchstens vier Kameras** gleichzeitig im Bild (ein Hauptbild, drei kleine).
- **Kamerawechsel bei „Eine Kamera“:** Wählst du dort eine andere Kamera als Hauptbild, startet die Sendekette neu (ein paar Sekunden ohne Bild), weil der Hardware-Decoder den Strom nicht wechseln kann. Beim Bild-in-Bild tauschen nur die Rollen, ohne Unterbrechung.
- **H.264 direkt aus der USB-Kamera** ist mit dem Kernel 4.9 nicht nutzbar; die Box nimmt MJPEG, dekodiert und kodiert es in der Video-Hardware neu (1080p, 30 Bilder pro Sekunde, wählbare Bitrate).
- **Bluetooth-Sticks:** Bewährt ist der ASUS USB-BT500 (Realtek RTL8761B). Nachbauten des CSR8510 verbinden sich mit DJI-Kameras oft nicht zuverlässig. Bei Überstrom einen USB-Hub mit eigenem Netzteil nehmen.
- **Das 4-GB-Modell ist nicht getestet.**

## Installation

Voraussetzung: Jetson Nano 2GB mit BELABOX-Image, Internet und ein Terminal (SSH). **Nicht während einer Übertragung.**

```sh
cd /tmp && rm -rf irl4you-jetson-2gb-pip-main irl4you-jetson-2gb-pip.tar.gz && wget -q -O irl4you-jetson-2gb-pip.tar.gz https://github.com/IRL4YOU/irl4you-jetson-2gb-pip/archive/refs/heads/main.tar.gz && tar xzf irl4you-jetson-2gb-pip.tar.gz && cd irl4you-jetson-2gb-pip-main && sudo sh install/setup.sh
```

Das Skript

1. aktualisiert das Grundsystem (Fortschrittsbalken, Paketliste im Protokoll `~/install-ausgabe.txt`),
2. installiert die fehlenden Werkzeuge (`gstreamer1.0-tools`, `git`, `curl`) und richtet die Weboberfläche als Dienst `pipbox` ein (Autostart, Port 8780),
3. meldet am Ende „Alles fehlerfrei installiert“ oder die Hinweise. Bringt das Update einen neuen Kernel mit, sagt es, dass neu gestartet werden soll.

Ohne Systemupdate: `sudo sh install/setup.sh --ohne-systemupdate`. Rückweg: `sudo sh install/install.sh uninstall`.

## Aufbau

| Pfad | Inhalt |
|---|---|
| `install/setup.sh` | Komplett-Einrichtung (Systemupdate, dann `install.sh`) |
| `install/install.sh` | Pakete, Benutzer, Dateien und Dienst einrichten, `uninstall` |
| `install/pipbox.service` | systemd-Dienst der Weboberfläche |
| `pipbox/` | Weboberfläche und Dienste (Python 3.6, nur Standardbibliothek): Sendekette, Weichen, Kameradienste |
| `belacoder/`, `srtla/` | Patches für `belacoder` und `srtla_send`, die bei der Einrichtung auf dem Gerät gebaut werden |

Die Oberfläche erreichst du danach unter `http://<Adresse des Jetson>:8780`.

## Fehler melden

Wenn etwas nicht geht, hilft die Protokolldatei der Box am meisten:

1. In der Oberfläche die Karte **Protokolle** öffnen und **Protokolle herunterladen** drücken. Die Box sammelt etwa eine halbe Minute lang (Journal der Dienste, Zustand der Sendekette, Kameras, Netzwerk, Jetson-Werte wie Video-Hardware und Takte, die Berichte unerwarteter Enden von belacoder) und liefert eine Textdatei `irl4you-protokolle-<Datum>.txt`.
2. Die Datei ist bereinigt: Passwörter, Stream-ID, Serveradressen, WLAN-Namen, IP- und MAC-Adressen, Kamera-Schlüssel, Tailscale-Namen und Zugangsschlüssel sind durch Platzhalter ersetzt (gleiche Werte haben gleiche Nummern). Eigene Bezeichnungen (Name des Servers, Name einer Kamera) bleiben lesbar; bitte vor dem Weitergeben kurz durchsehen.
3. Die Datei an ein [Issue auf GitHub](https://github.com/IRL4YOU/irl4you-jetson-2gb-pip/issues) anhängen, mit Uhrzeit des Problems (die Zeiten in der Datei sind UTC) und einem Satz, was zu sehen war.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
