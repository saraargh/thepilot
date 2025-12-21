# birthday.py
from __future__ import annotations

import os
import json
import base64
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
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
        "channel_id": None,
        "birthday_role_id": None,
        "announce": True,
        "message_single": "🎂 Happy Birthday {user}! ✈️",
        "message_multiple": "🎉 Happy Birthday {users}! 🎂"
    },
    "birthdays": {
        # "user_id_str": {"day": 21, "month": 3, "timezone": "Europe/London"}
    },
    # Prevent duplicate posts / track role assignments we applied
    "state": {
        "announced_keys": [],        # list of "YYYY-MM-DD|user_id" (in user's local date)
        "role_assigned_keys": []     # list of "YYYY-MM-DD|user_id" (in user's local date)
    }
}


# ------------------- GitHub JSON Helpers -------------------
async def _gh_get_file() -> Tuple[Optional[dict], Optional[str]]:
    """Return (json_data, sha) from GitHub. If not found, returns (None, None)."""
    if not GITHUB_TOKEN:
        return None, None

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    import requests
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

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    import requests

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


_lock = asyncio.Lock()


async def load_data() -> Tuple[dict, Optional[str]]:
    async with _lock:
        data, sha = await _gh_get_file()
        if not data:
            # Use defaults (but do not auto-write unless a save happens)
            return json.loads(json.dumps(DEFAULT_DATA)), sha
        # Merge defaults safely (in case you add keys later)
        merged = json.loads(json.dumps(DEFAULT_DATA))
        merged.update(data)
        merged["settings"] = {**DEFAULT_DATA["settings"], **data.get("settings", {})}
        merged["birthdays"] = data.get("birthdays", {}) or {}
        merged["state"] = {**DEFAULT_DATA["state"], **data.get("state", {})}
        # Ensure lists exist
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
    # Keep them bounded so file doesn’t grow forever
    st["announced_keys"] = st["announced_keys"][-2000:]
    st["role_assigned_keys"] = st["role_assigned_keys"][-2000:]


def _fmt_template(tpl: str, *, member: discord.Member, local_date: date, tz: str) -> str:
    return (
        tpl.replace("{user}", member.mention)
           .replace("{username}", member.display_name)
           .replace("{date}", local_date.strftime("%-d %B") if hasattr(local_date, "strftime") else str(local_date))
           .replace("{timezone}", tz)
    )


def _next_occurrence(day: int, month: int, now_local: date) -> date:
    # Find next occurrence from now_local date, year-aware
    year = now_local.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        # Invalid date like 31 Feb -> treat as 1 Mar (you can decide policy later)
        candidate = date(year, month, 1)
    if candidate < now_local:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            candidate = date(year + 1, month, 1)
    return candidate

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

    # Simple scoring: contains / startswith
    matches: List[str] = []
    if not cur:
        # Common ones first
        common = ["Europe/London", "Europe/Paris", "America/New_York", "America/Los_Angeles", "Australia/Sydney", "UTC"]
        for c in common:
            if c in tzs:
                matches.append(c)
        # fill with Europe/… as a gentle default
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


#dualmodal#

class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Messages"):
    single_message = discord.ui.TextInput(
        label="Single birthday message",
        style=discord.TextStyle.paragraph,
        required=True
    )

    multiple_message = discord.ui.TextInput(
        label="Multiple birthdays message",
        style=discord.TextStyle.paragraph,
        required=True
    )

    def __init__(self, data: dict):
        super().__init__()
        self.data = data
        s = data.get("settings", {})
        self.single_message.default = s.get("message_single", "")
        self.multiple_message.default = s.get("message_multiple", "")

    async def on_submit(self, interaction: discord.Interaction):
        s = self.data.setdefault("settings", {})
        s["message_single"] = self.single_message.value
        s["message_multiple"] = self.multiple_message.value
    
        # persist
        data, sha = await load_data()
        data["settings"].update(s)
        await save_data(data, sha)
    
        await interaction.response.send_message(
            "✅ Birthday messages updated.",
            ephemeral=True
        )
###select channel and role###

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
            return await interaction.response.send_message(
                "❌ You don’t have permission to manage birthdays.",
                ephemeral=True
            )

        channel = self.values[0]
        view.data.setdefault("settings", {})["channel_id"] = channel.id

        await view._save_and_refresh(interaction)


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
            return await interaction.response.send_message(
                "❌ You don’t have permission to manage birthdays.",
                ephemeral=True
            )

        role = self.values[0]
        if role.is_default():
            return await interaction.response.send_message(
                "❌ You can’t use @everyone.",
                ephemeral=True
            )

        view.data.setdefault("settings", {})["birthday_role_id"] = role.id
        await view._save_and_refresh(interaction)

# ------------------- Settings View -------------------

