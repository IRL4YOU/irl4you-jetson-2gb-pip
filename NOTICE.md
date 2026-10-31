# Hinweise zu Herkunft und Drittprojekten

Die Weboberfläche in `pipbox/` stammt aus dem Projekt IRL4YOU BOX (MIT-Lizenz) und wurde für den Jetson Nano 2GB und Python 3.6 angepasst.

## Moblin (MIT-Lizenz)

Die DJI-Kopplung (`pipbox/dji_daemon.py`) folgt dem Ablauf, den das Projekt
[Moblin](https://github.com/eerimoq/moblin) von Erik Moqvist für DJI-Kameras
per Bluetooth umsetzt (Ordner `Moblin/Integrations/Dji/`). Nachrichtenformat,
Konstanten und Ablauf wurden von dort nach Python übertragen. Gegenprobe mit
[dimadesu/dji-remote](https://github.com/dimadesu/dji-remote) (MIT).
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

## BELABOX

Unabhängiges Zusatzprojekt, kein Produkt von BELABOX, NVIDIA oder DJI.
Es ändert keine Dateien von BELABOX und liest das BELABOX-Passwort nur zur Anmeldeprüfung.

## Welche Lizenz gilt wo

- **MIT** (eigener Code): alles in diesem Repository, außer den oben genannten Teilen, die auf MIT-lizenzierten Projekten beruhen.
- Keine Rechtsberatung.
