# adminsettings.py
from __future__ import annotations

import io
import random
from typing import List, Dict, Any, Optional

import discord
from discord import app_commands
from datetime import date

from permissions import (
    has_global_access,
    has_app_access,
    load_settings,
    save_settings,
)

from joinleave import (
    load_config,
    save_config,
    render,
    human_member_number,
)

# --- Birthdays (GitHub-backed) ---
# Uses your existing birthdays.json storage via birthdays.py
try:
    from birthdays import load_data as bday_load_data, save_data as bday_save_data, DEFAULT_DATA as BDAY_DEFAULT_DATA
    from birthdays import _send_announcement_like as bday_send_announcement_like  # for previews
except Exception:
    bday_load_data = None
    bday_save_data = None
    BDAY_DEFAULT_DATA = None
    bday_send_announcement_like = None


# ======================================================
# SCOPES (roles panel)
# ======================================================

SCOPES = {
    "global": "🔐 Global Admin Roles",
    "mute": "🔇 Mute",
    "warnings": "⚠️ Warnings",
    "poo_goat": "💩🐐 Poo / Goat",
    "welcome_leave": "👋📄🚀 Welcome / Leave / Boost",
    "roles": "🧩 Roles / Self-Roles",
    "birthdays": "🎂 Birthdays",
}

# ======================================================
# Helpers
# ======================================================

def _cid(v) -> int:
    return v.id if hasattr(v, "id") else int(v)

def format_roles(guild: discord.Guild, role_ids: List[int]) -> str:
    mentions = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            mentions.append(role.mention)
    return "\n".join(mentions) if mentions else "*None*"


def build_role_pages(guild: discord.Guild, settings: Dict[str, Any]) -> List[discord.Embed]:
    sections = [
        ("🔐 Global Admin", settings.get("global_allowed_roles", [])),
        ("🔇 Mute", settings.get("apps", {}).get("mute", {}).get("allowed_roles", [])),
        ("⚠️ Warnings", settings.get("apps", {}).get("warnings", {}).get("allowed_roles", [])),
        ("💩🐐 Poo / Goat", settings.get("apps", {}).get("poo_goat", {}).get("allowed_roles", [])),
        ("👋📄🚀 Welcome / Leave / Boost", settings.get("apps", {}).get("welcome_leave", {}).get("allowed_roles", [])),
        ("🧩 Roles / Self-Roles", settings.get("apps", {}).get("roles", {}).get("allowed_roles", [])),
        ("🎂 Birthdays", settings.get("apps", {}).get("birthdays", {}).get("allowed_roles", [])),
    ]

    chunk = 2
    pages: List[discord.Embed] = []
    for i in range(0, len(sections), chunk):
        embed = discord.Embed(title="⚙️ Pilot Role Permissions", color=discord.Color.blurple())
        for name, ids in sections[i:i + chunk]:
            embed.add_field(name=name, value=format_roles(guild, ids), inline=False)
        embed.set_footer(text="Server owner & override role always have access")
        pages.append(embed)
    return pages


def welcome_status_text(cfg: Dict[str, Any]) -> str:
    w = cfg.get("welcome", {}) or {}
    ch = f"<#{w.get('welcome_channel_id')}>" if w.get("welcome_channel_id") else "*Not set*"
    return (
        f"**Enabled:** `{w.get('enabled', False)}`\n"
        f"**Channel:** {ch}\n"
        f"**Bot Add Logs:** `{(w.get('bot_add', {}) or {}).get('enabled', False)}`"
    )


def logs_status_text(cfg: Dict[str, Any]) -> str:
    m = cfg.get("member_logs", {}) or {}
    ch = f"<#{m.get('channel_id')}>" if m.get("channel_id") else "*Not set*"
    return (
        f"**Enabled:** `{m.get('enabled', False)}`\n"
        f"**Channel:** {ch}\n"
        f"**Leave:** `{m.get('log_leave', False)}` | **Kick:** `{m.get('log_kick', False)}` | **Ban:** `{m.get('log_ban', False)}`"
    )


def boost_status_text(cfg: Dict[str, Any]) -> str:
    b = cfg.get("boost", {}) or {}
    ch = f"<#{b.get('channel_id')}>" if b.get("channel_id") else "*Not set*"
    return f"**Enabled:** `{b.get('enabled', False)}`\n**Channel:** {ch}"


def birthday_status_text(data: Optional[Dict[str, Any]]) -> str:
    if not data or "settings" not in data:
        return "**Enabled:** `False`\n**Channel:** *Not set*\n**Role:** *Not set*"

    s = data.get("settings", {}) or {}
    ch = f"<#{s.get('channel_id')}>" if s.get("channel_id") else "*Not set*"
    role = f"<@&{s.get('birthday_role_id')}>" if s.get("birthday_role_id") else "*Not set*"
    t = f"{int(s.get('post_hour', 15)):02d}:{int(s.get('post_minute', 0)):02d}"
    imgs = len(s.get("image_urls", []) or [])
    return (
        f"**Enabled:** `{bool(s.get('enabled', True))}`\n"
        f"**Announce:** `{bool(s.get('announce', True))}`\n"
        f"**Channel:** {ch}\n"
        f"**Role:** {role}\n"
        f"**Time:** `{t}`\n"
        f"**Images:** `{imgs}`"
    )


