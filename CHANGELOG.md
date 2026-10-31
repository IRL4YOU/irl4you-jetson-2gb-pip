# Änderungen

## 0.1.25
- **USB-Kamera (zum Beispiel DJI Osmo Action 4 über USB) lieferte nur etwa 4 bis 5 Bilder je Sekunde und rund 1 Mbit/s statt 30 fps und 8000 kbit/s.** Auslöser war ein Protokoll eines anderen Streamers (Thread `v4l2src` mit fast 100 %, Stream mit 3,8 fps). Der Fehler ließ sich mit der echten Kamera am Gerät nachstellen: Der MJPEG-Strom der Kamera kam mit 26 fps an (rund 210 KB je Bild), aber `nvjpegdec` brauchte für 120 Bilder 24 Sekunden, fast nur Systemzeit. Jetzt dekodiert der Hardware-Dekoder (`nvv4l2decoder mjpeg=1`): dieselben 120 Bilder in 4,4 Sekunden. Gilt für die Einspeisung und den Probelauf der USB-Kamera.

## 0.1.24
- **0.1.23 war zu teuer, jetzt behoben:** Das dauernd laufende Füllbild (ein Encoder-Prozess je Platz) trieb die CPU von etwa 50 % auf fast 100 % und füllte den Arbeitsspeicher (vier Prozesse mit je rund 40 MB und 25 bis 50 % eines Kerns). Jetzt wird das schwarze Füllbild beim Start ein Mal aufgenommen (eine Gruppe von Bildern, 25 Pakete, einige Sekunden Encoder) und die Weiche jedes Platzes spielt es selbst ab, wenn ihre Kamera nichts liefert. Es läuft kein Prozess mehr dafür; der Ausfall einer Kamera lässt die Ausgabe trotzdem nicht stehen (Prüfstand: durchgehend rund 750 KB je 2 s, auch während des Ausfalls und bei der Rückkehr der Kamera).
- Zeitstempel des abgespielten Füllbildes zählen lückenlos weiter, das Abspielen beginnt immer an der Gruppe mit SPS/PPS und IDR.

## 0.1.23
- **Sendung bleibt stehen, wenn eine Kamera ausfällt: behoben.** Endet der Strom einer Kamera (DJI „Trennen“ oder „Neu verbinden“, Kabel gezogen, Akku leer), stand bisher die ganze Ausgabe (im Prüfstand gemessen: 25 Sekunden ohne ein Byte, bis die Kamera wieder da war; am Gerät schlug der Wächter nach etwa 6 Sekunden zu und startete belacoder neu, 30 bis 40 Sekunden ohne Bild). Grund: der Bild-Mischer (nvcompositor) wartet an jedem Platz auf Bilder. Jetzt läuft das schwarze Füllbild an jedem belegten Platz dauernd mit, und die Weiche schaltet darauf zurück, sobald die Kamera nichts mehr liefert. Im Prüfstand läuft die Ausgabe durchgehend weiter (etwa 750 KB je 2 s auch während des Ausfalls), die Kamera kommt nach dem Neustart des Zubringers wieder ins Bild.
- **Verpixeln per Chat entfernt** („!pixel“, „Moderatoren dürfen auch Köpfe ausschalten“): Die Jetson-Version hat kein Verpixeln. Mit dem Abschnitt in der Oberfläche fallen die Platzhalter `srv/datenschutz.py`, die Schalter in der Pipeline und die Hinweise (Facecam, „Alle Kameras immer bereit“) weg.
- **Mikro-Akku (DJI) entfernt** (Haken, Erinnerung, Meldungstext): Der Dienst `pipbox-mic`, der die Akkustände liefert, gehört nicht zu diesem Paket, die Einstellung hätte nie etwas gemeldet.
- Update-Helfer: Fortschrittsanzeige mit den echten Schritten von `install.sh` (Pakete, Dienst, Dateien, Encoder, SRTLA, Start); die toten Schritte „Baustein“ und „Datenschutz“ entfallen. Übersetzungen ohne die entfernten Texte.

