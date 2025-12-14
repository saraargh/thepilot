# permissions.py
import json
import os
import discord

SETTINGS_FILE = "pilot_settings.json"

# Permanent override role (cannot be locked out)
OVERRIDE_ROLE_ID = 1404104881098195015


# =========================
# Load / Save
# =========================

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {
            "global_allowed_roles": [],
            "apps": {}
        }

    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)


def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# =========================
# Core Checks
# =========================

def is_server_owner(member: discord.Member):
    return member.guild and member.guild.owner_id == member.id


def has_override_access(member: discord.Member):
    return any(role.id == OVERRIDE_ROLE_ID for role in member.roles)


def has_global_access(member: discord.Member):
    # Absolute failsafes
    if is_server_owner(member) or has_override_access(member):
        return True

    settings = load_settings()
    allowed = settings.get("global_allowed_roles", [])

    return any(role.id in allowed for role in member.roles)


def has_app_access(member: discord.Member, app_name: str):
    # Absolute failsafes
    if is_server_owner(member) or has_override_access(member):
        return True

    # Global admins can access everything
    if has_global_access(member):
        return True

    settings = load_settings()
    app = settings.get("apps", {}).get(app_name, {})
    allowed = app.get("allowed_roles", [])

    return any(role.id in allowed for role in member.roles)