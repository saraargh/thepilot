import discord
from discord import app_commands
from discord.ui import View, Modal, TextInput, Select
from datetime import datetime
import asyncio
import random
import os
import json
import base64
import requests

# =========================
# GITHUB CONFIG
# =========================
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "welcome_config.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,  # serversorter
    1420817462290681936,  # kd
    1404105470204969000,  # greg
    1404104881098195015   # sazzles
]

# =========================
# DEFAULT CONFIG
# =========================
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

# =========================
# CONFIG HELPERS
# =========================
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

# =========================
# UTILS
# =========================
def has_permission(interaction):
    return any(r.id in ALLOWED_ROLE_IDS for r in interaction.user.roles)

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

# =========================
# MODALS
# =========================
class EditTitleModal(Modal):
    def __init__(self):
        super().__init__(title="Edit Welcome Title")
        self.value = TextInput(label="Title", max_length=256)
        self.add_item(self.value)

    async def on_submit(self, interaction):
        cfg = load_config()
        cfg["welcome"]["title"] = self.value.value
        save_config(cfg)
        await interaction.response.send_message("Title updated.", ephemeral=True)

class EditTextModal(Modal):
    def __init__(self):
        super().__init__(title="Edit Welcome Text")
        self.value = TextInput(label="Text", style=discord.TextStyle.paragraph, max_length=2000)
        self.add_item(self.value)

    async def on_submit(self, interaction):
        cfg = load_config()
        cfg["welcome"]["description"] = self.value.value
        save_config(cfg)
        await interaction.response.send_message("Text updated.", ephemeral=True)

# =========================
# SETTINGS VIEW (BUTTON SAFE)
# =========================
class WelcomeSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(discord.ui.Button(label="Edit Title", custom_id="edit_title"))
        self.add_item(discord.ui.Button(label="Edit Text", custom_id="edit_text"))

    async def interaction_check(self, interaction):
        if not has_permission(interaction):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        pass

    async def on_error(self, error, item, interaction):
        raise error

    async def handle(self, interaction):
        if interaction.data["custom_id"] == "edit_title":
            await interaction.response.send_modal(EditTitleModal())
        elif interaction.data["custom_id"] == "edit_text":
            await interaction.response.send_modal(EditTextModal())

    async def interaction_callback(self, interaction):
        await self.handle(interaction)

# =========================
# MAIN SYSTEM
# =========================
class WelcomeSystem:
    def __init__(self, client):
        self.client = client

    async def on_member_join(self, member):
        if member.bot:
            return

        cfg = load_config()
        w = cfg["welcome"]

        if not w["enabled"]:
            return

        channel = self.client.get_channel(w["welcome_channel_id"])
        if not channel:
            return

        humans = len([m for m in member.guild.members if not m.bot])

        embed = discord.Embed(
            title=render(w["title"], user=member, guild=member.guild,
                         member_count=humans, channels=w["channels"]),
            description=render(w["description"], user=member, guild=member.guild,
                               member_count=humans, channels=w["channels"]),
            timestamp=datetime.utcnow()
        )

        if w["arrival_images"]:
            embed.set_image(url=random.choice(w["arrival_images"]))

        await channel.send(content=member.mention, embed=embed)

    async def on_member_remove(self, member):
        cfg = load_config()
        logs = cfg["member_logs"]

        if not logs["enabled"] or not logs["channel_id"]:
            return

        channel = self.client.get_channel(logs["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)

        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                if logs["log_kick"]:
                    await channel.send(f"{member.name} was kicked by {entry.user}")
                return

        if logs["log_leave"]:
            await channel.send(f"{member.name} left the server")

    async def on_member_ban(self, guild, user):
        cfg = load_config()
        logs = cfg["member_logs"]

        if not logs["enabled"] or not logs["log_ban"] or not logs["channel_id"]:
            return

        channel = self.client.get_channel(logs["channel_id"])
        if not channel:
            return

        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                await channel.send(f"{user.name} was banned by {entry.user}")
                return

# =========================
# SLASH COMMAND
# =========================
def setup_welcome_commands(tree):
    @tree.command(name="setwelcome", description="Open welcome settings")
    async def setwelcome(interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        cfg = load_config()
        msg = await interaction.channel.send(
            f"Welcome Settings\nEdited by {interaction.user.mention}",
            view=WelcomeSettingsView()
        )

        cfg["welcome"]["control_panel_message_id"] = msg.id
        save_config(cfg)