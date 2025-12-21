# birthdays.py
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


# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "birthdays.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
GITHUB_API_BASE = "https://api.github.com"

UK_TZ = ZoneInfo("Europe/London")


# ------------------- Default JSON -------------------
DEFAULT_DATA: Dict[str, Any] = {
    "settings": {
        "enabled": True,
        "announce": True,
        "channel_id": None,
        "birthday_role_id": None,

        # Message templates (used INSIDE the embed)
        # placeholders:
        # {username} single user display name
        # {usernames} comma separated display names (multiple)
        # {count} number of users
        # {date} e.g. 21 December
        # {timezone} user's timezone string
        "message_single": "🎂 Happy Birthday **{username}**! ✈️",
        "message_multiple": "🎉 Happy Birthday **{usernames}**! 🎂",

        # Embed settings
        "embed": {
            "enabled": True,
            "title": "🎉 Birthday Time!",
            "description": "{message}",  # keep as "{message}" normally
            "color": 0xFF69B4,
            "images": []
        }
    },
    "birthdays": {
        # "user_id_str": {"day": 21, "month": 3, "timezone": "Europe/London"}
    },
    "state": {
        # for announcements (once per local date group)
        "announced_keys": [],        # list of "YYYY-MM-DD|announce"
        # for roles we applied (so we only remove what WE added)
        "role_assigned_keys": []     # list of "YYYY-MM-DD|user_id"
    }
}


# ------------------- GitHub JSON Helpers -------------------
_lock = asyncio.Lock()

async def _gh_get_file() -> Tuple[Optional[dict], Optional[str]]:
    """Return (json_data, sha). If not found, returns (None, None)."""
    if not GITHUB_TOKEN:
        return None, None

    import requests
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS, timeout=20)

    if r.status_code == 404:
        return None, None
    r.raise_for_status()

    payload = r.json()
    sha = payload.get("sha")
    content_b64 = payload.get("content", "")
    raw = base64.b64decode(content_b64).decode("utf-8")
    data = json.loads(raw)
    return data, sha


async def _gh_put_file(data: dict, sha: Optional[str]) -> Optional[str]:
    """Write json_data to GitHub, return new sha."""
    if not GITHUB_TOKEN:
        return None

    import requests
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

    raw = json.dumps(data, indent=2, ensure_ascii=False)
    content_b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    body = {
        "message": f"Update {GITHUB_FILE_PATH}",
        "content": content_b64,
        "sha": sha
    } if sha else {
        "message": f"Create {GITHUB_FILE_PATH}",
        "content": content_b64
    }

    r = requests.put(url, headers=HEADERS, json=body, timeout=25)
    r.raise_for_status()
    return r.json().get("content", {}).get("sha")


async def load_data() -> Tuple[dict, Optional[str]]:
    async with _lock:
        data, sha = await _gh_get_file()
        if not data:
            return json.loads(json.dumps(DEFAULT_DATA)), sha

        merged = json.loads(json.dumps(DEFAULT_DATA))
        merged.update(data)
        merged["settings"] = {**DEFAULT_DATA["settings"], **data.get("settings", {})}
        merged["settings"]["embed"] = {
            **DEFAULT_DATA["settings"]["embed"],
            **merged["settings"].get("embed", {})
        }
        merged["birthdays"] = data.get("birthdays", {}) or {}
        merged["state"] = {**DEFAULT_DATA["state"], **data.get("state", {})}
        merged["state"]["announced_keys"] = list(merged["state"].get("announced_keys", []))
        merged["state"]["role_assigned_keys"] = list(merged["state"].get("role_assigned_keys", []))
        return merged, sha


async def save_data(data: dict, sha: Optional[str]) -> Optional[str]:
    async with _lock:
        return await _gh_put_file(data, sha)


