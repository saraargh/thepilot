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
# UTILS
# ======================================================
def has_permission(interaction: discord.Interaction) -> bool:
    if not interaction.user or not hasattr(interaction.user, "roles"):
        return False
    return any(r.id in ALLOWED_ROLE_IDS for r in interaction.user.roles)

def render(text: str, *, user: discord.abc.User, guild: discord.Guild, member_count: int, channels: dict) -> str:
    if not text:
        return ""

    out = (
        text.replace("{user}", user.name)
            .replace("{mention}", user.mention)
            .replace("{server}", guild.name)
            .replace("{member_count}", str(member_count))
    )

    for name, cid in (channels or {}).items():
        out = out.replace(f"{{channel:{name}}}", f"<#{cid}>")

    return out

def _channel_id_from_select_value(val):
    # Some versions give channel objects; some give IDs as strings
    if hasattr(val, "id"):
        return int(val.id)
    try:
        return int(val)
    except Exception:
        return None

# ======================================================
# MODALS
# ======================================================
class EditTitleModal(Modal):
    def __init__(self):
        super().__init__(title="Edit Welcome Title")
        cfg = load_config()
        current = cfg.get("welcome", {}).get("title", "")
        self.value = TextInput(label="Title", max_length=256, default=current)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"]["title"] = self.value.value
        save_config(cfg)
        await interaction.response.send_message("Title updated.", ephemeral=True)

class EditTextModal(Modal):
    def __init__(self):
        super().__init__(title="Edit Welcome Text")
        cfg = load_config()
        current = cfg.get("welcome", {}).get("description", "")
        self.value = TextInput(label="Text", style=discord.TextStyle.paragraph, max_length=2000, default=current)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"]["description"] = self.value.value
        save_config(cfg)
        await interaction.response.send_message("Text updated.", ephemeral=True)

class AddImageModal(Modal):
    def __init__(self):
        super().__init__(title="Add Welcome Image")
        self.url = TextInput(label="Image URL", max_length=500)
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"].setdefault("arrival_images", [])
        cfg["welcome"]["arrival_images"].append(self.url.value.strip())
        save_config(cfg)
        await interaction.response.send_message("Image added.", ephemeral=True)

class AddChannelSlotModal(Modal):
    def __init__(self):
        super().__init__(title="Add / Edit Channel Slot")
        self.name = TextInput(label="Slot name (e.g. self_roles)", max_length=32)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        slot = self.name.value.strip()
        if not slot:
            return await interaction.response.send_message("Slot name can’t be empty.", ephemeral=True)

        await interaction.response.send_message(
            f"Select the channel for `{slot}`:",
            view=ChannelSlotPickerView(slot),
            ephemeral=True
        )

