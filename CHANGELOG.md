# Änderungen

## 0.1.15
- Dringende Korrektur: Seit 0.1.11 fehlte in der Antwort der Bildaufbau-Schnittstelle die Kameraliste (eine Zeile war versehentlich auskommentiert). Folge: Fehler in der Karte „Bildaufbau“ (Vorschau, Kamerawahl, Speichern von Aussehen-Einstellungen), die Eckenrundung blieb sichtbar. 0.1.11 bis 0.1.14 bitte überspringen.

## 0.1.14
- Korrektur zu 0.1.13: Ein Fehler in der Oberfläche (Zugriff auf eine noch nicht angelegte Variable) hätte die Karte „Bildaufbau“ lahmgelegt; 0.1.13 bitte überspringen.

## 0.1.13
- Bildaufbau, Karte „Aussehen“: Eine Änderung an Beschnitt, Rahmen oder Sichtbarkeit ging verloren, wenn die Oberfläche zwischen Eingabe und „Bildaufbau speichern“ die Einstellung neu abfragte (alle paar Sekunden). Jetzt gilt die Eingabe als ungespeichert („Nicht gespeichert: …“) und bleibt bis zum Speichern stehen. Betrifft auch das andere Paket. Die Eckenrundung wird auf dem Jetson jetzt zuverlässig ausgeblendet.

## 0.1.12
- Aussehen der kleinen Bilder auf dem Jetson: **Beschnitt** (links, rechts, oben, unten, wie bei einem Bild von 1920x1080) und **Rahmen** (Dicke, Farbe, Deckkraft) gehen jetzt, beides im Betrieb ohne Neustart. Der Beschnitt läuft über den nvvidconv des Platzes (feste Ausgabegröße 1920x1080, so ändert sich das Format zum Compositor nie; er wird auf die Bildgröße der Kamera umgerechnet, und die 8 Füllzeilen der Osmo Action 6 fallen dabei an jedem Platz weg, auch nach einem Tausch), der Rahmen ist eine Farbfläche hinter dem kleinen Bild (eigenes Pad im Compositor, Ebene zwischen Hauptbild und Bild). Die Eckenrundung gibt es auf dem Jetson nicht (der Compositor kennt keine Rundung); die Oberfläche blendet sie aus. Dafür versteht die Steuerdatei von belacoder jetzt auch Element-Eigenschaften („vc1 left 64“, „frame1 foreground-color …“); belacoder wird beim Update einmal neu gebaut.
- Update-Helfer: keine Reste der Datenschutz-Beta des anderen Pakets mehr.
- Noch nicht geprüft: Beschnitt im laufenden Betrieb über längere Zeit (nvvidconv meldet die Eigenschaften als im Betrieb änderbar).

## 0.1.11
- Ursache der Stillstände eingegrenzt und behoben (gemessen über 25 Minuten mit vier Kameras): Die Pakete der Zubringer kamen an der Weiche in vertauschter Reihenfolge an (Lücken von 1 bis 91 Paketen an allen Plätzen, in fallenden Serien, ohne dass der Kernel etwas verwarf, je Platz nur ein Sender). UDP über Loopback hält die Reihenfolge nur, solange der sendende Thread auf demselben Kern bleibt. Die Weiche nummerierte die vertauschten Pakete neu, der Depayloader setzte Bildteile falsch zusammen, der Decoder meldete „reference in DPB was never decoded“ und stand nach einiger Zeit (Stillstand, Neustart von belacoder, 20 bis 40 s ohne Bild). Jetzt laufen Zubringer, Füllbild und Weiche jedes Platzes auf einem festen Kern (Kerne 1 bis 3). Der Endbericht zählt Lücken und Nachzügler getrennt und die Starts der Zubringer, damit sich die Wirkung prüfen lässt. Ein reiner Verlust von 300 Paketen am Stück ließ die Kette im Versuch dagegen ungestört weiterlaufen.
- Kleine Bilder ausblenden, Tonquelle wechseln und Stumm gehen jetzt ohne Neustart der Sendung. Vorher erwartete die Oberfläche die Rückmeldung des Rockchip-Bausteins, die es auf dem Jetson nicht gibt, und startete die Sendung neu („Ansicht nicht bestätigt, Neustart der Sendung folgt“). Jetzt setzt der Sendedienst Sichtbarkeit (alpha) und Lautstärke der Pads über die Steuerdatei und meldet den Zustand in view-state zurück.
- Weitere Rockchip-Reste auf den Jetson umgestellt: Die Prüfungen auf den Rockchip-Baustein (Ecken, Tausch, Füllbild, Ansicht, Stil) antworten auf dem Jetson mit dem, was die Nvidia-Kette kann (alle sechs Positionen, Tausch über Rollen, Füllbild über die Weiche, Ansicht im Betrieb; Beschnitt/Deckkraft/Rahmen noch nicht); die Lage der kleinen Bilder rechnet die Jetson-Kette selbst (vorher aus dem Rockchip-Modul). Statistik: statt NPU zeigt die Seite die Video-Hardware des Jetson (Bildwandler VIC, Decoder NVDEC, Encoder NVENC, 2 s gemittelt) neben der GPU. Diagnose: die Probe-Dekodierung nutzt nvv4l2decoder, die Kernel-Hinweise kennen tegra/nvhost/nvdec/nvenc/vic.

## 0.1.10
- Der Bericht bei einem unerwarteten Ende von belacoder (`/var/lib/pipbox/belacoder-ende.txt`) zeigt jetzt auch, wo Pakete verloren gehen: je Platz die Pakete, die laut Folgenummer zwischen Zubringer und Weiche fehlen (mit Uhrzeit, wenn es bei offenem Tor passiert), und die verworfenen Pakete je lokalem UDP-Port (Eingänge der Kette, Weichen, srtla_send). Damit lässt sich die Ursache des seltenen Decoderfehlers „reference in DPB was never decoded“ eingrenzen. Gemessen: Der Zähler von srtla_send (Port 9100) hatte einmal 115 Pakete verworfen (SRT holt sie per Wiederholung nach), die Kamera-Eingänge standen auf 0.
- README: Link zur Webseite und zum Schwesterprojekt, aktueller Funktionsstand.

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
