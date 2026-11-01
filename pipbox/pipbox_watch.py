"""Wächter für die Sendekette: erkennt drei Hänger von belacoder, schreibt vor dem Neustart ein Diagnosepaket und startet belacoder neu.

  "dstate"  Threads von belacoder hängen im Kernel (Zustand D, "2 Prozesse blockiert (D-State)" in der Oberfläche), vermutlich im Treiber der Video-Hardware.
  "stats"   Die Kennzahlen-Datei von belacoder (einmal je Sekunde) steht still: die Hauptschleife des Prozesses hängt.
  "output"  Der Encoder liefert seit OUT_DEAD_S keine Bilder mehr (Feld fps der Kennzahlen unter 1), der Prozess lebt aber: die Ausgabe steht.
Bis die Ursache solcher Hänger gefunden ist, hilft nur ein Neustart von belacoder. Der Wächter macht ihn selbst und sichert vorher, was zur Ursache führt: alle Threads
von belacoder mit Zustand, Wartestelle im Kernel (wchan) und CPU-Zeit, die Kennzahlen, die letzten Ereignisse und den Zustand der Weichen. Das Paket enthält keine Schlüssel
und keine Adressen (nur Plätze), liegt in /var/lib/pipbox/hang-diagnose.txt und steht in den Protokollen der Oberfläche."""
import collections
import os
import re
import time

STALE_S = 15.0           # so lange darf die Kennzahlen-Datei von belacoder alt sein
START_GRACE_S = 30.0     # nach dem Start von belacoder: so lange wird nichts bewertet (die Kette läuft erst an)
DSTATE_S = 12.0          # so lange darf ein Thread von belacoder im Zustand D (Kernel, nicht unterbrechbar) bleiben
OUT_DEAD_S = 12.0        # so lange darf der Encoder ohne Bilder bleiben (die Ausgabe steht dann; der Empfänger wirft eine Sendung ohne Daten nach 14 s hinaus)
COOLDOWN_S = 90.0        # nach einem Eingriff mindestens so lange Ruhe
MAX_PER_HOUR = 4         # mehr Eingriffe je Stunde macht der Wächter nicht (ein Dauerfehler wäre sonst eine Neustartschleife)
REPORT_KEEP = 6          # so viele Pakete bleiben
REPORT_MARK = "===== HÄNGER "
REPORT_FILE = "hang-diagnose.txt"


class HangWatch:
    """Die Entscheidung, ohne Prozesse und Dateien (testbar mit gestellten Uhren)."""

    def __init__(self, clock=time.monotonic, wall=time.time):
        self.clock, self.wall = clock, wall
        self.started = None
        self.dstate_since = None
        self.silent_since = None
        self.acted = collections.deque()          # Zeiten (monotonic) der Eingriffe

    def started_now(self):
        """belacoder wurde (neu) gestartet."""
        self.started = self.clock()
        self.dstate_since = None
        self.silent_since = None

    def check(self, stats_mtime, fps, d_threads=0):
        """None oder {"kind": "dstate"|"stats"|"output", "slot": None, "text": …}. stats_mtime: Änderungszeit der Kennzahlen-Datei (Wanduhr) oder None; fps: Bilder
        je Sekunde, die der Encoder laut Kennzahlen liefert, oder None; d_threads: Zahl der Threads von belacoder im Zustand D."""
        now = self.clock()
        if self.started is None or now - self.started < START_GRACE_S:
            return None
        if d_threads > 0:
            self.dstate_since = self.dstate_since if self.dstate_since is not None else now
            if now - self.dstate_since >= DSTATE_S:
                return {"kind": "dstate", "slot": None, "text": "%d Thread(s) von belacoder hängen seit %d s im Kernel (Zustand D)" % (d_threads, int(now - self.dstate_since))}
        else:
            self.dstate_since = None
        if stats_mtime is None or self.wall() - stats_mtime > STALE_S:
            age = "fehlt" if stats_mtime is None else "%d s alt" % int(self.wall() - stats_mtime)
            return {"kind": "stats", "slot": None, "text": "Statistik von belacoder steht still (%s)" % age}
        if fps is not None and fps < 1.0:
            self.silent_since = self.silent_since if self.silent_since is not None else now
            if now - self.silent_since >= OUT_DEAD_S:
                return {"kind": "output", "slot": None, "text": "Der Encoder liefert seit %d s keine Bilder, die Ausgabe steht" % int(now - self.silent_since)}
        else:
            self.silent_since = None
        return None

    def allow(self):
        """Darf jetzt eingegriffen werden (Ruhezeit, höchstens MAX_PER_HOUR je Stunde)?"""
        now = self.clock()
        while self.acted and now - self.acted[0] > 3600:
            self.acted.popleft()
        if self.acted and now - self.acted[-1] < COOLDOWN_S:
            return False
        return len(self.acted) < MAX_PER_HOUR

    def acted_now(self):
        self.acted.append(self.clock())
        self.dstate_since = None
        self.silent_since = None


# ----------------------------------------------------------------------------------------------------------------------- Diagnosepaket

def _read(path, limit=400):
    try:
        with open(path, errors="replace") as f:
            return f.read(limit).strip()
    except OSError:
        return ""


