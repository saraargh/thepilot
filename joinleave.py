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

# ======================================================
# ALLOWED ROLE IDS (LOCKED)
# ======================================================
ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,  # serversorter
    1420817462290681936,  # kd
    1404105470204969000,  # greg
    1404104881098195015   # sazzles
]

# ======================================================
# GITHUB CONFIG
# ======================================================
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "welcome_config.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ======================================================
# DEFAULT CONFIG
# ======================================================
DEFAULT_CONFIG = {
    "welcome": {
        "enabled": True,
        "welcome_channel_id": None,
        "title": "Welcome to the server, {user}! 👋🏼",
        "description": "",
        "channels": {},
        "arrival_images": []
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

def save_config(cfg):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS)

    data = {
        "message": "Update member settings",
        "content": base64.b64encode(json.dumps(cfg, indent=2).encode()).decode()
    }

    if r.status_code == 200:
        data["sha"] = r.json()["sha"]

    requests.put(url, headers=HEADERS, json=data)

# ======================================================
# UTILS
# ======================================================
def has_permission(interaction: discord.Interaction):
    return any(r.id in ALLOWED_ROLE_IDS for r in interaction.user.roles)

def render(text, *, user, guild, member_count, channels):
    if not text:
        return ""

    out = (
        text.replace("{user}", user.name)
        .replace("{mention}", user.mention)
        .replace("{server}", guild.name)
        .replace("{member_count}", str(member_count))
    )

    for name, cid in channels.items():
        out = out.replace(f"{{channel:{name}}}", f"<#{cid}>")

    return out

def _cid(val):
    return val.id if hasattr(val, "id") else int(val)

# ======================================================
# MODALS
# ======================================================
class EditTitleModal(Modal):
    def __init__(self):
        super().__init__(title="Edit Welcome Title")
        self.text = TextInput(label="Title", max_length=256)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        cfg = load_config()
        cfg["welcome"]["title"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("Title updated.")

class EditTextModal(Modal):
    def __init__(self):
        super().__init__(title="Edit Welcome Text")
        self.text = TextInput(label="Text", style=discord.TextStyle.paragraph, max_length=2000)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        cfg = load_config()
        cfg["welcome"]["description"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("Text updated.")

class AddImageModal(Modal):
    def __init__(self):
        super().__init__(title="Add Welcome Image")
        self.url = TextInput(label="Image URL")
        self.add_item(self.url)

    async def on_submit(self, interaction):
        cfg = load_config()
        cfg["welcome"]["arrival_images"].append(self.url.value)
        save_config(cfg)
        await interaction.response.send_message("Image added.")

class AddChannelSlotModal(Modal):
    def __init__(self):
        super().__init__(title="Add / Edit Channel Slot")
        self.name = TextInput(label="Slot name (e.g. self_roles)")
        self.add_item(self.name)

    async def on_submit(self, interaction):
        await interaction.response.send_message(
            f"Select channel for `{self.name.value}`:",
            view=ChannelSlotPickerView(self.name.value)
        )

# ======================================================
# PICKERS
# ======================================================
class ChannelSlotPickerView(View):
    def __init__(self, slot):
        super().__init__(timeout=60)
        self.slot = slot

        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction):
        cfg = load_config()
        cfg["welcome"]["channels"][self.slot] = _cid(interaction.data["values"][0])
        save_config(cfg)
        await interaction.response.edit_message(
            content=f"Saved `{self.slot}` → <#{cfg['welcome']['channels'][self.slot]}>",
            view=None
        )

class WelcomeChannelPicker(View):
    def __init__(self):
        super().__init__(timeout=60)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction):
        cfg = load_config()
        cfg["welcome"]["welcome_channel_id"] = _cid(interaction.data["values"][0])
        save_config(cfg)
        await interaction.response.edit_message(
            content=f"Welcome channel set to <#{cfg['welcome']['welcome_channel_id']}>",
            view=None
        )

class RemoveChannelSlotView(View):
    def __init__(self):
        super().__init__(timeout=60)
        cfg = load_config()
        opts = [discord.SelectOption(label=k, value=k) for k in cfg["welcome"]["channels"]] or \
               [discord.SelectOption(label="None", value="none")]
        sel = Select(options=opts)
        sel.callback = self.remove
        self.add_item(sel)

    async def remove(self, interaction):
        key = interaction.data["values"][0]
        if key == "none":
            return await interaction.response.send_message("Nothing to remove.")
        cfg = load_config()
        cfg["welcome"]["channels"].pop(key, None)
        save_config(cfg)
        await interaction.response.edit_message(content=f"Removed `{key}`", view=None)

class RemoveImageView(View):
    def __init__(self):
        super().__init__(timeout=60)
        cfg = load_config()
        opts = [discord.SelectOption(label=url[:90], value=url)
                for url in cfg["welcome"]["arrival_images"]] or \
               [discord.SelectOption(label="None", value="none")]
        sel = Select(options=opts)
        sel.callback = self.remove
        self.add_item(sel)

    async def remove(self, interaction):
        val = interaction.data["values"][0]
        if val == "none":
            return await interaction.response.send_message("Nothing to remove.")
        cfg = load_config()
        cfg["welcome"]["arrival_images"].remove(val)
        save_config(cfg)
        await interaction.response.edit_message(content="Image removed.", view=None)

class LogChannelPicker(View):
    def __init__(self):
        super().__init__(timeout=60)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction):
        cfg = load_config()
        cfg["member_logs"]["channel_id"] = _cid(interaction.data["values"][0])
        save_config(cfg)
        await interaction.response.edit_message(
            content=f"Member log channel set to <#{cfg['member_logs']['channel_id']}>",
            view=None
        )

