from __future__ import annotations

import os
import json
import base64
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List

import requests
import discord
from discord import app_commands

# =========================
# GitHub storage (mute_settings.json)
# =========================
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_FILE_PATH = os.getenv("MUTE_SETTINGS_FILE_PATH", "mute_settings.json")

HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

def _gh_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

_SETTINGS_CACHE: Dict[str, Any] = {"data": None, "sha": None}

DEFAULT_SETTINGS = {
    "allowed_role_ids": [],      # roles that CAN use /mute & /unmute
    "restricted_role_ids": [],   # roles that CANNOT mute at all (even if admin roles etc.)
}

def _gh_get_file() -> tuple[dict, Optional[str]]:
    r = requests.get(_gh_url(), headers=HEADERS, timeout=20)
    if r.status_code == 404:
        return DEFAULT_SETTINGS.copy(), None
    r.raise_for_status()
    payload = r.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")
    data = json.loads(content) if content.strip() else {}
    merged = DEFAULT_SETTINGS.copy()
    merged.update(data or {})
    return merged, payload.get("sha")

def _gh_put_file(data: dict, sha: Optional[str]) -> tuple[dict, str]:
    body = {
        "message": "Update mute settings",
        "content": base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("utf-8"),
    }
    if sha:
        body["sha"] = sha

    r = requests.put(_gh_url(), headers=HEADERS, json=body, timeout=20)
    r.raise_for_status()
    payload = r.json()
    new_sha = payload.get("content", {}).get("sha") or payload.get("sha")
    return data, new_sha


def load_mute_settings(force: bool = False) -> dict:
    if not force and _SETTINGS_CACHE["data"] is not None:
        return _SETTINGS_CACHE["data"]

    data, sha = _gh_get_file()
    _SETTINGS_CACHE["data"] = data
    _SETTINGS_CACHE["sha"] = sha
    return data


def save_mute_settings(new_data: dict) -> dict:
    # Always re-fetch to avoid SHA conflicts
    current, sha = _gh_get_file()
    merged = DEFAULT_SETTINGS.copy()
    merged.update(current or {})
    merged.update(new_data or {})

    saved, new_sha = _gh_put_file(merged, sha)
    _SETTINGS_CACHE["data"] = saved
    _SETTINGS_CACHE["sha"] = new_sha
    return saved


# =========================
# Cosmetic mute runtime store
# =========================
# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int} }
muted_users: dict[int, dict] = {}

_LISTENER_INSTALLED = False


# =========================
# Permission checks
# =========================
def _has_any_role(member: discord.Member, role_ids: List[int]) -> bool:
    s = set(role_ids)
    return any(r.id in s for r in member.roles)

def can_manage_mute(interaction: discord.Interaction, settings: dict) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False

    restricted = settings.get("restricted_role_ids", [])
    allowed = settings.get("allowed_role_ids", [])

    # hard block
    if restricted and _has_any_role(interaction.user, restricted):
        return False

    # if allowed roles configured, require one
    if allowed:
        return _has_any_role(interaction.user, allowed)

    # fallback (if you haven’t configured anything yet):
    # allow server admins to open settings + use mute
    return interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild


# =========================
# Listener installation (reliable even if other modules override on_message)
# =========================
def install_mute_listener(client: discord.Client):
    global _LISTENER_INSTALLED
    if _LISTENER_INSTALLED:
        return
    _LISTENER_INSTALLED = True

    async def _cosmetic_mute_on_message(message: discord.Message):
        if message.author.bot:
            return

        info = muted_users.get(message.author.id)
        if not info:
            return

        # only in same guild we muted in
        if message.guild is None or info.get("guild_id") != message.guild.id:
            return

        until = info.get("until")
        if not until:
            muted_users.pop(message.author.id, None)
            return

        # expired -> clear (scheduled loop announces)
        if datetime.utcnow() >= until:
            muted_users.pop(message.author.id, None)
            return

        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            return

    # stacked events list
    if not hasattr(client, "extra_events") or client.extra_events is None:
        client.extra_events = {}
    client.extra_events.setdefault("on_message", []).append(_cosmetic_mute_on_message)