class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot: discord.Client, data: dict, sha: Optional[str]):
        super().__init__(timeout=300)
        self.bot = bot
        self.data = data
        self.sha = sha

        # ✅ Add selects
        self.add_item(BirthdayChannelSelect())
        self.add_item(BirthdayRoleSelect())

    def _embed(self) -> discord.Embed:
        s = self.data.get("settings", {})
        enabled = s.get("enabled", True)
        channel_id = s.get("channel_id")
        role_id = s.get("birthday_role_id")
        announce = s.get("announce", True)
        msg = (
            f"Single:\n{s.get('message_single')}\n\n"
            f"Multiple:\n{s.get('message_multiple')}"
        )

        channel_str = f"<#{channel_id}>" if channel_id else "Not set"
        role_str = f"<@&{role_id}>" if role_id else "Not set"
        onoff = "✅ Enabled" if enabled else "⛔ Disabled"
        ann = "✅ Announcements ON" if announce else "⛔ Announcements OFF"

        e = discord.Embed(
            title="🎂 Pilot Birthdays Settings",
            description=f"{onoff}\n{ann}",
            color=discord.Color.pink()
        )
        e.add_field(name="Announcement channel", value=channel_str, inline=False)
        e.add_field(name="Birthday role", value=role_str, inline=False)
        e.add_field(name="Message template", value=f"```{msg}```", inline=False)
        e.set_footer(text="The Pilot • Birthdays")
        return e

    async def _save_and_refresh(self, interaction: discord.Interaction):
        _normalize_state_lists(self.data)
        new_sha = await save_data(self.data, self.sha)
        if new_sha:
            self.sha = new_sha
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Toggle enabled", style=discord.ButtonStyle.primary)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to manage birthdays.",
                ephemeral=True
            )
        s = self.data.setdefault("settings", {})
        s["enabled"] = not bool(s.get("enabled", True))
        await self._save_and_refresh(interaction)

    @discord.ui.button(label="Toggle announcements", style=discord.ButtonStyle.secondary)
    async def toggle_announce(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to manage birthdays.",
                ephemeral=True
                )

        s = self.data.setdefault("settings", {})
        s["announce"] = not bool(s.get("announce", True))
        await self._save_and_refresh(interaction)

    @discord.ui.button(label="Edit birthday messages", style=discord.ButtonStyle.success)
    async def edit_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to manage birthdays.",
                ephemeral=True
            )
        
        modal = BirthdayMessageModal(self.data)
        await interaction.response.send_modal(modal)
        
    @discord.ui.button(label="Export all birthdays", style=discord.ButtonStyle.danger)
    async def export_birthdays(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to manage birthdays.",
                ephemeral=True
            )
            
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
        await interaction.response.send_message("✅ Export:", file=file, ephemeral=True)


