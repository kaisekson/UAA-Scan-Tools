import json, os

SETTINGS_FILE = "settings.json"

DEFAULT = {
    "devices": {
        "power_supply_1": {"name": "E36103B", "ip": "", "port": 5025, "enabled": True},
        "power_supply_2": {"name": "E36441A", "ip": "", "port": 5025, "enabled": True},
        "smu":            {"name": "2602B",   "ip": "", "port": 5025, "enabled": True},
        "dispense":       {"name": "Musashi ML-6000X", "ip": "", "port": 23, "enabled": True},
        "uv_cure":        {"name": "DYMAX QX4", "ip": "", "port": 10001, "enabled": True},
        "hexapod":        {"name": "C-887",   "ip": "", "port": 50000, "enabled": True},
    }
}

def load():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT.copy()

def save(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[Settings] Saved → {SETTINGS_FILE}")
