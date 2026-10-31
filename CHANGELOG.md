# Änderungen

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
