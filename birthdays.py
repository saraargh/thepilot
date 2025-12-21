# birthday.py
from __future__ import annotations

import os
import json
import base64
import asyncio
import io
import random
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import tasks
from zoneinfo import ZoneInfo, available_timezones

from permissions import has_app_access


# =========================================================
# GitHub Config
# =========================================================
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = os.getenv("BIRTHDAYS_GITHUB_FILE", "birthdays.json")  # optional override
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
GITHUB_API_BASE = "https://api.github.com"

UK_TZ = ZoneInfo("Europe/London")


# =========================================================
# Default JSON
# =========================================================
DEFAULT_DATA: Dict[str, Any] = {
    "settings": {
        "enabled": True,
        "channel_id": None,
        "birthday_role_id": None,
        "announce": True,
        "message_single": "🎂 Happy Birthday {user}! ✈️",
        "message_multiple": "🎉 Happy Birthday {users}! 🎂",
        # Image URLs (posted as plain URLs; Discord will auto-preview)
        "images": []
    },
    "birthdays": {
        # "user_id_str": {"day": 21, "month": 3, "timezone": "Europe/London"}
    },
    "state": {
        # list of "YYYY-MM-DD|announce" (date in the birthday person's local date)
        "announced_keys": [],
        # list of "YYYY-MM-DD|user_id" (date in the birthday person's local date)
        "role_assigned_keys": []
    }
}


# =========================================================
# GitHub JSON Helpers (requests wrapped in to_thread to avoid blocking)
# =========================================================
_lock = asyncio.Lock()


def _gh_get_file_sync() -> Tuple[Optional[dict], Optional[str]]:
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


def _gh_put_file_sync(data: dict, sha: Optional[str]) -> Optional[str]:
    if not GITHUB_TOKEN:
        return None

    import requests
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

    raw = json.dumps(data, indent=2, ensure_ascii=False)
    content_b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    body = (
        {"message": f"Update {GITHUB_FILE_PATH}", "content": content_b64, "sha": sha}
        if sha
        else {"message": f"Create {GITHUB_FILE_PATH}", "content": content_b64}
    )

    r = requests.put(url, headers=HEADERS, json=body, timeout=25)
    r.raise_for_status()
    return r.json().get("content", {}).get("sha")


async def load_data() -> Tuple[dict, Optional[str]]:
    async with _lock:
        data, sha = await asyncio.to_thread(_gh_get_file_sync)

        if not data:
            return json.loads(json.dumps(DEFAULT_DATA)), sha

        merged = json.loads(json.dumps(DEFAULT_DATA))
        merged.update(data)

        merged["settings"] = {**DEFAULT_DATA["settings"], **(data.get("settings") or {})}
        merged["birthdays"] = data.get("birthdays") or {}
        merged["state"] = {**DEFAULT_DATA["state"], **(data.get("state") or {})}

        # ensure types
        merged["settings"]["images"] = list(merged["settings"].get("images") or [])
        merged["state"]["announced_keys"] = list(merged["state"].get("announced_keys") or [])
        merged["state"]["role_assigned_keys"] = list(merged["state"].get("role_assigned_keys") or [])

        _normalize_state_lists(merged)
        return merged, sha


async def save_data(data: dict, sha: Optional[str]) -> Optional[str]:
    async with _lock:
        _normalize_state_lists(data)
        return await asyncio.to_thread(_gh_put_file_sync, data, sha)


# =========================================================
# Utility
# =========================================================
_TZ_CACHE: Optional[List[str]] = None


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
    st["announced_keys"] = list(st.get("announced_keys") or [])[-2000:]
    st["role_assigned_keys"] = list(st.get("role_assigned_keys") or [])[-2000:]


def _get_all_timezones() -> List[str]:
    global _TZ_CACHE
    if _TZ_CACHE is None:
        _TZ_CACHE = sorted(list(available_timezones()))
    return _TZ_CACHE


async def timezone_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
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


