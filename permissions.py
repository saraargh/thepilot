# permissions.py
import json
import os

SETTINGS_FILE = "pilot_settings.json"

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"allowed_roles": []}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def user_is_allowed(member):
    settings = load_settings()
    allowed_roles = settings.get("allowed_roles", [])
    return any(role.id in allowed_roles for role in member.roles)