def _thread_sample(pid, proc):
    out = {}
    base = f"{proc}/{pid}/task"
    try:
        tids = sorted(os.listdir(base), key=int)
    except (OSError, ValueError):
        return out
    for tid in tids:
        stat = _read(f"{base}/{tid}/stat", 1000)
        m = re.match(r"^\d+ \((.*)\) (\S) (.*)$", stat)
        if not m:
            continue
        f = m.group(3).split()
        try:
            cpu = int(f[11]) + int(f[12])             # utime + stime (Felder 14 und 15 der Datei)
        except (IndexError, ValueError):
            cpu = 0
        out[tid] = {"name": m.group(1), "state": m.group(2), "cpu": cpu, "wchan": _read(f"{base}/{tid}/wchan", 80) or "-"}
    return out


def d_state_threads(pid, proc="/proc"):
    """Zahl der Threads dieses Prozesses im Zustand D (wartet im Kernel, nicht unterbrechbar)."""
    return sum(1 for t in _thread_sample(pid, proc).values() if t["state"] == "D")


def blocked_tasks(proc="/proc", limit=12):
    """Alle Threads im Zustand D im ganzen System (Prozessname, Wartestelle, oberste Zeilen des Kernel-Stapels, falls lesbar) und der Zähler der Oberfläche
    (procs_blocked aus /proc/stat). Der Kernel-Stapel nennt die Funktion, in der der Thread hängt (zum Beispiel im Treiber des Hardware-Dekoders)."""
    rows = []
    try:
        pids = [d for d in os.listdir(proc) if d.isdigit()]
    except OSError:
        pids = []
    for pid in pids:
        base = f"{proc}/{pid}/task"
        try:
            tids = os.listdir(base)
        except OSError:
            continue
        for tid in tids:
            stat = _read(f"{base}/{tid}/stat", 1000)
            m = re.match(r"^\d+ \((.*)\) (\S) ", stat)
            if not m or m.group(2) != "D":
                continue
            stack = [re.sub(r"^\[<[0-9a-f]+>\]\s*", "", x.strip()) for x in _read(f"{base}/{tid}/stack", 2000).splitlines()[:6]]
            rows.append("  %s (%s): %s%s" % (m.group(1), tid, _read(f"{base}/{tid}/wchan", 80) or "-",
                                          ("  Stapel: " + " < ".join(x for x in stack if x)) if any(stack) else ""))
            if len(rows) >= limit:
                break
    blocked = re.search(r"^procs_blocked (\d+)", _read(f"{proc}/stat", 4000) + "\n", re.M)
    head = "procs_blocked laut /proc/stat: %s" % (blocked.group(1) if blocked else "?")
    return head + ("\n" + "\n".join(rows) if rows else "\n  (kein Thread im Zustand D)")


def thread_table(pid, proc="/proc", sleep=time.sleep, interval=1.0):
    """Alle Threads des Prozesses: Name, Zustand (R läuft, S wartet, D wartet im Kernel), Wartestelle im Kernel, CPU-Ticks im Messzeitraum.
    Namen kommen von GStreamer (<Element>:src), sie nennen die Zweige (udpsrc, nvv4l2decoder, nvcompositor …) und enthalten keine Schlüssel."""
    a = _thread_sample(pid, proc)
    sleep(interval)
    b = _thread_sample(pid, proc)
    rows = ["TID      Zustand  CPU-Ticks  Wartestelle                      Name"]
    for tid, t in sorted(b.items(), key=lambda kv: (kv[1]["name"], int(kv[0]))):
        d = t["cpu"] - a.get(tid, {}).get("cpu", t["cpu"])
        rows.append("%-8s %-8s %-10d %-32s %s" % (tid, t["state"], d, t["wchan"][:32], t["name"]))
    return "\n".join(rows)


def build_report(hit, pid, uptime_s, live_text, events, slots, proc="/proc", sleep=time.sleep, wall=time.time):
    """Das Paket als Text. slots: [(Platz, Zustand der Weiche)]. Nur Zahlen und Namen von Elementen, nie Schlüssel oder Adressen."""
    parts = [
        "%s%s UTC · %s" % (REPORT_MARK, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(wall())), hit["text"]),
        "Art: %s | belacoder läuft seit %d s" % (hit["kind"], int(uptime_s)),
        "",
        "Status von belacoder (%s):" % proc.rstrip("/"),
    ]
    for line in _read(f"{proc}/{pid}/status", 4000).splitlines():
        if re.match(r"^(Name|State|Threads|voluntary_ctxt_switches|nonvoluntary_ctxt_switches|VmRSS):", line):
            parts.append("  " + line)
    parts += ["", "Threads (Messung über 1 s):", thread_table(pid, proc, sleep), "", "Threads im Zustand D (ganzes System):", blocked_tasks(proc), "", "Plätze (Zustand der Weichen):"]
    for slot, state in slots:
        parts.append("  Platz %s: %s" % (slot, state))
    parts += ["", "Statistik von belacoder (erste Zeilen):", live_text.strip()[:6000], "", "Letzte Ereignisse:"]
    parts += ["  " + e for e in events[-25:]]
    return "\n".join(parts) + "\n"


def write_report(directory, text, keep=REPORT_KEEP, name=REPORT_FILE, limit=60000):
    """Hängt das Paket an die Datei an und behält die letzten `keep` Pakete (und höchstens `limit` Zeichen je Datei). True bei Erfolg."""
    path = os.path.join(directory, name)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            old = f.read()
    except OSError:
        old = ""
    blocks = [REPORT_MARK + b for b in old.split(REPORT_MARK) if b.strip()]
    blocks.append(text)
    blocks = blocks[-keep:]
    data = "".join(b if b.endswith("\n") else b + "\n" for b in blocks)
    if len(data) > limit:
        data = data[-limit:]
    try:
        os.makedirs(directory, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        return True
    except OSError:
        return False