def _ensure_bday_data_shape(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure birthdays.json has required keys; merges defaults without deleting existing."""
    if not BDAY_DEFAULT_DATA:
        return data

    # shallow + nested merge for known top-level keys
    out = data or {}
    for k, v in BDAY_DEFAULT_DATA.items():
        if k not in out:
            out[k] = v
    out.setdefault("settings", {})
    out.setdefault("birthdays", {})
    out.setdefault("state", {"announced_keys": []})

    # merge settings defaults
    def_s = (BDAY_DEFAULT_DATA.get("settings") or {}) if isinstance(BDAY_DEFAULT_DATA, dict) else {}
    s = out["settings"]
    for k, v in def_s.items():
        if k not in s:
            s[k] = v
    s.setdefault("image_urls", [])
    return out


# ======================================================
# Interaction-safe helpers (public)
# ======================================================

async def _no_perm(interaction: discord.Interaction, msg: str = "❌ You do not have permission."):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg)
        else:
            await interaction.response.send_message(msg)
    except Exception:
        if interaction.channel:
            await interaction.channel.send(msg)


async def _safe_defer(interaction: discord.Interaction):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=False)
    except Exception:
        pass


async def _safe_edit_panel_message(interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View):
    try:
        if interaction.message:
            await interaction.message.edit(content=None, embed=embed, view=view)
        elif interaction.channel:
            await interaction.channel.send(embed=embed, view=view)
    except Exception:
        if interaction.channel:
            await interaction.channel.send("❌ Panel update failed.")


# ======================================================
# Panel states
# ======================================================

class PanelState:
    ROOT = "root"
    ROLES = "roles"
    WELCOME = "welcome"
    LEAVE = "leave"
    BOOST = "boost"
    BIRTHDAYS = "birthdays"


# ======================================================
# Shared image paging + removal picker (welcome/boost/birthdays)
# ======================================================

def image_embed(title: str, urls: List[str], index: int) -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.blurple())
    if urls:
        embed.set_image(url=urls[index])
        embed.set_footer(text=f"Image {index + 1} / {len(urls)}")
    else:
        embed.description = "No images."
    return embed


class ImagePagerView(discord.ui.View):
    def __init__(self, title: str, urls: List[str], index: int = 0):
        super().__init__(timeout=300)
        self.title = title
        self.urls = urls
        self.index = index
        self._sync()

    def _sync(self):
        self.prev.disabled = self.index <= 0
        self.next.disabled = self.index >= len(self.urls) - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        await interaction.response.edit_message(
            embed=image_embed(self.title, self.urls, self.index),
            view=ImagePagerView(self.title, self.urls, self.index),
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        await interaction.response.edit_message(
            embed=image_embed(self.title, self.urls, self.index),
            view=ImagePagerView(self.title, self.urls, self.index),
        )


class RemoveImagePicker(discord.ui.View):
    def __init__(self, kind: str, urls: List[str]):
        super().__init__(timeout=180)
        self.add_item(RemoveImageSelect(kind, urls))


class RemoveImageSelect(discord.ui.Select):
    def __init__(self, kind: str, urls: List[str]):
        self.kind = kind
        self.urls = urls
        opts = [discord.SelectOption(label=f"Image {i+1}", value=str(i)) for i in range(min(25, len(urls)))]
        super().__init__(placeholder="Pick an image…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])

        if self.kind == "welcome":
            cfg = load_config()
            arr = (cfg.get("welcome", {}) or {}).get("arrival_images") or []
            if 0 <= idx < len(arr):
                arr.pop(idx)
                cfg["welcome"]["arrival_images"] = arr
                save_config(cfg)
                return await interaction.response.send_message("✅ Removed that arrival image.")
            return await interaction.response.send_message("❌ Couldn’t remove that image.")

        if self.kind == "boost":
            cfg = load_config()
            b = cfg.setdefault("boost", {})
            imgs = b.get("images") or []
            if 0 <= idx < len(imgs):
                imgs.pop(idx)
                b["images"] = imgs
                save_config(cfg)
                return await interaction.response.send_message("✅ Removed that boost image.")
            return await interaction.response.send_message("❌ Couldn’t remove that image.")

        if self.kind == "birthdays":
            if not bday_load_data or not bday_save_data:
                return await interaction.response.send_message("❌ Birthdays module not available.")
            data, sha = await bday_load_data()
            data = _ensure_bday_data_shape(data)
            imgs = (data.get("settings", {}) or {}).get("image_urls") or []
            if 0 <= idx < len(imgs):
                imgs.pop(idx)
                data["settings"]["image_urls"] = imgs
                await bday_save_data(data, sha)
                return await interaction.response.send_message("✅ Removed that birthday image.")
            return await interaction.response.send_message("❌ Couldn’t remove that image.")

        await interaction.response.send_message("❌ Unknown image type.")


# ======================================================
# LOCAL CHANNEL PICKERS (welcome/leave)
# ======================================================

class WelcomeChannelPickerViewLocal(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cid = _cid(interaction.data["values"][0])
        cfg = load_config()
        cfg.setdefault("welcome", {})
        cfg["welcome"]["welcome_channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Welcome channel set to <#{cid}>", view=None)


class BotAddChannelPickerViewLocal(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cid = _cid(interaction.data["values"][0])
        cfg = load_config()
        cfg.setdefault("welcome", {})
        cfg["welcome"].setdefault("bot_add", {"enabled": True, "channel_id": None})
        cfg["welcome"]["bot_add"]["channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Bot add channel set to <#{cid}>", view=None)


class LogChannelPickerViewLocal(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cid = _cid(interaction.data["values"][0])
        cfg = load_config()
        cfg.setdefault("member_logs", {})
        cfg["member_logs"]["channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Member log channel set to <#{cid}>", view=None)


class ChannelSlotPickerViewLocal(discord.ui.View):
    def __init__(self, slot: str):
        super().__init__(timeout=120)
        self.slot = slot
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cid = _cid(interaction.data["values"][0])
        cfg = load_config()
        cfg.setdefault("welcome", {})
        cfg["welcome"].setdefault("channels", {})
        cfg["welcome"]["channels"][self.slot] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Saved slot **{self.slot}** → <#{cid}>", view=None)


# ======================================================
# BOOST MANAGEMENT (unchanged)
# ======================================================

def _ensure_boost(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg.setdefault("boost", {})
    b = cfg["boost"]
    b.setdefault("enabled", True)
    b.setdefault("channel_id", None)
    b.setdefault("images", [])
    b.setdefault("title", "")
    b.setdefault("messages", {})
    b["messages"].setdefault("single", "💎 {user} just boosted the server! 💎")
    b["messages"].setdefault("double", "🔥 {user} just used **both boosts**! 🔥")
    b["messages"].setdefault("tier", "🚀 **NEW BOOST TIER UNLOCKED!** 🚀\nThanks to {user}!")
    return cfg


class BoostChannelPickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cid = _cid(interaction.data["values"][0])
        cfg = _ensure_boost(load_config())
        cfg["boost"]["channel_id"] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Boost channel set to <#{cid}>", view=None)


class EditBoostTitleModal(discord.ui.Modal, title="Edit Boost Title"):
    text = discord.ui.TextInput(label="Title", max_length=256)

    def __init__(self, default: str):
        super().__init__()
        self.text.default = default

    async def on_submit(self, interaction: discord.Interaction):
        cfg = _ensure_boost(load_config())
        cfg["boost"]["title"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("✅ Boost title updated.")


class EditBoostMessageModal(discord.ui.Modal):
    def __init__(self, *, modal_title: str, key: str, default: str):
        super().__init__(title=modal_title)
        self.key = key
        self.text = discord.ui.TextInput(
            label="Text",
            style=discord.TextStyle.paragraph,
            default=default,
            max_length=2000
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = _ensure_boost(load_config())
        cfg["boost"]["messages"][self.key] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("✅ Boost text updated.")


class AddBoostImageModal(discord.ui.Modal, title="Add Boost Image"):
    url = discord.ui.TextInput(label="Image URL", max_length=400)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = _ensure_boost(load_config())
        cfg["boost"]["images"].append(self.url.value.strip())
        save_config(cfg)
        await interaction.response.send_message("✅ Boost image added.")


class BoostRemoveImageMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(BoostRemoveImageSelect())


class BoostRemoveImageSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Boost images…",
            options=[
                discord.SelectOption(label="👀 View images", value="view"),
                discord.SelectOption(label="🗑️ Remove an image", value="remove"),
            ],
            min_values=1, max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = _ensure_boost(load_config())
        imgs = cfg["boost"].get("images") or []

        if self.values[0] == "view":
            if not imgs:
                return await interaction.response.send_message("No boost images.")
            return await interaction.response.send_message(
                embed=image_embed("🚀 Boost Images", imgs, 0),
                view=ImagePagerView("🚀 Boost Images", imgs, 0)
            )

        if not imgs:
            return await interaction.response.send_message("No boost images to remove.")
        await interaction.response.send_message("Pick an image to remove:", view=RemoveImagePicker("boost", imgs))


class BoostActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Boost action…",
            options=[
                discord.SelectOption(label="🔁 Toggle Boost On/Off", value="toggle"),
                discord.SelectOption(label="📍 Set Boost Channel", value="set_channel"),
                discord.SelectOption(label="✏️ Edit Title", value="edit_title"),
                discord.SelectOption(label="📝 Edit Boost Text", value="edit_single"),
                discord.SelectOption(label="💎 Edit Double Boost Text", value="edit_double"),
                discord.SelectOption(label="🏆 Edit Tier Unlock Text", value="edit_tier"),
                discord.SelectOption(label="🖼️ Add Boost Image", value="add_img"),
                discord.SelectOption(label="🗑️ Remove Boost Image", value="rm_img"),
                discord.SelectOption(label="🚀 Preview Boost", value="preview"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave/Boost settings.")

        choice = self.values[0]

        if choice == "set_channel":
            return await interaction.response.send_message("Select the boost channel:", view=BoostChannelPickerView())

        if choice == "edit_title":
            cfg = _ensure_boost(load_config())
            return await interaction.response.send_modal(EditBoostTitleModal(cfg["boost"].get("title", "")))

        if choice == "edit_single":
            cfg = _ensure_boost(load_config())
            return await interaction.response.send_modal(
                EditBoostMessageModal(
                    modal_title="Edit Boost Text",
                    key="single",
                    default=cfg["boost"]["messages"].get("single", "")
                )
            )

        if choice == "edit_double":
            cfg = _ensure_boost(load_config())
            return await interaction.response.send_modal(
                EditBoostMessageModal(
                    modal_title="Edit Double Boost Text",
                    key="double",
                    default=cfg["boost"]["messages"].get("double", "")
                )
            )

        if choice == "edit_tier":
            cfg = _ensure_boost(load_config())
            return await interaction.response.send_modal(
                EditBoostMessageModal(
                    modal_title="Edit Tier Unlock Text",
                    key="tier",
                    default=cfg["boost"]["messages"].get("tier", "")
                )
            )

        if choice == "add_img":
            return await interaction.response.send_modal(AddBoostImageModal())

        await _safe_defer(interaction)
        cfg = _ensure_boost(load_config())
        b = cfg["boost"]

        if choice == "toggle":
            b["enabled"] = not b.get("enabled", True)
            save_config(cfg)

        elif choice == "rm_img":
            imgs = b.get("images") or []
            if not imgs:
                if interaction.channel:
                    await interaction.channel.send("No boost images to remove.")
            else:
                if interaction.channel:
                    await interaction.channel.send("Choose:", view=BoostRemoveImageMenu())

        elif choice == "preview":
            await send_boost_preview(interaction)
            return

        cfg2 = load_config()
        embed = discord.Embed(title="🚀 Boost Settings", description=boost_status_text(cfg2), color=discord.Color.blurple())
        await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.BOOST))


async def send_boost_preview(interaction: discord.Interaction):
    cfg = _ensure_boost(load_config())
    b = cfg["boost"]

    boosts_total = interaction.guild.premium_subscription_count or 0
    now = discord.utils.utcnow().strftime("%H:%M")

    title = render(b.get("title", ""), user=interaction.user, guild=interaction.guild, member_count=boosts_total, channels={})
    desc = render(b["messages"].get("single", ""), user=interaction.user, guild=interaction.guild, member_count=boosts_total, channels={})

    embed = discord.Embed(title=title or None, description=desc, color=discord.Color.blurple())
    embed.set_footer(text=f"this server has {boosts_total} total boosts! | Today at {now}")

    imgs = b.get("images") or []
    if imgs:
        embed.set_image(url=random.choice(imgs))

    if interaction.channel:
        await interaction.channel.send(embed=embed)


# ======================================================
# BIRTHDAYS MANAGEMENT (GitHub-backed, select+modals)
# ======================================================

class BirthdayChannelPickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await _no_perm(interaction, "❌ You don’t have permission for Birthdays settings.")

        if not bday_load_data or not bday_save_data:
            return await interaction.response.edit_message(content="❌ Birthdays module not available.", view=None)

        cid = _cid(interaction.data["values"][0])
        data, sha = await bday_load_data()
        data = _ensure_bday_data_shape(data)
        data["settings"]["channel_id"] = cid
        await bday_save_data(data, sha)
        await interaction.response.edit_message(content=f"✅ Birthday channel set to <#{cid}>", view=None)


class BirthdayRolePickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        sel = discord.ui.RoleSelect(min_values=1, max_values=1)
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await _no_perm(interaction, "❌ You don’t have permission for Birthdays settings.")

        if not bday_load_data or not bday_save_data:
            return await interaction.response.edit_message(content="❌ Birthdays module not available.", view=None)

        rid = _cid(interaction.data["values"][0])
        data, sha = await bday_load_data()
        data = _ensure_bday_data_shape(data)
        data["settings"]["birthday_role_id"] = rid
        await bday_save_data(data, sha)
        await interaction.response.edit_message(content=f"✅ Birthday role set to <@&{rid}>", view=None)


class EditBirthdayTimeModal(discord.ui.Modal, title="Edit Birthday Announcement Time"):
    hour = discord.ui.TextInput(label="Hour (0-23)", placeholder="15", min_length=1, max_length=2)
    minute = discord.ui.TextInput(label="Minute (0-59)", placeholder="00", min_length=1, max_length=2)

    def __init__(self, default_hour: int, default_minute: int):
        super().__init__()
        self.hour.default = str(default_hour)
        self.minute.default = str(default_minute)

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await _no_perm(interaction, "❌ You don’t have permission for Birthdays settings.")

        if not bday_load_data or not bday_save_data:
            return await interaction.response.send_message("❌ Birthdays module not available.")

        try:
            h = int(self.hour.value)
            m = int(self.minute.value)
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError()

            data, sha = await bday_load_data()
            data = _ensure_bday_data_shape(data)
            data["settings"]["post_hour"] = h
            data["settings"]["post_minute"] = m
            await bday_save_data(data, sha)
            await interaction.response.send_message(f"✅ Birthday time set to **{h:02d}:{m:02d}**.")
        except Exception:
            await interaction.response.send_message("❌ Invalid time.")


class EditBirthdayCardModal(discord.ui.Modal, title="Edit Birthday Card Text"):
    header = discord.ui.TextInput(label="Title", placeholder="🎂 Birthday Celebration!", max_length=256)
    single = discord.ui.TextInput(label="Single Message", style=discord.TextStyle.paragraph, max_length=2000)
    multi = discord.ui.TextInput(label="Multiple Message", style=discord.TextStyle.paragraph, max_length=2000, required=False)

    def __init__(self, header_default: str, single_default: str, multi_default: str):
        super().__init__()
        self.header.default = header_default or "🎂 Birthday Celebration!"
        self.single.default = single_default or "Happy Birthday {username}! 🎂"
        self.multi.default = multi_default or "We have {count} birthdays today! Happy Birthday to {usernames}! 🎂🎉"

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await _no_perm(interaction, "❌ You don’t have permission for Birthdays settings.")

        if not bday_load_data or not bday_save_data:
            return await interaction.response.send_message("❌ Birthdays module not available.")

        data, sha = await bday_load_data()
        data = _ensure_bday_data_shape(data)
        s = data["settings"]
        s["message_header"] = str(self.header.value)
        s["message_single"] = str(self.single.value)
        s["message_multiple"] = str(self.multi.value) or str(self.single.value)
        await bday_save_data(data, sha)
        await interaction.response.send_message("✅ Birthday card text updated.")


class AddBirthdayImageModal(discord.ui.Modal, title="Add Birthday Image"):
    url = discord.ui.TextInput(label="Image URL", max_length=400)

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await _no_perm(interaction, "❌ You don’t have permission for Birthdays settings.")

        if not bday_load_data or not bday_save_data:
            return await interaction.response.send_message("❌ Birthdays module not available.")

        data, sha = await bday_load_data()
        data = _ensure_bday_data_shape(data)
        data["settings"].setdefault("image_urls", [])
        data["settings"]["image_urls"].append(self.url.value.strip())
        await bday_save_data(data, sha)
        await interaction.response.send_message("✅ Birthday image added.")


class BirthdayActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Birthdays action…",
            options=[
                discord.SelectOption(label="🔁 Toggle Birthdays On/Off", value="toggle"),
                discord.SelectOption(label="📣 Toggle Announcements On/Off", value="toggle_announce"),
                discord.SelectOption(label="📍 Set Birthday Channel", value="set_channel"),
                discord.SelectOption(label="🏷️ Set Birthday Role", value="set_role"),
                discord.SelectOption(label="🕒 Edit Post Time", value="edit_time"),
                discord.SelectOption(label="📝 Edit Card Text", value="edit_card"),
                discord.SelectOption(label="🖼️ Add Image", value="add_img"),
                discord.SelectOption(label="👀 View Images", value="view_imgs"),
                discord.SelectOption(label="🗑️ Remove Image", value="rm_img"),
                discord.SelectOption(label="📂 Export TXT", value="export"),
                discord.SelectOption(label="✨ Preview Single", value="preview_single"),
                discord.SelectOption(label="✨ Preview Multi", value="preview_multi"),
                discord.SelectOption(label="♻️ Reset Birthday Settings", value="reset_settings"),
            ],
            min_values=1, max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await _no_perm(interaction, "❌ You don’t have permission for Birthdays settings.")

        if not bday_load_data or not bday_save_data:
            return await interaction.response.send_message("❌ Birthdays module not available.", ephemeral=False)

        choice = self.values[0]

        # Modal / picker actions (first-response)
        if choice == "set_channel":
            return await interaction.response.send_message("Select the birthday channel:", view=BirthdayChannelPickerView())

        if choice == "set_role":
            return await interaction.response.send_message("Select the birthday role:", view=BirthdayRolePickerView())

        # Load data once for most actions
        data, sha = await bday_load_data()
        data = _ensure_bday_data_shape(data)
        s = data.get("settings", {}) or {}

        if choice == "edit_time":
            return await interaction.response.send_modal(
                EditBirthdayTimeModal(int(s.get("post_hour", 15)), int(s.get("post_minute", 0)))
            )

        if choice == "edit_card":
            return await interaction.response.send_modal(
                EditBirthdayCardModal(
                    s.get("message_header", ""),
                    s.get("message_single", ""),
                    s.get("message_multiple", ""),
                )
            )

        if choice == "add_img":
            return await interaction.response.send_modal(AddBirthdayImageModal())

        await _safe_defer(interaction)

        if choice == "toggle":
            s["enabled"] = not bool(s.get("enabled", True))
            data["settings"] = s
            await bday_save_data(data, sha)

        elif choice == "toggle_announce":
            s["announce"] = not bool(s.get("announce", True))
            data["settings"] = s
            await bday_save_data(data, sha)

        elif choice == "view_imgs":
            imgs = s.get("image_urls", []) or []
            if not imgs:
                if interaction.channel:
                    await interaction.channel.send("No birthday images.")
            else:
                if interaction.channel:
                    await interaction.channel.send(
                        embed=image_embed("🎂 Birthday Images", imgs, 0),
                        view=ImagePagerView("🎂 Birthday Images", imgs, 0)
                    )
            # panel refresh below

        elif choice == "rm_img":
            imgs = s.get("image_urls", []) or []
            if not imgs:
                if interaction.channel:
                    await interaction.channel.send("No birthday images to remove.")
            else:
                if interaction.channel:
                    await interaction.channel.send("Pick an image to remove:", view=RemoveImagePicker("birthdays", imgs))

        elif choice == "export":
            bdays = data.get("birthdays", {}) or {}
            txt = "USER ID | BIRTHDAY | TIMEZONE\n" + "-" * 35 + "\n"
            for uid, rec in bdays.items():
                try:
                    txt += f"{uid} | {rec['day']}/{rec['month']} | {rec.get('timezone','Europe/London')}\n"
                except Exception:
                    txt += f"{uid} | (invalid)\n"
            f = discord.File(io.BytesIO(txt.encode("utf-8")), filename="birthdays.txt")
            if interaction.channel:
                await interaction.channel.send(f"📂 {interaction.user.mention} exported birthday data.", file=f)

        elif choice == "preview_single":
            # Same preview behaviour as your birthdays.py panel used (uses _send_announcement_like)
            cid = s.get("channel_id")
            if not cid:
                if interaction.channel:
                    await interaction.channel.send("❌ Set a birthday channel first.")
            else:
                ch = interaction.client.get_channel(int(cid))
                if ch and bday_send_announcement_like:
                    await bday_send_announcement_like(
                        channel=ch,
                        settings=s,
                        members=[interaction.user],
                        local_date=date.today(),
                        tz_label="Preview",
                        test_mode=True
                    )
                if interaction.channel:
                    await interaction.channel.send(f"✨ {interaction.user.mention} previewed single.")

        elif choice == "preview_multi":
            cid = s.get("channel_id")
            if not cid:
                if interaction.channel:
                    await interaction.channel.send("❌ Set a birthday channel first.")
            else:
                ch = interaction.client.get_channel(int(cid))
                bot_member = interaction.guild.me if interaction.guild else None
                members = [interaction.user] + ([bot_member] if bot_member else [])
                if ch and bday_send_announcement_like:
                    await bday_send_announcement_like(
                        channel=ch,
                        settings=s,
                        members=members,
                        local_date=date.today(),
                        tz_label="Preview",
                        test_mode=True,
                        force_multiple=True
                    )
                if interaction.channel:
                    await interaction.channel.send(f"✨ {interaction.user.mention} previewed multi.")

        elif choice == "reset_settings":
            # Reset only settings; keep birthdays + state
            if BDAY_DEFAULT_DATA and isinstance(BDAY_DEFAULT_DATA, dict):
                keep_birthdays = data.get("birthdays", {}) or {}
                keep_state = data.get("state", {}) or {"announced_keys": []}
                data["settings"] = (BDAY_DEFAULT_DATA.get("settings") or {}).copy()
                data["birthdays"] = keep_birthdays
                data["state"] = keep_state
                data = _ensure_bday_data_shape(data)
                await bday_save_data(data, sha)
                if interaction.channel:
                    await interaction.channel.send("♻️ Reset birthday settings to defaults (kept birthdays).")

        # Refresh panel
        data2, _ = await bday_load_data()
        embed = discord.Embed(title="🎂 Birthday Settings", description=birthday_status_text(data2), color=discord.Color.blurple())
        await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.BIRTHDAYS))


# ======================================================
# MAIN PANEL VIEW
# ======================================================

class PilotPanelView(discord.ui.View):
    def __init__(self, state: str = PanelState.ROOT):
        super().__init__(timeout=600)
        self.state = state
        self.build()

    def build(self):
        self.clear_items()
        self.add_item(PanelNavSelect(current=self.state))

        if self.state == PanelState.ROLES:
            self.add_item(RoleScopeSelect())
        elif self.state == PanelState.WELCOME:
            self.add_item(WelcomeActionSelect())
        elif self.state == PanelState.LEAVE:
            self.add_item(LeaveActionSelect())
        elif self.state == PanelState.BOOST:
            self.add_item(BoostActionSelect())
        elif self.state == PanelState.BIRTHDAYS:
            self.add_item(BirthdayActionSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await _no_perm(interaction)
            return False
        return True


class PanelNavSelect(discord.ui.Select):
    def __init__(self, current: str):
        opts = [
            discord.SelectOption(label="⚙️ Home", value=PanelState.ROOT),
            discord.SelectOption(label="🛂 Roles", value=PanelState.ROLES),
            discord.SelectOption(label="👋 Welcome", value=PanelState.WELCOME),
            discord.SelectOption(label="📄 Leave / Logs", value=PanelState.LEAVE),
            discord.SelectOption(label="🚀 Boost", value=PanelState.BOOST),
            discord.SelectOption(label="🎂 Birthdays", value=PanelState.BIRTHDAYS),
        ]
        super().__init__(placeholder="Navigate panel…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        target = self.values[0]
        await _safe_defer(interaction)

        cfg = load_config()

        if target == PanelState.ROOT:
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
            embed.add_field(name="🚀 Boost", value=boost_status_text(cfg), inline=False)

            # birthdays status from GitHub
            btxt = "*Birthdays module not available*"
            if bday_load_data:
                try:
                    bdata, _ = await bday_load_data()
                    btxt = birthday_status_text(bdata)
                except Exception:
                    btxt = "*Couldn’t load birthdays.json*"
            embed.add_field(name="🎂 Birthdays", value=btxt, inline=False)

            embed.add_field(name="🛂 Roles", value="Manage access inside **🛂 Roles**.", inline=False)
            return await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.ROOT))

        if target == PanelState.ROLES:
            embed = discord.Embed(
                title="🛂 Role Permissions",
                description="Pick a scope to manage roles, or view the overview.",
                color=discord.Color.blurple()
            )
        elif target == PanelState.WELCOME:
            embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status_text(cfg), color=discord.Color.blurple())
        elif target == PanelState.LEAVE:
            embed = discord.Embed(title="📄 Leave / Logs Settings", description=logs_status_text(cfg), color=discord.Color.blurple())
        elif target == PanelState.BOOST:
            embed = discord.Embed(title="🚀 Boost Settings", description=boost_status_text(cfg), color=discord.Color.blurple())
        else:
            btxt = "*Birthdays module not available*"
            if bday_load_data:
                try:
                    bdata, _ = await bday_load_data()
                    btxt = birthday_status_text(bdata)
                except Exception:
                    btxt = "*Couldn’t load birthdays.json*"
            embed = discord.Embed(title="🎂 Birthday Settings", description=btxt, color=discord.Color.blurple())

        await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=target))


# ======================================================
# ROLES MANAGEMENT (unchanged)
# ======================================================

class RolesOverviewView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed], index: int = 0):
        super().__init__(timeout=300)
        self.pages = pages
        self.index = index
        self._sync_disabled()

    def _sync_disabled(self):
        self.prev.disabled = self.index <= 0
        self.next.disabled = self.index >= len(self.pages) - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        v = RolesOverviewView(self.pages, self.index)
        await interaction.response.edit_message(embed=self.pages[self.index], view=v)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        v = RolesOverviewView(self.pages, self.index)
        await interaction.response.edit_message(embed=self.pages[self.index], view=v)

    @discord.ui.button(label="↩ Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🛂 Role Permissions",
            description="Pick a scope to manage roles, or view the overview.",
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=PilotPanelView(state=PanelState.ROLES))


class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label="👀 View Roles Overview", value="__overview__")]
        options += [discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()]
        super().__init__(placeholder="Choose a role scope…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        choice = self.values[0]

        if choice == "__overview__":
            await _safe_defer(interaction)
            settings = load_settings()
            pages = build_role_pages(interaction.guild, settings)
            if not pages:
                return await _safe_edit_panel_message(
                    interaction,
                    embed=discord.Embed(title="🛂 Role Permissions", description="No role permissions configured.", color=discord.Color.blurple()),
                    view=PilotPanelView(state=PanelState.ROLES)
                )

            return await _safe_edit_panel_message(
                interaction,
                embed=pages[0],
                view=RolesOverviewView(pages, 0)
            )

        scope = choice
        embed = discord.Embed(
            title=f"🛂 Editing: {SCOPES[scope]}",
            description="Choose add/remove/show.",
            color=discord.Color.blurple()
        )
        view = PilotPanelView(state=PanelState.ROLES)
        view.add_item(RoleActionSelect(scope))
        await interaction.response.edit_message(embed=embed, view=view)


class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Choose add/remove/show…",
            options=[
                discord.SelectOption(label="➕ Add roles", value="add"),
                discord.SelectOption(label="➖ Remove roles", value="remove"),
                discord.SelectOption(label="👀 Show current roles", value="show"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        action = self.values[0]
        settings = load_settings()

        if action == "show":
            ids = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
            embed = discord.Embed(
                title=f"👀 Current roles — {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids),
                color=discord.Color.blurple()
            )
            view = PilotPanelView(state=PanelState.ROLES)
            view.add_item(RoleActionSelect(self.scope))
            return await interaction.response.edit_message(embed=embed, view=view)

        picker = discord.ui.View(timeout=180)
        if action == "add":
            picker.add_item(AddRolesSelect(self.scope))
            await interaction.response.send_message("Select roles to **ADD**:", view=picker)
        else:
            picker.add_item(RemoveRolesSelect(self.scope))
            await interaction.response.send_message("Select roles to **REMOVE**:", view=picker)


class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to ADD", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        settings = load_settings()
        role_set = set(settings.get("global_allowed_roles", [])) if self.scope == "global" else set(settings["apps"][self.scope]["allowed_roles"])

        for r in self.values:
            role_set.add(r.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(role_set)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(role_set)

        save_settings(settings)
        await interaction.response.send_message(f"✅ Added roles to **{SCOPES[self.scope]}**.")


class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to REMOVE", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        settings = load_settings()
        role_set = set(settings.get("global_allowed_roles", [])) if self.scope == "global" else set(settings["apps"][self.scope]["allowed_roles"])

        for r in self.values:
            role_set.discard(r.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(role_set)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(role_set)

        save_settings(settings)
        await interaction.response.send_message(f"✅ Removed roles from **{SCOPES[self.scope]}**.")


# ======================================================
# WELCOME MANAGEMENT (unchanged)
# ======================================================

class EditWelcomeTitleModalLocal(discord.ui.Modal, title="Edit Welcome Title"):
    text = discord.ui.TextInput(label="Title", max_length=256)

    def __init__(self, default: str):
        super().__init__()
        self.text.default = default

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg.setdefault("welcome", {})
        cfg["welcome"]["title"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("✅ Welcome title updated.")


class EditWelcomeTextModalLocal(discord.ui.Modal, title="Edit Welcome Text"):
    text = discord.ui.TextInput(label="Text", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, default: str):
        super().__init__()
        self.text.default = default

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg.setdefault("welcome", {})
        cfg["welcome"]["description"] = self.text.value
        save_config(cfg)
        await interaction.response.send_message("✅ Welcome text updated.")


class AddArrivalImageModalLocal(discord.ui.Modal, title="Add Arrival Image"):
    url = discord.ui.TextInput(label="Image URL", max_length=400)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        cfg.setdefault("welcome", {})
        cfg["welcome"].setdefault("arrival_images", [])
        cfg["welcome"]["arrival_images"].append(self.url.value.strip())
        save_config(cfg)
        await interaction.response.send_message("✅ Arrival image added.")


class AddChannelSlotNameModalLocal(discord.ui.Modal, title="Add / Edit Channel Slot"):
    name = discord.ui.TextInput(label="Slot name (e.g. self_roles)", max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        slot = self.name.value.strip()
        if not slot:
            return await interaction.response.send_message("❌ Slot name cannot be empty.")
        await interaction.response.send_message(f"Select a channel for slot **{slot}**:", view=ChannelSlotPickerViewLocal(slot))


class WelcomeRemoveImageMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(WelcomeRemoveImageSelect())


class WelcomeRemoveImageSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Arrival images…",
            options=[
                discord.SelectOption(label="👀 View images", value="view"),
                discord.SelectOption(label="🗑️ Remove an image", value="remove"),
            ],
            min_values=1, max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        imgs = (cfg.get("welcome", {}) or {}).get("arrival_images") or []

        if self.values[0] == "view":
            if not imgs:
                return await interaction.response.send_message("No arrival images.")
            return await interaction.response.send_message(
                embed=image_embed("👋 Arrival Images", imgs, 0),
                view=ImagePagerView("👋 Arrival Images", imgs, 0)
            )

        if not imgs:
            return await interaction.response.send_message("No arrival images to remove.")
        await interaction.response.send_message("Pick an image to remove:", view=RemoveImagePicker("welcome", imgs))


class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Welcome action…",
            options=[
                discord.SelectOption(label="🔁 Toggle Welcome On/Off", value="toggle"),
                discord.SelectOption(label="📍 Set Welcome Channel", value="set_channel"),
                discord.SelectOption(label="✏️ Edit Title", value="edit_title"),
                discord.SelectOption(label="📝 Edit Text", value="edit_text"),
                discord.SelectOption(label="🔧 Add / Edit Channel Slot", value="slot"),
                discord.SelectOption(label="🖼️ Add Arrival Image", value="add_img"),
                discord.SelectOption(label="🗑️ Remove Arrival Image", value="rm_img"),
                discord.SelectOption(label="🤖 Toggle Bot Add Logs", value="toggle_bot"),
                discord.SelectOption(label="📍 Set Bot Add Channel", value="bot_channel"),
                discord.SelectOption(label="🛬 Preview Welcome", value="preview"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave/Boost settings.")

        choice = self.values[0]

        if choice == "set_channel":
            return await interaction.response.send_message("Select the welcome channel:", view=WelcomeChannelPickerViewLocal())

        if choice == "edit_title":
            cfg = load_config()
            w = cfg.get("welcome", {}) or {}
            return await interaction.response.send_modal(EditWelcomeTitleModalLocal(w.get("title", "")))

        if choice == "edit_text":
            cfg = load_config()
            w = cfg.get("welcome", {}) or {}
            return await interaction.response.send_modal(EditWelcomeTextModalLocal(w.get("description", "")))

        if choice == "slot":
            return await interaction.response.send_modal(AddChannelSlotNameModalLocal())

        if choice == "add_img":
            return await interaction.response.send_modal(AddArrivalImageModalLocal())

        if choice == "bot_channel":
            return await interaction.response.send_message("Select the bot-add log channel:", view=BotAddChannelPickerViewLocal())

        await _safe_defer(interaction)
        cfg = load_config()
        cfg.setdefault("welcome", {})
        w = cfg["welcome"]

        if choice == "toggle":
            w["enabled"] = not w.get("enabled", True)
            save_config(cfg)

        elif choice == "toggle_bot":
            w.setdefault("bot_add", {"enabled": True, "channel_id": None})
            w["bot_add"]["enabled"] = not w["bot_add"].get("enabled", True)
            save_config(cfg)

        elif choice == "rm_img":
            imgs = w.get("arrival_images") or []
            if not imgs:
                if interaction.channel:
                    await interaction.channel.send("No arrival images to remove.")
            else:
                if interaction.channel:
                    await interaction.channel.send("Choose:", view=WelcomeRemoveImageMenu())

        elif choice == "preview":
            await send_welcome_preview(interaction)
            return

        cfg2 = load_config()
        embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status_text(cfg2), color=discord.Color.blurple())
        await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.WELCOME))


async def send_welcome_preview(interaction: discord.Interaction):
    cfg = load_config()
    w = cfg.get("welcome", {}) or {}

    count = human_member_number(interaction.guild)
    now = discord.utils.utcnow().strftime("%H:%M")

    embed = discord.Embed(
        title=render(w.get("title", ""), user=interaction.user, guild=interaction.guild, member_count=count, channels=w.get("channels", {})),
        description=render(w.get("description", ""), user=interaction.user, guild=interaction.guild, member_count=count, channels=w.get("channels", {})),
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"You landed as passenger #{count} 🛬 | Today at {now}")

    imgs = w.get("arrival_images") or []
    if imgs:
        embed.set_image(url=random.choice(imgs))

    if interaction.channel:
        await interaction.channel.send(embed=embed)


# ======================================================
# LEAVE / LOGS MANAGEMENT (unchanged)
# ======================================================

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Leave/log action…",
            options=[
                discord.SelectOption(label="🔁 Toggle Logs On/Off", value="toggle_logs"),
                discord.SelectOption(label="📍 Set Log Channel", value="set_log_channel"),
                discord.SelectOption(label="👋 Toggle Leave Logs", value="toggle_leave"),
                discord.SelectOption(label="🥾 Toggle Kick Logs", value="toggle_kick"),
                discord.SelectOption(label="⛔ Toggle Ban Logs", value="toggle_ban"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave/Boost settings.")

        choice = self.values[0]

        if choice == "set_log_channel":
            return await interaction.response.send_message("Select the member log channel:", view=LogChannelPickerViewLocal())

        await _safe_defer(interaction)
        cfg = load_config()
        cfg.setdefault("member_logs", {})
        m = cfg["member_logs"]

        if choice == "toggle_logs":
            m["enabled"] = not m.get("enabled", True)
        elif choice == "toggle_leave":
            m["log_leave"] = not m.get("log_leave", True)
        elif choice == "toggle_kick":
            m["log_kick"] = not m.get("log_kick", True)
        elif choice == "toggle_ban":
            m["log_ban"] = not m.get("log_ban", True)

        save_config(cfg)

        cfg2 = load_config()
        embed = discord.Embed(title="📄 Leave / Logs Settings", description=logs_status_text(cfg2), color=discord.Color.blurple())
        await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.LEAVE))


# ======================================================
# Slash Command
# ======================================================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ You do not have permission.")

        await _safe_defer(interaction)

        cfg = load_config()
        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(name="🚀 Boost", value=boost_status_text(cfg), inline=False)

        btxt = "*Birthdays module not available*"
        if bday_load_data:
            try:
                bdata, _ = await bday_load_data()
                btxt = birthday_status_text(bdata)
            except Exception:
                btxt = "*Couldn’t load birthdays.json*"
        embed.add_field(name="🎂 Birthdays", value=btxt, inline=False)

        embed.add_field(name="🛂 Roles", value="Go to **🛂 Roles** to edit scopes / overview.", inline=False)

        await interaction.followup.send(embed=embed, view=PilotPanelView(state=PanelState.ROOT))