# ------------------- Main Setup -------------------
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
                ephemeral=True
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
            ephemeral=True
        )

    @birthday_group.command(name="view", description="View someone’s birthday.")
    @app_commands.describe(user="The user whose birthday you want to view")
    async def view_birthday(
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None
    ):
        target = user or interaction.user

        data, _ = await load_data()
        rec = (data.get("birthdays", {}) or {}).get(str(target.id))

        if not rec:
            if target.id == interaction.user.id:
                return await interaction.response.send_message(
                    "You haven’t set your birthday yet. Use `/birthday set`.",
                    ephemeral=True
                    )
            return await interaction.response.send_message(
                "That user hasn’t set their birthday yet.",
                ephemeral=True
            )

        day = int(rec.get("day", 0))
        month = int(rec.get("month", 0))
        tz = rec.get("timezone", "Europe/London")

        await interaction.response.send_message(
            f"🎂 **{target.display_name}** — **{day:02d}/{month:02d}** (`{tz}`)",
            ephemeral=True
        )

    @birthday_group.command(name="remove", description="Remove a birthday.")
    @app_commands.describe(user="Optional: remove someone else")
    async def birthday_remove(
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None
    ):
        target = user or interaction.user
    
        if user and not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to remove birthdays for other members.",
                ephemeral=True
            )
    
        data, sha = await load_data()
        bds = data.get("birthdays", {}) or {}
    
        if str(target.id) not in bds:
            return await interaction.response.send_message(
                "No birthday set to remove.",
                ephemeral=True
            )
    
        del bds[str(target.id)]
        data["birthdays"] = bds
        _normalize_state_lists(data)
        await save_data(data, sha)
    
        await interaction.response.send_message("✅ Birthday removed.", ephemeral=True)
        
    @birthday_group.command(name="upcoming", description="Show upcoming birthdays.")
    @app_commands.describe(days="How many days ahead (default 14)")
    async def upcoming_birthdays(interaction: discord.Interaction, days: app_commands.Range[int, 1, 60] = 14):
        data, _ = await load_data()
        bds: Dict[str, Any] = data.get("birthdays", {}) or {}
        if not bds:
            return await interaction.response.send_message("No birthdays saved yet.", ephemeral=True)

        # We’ll display upcoming relative to UK date for a consistent server timeline
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
            return await interaction.response.send_message(f"No birthdays in the next {days} days.", ephemeral=True)

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
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @birthday_group.command(name="settings", description="Configure birthday settings (Pilot roles only).")
    async def birthdaysettings(interaction: discord.Interaction):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to manage birthdays.",
                ephemeral=True
            )

        data, sha = await load_data()
        view = BirthdaySettingsView(bot, data, sha)
        await interaction.response.send_message(embed=view._embed(), view=view, ephemeral=True)

    @birthday_group.command(name="test", description="Force-test birthday announcements.")
    @app_commands.describe(mode="Use 'today' to simulate today's birthdays")
    async def birthday_test(interaction: discord.Interaction, mode: str):
        if not has_app_access(interaction.user, "birthdays"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to test birthdays.",
                ephemeral=True
            )
    
        if mode.lower() != "today":
            return await interaction.response.send_message(
                "Only supported mode is `today`.",
                ephemeral=True
            )
    
        data, _ = await load_data()
        s = data.get("settings", {})
        channel_id = s.get("channel_id")
    
        if not channel_id:
            return await interaction.response.send_message(
                "❌ No birthday channel set.",
                ephemeral=True
            )
    
        channel = interaction.guild.get_channel(int(channel_id))
        if not channel:
            return await interaction.response.send_message(
                "❌ Birthday channel not found.",
                ephemeral=True
            )
    
        today = datetime.now(UK_TZ).date()
        members = []
    
        for uid, rec in data.get("birthdays", {}).items():
            if rec.get("day") == today.day and rec.get("month") == today.month:
                m = interaction.guild.get_member(int(uid))
                if m:
                    members.append(m)
    
        if not members:
            return await interaction.response.send_message(
                "No birthdays today to test.",
                ephemeral=True
            )
    
        if len(members) == 1:
            tpl = s.get("message_single")
            text = _fmt_template(tpl, member=members[0], local_date=today, tz="Europe/London")
        else:
            tpl = s.get("message_multiple")
            text = tpl.replace("{users}", ", ".join(m.mention for m in members))
    
        await channel.send(f"🧪 **TEST MODE**\n{text}")
        await interaction.response.send_message("✅ Test sent.", ephemeral=True)


    # ------------------- Background Task -------------------
    @tasks.loop(minutes=15)
    async def birthday_tick():
        for guild in bot.guilds:
            try:
                data, sha = await load_data()
                s = data.get("settings", {})
                if not s.get("enabled", True):
                    continue
    
                bds = data.get("birthdays", {})
                if not bds:
                    continue
    
                _normalize_state_lists(data)
                announced = set(data["state"].get("announced_keys", []))
                role_assigned = set(data["state"].get("role_assigned_keys", []))
    
                channel = guild.get_channel(s.get("channel_id")) if s.get("channel_id") else None
                role = guild.get_role(s.get("birthday_role_id")) if s.get("birthday_role_id") else None
                do_announce = bool(s.get("announce", True))
    
                now_utc = datetime.now(timezone.utc)
    
                # ---- collect birthdays by local date ----
                today_birthdays: Dict[str, List[discord.Member]] = {}
    
                for uid, rec in bds.items():
                    member = guild.get_member(int(uid))
                    if not member:
                        continue
    
                    tz = rec.get("timezone", "Europe/London")
                    if not _is_valid_tz(tz):
                        continue
    
                    local_now = now_utc.astimezone(ZoneInfo(tz))
                    local_date = local_now.date()
    
                    if rec["day"] == local_date.day and rec["month"] == local_date.month:
                        today_birthdays.setdefault(local_date.isoformat(), []).append(member)
    
                    # ---- role handling (per member) ----
                    key = f"{local_date.isoformat()}|{uid}"
    
                    if role:
                        if rec["day"] == local_date.day and rec["month"] == local_date.month:
                            if key not in role_assigned:
                                try:
                                    await member.add_roles(role, reason="Birthday role")
                                    role_assigned.add(key)
                                except Exception:
                                    pass
                        else:
                            if role in member.roles:
                                try:
                                    await member.remove_roles(role, reason="Birthday role expired")
                                except Exception:
                                    pass
    
                # ---- announcements ----
                for date_key, members in today_birthdays.items():
                    announce_key = f"{date_key}|announce"
                    if not do_announce or not channel or announce_key in announced:
                        continue
    
                    if len(members) == 1:
                        tpl = s.get("message_single")
                        text = _fmt_template(
                            tpl,
                            member=members[0],
                            local_date=date.fromisoformat(date_key),
                            tz = bds[str(members[0].id)]["timezone"]
                        )
                    else:
                        tpl = s.get("message_multiple")
                        mentions = ", ".join(m.mention for m in members)
                        text = tpl.replace("{users}", mentions).replace("{count}", str(len(members)))
    
                    try:
                        await channel.send(text)
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