def _pick_image_url(settings: dict) -> Optional[str]:
    urls = [u.strip() for u in (settings.get("images") or []) if isinstance(u, str) and u.strip()]
    return random.choice(urls) if urls else None


def _format_single(tpl: str, *, username: str, mention: str, local_date: date, tz: str) -> str:
    # {user} = username (display_name), {mention} = @mention
    return (
        (tpl or "")
        .replace("{user}", username)
        .replace("{username}", username)
        .replace("{mention}", mention)
        .replace("{date}", local_date.strftime("%-d %B"))
        .replace("{timezone}", tz)
    )


def _format_multiple(tpl: str, *, usernames: str, mentions: str, count: int) -> str:
    # {users} = usernames, {mentions} = @mentions, {count} = count
    return (
        (tpl or "")
        .replace("{users}", usernames)
        .replace("{mentions}", mentions)
        .replace("{count}", str(count))
    )


def _next_occurrence(day: int, month: int, now_local: date) -> date:
    year = now_local.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        candidate = date(year, month, 1)

    if candidate < now_local:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            candidate = date(year + 1, month, 1)

    return candidate


# =========================================================
# Modals
# =========================================================
class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Messages"):
    single_message = discord.ui.TextInput(
        label="Single birthday message",
        style=discord.TextStyle.paragraph,
        required=True,
        placeholder="Use {user} for username (mentions are sent automatically)"
    )
    multiple_message = discord.ui.TextInput(
        label="Multiple birthdays message",
        style=discord.TextStyle.paragraph,
        required=True,
        placeholder="Use {users} for usernames (mentions are sent automatically)"
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
        s["message_single"] = self.single_message.value
        s["message_multiple"] = self.multiple_message.value
        await self.view_ref._save_and_refresh(interaction)


class AddImageModal(discord.ui.Modal, title="Add Birthday Image"):
    url = discord.ui.TextInput(
        label="Image URL",
        style=discord.TextStyle.short,
        required=True,
        placeholder="https://..."
    )

    def __init__(self, view: "BirthdayImageSettingsView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        u = str(self.url.value).strip()
        if not (u.startswith("http://") or u.startswith("https://")):
            return await interaction.response.send_message("❌ Please paste a valid http(s) URL.", ephemeral=True)

        imgs = self.view_ref.data.setdefault("settings", {}).setdefault("images", [])
        imgs.append(u)

        await self.view_ref._save(interaction, message="✅ Image added.", ephemeral=True)


class RemoveImageModal(discord.ui.Modal, title="Remove Birthday Image"):
    number = discord.ui.TextInput(
        label="Image number to remove",
        style=discord.TextStyle.short,
        required=True,
        placeholder="e.g. 1"
    )

    def __init__(self, view: "BirthdayImageSettingsView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        try:
            idx = int(str(self.number.value).strip()) - 1
        except Exception:
            return await interaction.response.send_message("❌ Enter a valid number.", ephemeral=True)

        imgs = self.view_ref.data.setdefault("settings", {}).setdefault("images", [])
        if idx < 0 or idx >= len(imgs):
            return await interaction.response.send_message("❌ That number doesn’t exist.", ephemeral=True)

        removed = imgs.pop(idx)
        await self.view_ref._save(interaction, message=f"✅ Removed image #{idx+1}.", ephemeral=True)


# =========================================================
# Select Menus
# =========================================================
class BirthdayChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="📣 Set announcement channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: BirthdaySettingsView = self.view  # type: ignore

        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        channel = self.values[0]
        view.data.setdefault("settings", {})["channel_id"] = channel.id
        await view._save_and_refresh(interaction)


class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="🎂 Set birthday role (optional)…",
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
        await view._save_and_refresh(interaction)


# =========================================================
# Image Settings View
# =========================================================
class BirthdayImageSettingsView(discord.ui.View):
    def __init__(self, parent: "BirthdaySettingsView"):
        super().__init__(timeout=300)
        self.parent = parent
        self.data = parent.data
        self.sha = parent.sha

    def _count(self) -> int:
        return len(self.data.get("settings", {}).get("images", []) or [])

    async def _save(self, interaction: discord.Interaction, *, message: str, ephemeral: bool):
        new_sha = await save_data(self.data, self.sha)
        if new_sha:
            self.sha = new_sha
            self.parent.sha = new_sha

        # Keep parent view up to date too
        await interaction.response.send_message(message, ephemeral=ephemeral)
        try:
            await self.parent.message_ref.edit(content=self.parent._render_text(), view=self.parent)  # type: ignore
        except Exception:
            pass

    @discord.ui.button(label="🖼️ Add image", style=discord.ButtonStyle.success)
    async def add_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(AddImageModal(self))

    @discord.ui.button(label="📂 View images", style=discord.ButtonStyle.secondary)
    async def view_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        imgs = self.data.get("settings", {}).get("images", []) or []
        if not imgs:
            return await interaction.response.send_message("No images saved yet.", ephemeral=True)

        lines = []
        for i, u in enumerate(imgs, start=1):
            lines.append(f"**{i}.** {u}")

        # Ephemeral list (numbered). URLs will auto-preview in Discord.
        await interaction.response.send_message("\n".join(lines[:50]), ephemeral=True)

    @discord.ui.button(label="🗑️ Remove image", style=discord.ButtonStyle.danger)
    async def remove_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(RemoveImageModal(self))

    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.edit_message(content=self.parent._render_text(), view=self.parent)
        except Exception:
            await interaction.response.send_message("✅ Back.", ephemeral=True)


# =========================================================
# Main Settings View
# =========================================================
class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot: discord.Client, data: dict, sha: Optional[str]):
        super().__init__(timeout=300)
        self.bot = bot
        self.data = data
        self.sha = sha
        self.message_ref: Optional[discord.Message] = None  # set after send

        # “the way it was before” = proper select menus
        self.add_item(BirthdayChannelSelect())
        self.add_item(BirthdayRoleSelect())

    def _render_text(self) -> str:
        s = self.data.get("settings", {})
        enabled = bool(s.get("enabled", True))
        announce = bool(s.get("announce", True))
        channel_id = s.get("channel_id")
        role_id = s.get("birthday_role_id")
        images = s.get("images", []) or []

        channel_str = f"<#{channel_id}>" if channel_id else "Not set"
        role_str = f"<@&{role_id}>" if role_id else "Not set"

        single = str(s.get("message_single", ""))
        multi = str(s.get("message_multiple", ""))

        return (
            "🎂 **Birthday Settings**\n"
            f"Enabled: {'✅' if enabled else '⛔'}\n"
            f"Announcements: {'✅' if announce else '⛔'}\n"
            f"Channel: {channel_str}\n"
            f"Role: {role_str}\n"
            f"Images: **{len(images)}** saved\n\n"
            "**Single:**\n"
            f"{single}\n\n"
            "**Multiple:**\n"
            f"{multi}"
        )

    async def _save_and_refresh(self, interaction: discord.Interaction):
        new_sha = await save_data(self.data, self.sha)
        if new_sha:
            self.sha = new_sha
        await interaction.response.edit_message(content=self._render_text(), view=self)

    @discord.ui.button(label="Toggle enabled", style=discord.ButtonStyle.primary)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        s = self.data.setdefault("settings", {})
        s["enabled"] = not bool(s.get("enabled", True))
        await self._save_and_refresh(interaction)

    @discord.ui.button(label="Toggle announcements", style=discord.ButtonStyle.secondary)
    async def toggle_announce(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        s = self.data.setdefault("settings", {})
        s["announce"] = not bool(s.get("announce", True))
        await self._save_and_refresh(interaction)

    @discord.ui.button(label="Edit messages", style=discord.ButtonStyle.success)
    async def edit_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(BirthdayMessageModal(self))

    @discord.ui.button(label="Image settings", style=discord.ButtonStyle.secondary)
    async def image_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.edit_message(
            content=f"🖼️ **Image Settings** (saved: {len(self.data.get('settings', {}).get('images', []) or [])})",
            view=BirthdayImageSettingsView(self)
        )

    @discord.ui.button(label="Export all birthdays", style=discord.ButtonStyle.danger)
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

    @discord.ui.button(label="Send test announcement", style=discord.ButtonStyle.secondary)
    async def test_announcement(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        s = self.data.get("settings", {})
        channel_id = s.get("channel_id")
        if not channel_id:
            return await interaction.response.send_message("❌ No birthday channel set.", ephemeral=True)

        channel = interaction.guild.get_channel(int(channel_id)) if interaction.guild else None
        if not isinstance(channel, discord.abc.Messageable):
            return await interaction.response.send_message("❌ Birthday channel not found.", ephemeral=True)

        today_uk = datetime.now(UK_TZ).date()

        # Try real birthdays today (UK date) first
        members: List[discord.Member] = []
        for uid, rec in (self.data.get("birthdays", {}) or {}).items():
            if int(rec.get("day", 0)) == today_uk.day and int(rec.get("month", 0)) == today_uk.month:
                m = interaction.guild.get_member(int(uid))
                if m:
                    members.append(m)

        # Fallback if none today
        if not members:
            members = [interaction.user]  # type: ignore
            for m in interaction.guild.members:
                if not m.bot and m.id != interaction.user.id:
                    members.append(m)
                    break

        mentions = " ".join(m.mention for m in members)
        usernames = ", ".join(m.display_name for m in members)

        if len(members) == 1:
            text = _format_single(
                s.get("message_single", ""),
                username=members[0].display_name,
                mention=members[0].mention,
                local_date=today_uk,
                tz="Europe/London"
            )
        else:
            text = _format_multiple(
                s.get("message_multiple", ""),
                usernames=usernames,
                mentions=mentions,
                count=len(members)
            )

        # Mentions outside (as requested)
        await channel.send(f"🧪 **TEST MODE**\n{mentions}\n{text}")

        img = _pick_image_url(s)
        if img:
            await channel.send(img)

        await interaction.response.send_message("✅ Test sent.", ephemeral=True)


# =========================================================
# Main Setup + Commands + Background Task
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
            return await interaction.response.send_message("❌ Invalid timezone. Pick one from autocomplete.", ephemeral=True)

        target = user or interaction.user
        if user and not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission to set for others.", ephemeral=True)

        data, sha = await load_data()
        data.setdefault("birthdays", {})
        data["birthdays"][str(target.id)] = {"day": int(day), "month": int(month), "timezone": tz}
        new_sha = await save_data(data, sha)

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

        day = int(rec.get("day", 0))
        month = int(rec.get("month", 0))
        tz = str(rec.get("timezone", "Europe/London"))

        await interaction.response.send_message(
            f"🎂 **{target.display_name}** — **{day:02d}/{month:02d}** (`{tz}`)",
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
        await save_data(data, sha)

        await interaction.response.send_message("✅ Birthday removed.", ephemeral=False)

    @birthday_group.command(name="upcoming", description="Show upcoming birthdays.")
    @app_commands.describe(days="How many days ahead (default 14)")
    async def birthday_upcoming(interaction: discord.Interaction, days: app_commands.Range[int, 1, 60] = 14):
        data, _ = await load_data()
        bds: Dict[str, Any] = data.get("birthdays", {}) or {}
        if not bds:
            return await interaction.response.send_message("No birthdays saved yet.", ephemeral=True)

        today_uk = datetime.now(UK_TZ).date()
        entries = []

        for uid, rec in bds.items():
            try:
                d = int(rec.get("day"))
                m = int(rec.get("month"))
                tz = str(rec.get("timezone"))
            except Exception:
                continue

            next_dt = _next_occurrence(d, m, today_uk)
            delta = (next_dt - today_uk).days
            if 0 <= delta <= int(days):
                entries.append((delta, next_dt, uid, tz))

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

        await interaction.response.send_message("🎂 **Upcoming Birthdays**\n" + "\n".join(lines), ephemeral=False)

    @birthday_group.command(name="settings", description="Configure birthday settings (Pilot roles only).")
    async def birthday_settings(interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        data, sha = await load_data()
        view = BirthdaySettingsView(bot, data, sha)
        await interaction.response.send_message(content=view._render_text(), view=view, ephemeral=False)

        # store message ref for later refreshes from image settings
        try:
            view.message_ref = await interaction.original_response()
        except Exception:
            view.message_ref = None

    # ------------------- Background Task -------------------
    @tasks.loop(minutes=15)
    async def birthday_tick():
        for guild in bot.guilds:
            try:
                data, sha = await load_data()
                s = data.get("settings", {})
                if not bool(s.get("enabled", True)):
                    continue

                bds = data.get("birthdays", {}) or {}
                if not bds:
                    continue

                announced = set(data.get("state", {}).get("announced_keys", []) or [])
                role_assigned = set(data.get("state", {}).get("role_assigned_keys", []) or [])

                channel = guild.get_channel(s.get("channel_id")) if s.get("channel_id") else None
                role = guild.get_role(s.get("birthday_role_id")) if s.get("birthday_role_id") else None
                do_announce = bool(s.get("announce", True))

                now_utc = datetime.now(timezone.utc)

                # map local_date_iso -> list[members]
                today_birthdays: Dict[str, List[discord.Member]] = {}

                for uid, rec in bds.items():
                    member = guild.get_member(int(uid))
                    if not member:
                        continue

                    tz = str(rec.get("timezone", "Europe/London"))
                    if not _is_valid_tz(tz):
                        continue

                    local_now = now_utc.astimezone(ZoneInfo(tz))
                    local_date = local_now.date()

                    is_bday = (int(rec.get("day", 0)) == local_date.day and int(rec.get("month", 0)) == local_date.month)

                    if is_bday:
                        today_birthdays.setdefault(local_date.isoformat(), []).append(member)

                    # Role assign/remove keyed by PERSON'S local date
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
                            # This is your “auto-cleanup after midnight per-user TZ”
                            if role in member.roles:
                                try:
                                    await member.remove_roles(role, reason="Birthday role expired")
                                except Exception:
                                    pass

                # Announcements (mentions outside, usernames inside)
                for date_key, members in today_birthdays.items():
                    announce_key = f"{date_key}|announce"
                    if not do_announce or not channel or announce_key in announced:
                        continue

                    mentions = " ".join(m.mention for m in members)
                    usernames = ", ".join(m.display_name for m in members)

                    if len(members) == 1:
                        uid = str(members[0].id)
                        tz = str((bds.get(uid) or {}).get("timezone", "Europe/London"))
                        text = _format_single(
                            s.get("message_single", ""),
                            username=members[0].display_name,
                            mention=members[0].mention,
                            local_date=date.fromisoformat(date_key),
                            tz=tz
                        )
                    else:
                        text = _format_multiple(
                            s.get("message_multiple", ""),
                            usernames=usernames,
                            mentions=mentions,
                            count=len(members)
                        )

                    try:
                        await channel.send(f"{mentions}\n{text}")
                        img = _pick_image_url(s)
                        if img:
                            await channel.send(img)
                        announced.add(announce_key)
                    except Exception:
                        pass

                data.setdefault("state", {})["announced_keys"] = list(announced)
                data.setdefault("state", {})["role_assigned_keys"] = list(role_assigned)
                await save_data(data, sha)

            except Exception:
                continue

    @birthday_tick.before_loop
    async def before_birthday_tick():
        await bot.wait_until_ready()

    # Start once
    if not getattr(bot, "_birthday_tick_started", False):
        birthday_tick.start()
        setattr(bot, "_birthday_tick_started", True)