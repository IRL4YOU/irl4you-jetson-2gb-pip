"""Ersatz für Funktionen, die es in Python 3.6 (Jetson, Ubuntu 18.04) noch nicht gibt."""
import datetime
import gzip
import io
import re
import socketserver
from http.server import HTTPServer


def gzip_compress(data, level=9, mtime=0):
    """gzip.compress mit mtime (erst ab Python 3.8): gleiche Ausgabe bei gleichem Inhalt."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=level, mtime=mtime) as f:
        f.write(data)
    return buf.getvalue()

try:
    from http.server import ThreadingHTTPServer
except ImportError:                                     # Python 3.6
    class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        daemon_threads = True

_ISO = re.compile(r"^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:[.,](\d+))?(?:([+-]\d\d):?(\d\d)|Z)?$")      # Bruchteil mit Punkt oder Komma, Zeitzone mit oder ohne Doppelpunkt


def fromiso(s):
    """datetime.fromisoformat (erst ab Python 3.7) für die Formen der Kernelmeldungen, zum Beispiel 2026-10-31T11:14:52.123456+01:00."""
    m = _ISO.match(s.strip())
    if not m:
        raise ValueError("kein ISO-Zeitstempel: %r" % s)
    day, clock, frac, tzh, tzm = m.groups()
    us = int(((frac or "0") + "000000")[:6])
    t = datetime.datetime.strptime("%s %s" % (day, clock), "%Y-%m-%d %H:%M:%S").replace(microsecond=us)
    if tzh is not None:
        sign = -1 if tzh.startswith("-") else 1
        t = t.replace(tzinfo=datetime.timezone(sign * datetime.timedelta(hours=abs(int(tzh)), minutes=int(tzm))))
    return t
