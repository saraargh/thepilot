import discord
from discord import app_commands
from discord.ui import View, Modal, TextInput
import asyncio
import random
import os
import json
import base64
import requests

# ======================================================
# ALLOWED ROLE IDS
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
        "arrival_images": [],
        "bot_add": {
            "enabled": True,
            "channel_id": None
        }
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
def ensure_config(cfg):
    cfg.setdefault("welcome", {})
    cfg.setdefault("member_logs", {})

    w = cfg["welcome"]
    w.setdefault("enabled", True)
    w.setdefault("welcome_channel_id", None)
    w.setdefault("title", DEFAULT_CONFIG["welcome"]["title"])
    w.setdefault("description", "")
    w.setdefault("channels", {})
    w.setdefault("arrival_images", [])
    w.setdefault("bot_add", {"enabled": True, "channel_id": None})

    m = cfg["member_logs"]
    m.setdefault("enabled", True)
    m.setdefault("channel_id", None)
    m.setdefault("log_leave", True)
    m.setdefault("log_kick", True)
    m.setdefault("log_ban", True)

    return cfg

def load_config():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        cfg = json.loads(base64.b64decode(r.json()["content"]).decode())
        cfg = ensure_config(cfg)
        save_config(cfg)
        return cfg
    save_config(DEFAULT_CONFIG.copy())
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS)
    payload = {
        "message": "Update welcome configuration",
        "content": base64.b64encode(json.dumps(cfg, indent=2).encode()).decode()
    }
    if r.status_code == 200:
        payload["sha"] = r.json()["sha"]
    requests.put(url, headers=HEADERS, json=payload)

# ======================================================
# UTILS
# ======================================================
def has_permission(interaction):
    return any(r.id in ALLOWED_ROLE_IDS for r in interaction.user.roles)

def human_member_number(guild):
    return len([m for m in guild.members if not m.bot])

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

def _cid(v):
    return v.id if hasattr(v, "id") else int(v)