## 0.1.22
- Installation und Update räumen `pipbox_live.py` (und einen alten Ordner `gst`) in `/opt/pipbox` weg, die frühere Versionen mitbrachten und die es nicht mehr gibt. Ohne das bliebe die Datei nach einem Update liegen. Sonst keine Änderung (0.1.21 ist am Gerät geprüft: Sendung 30 fps, Dienste laufen, Tausch-Hinweis „ohne Unterbrechung“, Statistik ohne NPU, kein Lüfterwert).

## 0.1.21
- **Rockchip-Reste umgestellt oder entfernt** (aus dem anderen Paket übernommen, auf dem Jetson tot oder irreführend). Verhalten der Sendekette, der Pläne und der Kettentexte ist unverändert (Vergleich über 240 Einstellungen und 42 Änderungspaare vor und nach dem Umbau: keine Abweichung), dazu kommen die Korrekturen unten.
  - Entfernt: die Engine mit Rockchip-Compositor (`pipbox_live.py`, 1100 Zeilen), die Rockchip-Zweige in `pipeline.py` (Umschalter, Überlagerungs-Baustein, Verpixeln-Zweig), die alten Zubringer-Klassen in `pipbox_always.py`, die Umschalter-Dateien und Prüfungen des Bausteins (`plugin.py`), `style_text`/`small_decode`, die NPU-Messung und die Rückmeldung der alten Kette im Sendedienst.
  - **Tausch-Knöpfe:** Der Hinweistext am Knopf „Als Hauptbild verwenden“ sagte auf dem Jetson immer „der Encoder startet dafür neu, etwa 5 Sekunden ohne Bild“. Der Tausch geht aber ohne Unterbrechung (Rollen, jede Kamera behält ihren Decoder). Der Text stimmt jetzt.
  - **DJI:** „Trennen“, „Neu verbinden“ und der Netzwechsel warteten 4,5 Sekunden auf einen Regler des anderen Pakets, den es hier nicht gibt (Zweig-Sperre `feed-hold.json`). Entfällt.
  - **Auslastungsliste** (System, Statistik): Video-Hardware zuerst, die GPU zuletzt (sie bleibt bei der Videoverarbeitung auf 0 %, weil Decoder, Bildwandler und Encoder die Arbeit machen); die NPU-Zeile gibt es nicht mehr. Die Demo zeigt Jetson-Werte.
  - Die Hauptverzögerung ist bei einer neuen Installation 0 ms (vorher 450 ms, das andere Paket braucht sie für seine langsameren kleinen Bilder; auf dem Jetson wirkt die Verzögerung seit 0.1.18 wirklich).
  - Offen: Der HDMI-Teil des Kameradienstes (Quelle „HDMI-Eingang“ des anderen Boards) ist noch im Code, wird auf dem Jetson aber abgelehnt und ist in der Oberfläche ausgeblendet.

## 0.1.20
- **Lüfterzeile (Karte „System“, Zeile „Lüfter: 0 % (Ansteuerung)“):** Der Jetson Nano kann nicht erkennen, ob ein Lüfter am Anschluss steckt, und liefert keine Drehzahl; der PWM-Ausgang wird auch ohne Lüfter oder bei einem extern gespeisten Lüfter (zum Beispiel über USB) gemeldet. Neue Einstellung **Optionen → Lüfter → „Lüfter am Anschluss der Box“**: *Automatisch* (Standard: die Zeile erscheint erst, wenn die Box den Ausgang wirklich ansteuert, also größer als 0, und bleibt dann bis zum Neustart des Dienstes), *Ja* (Zeile immer) oder *Nein, extern versorgt* (Zeile nie, auch nicht auf der Statistik-Seite). Die Wahl steht auf der Box (`fan.json`) und gilt für alle Geräte. Die Einstellung erscheint nur auf dem Jetson; auf dem Rockchip-Board ändert sich nichts.