# ======================================================
# SETTINGS VIEWS
# ======================================================
class WelcomeSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)

        self._btn("Edit Title", self.edit_title)
        self._btn("Edit Text", self.edit_text)
        self._btn("Set Welcome Channel", self.set_channel)
        self._btn("Add/Edit Channel Slot", self.add_slot)
        self._btn("Remove Channel Slot", self.remove_slot)
        self._btn("Add Image", self.add_image)
        self._btn("Remove Image", self.remove_image)
        self._btn("Preview", self.preview)
        self._btn("Toggle Welcome On/Off", self.toggle, discord.ButtonStyle.danger)

    def _btn(self, label, cb, style=discord.ButtonStyle.secondary):
        b = discord.ui.Button(label=label, style=style)
        b.callback = cb
        self.add_item(b)

    async def interaction_check(self, interaction):
        if not has_permission(interaction):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return False
        return True

    async def edit_title(self, interaction): await interaction.response.send_modal(EditTitleModal())
    async def edit_text(self, interaction): await interaction.response.send_modal(EditTextModal())
    async def set_channel(self, interaction): await interaction.response.send_message("Select welcome channel:", view=WelcomeChannelPicker())
    async def add_slot(self, interaction): await interaction.response.send_modal(AddChannelSlotModal())
    async def remove_slot(self, interaction): await interaction.response.send_message("Select slot to remove:", view=RemoveChannelSlotView())
    async def add_image(self, interaction): await interaction.response.send_modal(AddImageModal())
    async def remove_image(self, interaction): await interaction.response.send_message("Select image to remove:", view=RemoveImageView())

    async def toggle(self, interaction):
        cfg = load_config()
        cfg["welcome"]["enabled"] = not cfg["welcome"]["enabled"]
        save_config(cfg)
        await interaction.response.send_message(f"Welcome {'enabled' if cfg['welcome']['enabled'] else 'disabled'}.")

    async def preview(self, interaction):
        cfg = load_config()
        w = cfg["welcome"]
        humans = len([m for m in interaction.guild.members if not m.bot])

        embed = discord.Embed(
            title=render(w["title"], user=interaction.user, guild=interaction.guild, member_count=humans, channels=w["channels"]),
            description=render(w["description"], user=interaction.user, guild=interaction.guild, member_count=humans, channels=w["channels"]),
            timestamp=datetime.utcnow()
        )
        if w["arrival_images"]:
            embed.set_image(url=random.choice(w["arrival_images"]))
        await interaction.response.send_message(embed=embed)

class LeaveSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self._btn("Set Member Log Channel", self.set_log)
        self._btn("Toggle Leave Logs", self.toggle_leave)
        self._btn("Toggle Kick Logs", self.toggle_kick)
        self._btn("Toggle Ban Logs", self.toggle_ban)

    def _btn(self, label, cb):
        b = discord.ui.Button(label=label)
        b.callback = cb
        self.add_item(b)

    async def interaction_check(self, interaction):
        if not has_permission(interaction):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return False
        return True

    async def set_log(self, interaction): await interaction.response.send_message("Select log channel:", view=LogChannelPicker())
    async def toggle_leave(self, interaction): self._toggle(interaction, "log_leave", "Leave")
    async def toggle_kick(self, interaction): self._toggle(interaction, "log_kick", "Kick")
    async def toggle_ban(self, interaction): self._toggle(interaction, "log_ban", "Ban")

    def _toggle(self, interaction, key, name):
        cfg = load_config()
        cfg["member_logs"][key] = not cfg["member_logs"][key]
        save_config(cfg)
        return interaction.response.send_message(f"{name} logs {'enabled' if cfg['member_logs'][key] else 'disabled'}.")

# ======================================================
# JOIN / LEAVE / BAN HANDLERS
# ======================================================
class WelcomeSystem:
    def __init__(self, client):
        self.client = client

    async def on_member_join(self, member):
        if member.bot:
            return

        cfg = load_config()
        w = cfg["welcome"]
        if not w["enabled"] or not w["welcome_channel_id"]:
            return

        channel = self.client.get_channel(w["welcome_channel_id"])
        humans = len([m for m in member.guild.members if not m.bot])

        embed = discord.Embed(
            title=render(w["title"], user=member, guild=member.guild, member_count=humans, channels=w["channels"]),
            description=render(w["description"], user=member, guild=member.guild, member_count=humans, channels=w["channels"]),
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
        await asyncio.sleep(1.5)

        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                if logs["log_kick"]:
                    await channel.send(f"{member.name} was kicked from the server by {entry.user}")
                return

        if logs["log_leave"]:
            await channel.send(f"{member.name} left the server")

    async def on_member_ban(self, guild, user):
        cfg = load_config()
        logs = cfg["member_logs"]
        if not logs["enabled"] or not logs["log_ban"] or not logs["channel_id"]:
            return

        channel = self.client.get_channel(logs["channel_id"])
        await asyncio.sleep(1.5)

        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                await channel.send(f"{user.name} was banned from the server by {entry.user}")
                return

# ======================================================
# SLASH COMMANDS
# ======================================================
def setup_welcome_commands(tree: app_commands.CommandTree):
    @tree.command(name="welcomesettings", description="Manage welcome messages")
    async def welcomesettings(interaction: discord.Interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        await interaction.channel.send(view=WelcomeSettingsView())
        await interaction.response.send_message("Opened welcome settings.", ephemeral=True)

    @tree.command(name="leavesettings", description="Manage leave, kick and ban logs")
    async def leavesettings(interaction: discord.Interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        await interaction.channel.send(view=LeaveSettingsView())
        await interaction.response.send_message("Opened leave settings.", ephemeral=True)