# ------------------- Utility -------------------
def _is_valid_tz(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False


def _normalize_state_lists(data: dict) -> None:
    st = data.setdefault("state", {})
    st.setdefault("announced_keys", [])
    st.setdefault("role_assigned_keys", [])
    st["announced_keys"] = list(st.get("announced_keys", []))[-2000:]
    st["role_assigned_keys"] = list(st.get("role_assigned_keys", []))[-2000:]


def _fmt_date(d: date) -> str:
    try:
        return d.strftime("%-d %B")
    except Exception:
        return d.isoformat()


def _render_message(template: str, *, usernames: List[str], local_date: date, tz: str) -> str:
    # For single: {username}
    # For multiple: {usernames} and {count}
    username = usernames[0] if usernames else "Someone"
    return (
        template
        .replace("{username}", username)
        .replace("{usernames}", ", ".join(usernames))
        .replace("{count}", str(len(usernames)))
        .replace("{date}", _fmt_date(local_date))
        .replace("{timezone}", tz)
    )


def _pick_image(images: List[str], preferred_index: Optional[int] = None, randomize: bool = True) -> Optional[str]:
    images = [i for i in images if isinstance(i, str) and i.strip()]
    if not images:
        return None
    if preferred_index is not None and 0 <= preferred_index < len(images):
        return images[preferred_index]
    return random.choice(images) if randomize else images[0]


def _build_bday_embed(settings: dict, *, message_text: str, image_url: Optional[str], footer: str = "The Pilot • Birthdays") -> discord.Embed:
    emb = settings.get("embed", {}) or {}
    title = emb.get("title", "🎉 Birthday Time!")
    desc_tpl = emb.get("description", "{message}")
    color_int = int(emb.get("color", 0xFF69B4))

    desc = desc_tpl.replace("{message}", message_text)

    e = discord.Embed(title=title, description=desc, color=discord.Color(color_int))
    if image_url:
        e.set_image(url=image_url)
    e.set_footer(text=footer)
    return e


# ------------------- Timezone Autocomplete -------------------
_TZ_CACHE: Optional[List[str]] = None

def _get_all_timezones() -> List[str]:
    global _TZ_CACHE
    if _TZ_CACHE is None:
        _TZ_CACHE = sorted(list(available_timezones()))
    return _TZ_CACHE


async def timezone_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    cur = (current or "").strip().lower()
    tzs = _get_all_timezones()
    matches: List[str] = []

    if not cur:
        common = ["Europe/London", "Europe/Paris", "America/New_York", "America/Los_Angeles", "Australia/Sydney", "UTC"]
        for c in common:
            if c in tzs:
                matches.append(c)
        for t in tzs:
            if t.startswith("Europe/") and t not in matches:
                matches.append(t)
            if len(matches) >= 20:
                break
    else:
        for t in tzs:
            tl = t.lower()
            if tl.startswith(cur) or cur in tl:
                matches.append(t)
            if len(matches) >= 20:
                break

    return [app_commands.Choice(name=m, value=m) for m in matches[:20]]


# =========================================================
# Modals + UI
# =========================================================

class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Messages"):
    single_message = discord.ui.TextInput(
        label="Single birthday message (inside embed)",
        style=discord.TextStyle.paragraph,
        required=True
    )
    multiple_message = discord.ui.TextInput(
        label="Multiple birthday message (inside embed)",
        style=discord.TextStyle.paragraph,
        required=True
    )

    def __init__(self, view: "BirthdaySettingsView"):
        super().__init__()
        self.view = view
        s = view.data.get("settings", {})
        self.single_message.default = s.get("message_single", "")
        self.multiple_message.default = s.get("message_multiple", "")

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.view.data.setdefault("settings", {})
        s["message_single"] = str(self.single_message.value)
        s["message_multiple"] = str(self.multiple_message.value)

        _normalize_state_lists(self.view.data)
        self.view.sha = await save_data(self.view.data, self.view.sha)

        await interaction.response.send_message("✅ Birthday messages updated.", ephemeral=True)
        await self.view.refresh_message(interaction)


class BirthdayEmbedModal(discord.ui.Modal, title="Edit Birthday Embed"):
    title_in = discord.ui.TextInput(label="Embed title", required=True)
    desc_in = discord.ui.TextInput(
        label="Embed description template",
        style=discord.TextStyle.paragraph,
        required=True
    )
    color_in = discord.ui.TextInput(
        label="Embed color (hex, e.g. FF69B4)",
        required=True
    )

    def __init__(self, view: "BirthdaySettingsView"):
        super().__init__()
        self.view = view
        emb = view.data.get("settings", {}).get("embed", {}) or {}
        self.title_in.default = str(emb.get("title", "🎉 Birthday Time!"))
        self.desc_in.default = str(emb.get("description", "{message}"))
        self.color_in.default = f"{int(emb.get('color', 0xFF69B4)):06X}"

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        emb = self.view.data.setdefault("settings", {}).setdefault("embed", {})
        emb["title"] = str(self.title_in.value)
        emb["description"] = str(self.desc_in.value)

        raw = str(self.color_in.value).strip().lstrip("#")
        try:
            emb["color"] = int(raw, 16)
        except Exception:
            emb["color"] = 0xFF69B4

        _normalize_state_lists(self.view.data)
        self.view.sha = await save_data(self.view.data, self.view.sha)

        await interaction.response.send_message("✅ Embed settings updated.", ephemeral=True)
        await self.view.refresh_message(interaction)


class AddImageModal(discord.ui.Modal, title="Add Birthday Image"):
    url = discord.ui.TextInput(label="Image URL", style=discord.TextStyle.short, required=True)

    def __init__(self, view: "BirthdaySettingsView"):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        url = str(self.url.value).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return await interaction.response.send_message("❌ Please provide a valid http(s) URL.", ephemeral=True)

        images = self.view.data.setdefault("settings", {}).setdefault("embed", {}).setdefault("images", [])
        images.append(url)

        _normalize_state_lists(self.view.data)
        self.view.sha = await save_data(self.view.data, self.view.sha)

        await interaction.response.send_message("✅ Image added.", ephemeral=True)
        await self.view.refresh_message(interaction)


class BirthdayChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select birthday announcement channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: BirthdaySettingsView = self.view  # type: ignore
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        ch = self.values[0]
        view.data.setdefault("settings", {})["channel_id"] = ch.id

        _normalize_state_lists(view.data)
        view.sha = await save_data(view.data, view.sha)
        await view.refresh_message(interaction)


class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select birthday role (optional)…",
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: BirthdaySettingsView = self.view  # type: ignore
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        role = self.values[0]
        if role.is_default():
            return await interaction.response.send_message("❌ You can’t use @everyone.", ephemeral=True)

        view.data.setdefault("settings", {})["birthday_role_id"] = role.id

        _normalize_state_lists(view.data)
        view.sha = await save_data(view.data, view.sha)
        await view.refresh_message(interaction)


class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot: discord.Client, data: dict, sha: Optional[str]):
        super().__init__(timeout=300)
        self.bot = bot
        self.data = data
        self.sha = sha

        self.image_index: int = 0

        # Select menus
        self.add_item(BirthdayChannelSelect())
        self.add_item(BirthdayRoleSelect())

    def _settings_embed(self) -> discord.Embed:
        s = self.data.get("settings", {})
        emb = s.get("embed", {}) or {}
        images = emb.get("images", []) or []

        enabled = bool(s.get("enabled", True))
        announce = bool(s.get("announce", True))
        channel_id = s.get("channel_id")
        role_id = s.get("birthday_role_id")

        channel_str = f"<#{channel_id}>" if channel_id else "Not set"
        role_str = f"<@&{role_id}>" if role_id else "Not set"

        onoff = "✅ Enabled" if enabled else "⛔ Disabled"
        ann = "✅ Announcements ON" if announce else "⛔ Announcements OFF"

        msg_block = (
            f"Single:\n{s.get('message_single','')}\n\n"
            f"Multiple:\n{s.get('message_multiple','')}"
        )

        e = discord.Embed(
            title="🎂 Pilot Birthdays Settings",
            description=f"{onoff}\n{ann}",
            color=discord.Color.pink()
        )
        e.add_field(name="Announcement channel", value=channel_str, inline=False)
        e.add_field(name="Birthday role", value=role_str, inline=False)
        e.add_field(name="Messages (inside embed)", value=f"```{msg_block}```", inline=False)

        e.add_field(
            name="Embed",
            value=(
                f"Title: `{emb.get('title','')}`\n"
                f"Desc: `{emb.get('description','')}`\n"
                f"Color: `#{int(emb.get('color',0xFF69B4)):06X}`\n"
                f"Images: `{len(images)}` (use ◀ ▶ to preview)"
            ),
            inline=False
        )

        # Preview current image in the settings embed
        current = _pick_image(images, preferred_index=self.image_index, randomize=False)
        if current:
            e.set_image(url=current)

        e.set_footer(text="The Pilot • Birthdays")
        return e

    async def refresh_message(self, interaction: discord.Interaction):
        try:
            await interaction.message.edit(embed=self._settings_embed(), view=self)  # type: ignore
        except Exception:
            # If we can't edit message (older interaction), just try responding
            pass

    # ---- toggles ----
    @discord.ui.button(label="Toggle enabled", style=discord.ButtonStyle.primary, row=2)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.data.setdefault("settings", {})
        s["enabled"] = not bool(s.get("enabled", True))

        _normalize_state_lists(self.data)
        self.sha = await save_data(self.data, self.sha)
        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(label="Toggle announcements", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_announce(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.data.setdefault("settings", {})
        s["announce"] = not bool(s.get("announce", True))

        _normalize_state_lists(self.data)
        self.sha = await save_data(self.data, self.sha)
        await interaction.response.defer()
        await self.refresh_message(interaction)

    # ---- message + embed edit ----
    @discord.ui.button(label="Edit messages", style=discord.ButtonStyle.success, row=2)
    async def edit_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(BirthdayMessageModal(self))

    @discord.ui.button(label="Edit embed", style=discord.ButtonStyle.success, row=2)
    async def edit_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(BirthdayEmbedModal(self))

    # ---- image pagination ----
    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=3)
    async def img_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        images = self.data.get("settings", {}).get("embed", {}).get("images", []) or []
        if not images:
            return await interaction.response.send_message("No images yet.", ephemeral=True)

        self.image_index = (self.image_index - 1) % len(images)
        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=3)
    async def img_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        images = self.data.get("settings", {}).get("embed", {}).get("images", []) or []
        if not images:
            return await interaction.response.send_message("No images yet.", ephemeral=True)

        self.image_index = (self.image_index + 1) % len(images)
        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(label="Add image", style=discord.ButtonStyle.secondary, row=3)
    async def img_add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(AddImageModal(self))

    @discord.ui.button(label="Remove image", style=discord.ButtonStyle.danger, row=3)
    async def img_remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        images = self.data.setdefault("settings", {}).setdefault("embed", {}).setdefault("images", [])
        if not images:
            return await interaction.response.send_message("No images to remove.", ephemeral=True)

        idx = self.image_index % len(images)
        removed = images.pop(idx)
        if images:
            self.image_index = min(self.image_index, len(images) - 1)
        else:
            self.image_index = 0

        _normalize_state_lists(self.data)
        self.sha = await save_data(self.data, self.sha)

        await interaction.response.send_message(f"✅ Removed image:\n{removed}", ephemeral=True)
        await self.refresh_message(interaction)

    # ---- misc ----
    @discord.ui.button(label="Clear role", style=discord.ButtonStyle.danger, row=4)
    async def clear_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        self.data.setdefault("settings", {})["birthday_role_id"] = None
        _normalize_state_lists(self.data)
        self.sha = await save_data(self.data, self.sha)

        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(label="Clear channel", style=discord.ButtonStyle.danger, row=4)
    async def clear_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        self.data.setdefault("settings", {})["channel_id"] = None
        _normalize_state_lists(self.data)
        self.sha = await save_data(self.data, self.sha)

        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(label="Preview embed", style=discord.ButtonStyle.primary, row=4)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.data.get("settings", {})
        emb = s.get("embed", {}) or {}
        images = emb.get("images", []) or []

        # Preview uses currently selected image (pagination)
        image_url = _pick_image(images, preferred_index=self.image_index, randomize=False)

        today = datetime.now(UK_TZ).date()
        usernames = [interaction.user.display_name]
        tz = "Europe/London"

        msg = _render_message(s.get("message_single", ""), usernames=usernames, local_date=today, tz=tz)
        e = _build_bday_embed(s, message_text=msg, image_url=image_url)

        # @ outside, usernames inside (message is inside embed)
        await interaction.response.send_message("🧪 **PREVIEW**", embed=e, ephemeral=False)

    @discord.ui.button(label="Send test", style=discord.ButtonStyle.secondary, row=4)
    async def send_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.data.get("settings", {})
        channel_id = s.get("channel_id")
        if not channel_id:
            return await interaction.response.send_message("❌ No birthday channel set.", ephemeral=True)

        channel = interaction.guild.get_channel(int(channel_id)) if interaction.guild else None
        if not channel:
            return await interaction.response.send_message("❌ Birthday channel not found.", ephemeral=True)

        emb = s.get("embed", {}) or {}
        images = emb.get("images", []) or []

        # Prefer selected image in settings for test (so you can preview what you picked)
        image_url = _pick_image(images, preferred_index=self.image_index, randomize=False)

        today = datetime.now(UK_TZ).date()

        # If there are real birthdays today, use them, otherwise fallback
        real_members: List[discord.Member] = []
        for uid, rec in (self.data.get("birthdays", {}) or {}).items():
            if rec.get("day") == today.day and rec.get("month") == today.month:
                m = interaction.guild.get_member(int(uid)) if interaction.guild else None
                if m:
                    real_members.append(m)

        members = real_members
        if not members:
            members = [interaction.user]
            # add one more human if possible (so you can test multiple template)
            if interaction.guild:
                for m in interaction.guild.members:
                    if not m.bot and m.id != interaction.user.id:
                        members.append(m)
                        break

        mentions = ", ".join(m.mention for m in members)
        usernames = [m.display_name for m in members]

        if len(members) == 1:
            msg = _render_message(s.get("message_single", ""), usernames=usernames, local_date=today, tz="Europe/London")
        else:
            msg = _render_message(s.get("message_multiple", ""), usernames=usernames, local_date=today, tz="Europe/London")

        e = _build_bday_embed(s, message_text=msg, image_url=image_url)

        await channel.send("🧪 **TEST MODE**")
        await channel.send(mentions)           # @ outside embed
        await channel.send(embed=e)            # usernames inside embed
        await interaction.response.send_message("✅ Test sent.", ephemeral=True)

    @discord.ui.button(label="Export birthdays", style=discord.ButtonStyle.secondary, row=5)
    async def export_birthdays(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        bds: Dict[str, Any] = self.data.get("birthdays", {}) or {}
        if not bds:
            return await interaction.response.send_message("No birthdays saved yet.", ephemeral=True)

        lines = []
        for uid, rec in bds.items():
            try:
                d = int(rec.get("day", 0))
                m = int(rec.get("month", 0))
                tz = str(rec.get("timezone", ""))
            except Exception:
                continue
            lines.append(f"{uid}\t{d:02d}-{m:02d}\t{tz}")

        content = "USER_ID\tDD-MM\tTIMEZONE\n" + "\n".join(sorted(lines))
        file = discord.File(fp=content.encode("utf-8"), filename="birthdays_export.txt")
        await interaction.response.send_message("✅ Export:", file=file, ephemeral=False)


# =========================================================
# Main Setup
# =========================================================

def setup(bot: discord.Client):
    tree = bot.tree
    birthday_group = app_commands.Group(name="birthday", description="Birthday commands")
    tree.add_command(birthday_group)

    @birthday_group.command(name="set", description="Set a birthday (timezone required).")
    @app_commands.describe(
        day="Day (1-31)",
        month="Month (1-12)",
        timezone="IANA timezone (e.g. Europe/London)",
        user="Optional: set for someone else"
    )
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def birthday_set(
        interaction: discord.Interaction,
        day: app_commands.Range[int, 1, 31],
        month: app_commands.Range[int, 1, 12],
        timezone: str,
        user: Optional[discord.Member] = None
    ):
        tz = (timezone or "").strip()
        if not _is_valid_tz(tz):
            return await interaction.response.send_message(
                "❌ Invalid timezone. Pick one from autocomplete.",
                ephemeral=False
            )

        target = user or interaction.user

        if user and not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to set birthdays for other members.",
                ephemeral=True
            )

        data, sha = await load_data()
        data.setdefault("birthdays", {})
        data["birthdays"][str(target.id)] = {
            "day": int(day),
            "month": int(month),
            "timezone": tz
        }
        _normalize_state_lists(data)
        await save_data(data, sha)

        who = "your" if target.id == interaction.user.id else f"{target.mention}'s"
        await interaction.response.send_message(
            f"✅ Set {who} birthday to **{day:02d}/{month:02d}** in **{tz}**.",
            ephemeral=False
        )

    @birthday_group.command(name="view", description="View someone’s birthday.")
    @app_commands.describe(user="The user whose birthday you want to view")
    async def view_birthday(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user

        data, _ = await load_data()
        rec = (data.get("birthdays", {}) or {}).get(str(target.id))

        if not rec:
            return await interaction.response.send_message(
                "That user hasn’t set their birthday yet." if target.id != interaction.user.id
                else "You haven’t set your birthday yet. Use `/birthday set`.",
                ephemeral=False
            )

        day_v = int(rec.get("day", 0))
        month_v = int(rec.get("month", 0))
        tz = rec.get("timezone", "Europe/London")

        await interaction.response.send_message(
            f"🎂 **{target.display_name}** — **{day_v:02d}/{month_v:02d}** (`{tz}`)",
            ephemeral=False
        )

    @birthday_group.command(name="remove", description="Remove a birthday.")
    @app_commands.describe(user="Optional: remove someone else")
    async def birthday_remove(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user

        if user and not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to remove birthdays for other members.",
                ephemeral=True
            )

        data, sha = await load_data()
        bds = data.get("birthdays", {}) or {}

        if str(target.id) not in bds:
            return await interaction.response.send_message("No birthday set to remove.", ephemeral=False)

        del bds[str(target.id)]
        data["birthdays"] = bds
        _normalize_state_lists(data)
        await save_data(data, sha)

        await interaction.response.send_message("✅ Birthday removed.", ephemeral=False)

    @birthday_group.command(name="upcoming", description="Show upcoming birthdays.")
    @app_commands.describe(days="How many days ahead (default 14)")
    async def upcoming_birthdays(interaction: discord.Interaction, days: app_commands.Range[int, 1, 60] = 14):
        data, _ = await load_data()
        bds: Dict[str, Any] = data.get("birthdays", {}) or {}
        if not bds:
            return await interaction.response.send_message("No birthdays saved yet.", ephemeral=False)

        today_uk = datetime.now(UK_TZ).date()
        entries: List[Tuple[int, date, str, str]] = []

        def next_occurrence(d: int, m: int, now_local: date) -> date:
            year = now_local.year
            try:
                candidate = date(year, m, d)
            except ValueError:
                candidate = date(year, m, 1)
            if candidate < now_local:
                try:
                    candidate = date(year + 1, m, d)
                except ValueError:
                    candidate = date(year + 1, m, 1)
            return candidate

        for uid, rec in bds.items():
            try:
                d = int(rec.get("day"))
                m = int(rec.get("month"))
                tz = str(rec.get("timezone"))
            except Exception:
                continue

            nd = next_occurrence(d, m, today_uk)
            delta = (nd - today_uk).days
            if 0 <= delta <= int(days):
                entries.append((delta, nd, uid, tz))

        if not entries:
            return await interaction.response.send_message(f"No birthdays in the next {days} days.", ephemeral=False)

        entries.sort(key=lambda x: (x[0], x[1].month, x[1].day))

        lines = []
        guild = interaction.guild
        for delta, dt, uid, tz in entries[:25]:
            member = guild.get_member(int(uid)) if guild else None
            name = member.mention if member else f"`{uid}`"
            label = "Today" if delta == 0 else "Tomorrow" if delta == 1 else dt.strftime("%-d %b")
            lines.append(f"• **{label}** — {name} (`{tz}`)")

        embed = discord.Embed(
            title=f"🎂 Upcoming Birthdays (next {days} days)",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        embed.set_footer(text="The Pilot • Birthdays")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @birthday_group.command(name="settings", description="Configure birthday settings (Pilot roles only).")
    async def birthdaysettings(interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ You don’t have permission to manage birthdays.", ephemeral=True)

        data, sha = await load_data()
        view = BirthdaySettingsView(bot, data, sha)
        await interaction.response.send_message(embed=view._settings_embed(), view=view, ephemeral=False)

    # ------------------- Background Task -------------------
    @tasks.loop(minutes=15)
    async def birthday_tick():
        for guild in bot.guilds:
            try:
                data, sha = await load_data()
                s = data.get("settings", {})
                if not s.get("enabled", True):
                    continue

                bds = data.get("birthdays", {}) or {}
                if not bds:
                    continue

                _normalize_state_lists(data)

                announced = set(data["state"].get("announced_keys", []))
                role_assigned = set(data["state"].get("role_assigned_keys", []))

                channel = guild.get_channel(s.get("channel_id")) if s.get("channel_id") else None
                role = guild.get_role(s.get("birthday_role_id")) if s.get("birthday_role_id") else None
                do_announce = bool(s.get("announce", True))

                now_utc = datetime.now(timezone.utc)

                # ---- group birthdays by the USER'S LOCAL DATE ----
                today_birthdays: Dict[str, List[discord.Member]] = {}
                today_birthdays_tz: Dict[str, str] = {}  # date_key -> tz label (for embed tokens)

                for uid, rec in bds.items():
                    member = guild.get_member(int(uid))
                    if not member:
                        continue

                    tz_str = rec.get("timezone", "Europe/London")
                    if not _is_valid_tz(tz_str):
                        continue

                    local_now = now_utc.astimezone(ZoneInfo(tz_str))
                    local_date = local_now.date()

                    is_birthday = (int(rec.get("day")) == local_date.day and int(rec.get("month")) == local_date.month)
                    key = f"{local_date.isoformat()}|{uid}"

                    # ---- role add ----
                    if role and is_birthday and key not in role_assigned:
                        try:
                            await member.add_roles(role, reason="Birthday role (auto)")
                            role_assigned.add(key)
                        except Exception:
                            pass

                    # ---- role cleanup after their local midnight (only if WE assigned it) ----
                    # If they're not birthday today, remove role ONLY if we previously assigned it.
                    if role and (not is_birthday) and (role in member.roles):
                        # any past assignment key for this uid?
                        if any(k.endswith(f"|{uid}") for k in role_assigned):
                            try:
                                await member.remove_roles(role, reason="Birthday role expired (auto)")
                            except Exception:
                                pass

                    if is_birthday:
                        date_key = local_date.isoformat()
                        today_birthdays.setdefault(date_key, []).append(member)
                        today_birthdays_tz.setdefault(date_key, tz_str)

                # ---- announcements ----
                if do_announce and channel:
                    emb_cfg = s.get("embed", {}) or {}
                    images = emb_cfg.get("images", []) or []

                    for date_key, members in today_birthdays.items():
                        announce_key = f"{date_key}|announce"
                        if announce_key in announced:
                            continue

                        # mentions OUTSIDE embed
                        mentions = ", ".join(m.mention for m in members)

                        # usernames INSIDE embed
                        usernames = [m.display_name for m in members]
                        tz_label = today_birthdays_tz.get(date_key, "Europe/London")

                        if len(members) == 1:
                            msg_tpl = s.get("message_single", DEFAULT_DATA["settings"]["message_single"])
                        else:
                            msg_tpl = s.get("message_multiple", DEFAULT_DATA["settings"]["message_multiple"])

                        msg_text = _render_message(
                            msg_tpl,
                            usernames=usernames,
                            local_date=date.fromisoformat(date_key),
                            tz=tz_label
                        )

                        # random image on real announcements
                        image_url = _pick_image(images, preferred_index=None, randomize=True)
                        e = _build_bday_embed(s, message_text=msg_text, image_url=image_url)

                        try:
                            await channel.send(mentions)
                            await channel.send(embed=e)
                            announced.add(announce_key)
                        except Exception:
                            pass

                data["state"]["announced_keys"] = list(announced)
                data["state"]["role_assigned_keys"] = list(role_assigned)
                await save_data(data, sha)

            except Exception:
                continue

    @birthday_tick.before_loop
    async def before_birthday_tick():
        await bot.wait_until_ready()

    birthday_tick.start()