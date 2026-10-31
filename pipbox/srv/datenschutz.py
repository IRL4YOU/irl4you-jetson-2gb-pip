"""Platzhalter: In der Jetson-Version gibt es kein Verpixeln. Die Namen bleiben, damit die übrigen Bausteine unverändert laufen; alles ist ausgeschaltet."""

DATENSCHUTZ_DATEI = ""
DATENSCHUTZ_PY = ""
DATENSCHUTZ_MODELL = ""
DATENSCHUTZ_BAUSTEIN = ""
PRIVACY_URL = ""
PBPIXEL_TAP, PBPIXEL_BOXES = "", ""
SENDE_PIPELINE = ""

NICHT_ENTHALTEN = "Verpixeln ist in dieser Version nicht enthalten"


def kette_signatur(text):
    return text or ""


def neustart_noetig(build_text, pfad=None):
    return False


def pixel_stand(store):
    return {"an": False, "kopf": False, "kennz": False}


def pixel_umschalten(store, send, pipeline, an, kopf, kennz):
    return False, NICHT_ENTHALTEN


def privacy_status():
    return {"up": False}


def datenschutz_aktiv(pfad=None):
    return None


class DatenschutzStore:
    def __init__(self, state_dir=None):
        pass

    def config(self):
        return {"an": False, "kopf": False, "kennz": False}

    def get(self):
        return {"an": False, "kopf": False, "kennz": False, "nicht_enthalten": True}

    def put(self, d):
        raise ValueError(NICHT_ENTHALTEN)

    def addon_request(self, action, sending=False):
        raise ValueError(NICHT_ENTHALTEN)

    def lizenz_text(self):
        return ""
