import discord
from discord import app_commands
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
        "enabled": False,
        "welcome_channel_id": None,
        "title": "Welcome, {user}",
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
# PERMISSION CHECK
# ======================================================
def has_permission(interaction):
    return any(r.id in ALLOWED_ROLE_IDS for r in interaction.user.roles)

# ======================================================
# MODALS
# ======================================================
class EditTitleModal(Modal, title="Edit Welcome Title"):
    value = TextInput(label="Title", max_length=256)

    async def on_submit(self, interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"]["title"] = self.value.value
        save_config(cfg)
        await interaction.response.send_message("✅ Title updated.", ephemeral=True)

class EditTextModal(Modal, title="Edit Welcome Text"):
    value = TextInput(label="Text", style=discord.TextStyle.paragraph, max_length=2000)

    async def on_submit(self, interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"]["description"] = self.value.value
        save_config(cfg)
        await interaction.response.send_message("✅ Text updated.", ephemeral=True)

class AddImageModal(Modal, title="Add Welcome Image"):
    url = TextInput(label="Image URL")

    async def on_submit(self, interaction):
        cfg = load_config()
        cfg["welcome"]["arrival_images"].append(self.url.value)
        save_config(cfg)
        await interaction.response.send_message("🖼 Image added.", ephemeral=True)

class AddChannelNameModal(Modal, title="Add / Edit Channel Slot"):
    name = TextInput(label="Slot name (e.g. self_roles)", max_length=32)

    async def on_submit(self, interaction):
        await interaction.response.send_message(
            f"Select channel for `{self.name.value}`:",
            view=ChannelPickerView(self.name.value),
            ephemeral=True
        )

# ======================================================
# VIEWS
# ======================================================
class ChannelPickerView(View):
    def __init__(self, slot):
        super().__init__(timeout=60)
        self.slot = slot

    @discord.ui.channel_select(channel_types=[discord.ChannelType.text])
    async def pick(self, interaction, select):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"]["channels"][self.slot] = select.values[0].id
        save_config(cfg)

        await interaction.response.edit_message(
            content=f"✅ `{self.slot}` → {select.values[0].mention}",
            view=None
        )

class RemoveChannelView(View):
    def __init__(self):
        super().__init__(timeout=60)
        cfg = load_config()
        options = [
            discord.SelectOption(label=k, description=f"<#{v}>", value=k)
            for k, v in cfg["welcome"]["channels"].items()
        ] or [discord.SelectOption(label="No channels", value="none")]

        self.select = Select(options=options)
        self.select.callback = self.remove
        self.add_item(self.select)

    async def remove(self, interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        key = self.select.values[0]
        if key == "none":
            return await interaction.response.send_message("Nothing to remove.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"]["channels"].pop(key, None)
        save_config(cfg)

        await interaction.response.edit_message(f"🗑 Removed `{key}`", view=None)

class RemoveImageView(View):
    def __init__(self):
        super().__init__(timeout=60)
        cfg = load_config()
        options = [
            discord.SelectOption(label=f"Image {i+1}", description=url[:90], value=url)
            for i, url in enumerate(cfg["welcome"]["arrival_images"])
        ] or [discord.SelectOption(label="No images", value="none")]

        self.select = Select(options=options)
        self.select.callback = self.remove
        self.add_item(self.select)

    async def remove(self, interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        val = self.select.values[0]
        if val == "none":
            return await interaction.response.send_message("Nothing to remove.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"]["arrival_images"].remove(val)
        save_config(cfg)

        await interaction.response.edit_message("🗑 Image removed.", view=None)

class LogChannelPickerView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.channel_select(channel_types=[discord.ChannelType.text])
    async def pick(self, interaction, select):
        cfg = load_config()
        cfg["member_logs"]["channel_id"] = select.values[0].id
        save_config(cfg)

        await interaction.response.edit_message(
            content=f"✅ Member log channel set to {select.values[0].mention}",
            view=None
        )

class WelcomeSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @Button(label="✏️ Edit Title")
    async def title(self, interaction, _):
        await interaction.response.send_modal(EditTitleModal())

    @Button(label="📝 Edit Text")
    async def text(self, interaction, _):
        await interaction.response.send_modal(EditTextModal())

    @Button(label="🔗 Add/Edit Channel")
    async def add_channel(self, interaction, _):
        await interaction.response.send_modal(AddChannelNameModal())

    @Button(label="❌ Remove Channel")
    async def remove_channel(self, interaction, _):
        await interaction.response.send_message("Select channel slot:", view=RemoveChannelView(), ephemeral=True)

    @Button(label="🖼 Add Image")
    async def add_image(self, interaction, _):
        await interaction.response.send_modal(AddImageModal())

    @Button(label="🗑 Remove Image")
    async def remove_image(self, interaction, _):
        await interaction.response.send_message("Select image:", view=RemoveImageView(), ephemeral=True)

    @Button(label="📤 Log Channel")
    async def log_channel(self, interaction, _):
        await interaction.response.send_message("Select log channel:", view=LogChannelPickerView(), ephemeral=True)

    @Button(label="👁 Preview")
    async def preview(self, interaction, _):
        cfg = load_config()
        embed = discord.Embed(
            title=render(cfg["welcome"]["title"], user=interaction.user,
                         guild=interaction.guild,
                         member_count=interaction.guild.member_count,
                         channels=cfg["welcome"]["channels"]),
            description=render(cfg["welcome"]["description"], user=interaction.user,
                               guild=interaction.guild,
                               member_count=interaction.guild.member_count,
                               channels=cfg["welcome"]["channels"]),
            timestamp=datetime.utcnow()
        )

        imgs = cfg["welcome"]["arrival_images"]
        if imgs:
            embed.set_image(url=random.choice(imgs))

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ======================================================
# SLASH COMMAND + EVENT SYSTEM
# ======================================================
class WelcomeSystem:
    def __init__(self, client):
        self.client = client

    async def on_member_join(self, member):
        cfg = load_config()
        w = cfg["welcome"]

        if not w["enabled"] or member.bot:
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

        imgs = w["arrival_images"]
        if imgs:
            embed.set_image(url=random.choice(imgs))

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
                    await channel.send(f"👢 {member.name} was kicked by {entry.user}")
                return

        if logs["log_leave"]:
            await channel.send(f"👋 {member.name} left the server")

    async def on_member_ban(self, guild, user):
        cfg = load_config()
        logs = cfg["member_logs"]

        if not logs["enabled"] or not logs["log_ban"] or not logs["channel_id"]:
            return

        channel = self.client.get_channel(logs["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)

        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                await channel.send(f"🔨 {user.name} was banned by {entry.user}")
                return

# ======================================================
# COMMAND SETUP
# ======================================================
def setup_welcome(tree: app_commands.CommandTree, client: discord.Client):
    system = WelcomeSystem(client)

    @tree.command(name="setwelcome", description="Open welcome settings")
    async def setwelcome(interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        cfg = load_config()
        old_id = cfg["welcome"].get("control_panel_message_id")

        if old_id:
            try:
                old = await interaction.channel.fetch_message(old_id)
                await old.delete()
            except:
                pass

        msg = await interaction.channel.send(
            f"🛠 **Welcome Settings**\nEdited by {interaction.user.mention}",
            view=WelcomeSettingsView()
        )

        cfg["welcome"]["control_panel_message_id"] = msg.id
        save_config(cfg)

    return system