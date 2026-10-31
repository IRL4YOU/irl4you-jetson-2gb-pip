"""Gemeinsame Hilfen: Datei lesen, Ergebnisse kurz zwischenspeichern, Ordner der Weboberfläche."""

import json
import os
import time


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # Ordner mit server.py (srv/ liegt darin)
WEB_DIR = os.path.join(BASE_DIR, "web")


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


_TTL = {}


def ttl_cached(key, ttl, fn):
    """Ergebnis von fn() für ttl Sekunden merken. Spart Programmstarts und Dateilesen bei den vielen Abfragen der Oberfläche."""
    now = time.monotonic()
    hit = _TTL.get(key)
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _TTL[key] = (now, val)
    return val


def ttl_cached_drop(key):
    _TTL.pop(key, None)


NOT_HANDLED = object()       # eine Gruppe der Anfragen hat die Anfrage nicht beantwortet: die nächste ist dran


_JSON = {}
JSON_MAX_AGE = 5.0        # Sekunden: spätestens dann wird die Datei auf jeden Fall neu gelesen


def json_file(path):
    """Inhalt einer JSON-Datei oder None (fehlt oder kaputt). Wird nur neu gelesen, wenn sich Änderungsdatum, Größe oder Datei (Inode) ändern, spätestens alle
    JSON_MAX_AGE Sekunden: spart Öffnen und Auswerten bei den vielen Abfragen der Oberfläche. Der Aufrufer darf das Ergebnis nicht verändern."""
    try:
        st = os.stat(path)
    except OSError:
        _JSON.pop(path, None)
        return None
    sig = (st.st_mtime_ns, st.st_size, st.st_ino)
    now = time.monotonic()
    hit = _JSON.get(path)
    if hit is not None and hit[0] == sig and now - hit[1] < JSON_MAX_AGE:
        return hit[2]
    try:
        with open(path) as f:
            val = json.load(f)
    except (OSError, ValueError):
        val = None
    _JSON[path] = (sig, now, val)
    return val

