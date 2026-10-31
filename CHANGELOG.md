# Änderungen

## 0.1.0
- Erste Beta für den Jetson Nano 2GB (BELABOX-Image, JetPack 4.6).
- Einrichtung in zwei Schritten: Systemupdate mit Aufräumen, danach die Weboberfläche auf Port 8780.
- Anzeige von Temperaturen, Kernen, GPU und Lüfter des Jetson.
- Meldung bei Überlast der Stromversorgung und bei USB-Ausfällen.
- Helfer für das SSH-Passwort, System- und Software-Updates, WLAN, Neustart, Protokolle, Fernzugriff und feste Adresse.
- Senden mit Bild-in-Bild: eine große Kamera und bis zu 3 kleine Bilder, zusammengesetzt von der Video-Hardware des Jetson (nvcompositor), H.265 aus dem Hardware-Encoder.
- belacoder und srtla_send werden bei der Einrichtung mit den Patches aus `belacoder/` und `srtla/` gebaut (Kennzahlen und Zustand der Wege für die Anzeige Live).
- „Alle Kameras immer bereit“: Je Platz holt ein Zubringer den Stream der Kamera aus dem RTMP-Server, eine Weiche gibt bis zum ersten Keyframe der Kamera ein schwarzes Füllbild weiter und schaltet genau dort um. Die Sendung startet auch ohne Kamera und läuft weiter, wenn Kameras kommen und gehen (gemessen: durchgehend 30 Bilder/s).
- Fällt die Hauptkamera aus, springt die erste vorhandene Nebenkamera als Hauptbild ein (nicht deaktivierte, in der Reihenfolge der Einstellung), der Ton folgt; die Hauptkamera übernimmt nach 3 Sekunden stabilen Bildern wieder. Kleine Bilder ohne Kamera sind unsichtbar.
- Noch nicht enthalten: die Kameras (DJI per Bluetooth, HDMI, USB).