# ======================================================
# MODALS
# ======================================================
class EditTitleModal(Modal):
    def __init__(self):
        cfg = load_config()
        super().__init__(title="Edit Welcome Title")
        self.text = TextInput(label="Title", default=cfg["welcome"]["title"], max_length=256)
        self.add_item(self.text)

    async def on_submit(self, interaction):
        cfg = load_config()
        cfg["welcome"]["title"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("Title updated.")

class EditTextModal(Modal):
    def __init__(self):
        cfg = load_config()
        super().__init__(title="Edit Welcome Text")
        self.text = TextInput(
            label="Text",
            style=discord.TextStyle.paragraph,
            default=cfg["welcome"]["description"],
            max_length=2000
        )
        self.add_item(self.text)

    async def on_submit(self, interaction):
        cfg = load_config()
        cfg["welcome"]["description"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("Text updated.")

class AddImageModal(Modal):
    def __init__(self):
        super().__init__(title="Add Arrival Image")
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
        cid = _cid(interaction.data["values"][0])
        cfg["welcome"]["channels"][self.slot] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"Saved `{self.slot}` → <#{cid}>", view=None)

class WelcomeChannelPicker(View):
    def __init__(self):
        super().__init__(timeout=60)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction):
        cfg = load_config()
        cid = _cid(interaction.data["values"][0])
        cfg["welcome"]["welcome_channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"Welcome channel set to <#{cid}>", view=None)

class BotAddChannelPicker(View):
    def __init__(self):
        super().__init__(timeout=60)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction):
        cfg = load_config()
        cid = _cid(interaction.data["values"][0])
        cfg["welcome"]["bot_add"]["channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"Bot add channel set to <#{cid}>", view=None)

class LogChannelPicker(View):
    def __init__(self):
        super().__init__(timeout=60)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction):
        cfg = load_config()
        cid = _cid(interaction.data["values"][0])
        cfg["member_logs"]["channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"Member log channel set to <#{cid}>", view=None)

# ======================================================
# SETTINGS VIEWS
# ======================================================
class WelcomeSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self._b("Edit Title", self.edit_title)
        self._b("Edit Text", self.edit_text)
        self._b("Set Welcome Channel", self.set_channel)
        self._b("Add/Edit Channel Slot", self.add_slot)
        self._b("Add Image", self.add_image)
        self._b("Toggle Bot Add Logs", self.toggle_bot)
        self._b("Set Bot Add Channel", self.set_bot_channel)
        self._b("Preview", self.preview, discord.ButtonStyle.success)
        self._b("Toggle Welcome On/Off", self.toggle, discord.ButtonStyle.danger)

    def _b(self, label, cb, style=discord.ButtonStyle.secondary):
        btn = discord.ui.Button(label=label, style=style)
        btn.callback = cb
        self.add_item(btn)

    async def interaction_check(self, interaction):
        if not has_permission(interaction):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return False
        return True

    async def edit_title(self, i): await i.response.send_modal(EditTitleModal())
    async def edit_text(self, i): await i.response.send_modal(EditTextModal())
    async def set_channel(self, i): await i.response.send_message("Select welcome channel:", view=WelcomeChannelPicker())
    async def add_slot(self, i): await i.response.send_modal(AddChannelSlotModal())
    async def add_image(self, i): await i.response.send_modal(AddImageModal())
    async def set_bot_channel(self, i): await i.response.send_message("Select bot add channel:", view=BotAddChannelPicker())

    async def toggle(self, i):
        cfg = load_config()
        cfg["welcome"]["enabled"] = not cfg["welcome"]["enabled"]
        save_config(cfg)
        await i.response.send_message(f"Welcome {'enabled' if cfg['welcome']['enabled'] else 'disabled'}.")

    async def toggle_bot(self, i):
        cfg = load_config()
        cfg["welcome"]["bot_add"]["enabled"] = not cfg["welcome"]["bot_add"]["enabled"]
        save_config(cfg)
        await i.response.send_message(f"Bot add logs {'enabled' if cfg['welcome']['bot_add']['enabled'] else 'disabled'}.")

    async def preview(self, i):
        cfg = load_config()
        w = cfg["welcome"]
        count = human_member_number(i.guild)
        now = discord.utils.utcnow().strftime("%H:%M")

        embed = discord.Embed(
            title=render(w["title"], user=i.user, guild=i.guild, member_count=count, channels=w["channels"]),
            description=render(w["description"], user=i.user, guild=i.guild, member_count=count, channels=w["channels"])
        )

        embed.set_footer(text=f"You landed as passenger #{count} ✈️ | Today at {now}")

        if w["arrival_images"]:
            embed.set_image(url=random.choice(w["arrival_images"]))

        await i.response.send_message(embed=embed)

class LeaveSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self._b("Set Member Log Channel", self.set_log)
        self._b("Toggle Leave Logs", self.toggle_leave)
        self._b("Toggle Kick Logs", self.toggle_kick)
        self._b("Toggle Ban Logs", self.toggle_ban)

    def _b(self, label, cb):
        btn = discord.ui.Button(label=label)
        btn.callback = cb
        self.add_item(btn)

    async def interaction_check(self, i):
        if not has_permission(i):
            await i.response.send_message("No permission.", ephemeral=True)
            return False
        return True

    async def set_log(self, i):
        await i.response.send_message("Select log channel:", view=LogChannelPicker())

    async def _toggle(self, i, key, name):
        cfg = load_config()
        cfg["member_logs"][key] = not cfg["member_logs"][key]
        save_config(cfg)
        await i.response.send_message(f"{name} logs {'enabled' if cfg['member_logs'][key] else 'disabled'}.")

    async def toggle_leave(self, i): await self._toggle(i, "log_leave", "Leave")
    async def toggle_kick(self, i): await self._toggle(i, "log_kick", "Kick")
    async def toggle_ban(self, i): await self._toggle(i, "log_ban", "Ban")

# ======================================================
# RUNTIME SYSTEM
# ======================================================
class WelcomeSystem:
    def __init__(self, client):
        self.client = client

    async def on_member_join(self, member):
        if member.bot:
            await self.on_bot_join(member)
            return

        cfg = load_config()
        w = cfg["welcome"]
        if not w["enabled"] or not w["welcome_channel_id"]:
            return

        channel = self.client.get_channel(w["welcome_channel_id"])
        if not channel:
            return

        count = human_member_number(member.guild)
        time = discord.utils.utcnow().strftime("%H:%M")

        embed = discord.Embed(
            title=render(w["title"], user=member, guild=member.guild, member_count=count, channels=w["channels"]),
            description=render(w["description"], user=member, guild=member.guild, member_count=count, channels=w["channels"])
        )

        embed.set_footer(text=f"You landed as passenger #{count} ✈️ | Today at {time}")

        if w["arrival_images"]:
            embed.set_image(url=random.choice(w["arrival_images"]))

        await channel.send(content=member.mention, embed=embed)

    async def on_bot_join(self, member):
        cfg = load_config()
        b = cfg["welcome"]["bot_add"]
        if not b["enabled"] or not b["channel_id"]:
            return

        channel = self.client.get_channel(b["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
            if entry.target and entry.target.id == member.id:
                await channel.send(f"🤖 {entry.user.mention} added a bot ({member.name}) to the server.")
                return

    async def on_member_remove(self, member):
        cfg = load_config()
        m = cfg["member_logs"]
        if not m["enabled"] or not m["channel_id"]:
            return

        channel = self.client.get_channel(m["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target and entry.target.id == member.id:
                if m["log_kick"]:
                    await channel.send(f"{member.name} was kicked from the server by {entry.user}")
                return

        if m["log_leave"]:
            await channel.send(f"{member.name} left the server")

    async def on_member_ban(self, guild, user):
        cfg = load_config()
        m = cfg["member_logs"]
        if not m["enabled"] or not m["log_ban"] or not m["channel_id"]:
            return

        channel = self.client.get_channel(m["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target and entry.target.id == user.id:
                await channel.send(f"{user.name} was banned from the server by {entry.user}")
                return

# ======================================================
# SLASH COMMANDS
# ======================================================
def setup_welcome_commands(tree: app_commands.CommandTree):
    @tree.command(name="welcomesettings", description="Manage welcome settings")
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