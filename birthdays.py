from __future__ import annotations

import os
import json
import base64
import asyncio
import io
import random
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional, List, Tuple

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from zoneinfo import ZoneInfo, available_timezones

from permissions import has_app_access

# =========================================================
# GitHub Config
# =========================================================
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "birthdays.json"  # keep as-is
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_BASE = "https://api.github.com"
UK_TZ = ZoneInfo("Europe/London")

HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# =========================================================
# Default JSON
# =========================================================
DEFAULT_DATA: Dict[str, Any] = {
    "settings": {
        "enabled": True,
        "announce": True,
        "channel_id": None,
        "birthday_role_id": None,

        # Post time in EACH user's timezone
        # (e.g. 12:00 means 12:00 local for UK users, 12:00 local for AUS users, etc)
        "post_hour": 12,
        "post_minute": 0,

        # Templates: NAME ONLY (no mentions). Mentions are not posted.
        # SINGLE: use {username} (or {user} supported)
        # MULTIPLE: use {users} and {count}
        "message_single": "Happy Birthday {username}! 🎂✈️",
        "message_multiple": "Happy Birthday {users}! 🎉🎂",

        # Optional image URLs; bot posts ONE random URL after the message
        "image_urls": []
    },
    "birthdays": {
        # "user_id_str": {"day": 21, "month": 3, "timezone": "Europe/London"}
    },
    "state": {
        # Dedup announcements per local date bucket
        "announced_keys": [],        # ["YYYY-MM-DD|announce"]
        # Track role assigned per-user per local date
        "role_assigned_keys": []     # ["YYYY-MM-DD|user_id"]
    }
}

_lock = asyncio.Lock()

# =========================================================
# GitHub JSON Helpers (aiohttp)
# =========================================================
async def _gh_get_file() -> Tuple[Optional[dict], Optional[str]]:
    """Return (json_data, sha). If file missing -> (None, None)."""
    if not GITHUB_TOKEN:
        return None, None

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    timeout = aiohttp.ClientTimeout(total=25)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=HEADERS) as r:
            if r.status == 404:
                return None, None
            if r.status >= 400:
                raise RuntimeError(f"GitHub GET failed ({r.status}): {await r.text()}")
            payload = await r.json()
            sha = payload.get("sha")
            content_b64 = payload.get("content", "") or ""
            raw = base64.b64decode(content_b64).decode("utf-8")
            return json.loads(raw), sha


