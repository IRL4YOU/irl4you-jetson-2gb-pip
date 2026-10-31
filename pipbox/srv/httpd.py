"""HTTP-Server mit Verbindungsgrenzen sowie die Aktionen für Szenenwechsel und Controller."""

import socket
import sys
import threading
from compat36 import ThreadingHTTPServer

from srv.access import source_allowed
from srv.cameras import KEY_RE
from srv.pipeline import PipelineStore


class LimitedHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer mit Grenzen (Issue #25): höchstens MAX_CONN Verbindungen zugleich, davon höchstens PER_IP je Absender (ein einzelner
    Client mit lauter halb offenen Anfragen sperrt so nicht alle anderen aus), und keine Quelladressen aus dem öffentlichen Internet."""
    daemon_threads = True
    request_queue_size = 64
    MAX_CONN = 64
    PER_IP = 16
    allow_public = False
    ui_access = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._conn_lock = threading.Lock()
        self._conns = {}
        self._senders = {}
        self._total = 0

    LOOPBACK_CONN = 48        # vom Tailscale-Proxy (Serve/Funnel): davor nur diese Obergrenze, danach zählt der echte Absender aus X-Forwarded-For

    def verify_request(self, request, client_address):
        ip = client_address[0]
        if not self.allow_public and not source_allowed(ip):
            return False
        loop = self.is_loopback(ip)
        ua = self.ui_access
        if ua is not None and ua.block:                                   # über fremde WLANs (Gast-WLAN der Box) nicht erreichbar
            try:
                if ua.refuses(request.getsockname()[0]):
                    return False
            except (OSError, AttributeError):
                pass
        with self._conn_lock:
            if self._total >= self.MAX_CONN or (self._conns.get(ip, 0) >= (self.LOOPBACK_CONN if loop else self.PER_IP)):
                return False
            self._conns[ip] = self._conns.get(ip, 0) + 1
            self._total += 1
        return True

    @staticmethod
    def is_loopback(ip):
        return ip in ("127.0.0.1", "::1")

    def claim_sender(self, ip):
        """Hinter dem Proxy: den echten Absender zählen (höchstens PER_IP offene Verbindungen). Wahr, wenn noch Platz ist."""
        with self._conn_lock:
            if self._senders.get(ip, 0) >= self.PER_IP:
                return False
            self._senders[ip] = self._senders.get(ip, 0) + 1
            return True

    def release_sender(self, ip):
        with self._conn_lock:
            n = self._senders.get(ip, 1) - 1
            if n > 0:
                self._senders[ip] = n
            else:
                self._senders.pop(ip, None)

    def handle_error(self, request, client_address):
        """Ein Gegenüber, das die Verbindung abbricht oder zu langsam ist (Issue #25), ist kein Fehler des Dienstes: kein Traceback im Journal
        (sonst wird das Protokoll bei vielen abgeschnittenen Anfragen unlesbar)."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout)) or (isinstance(exc, OSError) and exc.errno in (9, 32, 54, 104)):
            return
        super().handle_error(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            ip = client_address[0]
            with self._conn_lock:
                self._total -= 1
                n = self._conns.get(ip, 1) - 1
                if n > 0:
                    self._conns[ip] = n
                else:
                    self._conns.pop(ip, None)


def scene_swap(pipeline, cams, send, with_key=None):
    """Hauptbild gegen ein kleines Bild tauschen (Oberfläche und Controller-Tasten). Ohne Angabe das erste kleine Bild.
    Gibt die Antwort der Schnittstelle zurück oder löst ValueError mit einem lesbaren Text aus."""
    if with_key is not None and (not isinstance(with_key, str) or not KEY_RE.match(with_key)):
        raise ValueError("Kamera unbekannt")
    target = with_key or pipeline.cfg.get("pip")
    if target and any(x["key"] == target and x.get("state") == "offline" for x in cams.listing("")):
        raise ValueError("Diese Kamera ist nicht verbunden und lässt sich nicht zum Hauptbild machen.")
    old_audio = PipelineStore.view_values(pipeline.cfg)[1]
    shown = pipeline.swap_main_pip(with_key)
    if send.always_live():
        note = "Getauscht, ohne Unterbrechung."
        moved = PipelineStore.view_values(pipeline.cfg)[1] != old_audio                  # eine Facecam nimmt ihren Ton mit
        if shown or moved:             # das kleine Bild der bisherigen Hauptkamera war ausgeblendet gespeichert und ist jetzt sichtbar
            hide, aud = PipelineStore.view_values(pipeline.cfg)
            cur = send.view_state()
            if not (send.view_live() and send.apply_view(hide, aud, bool(cur and cur["mute"]))):
                note += " Das kleine Bild erscheint beim nächsten Start der Sendung." if shown else " Der Ton wechselt beim nächsten Start der Sendung."
        return {"ok": True, "restarted": False, "note": note}
    restarted, note = send.restart_if_live()
    return {"ok": True, "restarted": restarted, "note": note or "Getauscht."}


def controller_action(fn, pipeline, cams, send):
    """Funktion einer Controller-Taste ausführen. Bild-Funktionen tauschen immer das Hauptbild: „Kleines Bild N“ holt die Kamera,
    die gerade dort ist, ins Hauptbild (die bisherige Hauptkamera nimmt ihren Platz ein; nochmal drücken tauscht zurück); „Hauptbild“
    holt die Kamera mit der Rolle Hauptbild der Kameraliste zurück. Ton: stumm schalten (an/aus) und zur nächsten Tonquelle."""
    cfg = pipeline.cfg
    if fn in ("pip1", "pip2", "pip3"):
        key = cfg.get({"pip1": "pip", "pip2": "pip2", "pip3": "pip3"}[fn])
        if not key or cfg.get("type") != "pip":
            return
        scene_swap(pipeline, cams, send, key)
    elif fn == "main":
        want = next((c["key"] for c in cams.cams if c.get("role") == "main"), None)
        if want and want != cfg.get("main") and cfg.get("type") == "pip":
            scene_swap(pipeline, cams, send, want)
    elif fn == "mute":
        f = send.footer()
        send.change_view(mute=not bool(f and f["audio"]["mute"]))
    elif fn == "audio_next":
        f = send.footer()
        if f:
            send.change_view(audio=f["audio"]["next"])


PHONE_FRAME = """<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>IRL4YOU BOX</title>
<script>try{if(window.top!==window||matchMedia("(max-width:620px)").matches)location.replace("/?app=1")}catch(e){location.replace("/?app=1")}</script></head>
<body style="margin:0;background:#0f172a"><iframe title="IRL4YOU BOX" src="/?app=1" style="display:block;margin:0 auto;border:0;width:480px;max-width:100%;height:100vh;height:100dvh"></iframe>
<script>try{var t=localStorage.getItem("pb_theme"),v=JSON.parse(localStorage.getItem("pb_views")||"null"),d=v&&v.mobile&&v.mobile.design;if(t==="light"||(t!=="dark"&&d==="klar"))document.body.style.background="#f1f5f9"}catch(e){}</script></body></html>"""