# ======================================================
# SMALL PICKER VIEWS (ephemeral)
# ======================================================
class ChannelSlotPickerView(View):
    def __init__(self, slot_name: str):
        super().__init__(timeout=60)
        self.slot_name = slot_name

        self.select = discord.ui.ChannelSelect(
            placeholder="Pick a channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        self.select.callback = self._picked
        self.add_item(self.select)

    async def _picked(self, interaction: discord.Interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        chosen = self.select.values[0]
        cid = _channel_id_from_select_value(chosen)
        if not cid:
            return await interaction.response.send_message("Couldn’t read that channel.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"].setdefault("channels", {})
        cfg["welcome"]["channels"][self.slot_name] = cid
        save_config(cfg)

        await interaction.response.edit_message(
            content=f"Saved `{self.slot_name}` → <#{cid}>",
            view=None
        )

class WelcomeChannelPickerView(View):
    def __init__(self):
        super().__init__(timeout=60)

        self.select = discord.ui.ChannelSelect(
            placeholder="Pick the welcome channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        self.select.callback = self._picked
        self.add_item(self.select)

    async def _picked(self, interaction: discord.Interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        chosen = self.select.values[0]
        cid = _channel_id_from_select_value(chosen)
        if not cid:
            return await interaction.response.send_message("Couldn’t read that channel.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"]["welcome_channel_id"] = cid
        save_config(cfg)

        await interaction.response.edit_message(
            content=f"Welcome channel set to <#{cid}>",
            view=None
        )

class MemberLogChannelPickerView(View):
    def __init__(self):
        super().__init__(timeout=60)

        self.select = discord.ui.ChannelSelect(
            placeholder="Pick the member log channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        self.select.callback = self._picked
        self.add_item(self.select)

    async def _picked(self, interaction: discord.Interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        chosen = self.select.values[0]
        cid = _channel_id_from_select_value(chosen)
        if not cid:
            return await interaction.response.send_message("Couldn’t read that channel.", ephemeral=True)

        cfg = load_config()
        cfg.setdefault("member_logs", {})
        cfg["member_logs"]["channel_id"] = cid
        save_config(cfg)

        await interaction.response.edit_message(
            content=f"Member log channel set to <#{cid}>",
            view=None
        )

class RemoveChannelSlotView(View):
    def __init__(self):
        super().__init__(timeout=60)
        cfg = load_config()
        channels = cfg.get("welcome", {}).get("channels", {}) or {}

        options = []
        for name, cid in channels.items():
            options.append(discord.SelectOption(label=name, value=name, description=f"<#{cid}>"))

        if not options:
            options = [discord.SelectOption(label="No slots to remove", value="__none__")]

        self.select = Select(placeholder="Select slot to remove…", options=options, min_values=1, max_values=1)
        self.select.callback = self._remove
        self.add_item(self.select)

    async def _remove(self, interaction: discord.Interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        key = self.select.values[0]
        if key == "__none__":
            return await interaction.response.send_message("Nothing to remove.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"].setdefault("channels", {})
        cfg["welcome"]["channels"].pop(key, None)
        save_config(cfg)

        await interaction.response.edit_message(content=f"Removed slot `{key}`", view=None)

class RemoveImageView(View):
    def __init__(self):
        super().__init__(timeout=60)
        cfg = load_config()
        images = cfg.get("welcome", {}).get("arrival_images", []) or []

        options = []
        for i, url in enumerate(images):
            options.append(discord.SelectOption(label=f"Image {i+1}", value=url, description=url[:95]))

        if not options:
            options = [discord.SelectOption(label="No images to remove", value="__none__")]

        self.select = Select(placeholder="Select image to remove…", options=options, min_values=1, max_values=1)
        self.select.callback = self._remove
        self.add_item(self.select)

    async def _remove(self, interaction: discord.Interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        val = self.select.values[0]
        if val == "__none__":
            return await interaction.response.send_message("Nothing to remove.", ephemeral=True)

        cfg = load_config()
        cfg["welcome"].setdefault("arrival_images", [])
        if val in cfg["welcome"]["arrival_images"]:
            cfg["welcome"]["arrival_images"].remove(val)
            save_config(cfg)

        await interaction.response.edit_message(content="Image removed.", view=None)

# ======================================================
# MAIN SETTINGS PANEL VIEW (public)
# ======================================================
class WelcomeSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)

        # Row 1
        b1 = discord.ui.Button(label="Edit Title", custom_id="ws_edit_title", style=discord.ButtonStyle.primary)
        b2 = discord.ui.Button(label="Edit Text", custom_id="ws_edit_text", style=discord.ButtonStyle.primary)
        b1.callback = self._edit_title
        b2.callback = self._edit_text
        self.add_item(b1)
        self.add_item(b2)

        # Row 2
        b3 = discord.ui.Button(label="Set Welcome Channel", custom_id="ws_set_welcome_channel", style=discord.ButtonStyle.secondary)
        b4 = discord.ui.Button(label="Add/Edit Channel Slot", custom_id="ws_add_channel_slot", style=discord.ButtonStyle.secondary)
        b3.callback = self._set_welcome_channel
        b4.callback = self._add_channel_slot
        self.add_item(b3)
        self.add_item(b4)

        # Row 3
        b5 = discord.ui.Button(label="Remove Channel Slot", custom_id="ws_remove_channel_slot", style=discord.ButtonStyle.secondary)
        b6 = discord.ui.Button(label="Add Image", custom_id="ws_add_image", style=discord.ButtonStyle.secondary)
        b5.callback = self._remove_channel_slot
        b6.callback = self._add_image
        self.add_item(b5)
        self.add_item(b6)

        # Row 4
        b7 = discord.ui.Button(label="Remove Image", custom_id="ws_remove_image", style=discord.ButtonStyle.secondary)
        b8 = discord.ui.Button(label="Preview", custom_id="ws_preview", style=discord.ButtonStyle.success)
        b7.callback = self._remove_image
        b8.callback = self._preview
        self.add_item(b7)
        self.add_item(b8)

        # Row 5
        b9 = discord.ui.Button(label="Toggle Welcome On/Off", custom_id="ws_toggle_welcome", style=discord.ButtonStyle.danger)
        b9.callback = self._toggle_welcome
        self.add_item(b9)

        # Member logs controls
        b10 = discord.ui.Button(label="Set Member Log Channel", custom_id="ws_set_log_channel", style=discord.ButtonStyle.secondary)
        b11 = discord.ui.Button(label="Toggle Leave Logs", custom_id="ws_toggle_leave", style=discord.ButtonStyle.secondary)
        b12 = discord.ui.Button(label="Toggle Kick Logs", custom_id="ws_toggle_kick", style=discord.ButtonStyle.secondary)
        b13 = discord.ui.Button(label="Toggle Ban Logs", custom_id="ws_toggle_ban", style=discord.ButtonStyle.secondary)
        b10.callback = self._set_log_channel
        b11.callback = self._toggle_leave
        b12.callback = self._toggle_kick
        b13.callback = self._toggle_ban
        self.add_item(b10)
        self.add_item(b11)
        self.add_item(b12)
        self.add_item(b13)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_permission(interaction):
            try:
                await interaction.response.send_message("No permission.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    async def _edit_title(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditTitleModal())

    async def _edit_text(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditTextModal())

    async def _set_welcome_channel(self, interaction: discord.Interaction):
        await interaction.response.send_message("Select the welcome channel:", view=WelcomeChannelPickerView(), ephemeral=True)

    async def _add_channel_slot(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddChannelSlotModal())

    async def _remove_channel_slot(self, interaction: discord.Interaction):
        await interaction.response.send_message("Select a slot to remove:", view=RemoveChannelSlotView(), ephemeral=True)

    async def _add_image(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddImageModal())

    async def _remove_image(self, interaction: discord.Interaction):
        await interaction.response.send_message("Select an image to remove:", view=RemoveImageView(), ephemeral=True)

    async def _preview(self, interaction: discord.Interaction):
        cfg = load_config()
        w = cfg.get("welcome", {})
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("No guild context.", ephemeral=True)

        humans = len([m for m in guild.members if not m.bot])

        embed = discord.Embed(
            title=render(w.get("title", ""), user=interaction.user, guild=guild, member_count=humans, channels=w.get("channels", {})),
            description=render(w.get("description", ""), user=interaction.user, guild=guild, member_count=humans, channels=w.get("channels", {})),
            timestamp=datetime.utcnow()
        )

        imgs = w.get("arrival_images", []) or []
        if imgs:
            embed.set_image(url=random.choice(imgs))

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _toggle_welcome(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"]["enabled"] = not bool(cfg["welcome"].get("enabled", True))
        save_config(cfg)
        state = "ON" if cfg["welcome"]["enabled"] else "OFF"
        await interaction.response.send_message(f"Welcome is now {state}.", ephemeral=True)

    async def _set_log_channel(self, interaction: discord.Interaction):
        await interaction.response.send_message("Select the member log channel:", view=MemberLogChannelPickerView(), ephemeral=True)

    async def _toggle_leave(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg.setdefault("member_logs", {})
        cfg["member_logs"]["log_leave"] = not bool(cfg["member_logs"].get("log_leave", True))
        save_config(cfg)
        state = "ON" if cfg["member_logs"]["log_leave"] else "OFF"
        await interaction.response.send_message(f"Leave logs: {state}.", ephemeral=True)

    async def _toggle_kick(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg.setdefault("member_logs", {})
        cfg["member_logs"]["log_kick"] = not bool(cfg["member_logs"].get("log_kick", True))
        save_config(cfg)
        state = "ON" if cfg["member_logs"]["log_kick"] else "OFF"
        await interaction.response.send_message(f"Kick logs: {state}.", ephemeral=True)

    async def _toggle_ban(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg.setdefault("member_logs", {})
        cfg["member_logs"]["log_ban"] = not bool(cfg["member_logs"].get("log_ban", True))
        save_config(cfg)
        state = "ON" if cfg["member_logs"]["log_ban"] else "OFF"
        await interaction.response.send_message(f"Ban logs: {state}.", ephemeral=True)

# ======================================================
# MAIN SYSTEM (join/leave/kick/ban)
# ======================================================
class WelcomeSystem:
    def __init__(self, client: discord.Client):
        self.client = client

    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        cfg = load_config()
        w = cfg.get("welcome", {})

        if not w.get("enabled", True):
            return

        welcome_channel_id = w.get("welcome_channel_id")
        if not welcome_channel_id:
            return

        channel = self.client.get_channel(int(welcome_channel_id))
        if not channel:
            return

        humans = len([m for m in member.guild.members if not m.bot])

        embed = discord.Embed(
            title=render(w.get("title", ""), user=member, guild=member.guild, member_count=humans, channels=w.get("channels", {})),
            description=render(w.get("description", ""), user=member, guild=member.guild, member_count=humans, channels=w.get("channels", {})),
            timestamp=datetime.utcnow()
        )

        imgs = w.get("arrival_images", []) or []
        if imgs:
            embed.set_image(url=random.choice(imgs))

        # Only outside text should be the mention
        await channel.send(content=member.mention, embed=embed)

    async def on_member_remove(self, member: discord.Member):
        cfg = load_config()
        logs = cfg.get("member_logs", {})

        if not logs.get("enabled", True):
            return

        channel_id = logs.get("channel_id")
        if not channel_id:
            return

        channel = self.client.get_channel(int(channel_id))
        if not channel:
            return

        await asyncio.sleep(1.5)

        # Kick check
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target and entry.target.id == member.id:
                if logs.get("log_kick", True):
                    await channel.send(f"{member.name} was kicked from the server by {entry.user}")
                return

        # Otherwise leave
        if logs.get("log_leave", True):
            await channel.send(f"{member.name} left the server")

    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        cfg = load_config()
        logs = cfg.get("member_logs", {})

        if not logs.get("enabled", True):
            return
        if not logs.get("log_ban", True):
            return

        channel_id = logs.get("channel_id")
        if not channel_id:
            return

        channel = self.client.get_channel(int(channel_id))
        if not channel:
            return

        await asyncio.sleep(1.5)

        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target and entry.target.id == user.id:
                await channel.send(f"{user.name} was banned from the server by {entry.user}")
                return

        await channel.send(f"{user.name} was banned from the server")

# ======================================================
# SLASH COMMAND REGISTRATION
# ======================================================
def setup_welcome_commands(tree: app_commands.CommandTree):
    @tree.command(name="setwelcome", description="Open welcome settings")
    async def setwelcome(interaction: discord.Interaction):
        if not has_permission(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        cfg = load_config()
        old_id = cfg.get("welcome", {}).get("control_panel_message_id")

        # delete old panel if it exists
        if old_id:
            try:
                old_msg = await interaction.channel.fetch_message(int(old_id))
                await old_msg.delete()
            except Exception:
                pass

        msg = await interaction.channel.send(
            content=f"Welcome Settings\nEdited by {interaction.user.mention}",
            view=WelcomeSettingsView()
        )

        cfg["welcome"]["control_panel_message_id"] = msg.id
        save_config(cfg)

        await interaction.response.send_message("Opened welcome settings.", ephemeral=True)