async def _gh_put_file(data: dict, sha: Optional[str]) -> Optional[str]:
    """Write json_data to GitHub, return new sha."""
    if not GITHUB_TOKEN:
        return None

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    timeout = aiohttp.ClientTimeout(total=30)

    raw = json.dumps(data, indent=2, ensure_ascii=False)
    content_b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    body = {
        "message": f"Update {GITHUB_FILE_PATH}",
        "content": content_b64,
        **({"sha": sha} if sha else {})
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.put(url, headers=HEADERS, json=body) as r:
            if r.status >= 400:
                raise RuntimeError(f"GitHub PUT failed ({r.status}): {await r.text()}")
            payload = await r.json()
            return payload.get("content", {}).get("sha")


async def load_data() -> Tuple[dict, Optional[str]]:
    async with _lock:
        data, sha = await _gh_get_file()

        if not data:
            # Return defaults if file doesn't exist yet
            return json.loads(json.dumps(DEFAULT_DATA)), sha

        # Merge defaults safely
        merged = json.loads(json.dumps(DEFAULT_DATA))
        merged.update(data)

        merged["settings"] = {**DEFAULT_DATA["settings"], **(data.get("settings") or {})}
        merged["birthdays"] = data.get("birthdays") or {}
        merged["state"] = {**DEFAULT_DATA["state"], **(data.get("state") or {})}

        # Ensure list types
        merged["settings"]["image_urls"] = list(merged["settings"].get("image_urls") or [])
        merged["state"]["announced_keys"] = list(merged["state"].get("announced_keys") or [])
        merged["state"]["role_assigned_keys"] = list(merged["state"].get("role_assigned_keys") or [])

        _normalize_state_lists(merged)
        return merged, sha


async def save_data(data: dict, sha: Optional[str]) -> Optional[str]:
    async with _lock:
        _normalize_state_lists(data)
        return await _gh_put_file(data, sha)

# =========================================================
# Utility
# =========================================================
_TZ_CACHE: Optional[List[str]] = None

def _normalize_state_lists(data: dict) -> None:
    st = data.setdefault("state", {})
    st.setdefault("announced_keys", [])
    st.setdefault("role_assigned_keys", [])
    st["announced_keys"] = list(st.get("announced_keys") or [])[-2000:]
    st["role_assigned_keys"] = list(st.get("role_assigned_keys") or [])[-2000:]

def _is_valid_tz(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False

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

def _next_occurrence(day: int, month: int, now_local: date) -> date:
    year = now_local.year
    try:
        candidate = date(year, month, day)
    except Exception:
        candidate = date(year, month, 1)
    if candidate < now_local:
        try:
            candidate = date(year + 1, month, day)
        except Exception:
            candidate = date(year + 1, month, 1)
    return candidate

def _pick_image_url(settings: dict) -> Optional[str]:
    urls = [u.strip() for u in (settings.get("image_urls") or []) if isinstance(u, str) and u.strip()]
    return random.choice(urls) if urls else None

def _fmt_template_name_only(tpl: str, *, name: str, names: str, local_date: date, tz: str, count: int) -> str:
    # {user} supported as name-only for backwards compat
    return (
        (tpl or "")
        .replace("{user}", name)
        .replace("{username}", name)
        .replace("{users}", names)
        .replace("{count}", str(count))
        .replace("{date}", local_date.strftime("%-d %B"))
        .replace("{timezone}", tz)
    )

def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default

# =========================================================
# Announcement sending (NO mentions)
# =========================================================
async def _send_announcement_like(
    *,
    channel: discord.abc.Messageable,
    settings: dict,
    members: List[discord.Member],
    local_date: date,
    tz_label: str,
    test_mode: bool
) -> None:
    if not members:
        return

    if test_mode:
        await channel.send("🧪 **TEST MODE**")

    if len(members) == 1:
        m = members[0]
        body = _fmt_template_name_only(
            str(settings.get("message_single", "")),
            name=m.display_name,
            names=m.display_name,
            local_date=local_date,
            tz=tz_label,
            count=1
        )
        await channel.send(body)
    else:
        names_line = ", ".join(m.display_name for m in members)
        body = _fmt_template_name_only(
            str(settings.get("message_multiple", "")),
            name=members[0].display_name,
            names=names_line,
            local_date=local_date,
            tz=tz_label,
            count=len(members)
        )
        await channel.send(body)

    img = _pick_image_url(settings)
    if img:
        await channel.send(img)

# =========================================================
# UI: Modals
# =========================================================
class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Messages"):
    single_message = discord.ui.TextInput(
        label="Single message (use {username})",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500
    )
    multiple_message = discord.ui.TextInput(
        label="Multiple message (use {users} / {count})",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500
    )

    def __init__(self, view: "BirthdaySettingsView"):
        super().__init__()
        self.view_ref = view
        s = view.data.get("settings", {})
        self.single_message.default = str(s.get("message_single", ""))
        self.multiple_message.default = str(s.get("message_multiple", ""))

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.view_ref.data.setdefault("settings", {})
        s["message_single"] = str(self.single_message.value)
        s["message_multiple"] = str(self.multiple_message.value)
        await self.view_ref._save_and_refresh(interaction, note="✅ Messages updated.")


class PostTimeModal(discord.ui.Modal, title="Set Birthday Post Time"):
    hour = discord.ui.TextInput(
        label="Hour (0-23)",
        style=discord.TextStyle.short,
        required=True,
        max_length=2
    )
    minute = discord.ui.TextInput(
        label="Minute (0-59)",
        style=discord.TextStyle.short,
        required=True,
        max_length=2
    )

    def __init__(self, view: "BirthdaySettingsView"):
        super().__init__()
        self.view_ref = view
        s = view.data.get("settings", {})
        self.hour.default = str(_safe_int(s.get("post_hour"), 12))
        self.minute.default = str(_safe_int(s.get("post_minute"), 0))

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        try:
            h = int(str(self.hour.value).strip())
            m = int(str(self.minute.value).strip())
        except Exception:
            return await interaction.response.send_message("❌ Enter numbers for hour/minute.", ephemeral=True)

        if not (0 <= h <= 23 and 0 <= m <= 59):
            return await interaction.response.send_message("❌ Time must be 0-23 and 0-59.", ephemeral=True)

        s = self.view_ref.data.setdefault("settings", {})
        s["post_hour"] = h
        s["post_minute"] = m
        await self.view_ref._save_and_refresh(interaction, note=f"⏰ Post time set to **{h:02d}:{m:02d}** (per-user timezone).")


class AddImageModal(discord.ui.Modal, title="Add Birthday Image URL"):
    url = discord.ui.TextInput(
        label="Image URL (http/https)",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    def __init__(self, view: "ImageSettingsView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        u = str(self.url.value).strip()
        if not (u.startswith("http://") or u.startswith("https://")):
            return await interaction.response.send_message("❌ That doesn’t look like a URL.", ephemeral=True)

        s = self.view_ref.data.setdefault("settings", {})
        imgs = list(s.get("image_urls", []) or [])
        imgs.append(u)
        s["image_urls"] = imgs

        await self.view_ref._save_and_refresh(interaction, note=f"✅ Added image #{len(imgs)}.")


class RemoveImageModal(discord.ui.Modal, title="Remove Birthday Image"):
    number = discord.ui.TextInput(
        label="Image number to remove (e.g. 1)",
        style=discord.TextStyle.short,
        required=True,
        max_length=10
    )

    def __init__(self, view: "ImageSettingsView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.view_ref.data.setdefault("settings", {})
        imgs = list(s.get("image_urls", []) or [])

        try:
            idx = int(str(self.number.value).strip())
        except Exception:
            return await interaction.response.send_message("❌ Enter a valid number.", ephemeral=True)

        if idx < 1 or idx > len(imgs):
            return await interaction.response.send_message("❌ That number doesn’t exist.", ephemeral=True)

        imgs.pop(idx - 1)
        s["image_urls"] = imgs
        await self.view_ref._save_and_refresh(interaction, note=f"🗑️ Removed image #{idx}.")

# =========================================================
# UI: Select Menus
# =========================================================
class BirthdayChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="📣 Set announcement channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: BirthdaySettingsView = self.view  # type: ignore
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        ch = self.values[0]
        view.data.setdefault("settings", {})["channel_id"] = ch.id
        await view._save_and_refresh(interaction, note=f"✅ Channel set to {ch.mention}")


class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="🎂 Set birthday role (optional)…",
            min_values=1,
            max_values=1,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: BirthdaySettingsView = self.view  # type: ignore
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        role = self.values[0]
        if role.is_default():
            return await interaction.response.send_message("❌ You can’t use @everyone.", ephemeral=True)

        view.data.setdefault("settings", {})["birthday_role_id"] = role.id
        await view._save_and_refresh(interaction, note=f"✅ Role set to {role.mention}")

# =========================================================
# UI: Views
# =========================================================
class ImageSettingsView(discord.ui.View):
    def __init__(self, parent: "BirthdaySettingsView"):
        super().__init__(timeout=300)
        self.parent = parent
        self.bot = parent.bot
        self.data = parent.data
        self.sha = parent.sha

    def _embed(self) -> discord.Embed:
        s = self.data.get("settings", {})
        imgs = list(s.get("image_urls", []) or [])

        desc = (
            "These URLs are posted as normal messages (Discord auto-previews).\n"
            "One random image is chosen per birthday announcement.\n\n"
        )
        if imgs:
            preview = "\n".join(f"{i+1}. {u}" for i, u in enumerate(imgs[:15]))
            if len(imgs) > 15:
                preview += f"\n… +{len(imgs)-15} more"
            desc += f"**Saved images:**\n{preview}"
        else:
            desc += "**Saved images:** *(none yet)*"

        return discord.Embed(title="🖼️ Birthday Image Settings", description=desc, color=discord.Color.blurple())

    async def _save_and_refresh(self, interaction: discord.Interaction, note: Optional[str] = None):
        _normalize_state_lists(self.data)
        new_sha = await save_data(self.data, self.sha)
        if new_sha:
            self.sha = new_sha
            self.parent.sha = new_sha  # keep parent in sync

        await interaction.response.edit_message(embed=self._embed(), view=self)
        if note:
            await interaction.followup.send(note, ephemeral=True)

    @discord.ui.button(label="🖼️ Add image", style=discord.ButtonStyle.success)
    async def add_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(AddImageModal(self))

    @discord.ui.button(label="📂 View images", style=discord.ButtonStyle.secondary)
    async def view_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        imgs = list(self.data.get("settings", {}).get("image_urls", []) or [])
        if not imgs:
            return await interaction.response.send_message("No images saved yet.", ephemeral=True)

        # Keep it readable; public list can get spammy, so we cap.
        lines = "\n".join(f"{i+1}. {u}" for i, u in enumerate(imgs[:50]))
        if len(imgs) > 50:
            lines += f"\n… +{len(imgs)-50} more"
        await interaction.response.send_message(f"📂 **Saved birthday images:**\n{lines}", ephemeral=False)

    @discord.ui.button(label="🗑️ Remove image", style=discord.ButtonStyle.danger)
    async def remove_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(RemoveImageModal(self))

    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.parent._embed(), view=self.parent)


class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot: discord.Client, data: dict, sha: Optional[str]):
        super().__init__(timeout=300)
        self.bot = bot
        self.data = data
        self.sha = sha

        # Select menus
        self.add_item(BirthdayChannelSelect())
        self.add_item(BirthdayRoleSelect())

    def _embed(self) -> discord.Embed:
        s = self.data.get("settings", {})
        enabled = bool(s.get("enabled", True))
        announce = bool(s.get("announce", True))
        channel_id = s.get("channel_id")
        role_id = s.get("birthday_role_id")
        hour = _safe_int(s.get("post_hour"), 12)
        minute = _safe_int(s.get("post_minute"), 0)

        channel_str = f"<#{channel_id}>" if channel_id else "Not set"
        role_str = f"<@&{role_id}>" if role_id else "Not set"

        msg_single = str(s.get("message_single", ""))
        msg_multi = str(s.get("message_multiple", ""))
        imgs = list(s.get("image_urls", []) or [])

        e = discord.Embed(
            title="🎂 Birthday Settings",
            description=(
                f"Enabled: {'✅' if enabled else '⛔'}\n"
                f"Announcements: {'✅' if announce else '⛔'}\n"
                f"Channel: {channel_str}\n"
                f"Role: {role_str}\n"
                f"Post time: **{hour:02d}:{minute:02d}** (per-user timezone)\n"
                f"Images saved: **{len(imgs)}**\n\n"
                "Templates are **name-only** (no @mentions are posted):\n"
                "Single uses **{username}** | Multiple uses **{users}** / **{count}**"
            ),
            color=discord.Color.pink()
        )
        e.add_field(name="Single", value=f"```{msg_single}```", inline=False)
        e.add_field(name="Multiple", value=f"```{msg_multi}```", inline=False)
        e.set_footer(text="The Pilot • Birthdays")
        return e

    async def _save_and_refresh(self, interaction: discord.Interaction, note: Optional[str] = None):
        _normalize_state_lists(self.data)
        new_sha = await save_data(self.data, self.sha)
        if new_sha:
            self.sha = new_sha

        await interaction.response.edit_message(embed=self._embed(), view=self)
        if note:
            await interaction.followup.send(note, ephemeral=True)

    @discord.ui.button(label="Toggle enabled", style=discord.ButtonStyle.primary, row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        s = self.data.setdefault("settings", {})
        s["enabled"] = not bool(s.get("enabled", True))
        await self._save_and_refresh(interaction)

    @discord.ui.button(label="Toggle announcements", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_announce(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        s = self.data.setdefault("settings", {})
        s["announce"] = not bool(s.get("announce", True))
        await self._save_and_refresh(interaction)

    @discord.ui.button(label="Edit messages", style=discord.ButtonStyle.success, row=1)
    async def edit_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(BirthdayMessageModal(self))

    @discord.ui.button(label="Set post time", style=discord.ButtonStyle.secondary, row=1)
    async def set_post_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(PostTimeModal(self))

    @discord.ui.button(label="Image Settings", style=discord.ButtonStyle.secondary, row=2)
    async def image_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        view = ImageSettingsView(self)
        await interaction.response.edit_message(embed=view._embed(), view=view)

    @discord.ui.button(label="Send test", style=discord.ButtonStyle.secondary, row=2)
    async def send_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.data.get("settings", {})
        channel_id = s.get("channel_id")
        if not channel_id:
            return await interaction.response.send_message("❌ No birthday channel set.", ephemeral=True)

        channel = interaction.guild.get_channel(int(channel_id)) if interaction.guild else None
        if not channel or not isinstance(channel, discord.abc.Messageable):
            return await interaction.response.send_message("❌ Birthday channel not found.", ephemeral=True)

        today_uk = datetime.now(UK_TZ).date()

        # Real birthdays today (UK date) first
        members: List[discord.Member] = []
        for uid, rec in (self.data.get("birthdays", {}) or {}).items():
            try:
                if int(rec.get("day")) == today_uk.day and int(rec.get("month")) == today_uk.month:
                    m = interaction.guild.get_member(int(uid))
                    if m:
                        members.append(m)
            except Exception:
                continue

        # Fallback if none today
        if not members:
            members = [interaction.user]  # type: ignore[list-item]
            for m in interaction.guild.members:
                if not m.bot and m.id != interaction.user.id:
                    members.append(m)
                    break

        await _send_announcement_like(
            channel=channel,
            settings=s,
            members=members,
            local_date=today_uk,
            tz_label="Europe/London",
            test_mode=True
        )

        await interaction.response.send_message("✅ Test sent.", ephemeral=True)

    @discord.ui.button(label="Export birthdays", style=discord.ButtonStyle.danger, row=3)
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
        fp = io.BytesIO(content.encode("utf-8"))
        file = discord.File(fp=fp, filename="birthdays_export.txt")
        await interaction.response.send_message("✅ Export:", file=file, ephemeral=False)

# =========================================================
# Main Setup + Commands + Background Task
# =========================================================
def setup(bot: discord.Client):
    tree = bot.tree

    birthday_group = app_commands.Group(name="birthday", description="Birthday commands")
    try:
        tree.add_command(birthday_group)
    except Exception:
        pass  # already added

    # ------------------- Commands -------------------
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
            return await interaction.response.send_message("❌ Invalid timezone.", ephemeral=True)

        target = user or interaction.user
        if user and not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission to set for others.", ephemeral=True)

        data, sha = await load_data()
        data.setdefault("birthdays", {})
        data["birthdays"][str(target.id)] = {"day": int(day), "month": int(month), "timezone": tz}
        _normalize_state_lists(data)
        await save_data(data, sha)

        who = "your" if target.id == interaction.user.id else f"{target.mention}'s"
        await interaction.response.send_message(
            f"✅ Set {who} birthday to **{day:02d}/{month:02d}** in **{tz}**.",
            ephemeral=False
        )

    @birthday_group.command(name="view", description="View someone’s birthday.")
    @app_commands.describe(user="User to view")
    async def birthday_view(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        data, _ = await load_data()
        rec = (data.get("birthdays", {}) or {}).get(str(target.id))
        if not rec:
            return await interaction.response.send_message("No birthday set for that user.", ephemeral=True)

        dayv = int(rec.get("day", 0))
        monthv = int(rec.get("month", 0))
        tz = str(rec.get("timezone", "Europe/London"))
        await interaction.response.send_message(
            f"🎂 **{target.display_name}** — **{dayv:02d}/{monthv:02d}** (`{tz}`)",
            ephemeral=False
        )

    @birthday_group.command(name="remove", description="Remove a birthday.")
    @app_commands.describe(user="Optional: remove someone else")
    async def birthday_remove(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user

        if user and not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission to remove for others.", ephemeral=True)

        data, sha = await load_data()
        bds = data.get("birthdays", {}) or {}

        if str(target.id) not in bds:
            return await interaction.response.send_message("No birthday set to remove.", ephemeral=True)

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
            return await interaction.response.send_message("No birthdays saved yet.", ephemeral=True)

        today_uk = datetime.now(UK_TZ).date()
        entries: List[Tuple[int, date, str, str]] = []

        for uid, rec in bds.items():
            try:
                d = int(rec.get("day"))
                m = int(rec.get("month"))
                tz = str(rec.get("timezone"))
            except Exception:
                continue

            nxt = _next_occurrence(d, m, today_uk)
            delta = (nxt - today_uk).days
            if 0 <= delta <= int(days):
                entries.append((delta, nxt, uid, tz))

        if not entries:
            return await interaction.response.send_message(f"No birthdays in the next {days} days.", ephemeral=False)

        entries.sort(key=lambda x: (x[0], x[1].month, x[1].day))

        guild = interaction.guild
        lines = []
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

    @birthday_group.command(name="settings", description="Configure birthday settings.")
    async def birthday_settings(interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        data, sha = await load_data()
        view = BirthdaySettingsView(bot, data, sha)
        await interaction.response.send_message(embed=view._embed(), view=view, ephemeral=False)

    # ------------------- Background Task -------------------
    @tasks.loop(minutes=1)
    async def birthday_tick():
        # Run every minute so "post_hour:post_minute" works properly
        now_utc = datetime.now(timezone.utc)

        for guild in bot.guilds:
            try:
                data, sha = await load_data()
                s = data.get("settings", {})
                if not bool(s.get("enabled", True)):
                    continue

                bds = data.get("birthdays", {}) or {}
                if not bds:
                    continue

                _normalize_state_lists(data)
                announced = set(data["state"].get("announced_keys", []))
                role_assigned = set(data["state"].get("role_assigned_keys", []))

                channel = guild.get_channel(s.get("channel_id")) if s.get("channel_id") else None
                if not channel or not isinstance(channel, discord.abc.Messageable):
                    continue

                role = guild.get_role(s.get("birthday_role_id")) if s.get("birthday_role_id") else None
                do_announce = bool(s.get("announce", True))

                post_h = _safe_int(s.get("post_hour"), 12)
                post_m = _safe_int(s.get("post_minute"), 0)

                # bucket: date_key -> list[members], plus a tz label
                buckets: Dict[str, List[discord.Member]] = {}
                bucket_tz: Dict[str, str] = {}

                for uid, rec in bds.items():
                    member = guild.get_member(int(uid))
                    if not member:
                        continue

                    tz = str(rec.get("timezone", "Europe/London"))
                    if not _is_valid_tz(tz):
                        continue

                    local_now = now_utc.astimezone(ZoneInfo(tz))
                    local_date = local_now.date()

                    # ---- role assign/remove (per-user local date) ----
                    is_bday = (
                        int(rec.get("day", 0)) == local_date.day
                        and int(rec.get("month", 0)) == local_date.month
                    )

                    if role:
                        key = f"{local_date.isoformat()}|{uid}"

                        if is_bday:
                            if key not in role_assigned:
                                try:
                                    await member.add_roles(role, reason="Birthday role")
                                    role_assigned.add(key)
                                except Exception:
                                    pass
                        else:
                            # auto-clean after midnight in their TZ
                            if role in member.roles:
                                try:
                                    await member.remove_roles(role, reason="Birthday role expired")
                                except Exception:
                                    pass

                    # ---- announcement scheduling (per-user local time) ----
                    if not do_announce:
                        continue

                    if is_bday and local_now.hour == post_h and local_now.minute == post_m:
                        dk = local_date.isoformat()
                        buckets.setdefault(dk, []).append(member)
                        # best label: single -> their tz, multi -> "Multiple timezones"
                        if dk not in bucket_tz:
                            bucket_tz[dk] = tz
                        else:
                            if bucket_tz[dk] != tz:
                                bucket_tz[dk] = "Multiple timezones"

                # ---- send announcements (one per date bucket) ----
                for date_key, members in buckets.items():
                    announce_key = f"{date_key}|announce"
                    if announce_key in announced:
                        continue

                    try:
                        await _send_announcement_like(
                            channel=channel,
                            settings=s,
                            members=members,
                            local_date=date.fromisoformat(date_key),
                            tz_label=bucket_tz.get(date_key, "Europe/London"),
                            test_mode=False
                        )
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

    if not getattr(bot, "_birthday_tick_started", False):
        birthday_tick.start()
        setattr(bot, "_birthday_tick_started", True)
