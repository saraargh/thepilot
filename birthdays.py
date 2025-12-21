from __future__ import annotations

import os
import json
import base64
import asyncio
import random
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import tasks
from zoneinfo import ZoneInfo, available_timezones

from permissions import has_app_access

# ======================================================
# Config
# ======================================================
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "birthdays.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
GITHUB_API_BASE = "https://api.github.com"

UK_TZ = ZoneInfo("Europe/London")
_lock = asyncio.Lock()

# ======================================================
# Default JSON
# ======================================================
DEFAULT_DATA: Dict[str, Any] = {
    "settings": {
        "enabled": True,
        "announce": True,
        "channel_id": None,
        "birthday_role_id": None,
        "message_single": "🎂 Happy Birthday {user}! 🎉",
        "message_multiple": "🎉 Happy Birthday {users}! 🎂",
        "images": []
    },
    "birthdays": {},
    "state": {
        "announced_keys": [],
        "role_assigned_keys": []
    }
}

# ======================================================
# GitHub helpers
# ======================================================
async def _gh_get_file() -> Tuple[Optional[dict], Optional[str]]:
    if not GITHUB_TOKEN:
        return None, None

    import requests
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS, timeout=20)

    if r.status_code == 404:
        return None, None
    r.raise_for_status()

    payload = r.json()
    raw = base64.b64decode(payload["content"]).decode("utf-8")
    return json.loads(raw), payload["sha"]


async def _gh_put_file(data: dict, sha: Optional[str]) -> Optional[str]:
    if not GITHUB_TOKEN:
        return None

    import requests
    raw = json.dumps(data, indent=2, ensure_ascii=False)
    body = {
        "message": f"Update {GITHUB_FILE_PATH}",
        "content": base64.b64encode(raw.encode()).decode(),
        **({"sha": sha} if sha else {})
    }

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.put(url, headers=HEADERS, json=body, timeout=25)
    r.raise_for_status()
    return r.json()["content"]["sha"]


async def load_data() -> Tuple[dict, Optional[str]]:
    async with _lock:
        data, sha = await _gh_get_file()
        if not data:
            return json.loads(json.dumps(DEFAULT_DATA)), sha

        merged = json.loads(json.dumps(DEFAULT_DATA))
        merged["settings"].update(data.get("settings", {}))
        merged["birthdays"] = data.get("birthdays", {})
        merged["state"].update(data.get("state", {}))
        return merged, sha


async def save_data(data: dict, sha: Optional[str]) -> Optional[str]:
    async with _lock:
        return await _gh_put_file(data, sha)

