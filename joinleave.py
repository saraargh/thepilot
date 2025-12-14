# joinleave.py
import discord
from discord.ui import Modal, TextInput
import asyncio
import os
import json
import base64
import requests

from permissions import has_global_access

# ======================================================
# GITHUB CONFIG
# ======================================================

GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "welcome_config.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

DEFAULT_CONFIG = {
    "welcome": {
        "enabled": True,
        "welcome_channel_id": None,
        "title": "Welcome to the server, {user}! 👋🏼",
        "description": ""
    },
    "member_logs": {
        "enabled": True,
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


def save_config(cfg):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS)

    payload = {
        "message": "Update welcome config",
        "content": base64.b64encode(json.dumps(cfg, indent=2).encode()).decode()
    }

    if r.status_code == 200:
        payload["sha"] = r.json()["sha"]

    requests.put(url, headers=HEADERS, json=payload)

# ======================================================
# MODALS
# ======================================================

class EditWelcomeTitleModal(Modal):
    def __init__(self):
        super().__init__(title="Edit Welcome Title")
        cfg = load_config()
        self.title_input = TextInput(
            label="Title",
            default=cfg["welcome"]["title"],
            max_length=256
        )
        self.add_item(self.title_input)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"]["title"] = self.title_input.value
        save_config(cfg)
        await interaction.response.send_message("✅ Welcome title updated.")


class EditWelcomeTextModal(Modal):
    def __init__(self):
        super().__init__(title="Edit Welcome Text")
        cfg = load_config()
        self.text_input = TextInput(
            label="Text",
            style=discord.TextStyle.paragraph,
            default=cfg["welcome"]["description"],
            max_length=2000
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"]["description"] = self.text_input.value
        save_config(cfg)
        await interaction.response.send_message("✅ Welcome text updated.")

# ======================================================
# SELECTS — WELCOME
# ======================================================

class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a welcome action",
            options=[
                discord.SelectOption(label="Toggle Welcome On / Off"),
                discord.SelectOption(label="Edit Welcome Title"),
                discord.SelectOption(label="Edit Welcome Text"),
                discord.SelectOption(label="Preview Welcome"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        cfg = load_config()
        choice = self.values[0]

        if choice == "Toggle Welcome On / Off":
            cfg["welcome"]["enabled"] = not cfg["welcome"]["enabled"]
            save_config(cfg)
            await interaction.response.send_message(
                f"Welcome is now **{'enabled' if cfg['welcome']['enabled'] else 'disabled'}**."
            )

        elif choice == "Edit Welcome Title":
            await interaction.response.send_modal(EditWelcomeTitleModal())

        elif choice == "Edit Welcome Text":
            await interaction.response.send_modal(EditWelcomeTextModal())

        elif choice == "Preview Welcome":
            embed = discord.Embed(
                title=cfg["welcome"]["title"].replace("{user}", interaction.user.name),
                description=cfg["welcome"]["description"]
            )
            await interaction.response.send_message(embed=embed)

# ======================================================
# SELECTS — LEAVE
# ======================================================

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a leave/log action",
            options=[
                discord.SelectOption(label="Toggle Leave Logs"),
                discord.SelectOption(label="Toggle Kick Logs"),
                discord.SelectOption(label="Toggle Ban Logs"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        cfg = load_config()
        mapping = {
            "Toggle Leave Logs": "log_leave",
            "Toggle Kick Logs": "log_kick",
            "Toggle Ban Logs": "log_ban",
        }

        key = mapping[self.values[0]]
        cfg["member_logs"][key] = not cfg["member_logs"][key]
        save_config(cfg)

        await interaction.response.send_message(
            f"{self.values[0]} → **{'enabled' if cfg['member_logs'][key] else 'disabled'}**."
        )

# ======================================================
# RUNTIME SYSTEM
# ======================================================

class WelcomeSystem:
    def __init__(self, client):
        self.client = client

    async def on_member_join(self, member):
        cfg = load_config()
        if not cfg["welcome"]["enabled"]:
            return

        for channel in member.guild.text_channels:
            if channel.permissions_for(member.guild.me).send_messages:
                await channel.send(
                    embed=discord.Embed(
                        title=cfg["welcome"]["title"].replace("{user}", member.name),
                        description=cfg["welcome"]["description"]
                    )
                )
                break

    async def on_member_remove(self, member):
        pass

    async def on_member_ban(self, guild, user):
        pass