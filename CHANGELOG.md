# Änderungen

## 0.1.9
- Osmo Action 6: Das Bild kommt über WLAN mit 1920x1088 Zeilen an (die letzten 8 Zeilen sind Füllzeilen, schwarz). Die Sendekette schneidet sie jetzt ab (nvvidconv mit festem Ausschnitt 1920x1080) statt das Bild zu stauchen. Gemessen im Vorschaubild: unten kein schwarzer Streifen mehr. Der Zuschnitt gilt nur für eine Kamera, die beim Aufbau der Kette 1920x1088 meldet; beim Start von Live muss die Action 6 also schon senden (sonst greift er erst beim nächsten Neuaufbau).
- Der Ausgang des Compositors ist jetzt fest 1920x1080 (vorher folgte er der Größe der Bilder).
- Eine Kamera, die an einem Platz neu dazukommt, löst einen gezielten Neustart von belacoder aus (der Decoder kann den Strom nicht wechseln); gemessen mit einer Testkamera am dritten kleinen Platz: Neustart, danach 30 Bilder/s.

## 0.1.8
- Tausch von Hauptbild und kleinen Bildern ohne Unterbrechung (Dialog „Bildaufbau speichern“, „Hauptbild wählen“, Controller-Tasten): Vorher bekam der Decoder eines Platzes beim Tausch plötzlich den Strom einer anderen Kamera; der Hardware-Decoder des Jetson verkraftet das nicht („reference in DPB was never decoded“), der Ausgang stand etwa 15 Sekunden, dann startete belacoder neu. Jetzt behält jede Kamera ihren Decoder-Platz (wie im anderen Paket: ein Schlüssel behält seinen Platz), und ein Tausch ändert nur Lage, Größe und Ebene der Bilder und die Tonquelle. Nur eine Kamera, die neu dazukommt, startet belacoder gezielt neu. Gemessen: 12 Tauschwechsel (cam-a mit cam-b und cam-a mit der Action 6) ohne Stillstand.
- Bericht bei einem unerwarteten Ende von belacoder: Die letzten Ausgabezeilen (ohne Adressen und Schlüssel), der Zustand der Weichen je Platz mit Uhrzeiten und die UDP-Fehlerzähler stehen in /var/lib/pipbox/belacoder-ende.txt (die letzten 6 Berichte). Damit lassen sich seltene Ausfälle erklären.
- Bekannt, noch nicht erklärt: Selten (etwa alle 10 bis 30 Minuten mit vier Kameras) meldet der Decoder „reference in DPB was never decoded“ und belacoder startet von selbst neu, auch ohne Tausch.

## 0.1.7
- Weniger CPU-Last durch den DJI-Dienst: Die Oberfläche fragte bei jeder Statusabfrage die WLAN-Liste neu ab (rund sieben nmcli-Aufrufe je Abfrage, dabei liefen polkit, NetworkManager und dbus-daemon zusammen auf etwa einem Drittel eines Kerns). Die Anzeige darf jetzt 30 Sekunden alt sein; beim Verbinden einer Kamera wird weiter frisch gelesen. Gemessen: von etwa 40 auf 2 Aufrufe in 12 Sekunden.

## 0.1.6
- USB-Kamera als Kamera (Webcam, HDMI-USB-Grabber): Der Dienst aus dem anderen Paket speist die erste angeschlossene USB-Kamera als RTMP-Kamera ein (MJPEG, Rohbild oder H.264, mit dem Hardware-Kodierer des Jetson). **Nicht mit einer echten Kamera geprüft:** Getestet wurde der Weg ab der Kamera (MJPEG, Rohbild und H.264 aus einem Testbild bis zum RTMP-Server: richtige Größe, 30 Bilder/s, Ton). Wie sich echte Kameras und Grabber melden (Formate, Tongerät), bleibt offen. Ein H.264-Strom mit Füllzeilen (Osmo Action 6 am USB) wird nicht zugeschnitten. Der HDMI-Eingang des Rockchip-Boards fehlt dem Jetson. Hinweis: Eine USB-Kamera am Jetson braucht Strom; bei Ausfällen einen USB-Hub mit eigenem Netzteil verwenden.
- Fernzugriff über Tailscale auf Ubuntu 18.04: Die Paketquelle von tailscale.com hat für dieses System nur Version 1.8.2 von 2021 (ohne „serve“ und „funnel“). Der Helfer lädt deshalb das offizielle Programmpaket (rund 36 MB, aktuelle Version) und richtet den Dienst selbst ein. Die Anmeldung beim Tailscale-Konto machst du selbst.

