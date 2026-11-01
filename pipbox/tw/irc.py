"""Chat per IRC: Zeilen lesen, Verbindung, Pfade (Sendewege) für den Chat."""

import re
import socket
import threading
import time
import ssl
import unicodedata

from tw.store import TwitchStore


class _IrcLines:
    """Zeilen aus einem Socket lesen, mit Frist."""
    MAX = 16384

    def __init__(self, sock, clock):
        self.sock, self.clock, self.buf = sock, clock, b""

    def get(self, until):
        """Nächste Zeile ohne Zeilenende; None, wenn die Frist abläuft; EOFError, wenn die Gegenseite schließt (oder keine Zeile zu sehen ist: kein IRC)."""
        while True:
            i = self.buf.find(b"\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 1:]
                return line.rstrip(b"\r").decode("utf-8", "replace")
            if len(self.buf) > self.MAX:
                raise EOFError
            left = until - self.clock()
            if left <= 0:
                return None
            self.sock.settimeout(left)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise EOFError
            self.buf += chunk


class TwitchChat:
    """Schreibt eine Nachricht in den Twitch-Chat (IRC über TLS, nur Standardbibliothek). Nur Schreiben: Befehle aus dem Chat werden nicht gelesen.

    Ablauf je Nachricht (eine eigene Verbindung): verbinden (höchstens 10 s) -> PASS und NICK -> auf die Begrüßung (001) oder eine Absage warten -> die Fähigkeit
    "twitch.tv/commands" anfordern (nur dann meldet Twitch eine Ablehnung als NOTICE) -> JOIN -> PRIVMSG -> bis zu 2 s auf NOTICE-Antworten warten -> QUIT.
    PING wird mit PONG beantwortet. Alles zusammen dauert höchstens 15 s (die Namensauflösung zählt nicht mit). Host, Port und TLS sind für Tests einstellbar.
    Die PASS-Zeile mit dem Token wird nirgends ausgegeben. Text, den Twitch schickt, wird vor dem Anzeigen gekürzt und von Steuerzeichen und dem Token befreit.
    Twitch bestätigt eine angenommene Nachricht nicht: Kommt innerhalb der Wartezeit kein NOTICE, gilt sie als gesendet."""
    HOST, PORT = "irc.chat.twitch.tv", 6697
    MAX_BYTES = 450                  # Twitch erlaubt 500 Zeichen, eine IRC-Zeile höchstens 512 Byte
    OK = "Gesendet"
    NO_CONNECT = "Keine Verbindung zu Twitch"
    NO_TLS = "Sichere Verbindung zu Twitch nicht möglich (Zertifikat oder Uhrzeit der Box prüfen)"
    LOGIN_FAILED = "Anmeldung fehlgeschlagen (Token ungültig oder ohne Recht zum Schreiben)"
    NO_ANSWER = "Keine Antwort von Twitch (Zeitüberschreitung)"
    CLOSED = "Twitch hat die Verbindung beendet"
    NOT_ALLOWED = "Der Bot darf im Kanal nicht schreiben (z. B. nur Follower)"
    LOGIN_NOTICE_RE = re.compile(r"authentication failed|login unsuccessful|improperly formatted", re.I)      # so meldet Twitch eine Absage vor der Begrüßung

    def __init__(self, host=None, port=None, tls=True, context=None, connect_timeout=10.0, total=15.0, notice_wait=2.0, clock=time.monotonic, paths=None):
        self.paths = paths or ChatPaths()
        self.host, self.port, self.tls, self.context = host or self.HOST, port or self.PORT, tls, context
        self.connect_timeout, self.total, self.notice_wait, self.clock = connect_timeout, total, notice_wait, clock

    @staticmethod
    def clean_text(text):
        """Der Text für PRIVMSG oder None: nur druckbare Zeichen (kein CR, LF, NUL), nicht mit / oder . am Anfang, höchstens MAX_BYTES Byte."""
        t = "".join(" " if unicodedata.category(ch) == "Zs" else ch for ch in text).strip()                  # geschütztes Leerzeichen und Ähnliches -> Leerzeichen
        bad = ("Cc", "Zl", "Zp", "Cs", "Co")
        if not t or any(unicodedata.category(ch) in bad or not TwitchStore.printable(ch) and unicodedata.category(ch) == "Cn" or ch in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for ch in t) or t[0] in "/.":
            return None
        raw = t.encode("utf-8")
        return t if len(raw) <= TwitchChat.MAX_BYTES else raw[:TwitchChat.MAX_BYTES].decode("utf-8", "ignore").rstrip()

    @staticmethod
    def _parse(line):
        """(Befehl, Rest) einer Zeile vom Server; Tags (@…) und Absender (:…) davor werden übersprungen."""
        if line.startswith("@"):
            line = line.partition(" ")[2]
        if line.startswith(":"):
            line = line.partition(" ")[2]
        cmd, _, rest = line.partition(" ")
        return cmd.upper(), rest

    @staticmethod
    def _notice_text(rest):
        return rest[1:] if rest.startswith(":") else rest.partition(" :")[2]

    @staticmethod
    def _scrub(text, token):
        """Text von Twitch zum Anzeigen: ohne den Token, ohne Steuerzeichen, höchstens 120 Zeichen."""
        text = text.replace(token, "…")
        text = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
        return text[:120] + ("…" if len(text) > 120 else "")

    @staticmethod
    def _pong(sock, rest):
        arg = "".join(ch for ch in rest if ch.isprintable())[:100]
        sock.sendall(b"PONG " + arg.encode("utf-8") + b"\r\n")

    def send(self, login, token, channel, text):
        """Als `login` (mit dem Token des Kontos) `text` in den Chat von `channel` schreiben. Gibt (ok, kurze Meldung auf Deutsch) zurück und wirft nichts;
        der Text einer Ausnahme wird nie übernommen (er könnte Angaben enthalten)."""
        try:
            return self._send(login, token, channel, text)
        except Exception:
            return False, "unbekannter Fehler"

    def _send(self, login, token, channel, text):
        if not all(isinstance(v, str) for v in (login, token, channel, text)):
            return False, "Ungültige Anfrage"
        login, channel, body = login.lower(), channel.lower(), self.clean_text(text)
        if body is None or not (TwitchStore.NAME_RE.fullmatch(login) and TwitchStore.NAME_RE.fullmatch(channel) and TwitchStore.TOKEN_RE.fullmatch(token)):
            return False, "Ungültige Anfrage"                       # nichts, was eine Zeile umbrechen oder einen Befehl einschleusen könnte, geht auf die Leitung
        until = self.clock() + self.total
        try:
            sock, _ = self.paths.connect(self.host, self.port, timeout=max(0.1, min(self.connect_timeout, until - self.clock())))
        except OSError:
            return False, self.NO_CONNECT
        try:
            if self.tls:
                try:
                    sock = (self.context or ssl.create_default_context()).wrap_socket(sock, server_hostname=self.host)
                except ssl.SSLError:
                    return False, self.NO_TLS
                except OSError:
                    return False, self.NO_CONNECT
            return self._talk(sock, login, token, channel, body, until)
        except (EOFError, OSError):
            return False, self.CLOSED
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _talk(self, sock, login, token, channel, body, until):
        rd = _IrcLines(sock, self.clock)
        sock.settimeout(max(0.1, until - self.clock()))
        sock.sendall(b"PASS oauth:" + token.encode("ascii") + b"\r\nNICK " + login.encode("ascii") + b"\r\n")
        while True:                                                 # auf die Begrüßung warten
            line = rd.get(until)
            if line is None:
                return False, self.NO_ANSWER
            cmd, rest = self._parse(line)
            if cmd == "001":
                break
            if cmd == "PING":
                self._pong(sock, rest)
            elif cmd in ("464", "465") or (cmd == "NOTICE" and self.LOGIN_NOTICE_RE.search(self._notice_text(rest))):
                return False, self.LOGIN_FAILED
        chan = channel.encode("ascii")
        sock.settimeout(max(0.1, until - self.clock()))
        sock.sendall(b"CAP REQ :twitch.tv/commands\r\nJOIN #" + chan + b"\r\nPRIVMSG #" + chan + b" :" + body.encode("utf-8") + b"\r\n")
        notice, end = None, min(self.clock() + self.notice_wait, until)
        try:
            while notice is None:                                   # eine Ablehnung meldet Twitch als NOTICE
                line = rd.get(end)
                if line is None:
                    break
                cmd, rest = self._parse(line)
                if cmd == "PING":
                    self._pong(sock, rest)
                elif cmd == "NOTICE":
                    notice = self._scrub(self._notice_text(rest), token)
        except EOFError:
            pass                                                    # Twitch schließt nach einer Absage manchmal gleich
        try:
            sock.sendall(b"QUIT\r\n")
        except OSError:
            pass
        if notice is None:
            return True, self.OK
        return False, self.NOT_ALLOWED + (": " + notice if notice else "")


def _ascii_digits(v):
    """True nur für nicht leere Zeichenketten aus den Ziffern 0-9 (str.isdigit() lässt auch "²" und andere Ziffernzeichen zu, int() scheitert dann)."""
    return isinstance(v, str) and all(ord(ch) < 128 for ch in v) and v.isdigit()


class ChatPaths:
    """Wege ins Internet für den Chat (Anmeldung, Lesen, Schreiben, Moderation). Die Box hat je Sendeweg eine eigene Quelladresse mit eigener Route (Quell-Routing),
    wie sie auch srtla_send benutzt: Ein Socket, der an die Adresse eines Sendewegs gebunden wird, geht genau über diesen Weg hinaus. Der Chat nimmt die gewählten
    Sendewege der Reihe nach, den besten zuerst (nach der Güte in srtla-links.txt, sonst nach der Reihenfolge der Einstellung), und weicht bei Fehler oder
    Stille auf den nächsten aus; zuletzt kommt die normale Route. Ein Weg, der versagt hat, rückt für `hold` Sekunden ans Ende. Das ist Ausweichen, kein
    Bündeln: Eine TCP-Verbindung lässt sich nicht auf mehrere Wege verteilen, und der Chat braucht nur wenige Bytes. Ohne Quelle (Tests) gilt nur die normale Route."""

    def __init__(self, sources=None, clock=time.monotonic, links_file="/run/pipbox-send/srtla-links.txt"):
        self.sources, self.clock, self.links_file = sources, clock, links_file
        self.bad = {}
        self.lock = threading.Lock()

    def _quality(self):
        """{Adresse: Güte} aus den letzten Zeilen von srtla-links.txt (kleiner ist besser; Reserve-Wege gelten als schlechter)."""
        out = {}
        try:
            with open(self.links_file, errors="replace") as f:
                lines = f.read()[-6000:].splitlines()
        except OSError:
            return out
        for ln in lines:
            m = re.search(r"links: (\d+\.\d+\.\d+\.\d+) .*?guete=(-?\d+) (genutzt|reserve)", ln)
            if m:
                g = int(m.group(2))
                out[m.group(1)] = (9999 if g < 0 else g) + (0 if m.group(3) == "genutzt" else 100000)
        return out

    def order(self):
        try:
            srcs = [x for x in (self.sources() if self.sources else []) if isinstance(x, str) and x]
        except Exception:
            srcs = []
        q = self._quality()
        now = self.clock()
        with self.lock:
            good = [x for x in srcs if self.bad.get(x, 0) <= now]
            bad = [x for x in srcs if x not in good]
        good.sort(key=lambda x: q.get(x, 50000))                                  # stabil: gleiche Güte behält die Reihenfolge der Einstellung
        return good + [None] + bad

    def fail(self, src, hold=300.0):
        if src:
            with self.lock:
                self.bad[src] = self.clock() + hold

    def connect(self, host, port, timeout=6.0):
        """(Socket, Quelladresse) über den ersten Weg, der klappt; OSError, wenn keiner geht."""
        last = OSError()
        for src in self.order():
            try:
                return socket.create_connection((host, port), timeout=timeout, source_address=(src, 0) if src else None), src
            except socket.gaierror as e:                       # Namensauflösung: hängt nicht am Weg, also keinen Weg sperren und nicht jeden einzeln versuchen
                raise e
            except OSError as e:
                last = e
                self.fail(src, 120.0)
        raise last

    def request(self, method, url, data=None, headers=None, timeout=15.0, limit=200_000, once=False, prefer=False):
        """(Status, Antworttext als Bytes) einer HTTP(S)-Anfrage über den ersten Weg, der antwortet; (0, b"") ohne Verbindung.
        once=True für Anfragen, die sich nicht wiederholen lassen (Erneuern des Zugangs mit einmaligem Schlüssel): Nur ein Fehler beim Verbinden führt zum
        nächsten Weg; ist die Anfrage erst gesendet und die Antwort geht verloren, wird nicht ein zweites Mal gesendet (Ergebnis dann (-1, b"")).
        prefer: ein Weg (auch None = normale Route), der zuerst versucht wird, zum Beispiel der, über den gerade eine Verbindung steht."""
        import http.client
        import urllib.parse
        u = urllib.parse.urlsplit(url)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        target = u.path + ("?" + u.query if u.query else "")
        order = self.order()
        if prefer is not False and prefer in order:
            order.remove(prefer)
            order.insert(0, prefer)
        for src in order:
            conn = None
            try:
                conn = cls(u.hostname, u.port, timeout=timeout, source_address=(src, 0) if src else None)
                try:
                    conn.connect()
                except socket.gaierror:
                    return 0, b""                                  # Namensauflösung hängt nicht am Weg: keinen Weg sperren, nicht alle durchprobieren
                except (OSError, http.client.HTTPException, ValueError):
                    self.fail(src, 120.0)
                    continue
                try:
                    conn.request(method, target, body=data, headers=headers or {})
                    r = conn.getresponse()
                    status = r.status
                    try:
                        return status, r.read(limit)
                    except (OSError, http.client.HTTPException, ValueError):
                        self.fail(src, 120.0)
                        if once:
                            return status, b""                         # Antwortzeile da, Rumpf verloren: der Status gilt
                        raise
                except (OSError, http.client.HTTPException, ValueError):
                    self.fail(src, 120.0)
                    if once:
                        return -1, b""                                 # gesendet, aber keine Antwort: nicht noch einmal senden
            except (OSError, http.client.HTTPException, ValueError):
                self.fail(src, 120.0)
            finally:
                try:
                    if conn:
                        conn.close()
                except OSError:
                    pass
        return 0, b""
