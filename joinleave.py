import discord
from discord.ui import View, Button, Modal, TextInput, Select
from datetime import datetime
import asyncio
import random
import os
import json
import base64
import requests

# ======================================================
# GITHUB CONFIG
# ======================================================
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "welcome_config.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

ALLOWED_ROLE_IDS = [
    1413545658006110401,
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ======================================================
# DEFAULT CONFIG (BOOTSTRAP ONLY)
# ======================================================
DEFAULT_CONFIG = {
    "welcome": {
        "enabled": True,
        "welcome_channel_id": None,
        "title": "Welcome to the server, {user}! 👋🏼",
        "description": "",
        "channels": {},
        "arrival_images": [],
        "control_panel_message_id": None
    },
    "member_logs": {
        "enabled": True,
        "channel_id": None,
        "log_leave": True,
        "log_kick": True,
        "log_ban": True
    }
}

# ======================================================
# CONFIG HELPERS
# ======================================================
def load_config():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS)

    if r.status_code == 200:
        return json.loads(base64.b64decode(r.json()["content"]).decode())

    save_config(DEFAULT_CONFIG.copy())
    return DEFAULT_CONFIG.copy()

def save_config(config):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS)

    data = {
        "message": "Update welcome config",
        "content": base64.b64encode(json.dumps(config, indent=2).encode()).decode()
    }

    if r.status_code == 200:
        data["sha"] = r.json()["sha"]

    requests.put(url, headers=HEADERS, json=data)

# ======================================================
# PLACEHOLDER ENGINE
# ======================================================
def render(text, *, user, guild, member_count, channels):
    if not text:
        return ""

    text = (
        text.replace("{user}", user.name)
        .replace("{mention}", user.mention)
        .replace("{server}", guild.name)
        .replace("{member_count}", str(member_count))
    )

    for name, cid in channels.items():
        text = text.replace(f"{{channel:{name}}}", f"<#{cid}>")

    return text

# ======================================================
# PERMISSIONS
# ======================================================
def has_permission(interaction):
    return any(r.id in ALLOWED_ROLE_IDS for r in interaction.user.roles)

# ======================================================
# CHANNEL PICKERS (VERSION SAFE)
# ======================================================
class ChannelPickerView(View):
    def __init__(self, slot_name):
        super().__init__(timeout=60)
        self.slot_name = slot_name

        self.select = discord.ui.ChannelSelect(
            placeholder="Select a channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        self.select.callback = self.pick
        self.add_item(self.select)

    async def pick(self, interaction):
        if not has_permission(interaction):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return

        channel = self.select.values[0]

        cfg = load_config()
        cfg["welcome"]["channels"][self.slot_name] = channel.id
        save_config(cfg)

        await interaction.response.edit_message(
            content=f"Saved `{self.slot_name}` → {channel.mention}",
            view=None
        )

class LogChannelPickerView(View):
    def __init__(self):
        super().__init__(timeout=60)

        self.select = discord.ui.ChannelSelect(
            placeholder="Select member log channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        self.select.callback = self.pick
        self.add_item(self.select)

    async def pick(self, interaction):
        if not has_permission(interaction):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return

        channel = self.select.values[0]

        cfg = load_config()
        cfg["member_logs"]["channel_id"] = channel.id
        save_config(cfg)

        await interaction.response.edit_message(
            content=f"Member log channel set to {channel.mention}",
            view=None
        )

# ======================================================
# MAIN SYSTEM
# ======================================================
class WelcomeSystem:
    def __init__(self, client: discord.Client):
        self.client = client

    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        cfg = load_config()
        welcome = cfg["welcome"]

        if not welcome["enabled"]:
            return

        channel = self.client.get_channel(welcome["welcome_channel_id"])
        if not channel:
            return

        humans = len([m for m in member.guild.members if not m.bot])

        embed = discord.Embed(
            title=render(
                welcome["title"],
                user=member,
                guild=member.guild,
                member_count=humans,
                channels=welcome["channels"]
            ),
            description=render(
                welcome["description"],
                user=member,
                guild=member.guild,
                member_count=humans,
                channels=welcome["channels"]
            ),
            timestamp=datetime.utcnow()
        )

        if welcome["arrival_images"]:
            embed.set_image(url=random.choice(welcome["arrival_images"]))

        await channel.send(content=member.mention, embed=embed)

    async def on_member_remove(self, member: discord.Member):
        cfg = load_config()
        logs = cfg["member_logs"]

        if not logs["enabled"] or not logs["channel_id"]:
            return

        channel = self.client.get_channel(logs["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)

        async for entry in member.guild.audit_logs(
            limit=5,
            action=discord.AuditLogAction.kick
        ):
            if entry.target.id == member.id:
                if logs["log_kick"]:
                    await channel.send(
                        f"{member.name} was kicked from the server by {entry.user}"
                    )
                return

        if logs["log_leave"]:
            await channel.send(f"{member.name} left the server")

    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        cfg = load_config()
        logs = cfg["member_logs"]

        if not logs["enabled"] or not logs["log_ban"] or not logs["channel_id"]:
            return

        channel = self.client.get_channel(logs["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)

        async for entry in guild.audit_logs(
            limit=5,
            action=discord.AuditLogAction.ban
        ):
            if entry.target.id == user.id:
                await channel.send(
                    f"{user.name} was banned from the server by {entry.user}"
                )
                return