# ======================================================
# Utils
# ======================================================
def _is_valid_tz(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False


def _fmt_single(tpl: str, member: discord.Member) -> str:
    return (
        tpl.replace("{user}", member.mention)
           .replace("{username}", member.display_name)
    )


def _fmt_multi(tpl: str, members: List[discord.Member]) -> str:
    return (
        tpl.replace("{users}", ", ".join(m.mention for m in members))
           .replace("{count}", str(len(members)))
    )

# ======================================================
# Timezone autocomplete
# ======================================================
_TZ_CACHE: Optional[List[str]] = None

def _all_tzs() -> List[str]:
    global _TZ_CACHE
    if _TZ_CACHE is None:
        _TZ_CACHE = sorted(available_timezones())
    return _TZ_CACHE


async def timezone_autocomplete(_, current: str):
    cur = current.lower()
    return [
        app_commands.Choice(name=t, value=t)
        for t in _all_tzs()
        if cur in t.lower()
    ][:20]

# ======================================================
# Message modal
# ======================================================
class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Messages"):
    single = discord.ui.TextInput(label="Single birthday message", style=discord.TextStyle.paragraph)
    multiple = discord.ui.TextInput(label="Multiple birthdays message", style=discord.TextStyle.paragraph)

    def __init__(self, data: dict):
        super().__init__()
        self.data = data
        self.single.default = data["settings"]["message_single"]
        self.multiple.default = data["settings"]["message_multiple"]

    async def on_submit(self, interaction: discord.Interaction):
        data, sha = await load_data()
        data["settings"]["message_single"] = self.single.value
        data["settings"]["message_multiple"] = self.multiple.value
        await save_data(data, sha)
        await interaction.response.send_message("✅ Birthday messages updated.", ephemeral=True)

# ======================================================
# Settings view
# ======================================================
class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot: discord.Client, data: dict, sha: Optional[str]):
        super().__init__(timeout=300)
        self.bot = bot
        self.data = data
        self.sha = sha

    async def save(self, interaction: discord.Interaction):
        self.sha = await save_data(self.data, self.sha)
        await interaction.response.edit_message(content=self.render(), view=self)

    def render(self) -> str:
        s = self.data["settings"]
        return (
            "🎂 **Birthday Settings**\n"
            f"Enabled: {'✅' if s['enabled'] else '❌'}\n"
            f"Announcements: {'✅' if s['announce'] else '❌'}\n"
            f"Channel: <#{s['channel_id']}>\n"
            f"Role: <@&{s['birthday_role_id']}>\n\n"
            f"**Single:**\n{s['message_single']}\n\n"
            f"**Multiple:**\n{s['message_multiple']}"
        )

    @discord.ui.button(label="Toggle enabled", style=discord.ButtonStyle.primary)
    async def toggle_enabled(self, interaction: discord.Interaction, _):
        self.data["settings"]["enabled"] ^= True
        await self.save(interaction)

    @discord.ui.button(label="Toggle announcements", style=discord.ButtonStyle.secondary)
    async def toggle_announce(self, interaction: discord.Interaction, _):
        self.data["settings"]["announce"] ^= True
        await self.save(interaction)

    @discord.ui.button(label="Edit messages", style=discord.ButtonStyle.success)
    async def edit_messages(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(BirthdayMessageModal(self.data))

    @discord.ui.button(label="Send test announcement", style=discord.ButtonStyle.secondary)
    async def test(self, interaction: discord.Interaction, _):
        s = self.data["settings"]
        channel = interaction.guild.get_channel(s["channel_id"])
        if not channel:
            return await interaction.response.send_message("❌ Channel not set.", ephemeral=True)

        today = datetime.now(UK_TZ).date()
        members = [
            interaction.guild.get_member(int(uid))
            for uid, r in self.data["birthdays"].items()
            if r["day"] == today.day and r["month"] == today.month
        ]
        members = [m for m in members if m] or [interaction.user]

        images = s.get("images", [])
        image = random.choice(images) if images else None

        if len(members) == 1:
            msg = _fmt_single(s["message_single"], members[0])
        else:
            msg = _fmt_multi(s["message_multiple"], members)

        await channel.send(f"🧪 **TEST MODE**\n{msg}")
        if image:
            await channel.send(image)

        await interaction.response.send_message("✅ Test sent.", ephemeral=True)

# ======================================================
# Setup
# ======================================================
def setup(bot: discord.Client):
    tree = bot.tree
    group = app_commands.Group(name="birthday", description="Birthday commands")
    tree.add_command(group)

    @group.command(name="settings")
    async def settings(interaction: discord.Interaction):
        await interaction.response.defer()
        data, sha = await load_data()
        view = BirthdaySettingsView(bot, data, sha)
        await interaction.followup.send(view.render(), view=view)

    @group.command(name="set")
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def set_birthday(interaction: discord.Interaction, day: int, month: int, timezone: str, user: Optional[discord.Member] = None):
        if not _is_valid_tz(timezone):
            return await interaction.response.send_message("❌ Invalid timezone.", ephemeral=True)

        target = user or interaction.user
        data, sha = await load_data()
        data["birthdays"][str(target.id)] = {"day": day, "month": month, "timezone": timezone}
        await save_data(data, sha)

        await interaction.response.send_message(f"✅ Birthday set for {target.mention}")

# ======================================================
# Background task
# ======================================================
@tasks.loop(minutes=15)
async def birthday_tick(bot: discord.Client):
    data, sha = await load_data()
    s = data["settings"]

    if not s["enabled"]:
        return

    for guild in bot.guilds:
        channel = guild.get_channel(s["channel_id"])
        role = guild.get_role(s["birthday_role_id"]) if s["birthday_role_id"] else None
        if not channel:
            continue

        now_utc = datetime.now(timezone.utc)
        today_map: Dict[str, List[discord.Member]] = {}

        for uid, rec in data["birthdays"].items():
            member = guild.get_member(int(uid))
            if not member:
                continue

            tz = ZoneInfo(rec["timezone"])
            local_date = now_utc.astimezone(tz).date()
            key = f"{local_date.isoformat()}|{uid}"

            if rec["day"] == local_date.day and rec["month"] == local_date.month:
                today_map.setdefault(local_date.isoformat(), []).append(member)
                if role and key not in data["state"]["role_assigned_keys"]:
                    await member.add_roles(role, reason="Birthday")
                    data["state"]["role_assigned_keys"].append(key)
            else:
                if role and role in member.roles:
                    await member.remove_roles(role, reason="Birthday ended")

        for date_key, members in today_map.items():
            announce_key = f"{date_key}|announce"
            if announce_key in data["state"]["announced_keys"]:
                continue

            images = s.get("images", [])
            image = random.choice(images) if images else None

            if len(members) == 1:
                msg = _fmt_single(s["message_single"], members[0])
            else:
                msg = _fmt_multi(s["message_multiple"], members)

            await channel.send(msg)
            if image:
                await channel.send(image)

            data["state"]["announced_keys"].append(announce_key)

        await save_data(data, sha)


@birthday_tick.before_loop
async def before_tick():
    await bot.wait_until_ready()