## 0.1.19
- **Neue Installation startet gleich mit „Alle Kameras immer bereit“.** Bisher stand der Schalter auf dem Jetson bei einer frischen Installation noch aus („auf dem Jetson noch nicht verfügbar“, ein Rest aus der Anfangszeit): Die Sendung lief dann im alten Einzelmodus ohne Weichen, ohne Füllbild, ohne Verzögerung, Rahmen und Beschnitt im Betrieb und mit Neustart bei jedem Tausch. Wer schon einen Bildaufbau gespeichert hat, behält seine Wahl. Geprüft: der Kettentext für eine Kamera, Bild-in-Bild mit einem und mit drei kleinen Bildern; am Gerät ist die Betriebsart „eine Kamera“ noch nicht gesendet worden.
- **Karte „Kameras“, Abschnitt „USB-Kameras“:** Der Jetson hat keinen HDMI-Eingang. Der Kameradienst meldet das jetzt (hdmi_input), die Oberfläche zeigt nur die USB-Kamera (Webcam oder HDMI-USB-Grabber) ohne die Auswahl „HDMI-Eingang“, und der Dienst lehnt die Quelle „HDMI“ auf dem Jetson mit einer klaren Meldung ab.

## 0.1.18
- **Verzögerung je Kamera** (Bildaufbau, „Verzögerung: … ms“) wirkt jetzt auf dem Jetson. Bisher nahm die Oberfläche den Wert an („gilt sofort“), er hatte aber keine Wirkung: Der Regler stammte vom Rockchip-Baustein, den es hier nicht gibt. Jetzt hält die Weiche des Platzes die Pakete der Kamera (Bild und Ton zusammen) um die gewählte Zeit zurück, höchstens 750 ms wie im anderen Paket. Die Verzögerung gehört zur Kamera: Tauscht du Haupt- und kleines Bild, geht sie mit. Bis das erste verzögerte Bild ankommt, läuft das Füllbild weiter (der Platz ist nie leer), der Ton bis dahin als Stille. Eine Änderung im Betrieb hält den Strom einmalig um den Unterschied an (größer) oder gibt Aufgestautes auf einmal frei (kleiner). Der Endbericht nennt die Verzögerung je Platz.
- Geprüft mit simulierter Uhr und echten UDP-Sockets (300 ms: erstes Kamerabild nach 0,31 s, Reihenfolge erhalten, Kamera weg: Warteschlange leer). Am Gerät mit echten Kameras noch nicht gemessen.

## 0.1.17
- Protokolle: Die Lastliste der Video-Hardware nennt nur noch Einheiten mit lesbarem Wert (vic, nvdec, nvenc, nvjpg, gpu). Geprüft an einer Datei vom 31.10.: keine Serveradresse, keine Stream-ID, keine Heimnetz- oder MAC-Adressen, Kamera-Schlüssel und WLAN-Namen ersetzt; der Name des eigenen Hotspot-Profils („pipbox-hotspot-…“) und selbst vergebene Bezeichnungen (Server, Kamera) bleiben lesbar.
- README: Abschnitt „Fehler melden“ (Protokolldatei erzeugen, was darin ersetzt ist, wohin damit).

## 0.1.16
- „Bildaufbau speichern“ startet die Sendung auf dem Jetson nicht mehr neu, wenn sich nur Lage, Größe, Ecke, Beschnitt, Rahmen, Ton oder Sichtbarkeit ändern: Das alles setzt der Sende-Dienst im Betrieb über die Steuerdatei. Neu gebaut wird nur bei anderer Art oder anderer Zahl kleiner Bilder; eine neue Kamera an einem Platz startet der Sende-Dienst selbst gezielt neu. Vorher galt die Regel des Rockchip-Bausteins (Stile und Größen = Neustart).
- Protokolle (Karte „Protokolle“, Datei für die Fehlersuche): neue Abschnitte für den Jetson: L4T-Stand, Last der Video-Hardware (VIC, NVDEC, NVENC, GPU), Takte, Lüfter, tegrastats; die Steuerdatei der Kette, Ansicht (gewünscht/bestätigt), Zubringer und Weichen mit ihren Kernen; die Berichte unerwarteter Enden von belacoder (belacoder-ende.txt) und der Pipeline-Text der letzten Sendekette. Dienste pipbox-hdmi, pipbox-preview und pipbox-send-ctl stehen mit in der Dienstliste und im Journal. Alles läuft durch dieselbe Bereinigung (Adressen, Schlüssel, Namen).
- Update-Helfer ohne Reste der Datenschutz-Beta des anderen Pakets.

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
