"""Installierte Versionen der Systempakete und Versionsnummern vergleichen."""

import os
import re

from srv.util import _TTL, read


KEY_PACKAGES = ("belabox-linux-rk3588", "belaui", "belacoder", "belabox-rk3588")


def belacoder_running():
    try:
        for d in os.listdir("/proc"):
            if d.isdigit() and (read(f"/proc/{d}/comm", "") or "").strip() == "belacoder":
                return True
    except OSError:
        pass
    return False


def installed_versions():
    """Versionen wichtiger Pakete aus /var/lib/dpkg/status (nur lesend)."""
    try:
        st = os.stat("/var/lib/dpkg/status")
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    hit = _TTL.get("dpkg")
    if hit is not None and hit[0] == sig and sig is not None:
        return dict(hit[1])
    res = {}
    for block in (read("/var/lib/dpkg/status", "") or "").split("\n\n"):
        f = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(" "))
        if f.get("Package") in KEY_PACKAGES and "installed" in f.get("Status", "") and "not-installed" not in f.get("Status", ""):
            res[f["Package"]] = f.get("Version", "?")
    _TTL["dpkg"] = (sig, dict(res))
    return res


VERSION_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}(-[a-z0-9.]{1,16})?$")


def vkey(v):
    """Sortierschlüssel einer Versionsnummer (Release vor Vorabversion)."""
    core, _, pre = v.partition("-")
    return tuple(int(x) for x in core.split(".")), (1, ()) if not pre else (0, tuple(pre.split(".")))
