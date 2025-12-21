import os
import json
import base64
import requests
import discord
from discord import app_commands
from datetime import datetime, timedelta
import pytz

from permissions import has_app_access

# ======================
# CONFIG
# ======================
UK_TZ = pytz.timezone("Europe/London")

GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

GITHUB_FILE_PATH = "pilot_runtime_logs.json"

ERROR_COOLDOWN = timedelta(minutes=5)
_last_error_time: datetime | None = None


# ======================
# GITHUB HELPERS
# ======================
def _github_url():
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"


def _default_settings():
    return {
        "enabled": False,
        "channel_id": None
    }


def load_settings():
    try:
        res = requests.get(_github_url(), headers=HEADERS)
        if res.status_code == 404:
            return _default_settings(), None

        res.raise_for_status()
        data = res.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content), data["sha"]

    except Exception:
        return _default_settings(), None


def save_settings(settings: dict, sha: str | None):
    encoded = base64.b64encode(
        json.dumps(settings, indent=2).encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": "Update Pilot runtime log settings",
        "content": encoded,
    }

    if sha:
        payload["sha"] = sha

    res = requests.put(_github_url(), headers=HEADERS, json=payload)
    res.raise_for_status()


# ======================
# DEPLOY INFO
# ======================
def get_commit_hash():
    commit = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT")
    return commit[:7] if commit else "unknown"


def get_trigger_type(commit_hash: str):
    if commit_hash != "unknown":
        return "Auto deploy (GitHub commit)"
    return "Manual restart / crash recovery"


async def _get_channel(client: discord.Client, channel_id: int | None):
    if not channel_id:
        return None

    channel = client.get_channel(channel_id)
    if channel:
        return channel

    try:
        return await client.fetch_channel(channel_id)
    except Exception:
        return None


# ======================
# RUNTIME LOGGING
# ======================
async def log_startup(client: discord.Client):
    settings, _ = load_settings()
    if not settings.get("enabled"):
        return

    channel = await _get_channel(client, settings.get("channel_id"))
    if not channel:
        return

    commit = get_commit_hash()
    trigger = get_trigger_type(commit)
    now = datetime.now(UK_TZ).strftime("%d %b %Y · %H:%M:%S")

    await channel.send(
        "🚀 **The Pilot started**\n"
        f"🧾 Commit: `{commit}`\n"
        f"🔁 Trigger: {trigger}\n"
        f"🕒 {now} (UK time)"
    )


async def log_error(client: discord.Client, event_method: str):
    global _last_error_time

    settings, _ = load_settings()
    if not settings.get("enabled"):
        return

    channel = await _get_channel(client, settings.get("channel_id"))
    if not channel:
        return

    now = datetime.now(UK_TZ)

    if _last_error_time and now - _last_error_time < ERROR_COOLDOWN:
        return

    _last_error_time = now

    await channel.send(
        "💥 **The Pilot encountered an error**\n"
        f"📍 Event: `{event_method}`\n"
        f"🕒 {now.strftime('%d %b %Y · %H:%M:%S')} (UK time)\n"
        "📄 Check Render logs for full traceback."
    )


# ======================
# SLASH COMMANDS
# ======================
class PilotLogs(app_commands.Group):
    def __init__(self):
        super().__init__(
            name="pilotlogs",
            description="Control Pilot runtime logging"
        )

    @app_commands.command(name="enable", description="Enable Pilot runtime logs")
    async def enable(self, interaction: discord.Interaction):
        if not has_app_access(interaction):
            await interaction.response.send_message(
                "❌ You don’t have access to this command.",
                ephemeral=True
            )
            return

        settings, sha = load_settings()
        settings["enabled"] = True
        save_settings(settings, sha)

        await interaction.response.send_message(
            "✅ Pilot runtime logging **enabled**.",
            ephemeral=True
        )

    @app_commands.command(name="disable", description="Disable Pilot runtime logs")
    async def disable(self, interaction: discord.Interaction):
        if not has_app_access(interaction):
            await interaction.response.send_message(
                "❌ You don’t have access to this command.",
                ephemeral=True
            )
            return

        settings, sha = load_settings()
        settings["enabled"] = False
        save_settings(settings, sha)

        await interaction.response.send_message(
            "🛑 Pilot runtime logging **disabled**.",
            ephemeral=True
        )

    @app_commands.command(name="channel", description="Set the Pilot log channel")
    @app_commands.describe(channel="Channel to send Pilot runtime logs to")
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not has_app_access(interaction):
            await interaction.response.send_message(
                "❌ You don’t have access to this command.",
                ephemeral=True
            )
            return

        settings, sha = load_settings()
        settings["channel_id"] = channel.id
        save_settings(settings, sha)

        await interaction.response.send_message(
            f"📡 Pilot runtime log channel set to {channel.mention}",
            ephemeral=True
        )


# ======================
# SETUP
# ======================
def setup(tree: app_commands.CommandTree):
    tree.add_command(PilotLogs())