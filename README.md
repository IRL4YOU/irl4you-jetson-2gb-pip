# Jetson 2GB PIP (Beta)

Bild-in-Bild für den **Jetson Nano 2GB** (BELABOX-Image, JetPack 4.6.4 / L4T 32.7.4): mehrere Kameras zu einem Bild mischen und über SRT/SRTLA senden. Eigenständiges Projekt, die Jetson-Ausgabe von [IRL4YOU PIP](https://github.com/IRL4YOU/irl4you-pip).

**Webseite:** [irl4you.de](https://irl4you.de) · **Schwesterprojekt (Orange Pi / ROCK):** [IRL4YOU/irl4you-pip](https://github.com/IRL4YOU/irl4you-pip) · **Fehler und Wünsche:** [Issues](https://github.com/IRL4YOU/irl4you-jetson-2gb-pip/issues)

> **Beta:** Testversion, Änderungen sind jederzeit möglich. Die Versionsnummer steht in `VERSION`, die Änderungen in [CHANGELOG.md](CHANGELOG.md). Bisher gibt es: Senden mit Bild-in-Bild über die Video-Hardware des Jetson (alle Kameras immer bereit, Ausfall der Hauptkamera wird überbrückt), SRTLA, DJI-Kameras per Bluetooth, Vorschau, Update über die Oberfläche und Fernzugriff über Tailscale. Die USB-Kamera ist noch nicht mit echter Hardware geprüft; das 4-GB-Modell ist ebenfalls noch nicht getestet. Getestet auf dem Jetson Nano 2GB (JetPack 4.6.4).

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
| `pipbox/` | Weboberfläche (Python 3.6, nur Standardbibliothek) |

Die Oberfläche erreichst du danach unter `http://<Adresse des Jetson>:8780`.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
