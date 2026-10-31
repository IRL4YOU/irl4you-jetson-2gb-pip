"""Gemeinsame Hilfen des Chats: Datei lesen, Schlüsselprüfung, Prüfung ob belacoder läuft."""

import os
import re


KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")                 # Stream-Schlüssel einer Kamera (wie in server.py)


def read(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def belacoder_running():
    try:
        for d in os.listdir("/proc"):
            if d.isdigit() and (read(f"/proc/{d}/comm", "") or "").strip() == "belacoder":
                return True
    except OSError:
        pass
    return False