## 0.1.5
- DJI-Kameras per Bluetooth: Der Dienst aus dem anderen Paket (Protokoll nach Moblin) läuft jetzt auf dem Jetson. Er braucht die Bluetooth-Bibliothek bleak ab Version 0.22 und damit Python 3.8; das System hat 3.6, deshalb richtet die Installation eine eigene Umgebung ein (/opt/pipbox/venv-dji, Python 3.8 aus den Ubuntu-Paketen und bleak per pip, braucht Internet). Schlägt das fehl, läuft alles andere, nur die DJI-Kameras gehen dann nicht.
- Voraussetzung: ein USB-Bluetooth-Adapter (getestet: ASUS USB-BT500). Der Jetson Nano 2GB hat kein eingebautes Bluetooth.

## 0.1.4
- Vorschau des gesendeten Bildes: Ein eigener Dienst (startet erst, wenn jemand die Vorschau öffnet) liest den lokalen SRT-Strom mit, dekodiert ihn mit der Video-Hardware des Jetson und liefert dem Browser ein kleines Bild (640x360, 30 Bilder/s, rund 1,5 Mbit/s als H.264, ersatzweise Motion-JPEG). Die Sendung wird dabei nicht angefasst; die Vorschau kostet rund ein Fünftel eines Kerns.

## 0.1.3
- Wächter für die Sendekette (wie beim anderen Paket, in einer Fassung für den Jetson): Steht die Kennzahlen-Datei von belacoder 15 Sekunden still, hängen seine Threads 12 Sekunden im Kernel oder liefert der Encoder 12 Sekunden keine Bilder, sichert er ein Diagnosepaket (hang-diagnose.txt, ohne Schlüssel und Adressen) und startet belacoder neu. Höchstens 4 Eingriffe je Stunde, danach 90 Sekunden Ruhe.

## 0.1.2
- Behebt Abbrüche beim Start der Sendung mit „Alle Kameras immer bereit“: Der Hardware-Encoder sendet nur alle 256 Bilder einen Keyframe (IDR), ein neu startender Decoder wartete bis zu 9 Sekunden, und der Empfänger trennte die Verbindung nach 14 Sekunden ohne Daten. Jetzt kommt alle 2 Sekunden ein IDR (wie beim anderen Paket mit gop=60), das Füllbild alle halbe Sekunde.
- belacoder startet erst, wenn an allen Plätzen Bilder ankommen; die Weichen setzen bei jedem Start von belacoder zurück.
- Die Kameras erscheinen erst am Keyframe, ein Hauptbild-Wechsel beim Start wegen eines später ankommenden Keyframes unterbleibt.

## 0.1.1
- Senden mit Bild-in-Bild: eine große Kamera und bis zu 3 kleine Bilder, zusammengesetzt von der Video-Hardware des Jetson (nvcompositor), H.265 aus dem Hardware-Encoder.
- belacoder und srtla_send werden bei der Einrichtung mit den Patches aus `belacoder/` und `srtla/` gebaut (Kennzahlen und Zustand der Wege für die Anzeige Live).
- „Alle Kameras immer bereit“: Je Platz holt ein Zubringer den Stream der Kamera aus dem RTMP-Server, eine Weiche gibt bis zum ersten Keyframe der Kamera ein schwarzes Füllbild weiter und schaltet genau dort um. Die Sendung startet auch ohne Kamera und läuft weiter, wenn Kameras kommen und gehen (gemessen: durchgehend 30 Bilder/s).
- Fällt die Hauptkamera aus, springt die erste vorhandene Nebenkamera als Hauptbild ein (nicht deaktivierte, in der Reihenfolge der Einstellung), der Ton folgt; die Hauptkamera übernimmt nach 3 Sekunden stabilen Bildern wieder. Kleine Bilder ohne Kamera sind unsichtbar.
- Positionen und Größen der Bilder werden auf gerade Werte gerundet (der Compositor meldete sonst bei ungeraden Werten jedes Bild).
- Noch nicht enthalten: die Kameras (DJI per Bluetooth, HDMI, USB).

## 0.1.0
- Erste Beta für den Jetson Nano 2GB (BELABOX-Image, JetPack 4.6).
- Einrichtung in zwei Schritten: Systemupdate mit Aufräumen, danach die Weboberfläche auf Port 8780.
- Anzeige von Temperaturen, Kernen, GPU und Lüfter des Jetson.
- Meldung bei Überlast der Stromversorgung und bei USB-Ausfällen.
- Helfer für das SSH-Passwort, System- und Software-Updates, WLAN, Neustart, Protokolle, Fernzugriff und feste Adresse.
- Noch nicht enthalten: Senden mit Bild-in-Bild und die Kameras (DJI per Bluetooth, HDMI, USB).
