# joinleave.py
import discord
from discord.ui import Modal, TextInput
import asyncio
import random
import os
import json
import base64
import requests
from typing import Dict, Any, Optional

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "welcome_config.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Default Config -------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "welcome": {
        "enabled": True,
        "welcome_channel_id": None,
        "title": "Welcome to the server, {user}! 👋🏼",
        "description": "",
        "channels": {},              # slot_name -> channel_id
        "arrival_images": [],        # list[str]
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

def _gh_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

def ensure_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
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

def load_config() -> Dict[str, Any]:
    try:
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            raw = base64.b64decode(r.json()["content"]).decode()
            cfg = json.loads(raw) if raw.strip() else DEFAULT_CONFIG.copy()
            cfg = ensure_config(cfg)
            return cfg
        # create default
        save_config(DEFAULT_CONFIG.copy())
        return ensure_config(DEFAULT_CONFIG.copy())
    except Exception:
        return ensure_config(DEFAULT_CONFIG.copy())

def save_config(cfg: Dict[str, Any]) -> None:
    cfg = ensure_config(cfg)
    try:
        sha = None
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": "Update welcome configuration",
            "content": base64.b64encode(json.dumps(cfg, indent=2).encode()).decode()
        }
        if sha:
            payload["sha"] = sha
        requests.put(_gh_url(), headers=HEADERS, json=payload, timeout=10)
    except Exception:
        pass

def human_member_number(guild: discord.Guild) -> int:
    return len([m for m in guild.members if not m.bot])

def render(text: str, *, user: discord.abc.User, guild: discord.Guild, member_count: int, channels: Dict[str, int]) -> str:
    if not text:
        return ""
    out = (
        text.replace("{user}", getattr(user, "name", ""))
        .replace("{mention}", getattr(user, "mention", ""))
        .replace("{server}", getattr(guild, "name", ""))
        .replace("{member_count}", str(member_count))
    )
    for name, cid in (channels or {}).items():
        out = out.replace(f"{{channel:{name}}}", f"<#{cid}>")
    return out

# ======================================================
# MODALS
# ======================================================

class EditWelcomeTitleModal(Modal):
    def __init__(self):
        cfg = load_config()
        super().__init__(title="Edit Welcome Title")
        self.text = TextInput(label="Title", default=cfg["welcome"]["title"], max_length=256)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"]["title"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("✅ Welcome title updated.")

class EditWelcomeTextModal(Modal):
    def __init__(self):
        cfg = load_config()
        super().__init__(title="Edit Welcome Text")
        self.text = TextInput(label="Text", style=discord.TextStyle.paragraph, default=cfg["welcome"]["description"], max_length=2000)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"]["description"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("✅ Welcome text updated.")

class AddChannelSlotNameModal(Modal):
    def __init__(self):
        super().__init__(title="Add / Edit Channel Slot")
        self.name = TextInput(label="Slot name (e.g. self_roles)", max_length=50)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        slot = self.name.value.strip()
        if not slot:
            return await interaction.response.send_message("❌ Slot name cannot be empty.")
        await interaction.response.send_message(
            f"Select a channel for slot **{slot}**:",
            view=ChannelSlotPickerView(slot)
        )

class AddArrivalImageModal(Modal):
    def __init__(self):
        super().__init__(title="Add Arrival Image")
        self.url = TextInput(label="Image URL", max_length=400)
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg["welcome"]["arrival_images"].append(self.url.value.strip())
        save_config(cfg)
        await interaction.response.send_message("✅ Arrival image added.")

# ======================================================
# CHANNEL PICKERS
# ======================================================

def _cid(v):
    return v.id if hasattr(v, "id") else int(v)

class WelcomeChannelPickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cfg = load_config()
        cid = _cid(interaction.data["values"][0])
        cfg["welcome"]["welcome_channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Welcome channel set to <#{cid}>", view=None)

class BotAddChannelPickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cfg = load_config()
        cid = _cid(interaction.data["values"][0])
        cfg["welcome"]["bot_add"]["channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Bot add channel set to <#{cid}>", view=None)

class LogChannelPickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cfg = load_config()
        cid = _cid(interaction.data["values"][0])
        cfg["member_logs"]["channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Member log channel set to <#{cid}>", view=None)

class ChannelSlotPickerView(discord.ui.View):
    def __init__(self, slot: str):
        super().__init__(timeout=120)
        self.slot = slot
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cfg = load_config()
        cid = _cid(interaction.data["values"][0])
        cfg["welcome"]["channels"][self.slot] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Saved slot **{self.slot}** → <#{cid}>", view=None)

# ======================================================
# RUNTIME SYSTEM
# ======================================================

class WelcomeSystem:
    def __init__(self, client: discord.Client):
        self.client = client

    async def on_member_join(self, member: discord.Member):
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
        now = discord.utils.utcnow().strftime("%H:%M")

        embed = discord.Embed(
            title=render(w["title"], user=member, guild=member.guild, member_count=count, channels=w["channels"]),
            description=render(w["description"], user=member, guild=member.guild, member_count=count, channels=w["channels"])
        )
        embed.set_footer(text=f"You landed as passenger #{count} ✈️ | Today at {now}")

        imgs = w.get("arrival_images") or []
        if imgs:
            embed.set_image(url=random.choice(imgs))

        await channel.send(content=member.mention, embed=embed)

    async def on_bot_join(self, member: discord.Member):
        cfg = load_config()
        b = cfg["welcome"]["bot_add"]
        if not b.get("enabled") or not b.get("channel_id"):
            return

        channel = self.client.get_channel(b["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
            if entry.target and entry.target.id == member.id:
                await channel.send(f"🤖 {entry.user.mention} added a bot ({member.name}) to the server.")
                return

    async def on_member_remove(self, member: discord.Member):
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
                if m.get("log_kick"):
                    await channel.send(f"{member.name} was kicked from the server by {entry.user}")
                return

        if m.get("log_leave"):
            await channel.send(f"{member.name} left the server")

    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        cfg = load_config()
        m = cfg["member_logs"]
        if not m["enabled"] or not m.get("log_ban") or not m["channel_id"]:
            return

        channel = self.client.get_channel(m["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target and entry.target.id == user.id:
                await channel.send(f"{user.name} was banned from the server by {entry.user}")
                return