# =========================
# /mutesettings UI
# =========================
class MuteSettingsView(discord.ui.View):
    def __init__(self, settings: dict):
        super().__init__(timeout=300)
        self.settings = settings
        self.allowed_ids = list(settings.get("allowed_role_ids", []))
        self.restricted_ids = list(settings.get("restricted_role_ids", []))

        self.allowed_select.default_values = []
        self.restricted_select.default_values = []

    def _embed(self, guild: discord.Guild) -> discord.Embed:
        def fmt(ids: list[int]) -> str:
            if not ids:
                return "Not set"
            return "\n".join(f"<@&{rid}>" for rid in ids)

        em = discord.Embed(title="🔧 Mute Settings", description="Configure who can use /mute and /unmute.")
        em.add_field(name="Allowed roles", value=fmt(self.allowed_ids), inline=False)
        em.add_field(name="Restricted roles (cannot mute at all)", value=fmt(self.restricted_ids), inline=False)
        em.set_footer(text="Save to apply. Settings persist via GitHub JSON.")
        return em

    @discord.ui.role_select(
        placeholder="Select ALLOWED roles (can use /mute)",
        min_values=0,
        max_values=25
    )
    async def allowed_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.allowed_ids = [r.id for r in select.values]
        await interaction.response.edit_message(embed=self._embed(interaction.guild), view=self)

    @discord.ui.role_select(
        placeholder="Select RESTRICTED roles (cannot mute at all)",
        min_values=0,
        max_values=25
    )
    async def restricted_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.restricted_ids = [r.id for r in select.values]
        await interaction.response.edit_message(embed=self._embed(interaction.guild), view=self)

    @discord.ui.button(label="Save", style=discord.ButtonStyle.green)
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_settings = {
            "allowed_role_ids": self.allowed_ids,
            "restricted_role_ids": self.restricted_ids,
        }
        saved = save_mute_settings(new_settings)
        await interaction.response.edit_message(
            content="✅ Saved mute settings.",
            embed=self._embed(interaction.guild),
            view=self
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.gray)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="✅ Closed.", embed=None, view=None)


# =========================
# Commands + expiry announcer
# =========================
def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):
    # install listener once
    install_mute_listener(client)

    # de-dupe commands (stops the “posted twice” issue)
    for cmd_name in ("mute", "unmute", "mutesettings"):
        try:
            tree.remove_command(cmd_name)
        except Exception:
            pass

    @tree.command(name="mutesettings", description="Configure mute permissions (allowed/restricted roles)")
    async def mutesettings(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Server only.")

        settings = load_mute_settings(force=True)

        # allow only admins/manage_guild OR already-allowed roles (if configured)
        if not (isinstance(interaction.user, discord.Member) and (
            interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild
            or _has_any_role(interaction.user, settings.get("allowed_role_ids", []))
        )):
            return await interaction.response.send_message("❌ You can’t access mute settings.")

        view = MuteSettingsView(settings)
        await interaction.response.send_message(embed=view._embed(interaction.guild), view=view)

    @tree.command(name="mute", description="Mute (deletes a member’s messages)")
    @app_commands.describe(member="Member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
        try:
            await interaction.response.defer(thinking=False)
        except Exception:
            pass

        if not interaction.guild or not interaction.channel:
            return await interaction.followup.send("❌ Use this in a server channel.")

        settings = load_mute_settings()

        if not can_manage_mute(interaction, settings):
            return await interaction.followup.send("❌ You don’t have permission to use /mute.")

        if minutes <= 0:
            return await interaction.followup.send("❌ Minutes must be greater than 0.")

        muted_users[member.id] = {
            "until": datetime.utcnow() + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id,
        }

        return await interaction.followup.send(
            f"🔇 {member.mention} has been **muted** for **{minutes}** minute(s)."
        )

    @tree.command(name="unmute", description="Remove a mute")
    @app_commands.describe(member="Member to unmute")
    async def unmute(interaction: discord.Interaction, member: discord.Member):
        try:
            await interaction.response.defer(thinking=False)
        except Exception:
            pass

        settings = load_mute_settings()

        if not can_manage_mute(interaction, settings):
            return await interaction.followup.send("❌ You don’t have permission to use /unmute.")

        if member.id not in muted_users:
            return await interaction.followup.send(f"❌ {member.mention} is not muted.")

        muted_users.pop(member.id, None)
        return await interaction.followup.send(f"🔊 {member.mention} has been unmuted.")


async def process_expired_mutes(client: discord.Client):
    """Call from your scheduled loop. Announces auto-unmute even if they don't speak again."""
    now = datetime.utcnow()
    expired_ids = [uid for uid, info in muted_users.items() if info.get("until") and now >= info["until"]]

    for uid in expired_ids:
        info = muted_users.pop(uid, None)
        if not info:
            continue
        try:
            ch = client.get_channel(info.get("channel_id"))
            if ch:
                await ch.send(f"🔊 <@{uid}> has been automatically unmuted.")
        except Exception:
            pass