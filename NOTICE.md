# Hinweise zu Herkunft und Drittprojekten

Die Weboberfläche in `pipbox/` stammt aus dem Projekt IRL4YOU BOX (MIT-Lizenz) und wurde für den Jetson Nano 2GB und Python 3.6 angepasst.
Dieses Repository enthält kein Erkennungsmodul (Verpixeln), keine KI-Modelle und keine Schrift- oder Bilddateien. Das IRL4YOU-Logo steht als SVG im Seitenquelltext (Kopfzeile) und als Datei `pipbox/web/favicon.svg` (Symbol im Browser-Tab). Logo: Eigenentwurf von IRL4YOU (favicon.svg der Seite irl4you.de).

## Moblin (MIT-Lizenz)

Die DJI-Kopplung (`pipbox/dji_daemon.py`) folgt dem Ablauf, den das Projekt
[Moblin](https://github.com/eerimoq/moblin) von Erik Moqvist für DJI-Kameras
per Bluetooth umsetzt (Ordner `Moblin/Integrations/Dji/`). Nachrichtenformat,
Konstanten und Ablauf wurden von dort nach Python übertragen. Gegenproben mit
[dimadesu/dji-remote](https://github.com/dimadesu/dji-remote) (MIT, Copyright (c) 2026 Dmytro Antonov) und
[datagutt/node-osmo](https://github.com/datagutt/node-osmo) (MIT, Copyright (c) 2024 Thomas Lekanger).
Die Copyright-Zeilen stehen in der LICENSE-Datei des jeweiligen Projekts. Der Bezug zu node-osmo ist im Kopf von `pipbox/dji_daemon.py` vermerkt
(dort als Gegenprobe des Protokolls, seit der ersten Fassung dieses Repositorys).
Das Protokoll stammt aus dem Nachbau dieser Projekte und ist von DJI nicht
dokumentiert.

### Moblin – MIT License

Copyright (c) 2023 Erik Moqvist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## DJI-Dienst (MIT-Lizenz)

Sitzungsablauf, Verbindungsliste, Befehle und die Oberfläche der DJI-Kameras (`pipbox/dji_daemon.py`, Karten in `pipbox/web/js/dji.js`)
folgen dem DJI-Dienst von Bittersweet1987, hier angepasst. Der Urheber hat die Verwendung unter der MIT-Lizenz erlaubt
(Lizenzdatei in seinem Projekt vom 4. Oktober 2026).

### DJI-Dienst – MIT License

Copyright (c) 2026 Bittersweet

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## bleak (MIT-Lizenz)

Der Bluetooth-Dienst für die DJI-Kameras nutzt die Bibliothek [bleak](https://github.com/hbldh/bleak) (MIT-Lizenz, Henrik Blidh). Sie wird bei der Einrichtung per pip in eine eigene Python-Umgebung geladen und ist nicht Teil dieses Repositorys.

## belacoder und srtla_send (GPL-3.0 und AGPL-3.0)

Die Sendekette nutzt `belacoder` ([BELABOX/belacoder](https://github.com/BELABOX/belacoder), Commit ccce9ca, GPL-3.0)
und `srtla_send` ([BELABOX/srtla](https://github.com/BELABOX/srtla), Commit 37862da, AGPL-3.0).
Beide werden bei der Einrichtung auf dem Gerät aus dem Original-Quelltext gebaut. Dieses Repository enthält nur die eigenen Änderungen
als Patch-Dateien, nicht den Quelltext der Projekte:

- `belacoder/` (GPL-3.0), 4 Patches: `belacoder-jitter-tolerant.patch`, `belacoder-stall-output.patch`, `belacoder-stats.patch`, `belacoder-padctl.patch`
- `srtla/` (AGPL-3.0), 2 Patches: `srtla_send-latency-aware.patch`, `srtla_send-min-share.patch`

Die Patches ändern das Verhalten des Bitraten-Reglers, der Wegewahl und liefern Kennzahlen für die Anzeige Live.
Die Lizenztexte stehen in den jeweiligen Originalprojekten. Auf Wunsch gibt der Betreiber der Box den Quelltext der gebauten Fassung heraus.

## libsrt (MPL-2.0)

`belacoder` wird beim Bau gegen die Bibliothek libsrt (SRT) aus dem BELABOX-Paket `belabox-libsrt1` gelinkt; die Header für den Bau kommen aus demselben Paket (`belacoder/build.sh`).
Sie wird unverändert verwendet und gehört nicht zu diesem Repository. Lizenz: Mozilla Public License 2.0. BELABOX pflegt dazu den Fork [BELABOX/srt](https://github.com/BELABOX/srt) („SRT tweaked for use with srtla“, Fork von [Haivision/srt](https://github.com/Haivision/srt)); dessen LICENSE-Datei enthält die MPL-2.0.

## Nicht mitgeliefert, nur genutzt

Diese Programme gehören nicht zu diesem Repository, es enthält weder ihren Quelltext noch Kopien. Sie stehen jeweils unter ihrer eigenen Lizenz.

- **belaUI** ([BELABOX/belaUI](https://github.com/BELABOX/belaUI), GPL-3.0 laut LICENSE-Datei des Projekts) und der übrige Teil des BELABOX-Images (zum Beispiel nginx für den RTMP-Eingang): Läuft auf der Box. Von belaUI wird nur der Passwort-Hash aus `config.json` gelesen; es wird nichts daran geändert.
- **Jetson Linux (L4T) von NVIDIA**: Die Video-Elemente `nvvidconv`, `nvv4l2decoder`, `nvv4l2h264enc`, `nvcompositor` und `nvjpegdec`/`nvjpegenc` sind Teil von NVIDIAs Jetson-Linux-Paketen und unterliegen der Lizenz des Herstellers.
- **GStreamer und GLib** (LGPL): Systempakete. Für den Bau von `belacoder` werden ihre Header vorübergehend aus den Entwicklerpaketen entpackt, die Pakete selbst werden dabei nicht installiert.
- **bleak und deren Abhängigkeiten** (bleak: MIT, siehe oben): werden bei der Einrichtung per pip in eine eigene Python-Umgebung geladen, jeweils unter eigener Lizenz.
- **Tailscale** (nur wenn du den Fernzugriff einrichtest): Wird aus der offiziellen Paketquelle des Herstellers installiert, eigene Lizenz.
- **Twitch, BetterTTV, FrankerFaceZ, 7TV**: Der Chat holt Emotes zur Laufzeit von deren Diensten und speichert sie nicht im Repository. Die Emotes gehören ihren Urhebern.

## BELABOX

Unabhängiges Zusatzprojekt, kein Produkt von BELABOX, NVIDIA oder DJI.
Es ändert keine Dateien von BELABOX und liest das BELABOX-Passwort nur zur Anmeldeprüfung.

## Welche Lizenz gilt wo

- **MIT** (eigener Code): alles in diesem Repository, außer den Patch-Dateien unten. Teile, die auf MIT-lizenzierten Projekten beruhen (Moblin, DJI-Dienst, bleak), sind oben genannt.
- **GPL-3.0**: die 4 Patch-Dateien in `belacoder/` und das daraus gebaute Programm `belacoder`.
- **AGPL-3.0**: die 2 Patch-Dateien in `srtla/` und das daraus gebaute Programm `srtla_send`.
- **MPL-2.0**: libsrt (nicht Teil des Repositorys, siehe oben).
- Alle anderen genutzten Programme: eigene Lizenz, siehe „Nicht mitgeliefert, nur genutzt“.
- Keine Rechtsberatung.
