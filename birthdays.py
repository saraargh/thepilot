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

# If you already have a shared permissions helper, we’ll use it.
# We also provide a safe fallback in case you don’t.
try:
    from permissions import has_pilot_access  # expected signature: (member, pilot_settings_dict) -> bool
except Exception:
    has_pilot_access = None


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
        "channel_id": None,          # where announcements go
        "birthday_role_id": None,    # optional role to apply on birthday day
        "message": "🎂 Happy Birthday {user}! ✈️",  # supports placeholders
        "announce": True             # allow turning off announcements but keep role logic
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


def _pilot_access(member: discord.Member, pilot_settings: dict) -> bool:
    # Prefer your shared helper
    if has_pilot_access:
        return bool(has_pilot_access(member, pilot_settings))
    # Fallback: if pilot_settings has allowed_role_ids
    allowed = pilot_settings.get("allowed_role_ids", []) if isinstance(pilot_settings, dict) else []
    return any(r.id in allowed for r in member.roles)


async def _get_pilot_settings(interaction: discord.Interaction) -> dict:
    """
    We assume your adminsettings module already loads a settings blob.
    If you store Pilot settings in a file, import it here.
    If not available, we fallback to env-based ALLOWED_ROLE_IDS from botslash-like pattern.
    """
    try:
        # If you have an admin settings loader, use it.
        from adminsettings import load_admin_settings  # must return dict
        return await load_admin_settings()
    except Exception:
        # Fallback: try to read allowed role IDs from env as comma-separated
        raw = os.getenv("PILOT_ALLOWED_ROLE_IDS", "")
        ids = []
        for x in raw.split(","):
            x = x.strip()
            if x.isdigit():
                ids.append(int(x))
        return {"allowed_role_ids": ids}


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


# ------------------- Settings View -------------------
class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot: discord.Client, data: dict, sha: Optional[str]):
        super().__init__(timeout=300)
        self.bot = bot
        self.data = data
        self.sha = sha

    def _embed(self) -> discord.Embed:
        s = self.data.get("settings", {})
        enabled = s.get("enabled", True)
        channel_id = s.get("channel_id")
        role_id = s.get("birthday_role_id")
        announce = s.get("announce", True)
        msg = s.get("message", DEFAULT_DATA["settings"]["message"])

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
        pilot = await _get_pilot_settings(interaction)
        if not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access.", ephemeral=True)

        s = self.data.setdefault("settings", {})
        s["enabled"] = not bool(s.get("enabled", True))
        await self._save_and_refresh(interaction)

    @discord.ui.button(label="Toggle announcements", style=discord.ButtonStyle.secondary)
    async def toggle_announce(self, interaction: discord.Interaction, button: discord.ui.Button):
        pilot = await _get_pilot_settings(interaction)
        if not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access.", ephemeral=True)

        s = self.data.setdefault("settings", {})
        s["announce"] = not bool(s.get("announce", True))
        await self._save_and_refresh(interaction)

    @discord.ui.button(label="Set channel", style=discord.ButtonStyle.secondary)
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        pilot = await _get_pilot_settings(interaction)
        if not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access.", ephemeral=True)

        await interaction.response.send_message(
            "Reply with the channel mention (e.g. #birthdays) within 60s.",
            ephemeral=True
        )

        def check(m: discord.Message):
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel_id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            return

        if not msg.channel_mentions:
            return await interaction.followup.send("❌ No channel detected. Try again.", ephemeral=True)

        ch = msg.channel_mentions[0]
        self.data.setdefault("settings", {})["channel_id"] = ch.id
        await interaction.followup.send(f"✅ Channel set to {ch.mention}", ephemeral=True)

    @discord.ui.button(label="Set role", style=discord.ButtonStyle.secondary)
    async def set_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        pilot = await _get_pilot_settings(interaction)
        if not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access.", ephemeral=True)

        await interaction.response.send_message(
            "Reply with the role mention (e.g. @Birthday) or `none` within 60s.",
            ephemeral=True
        )

        def check(m: discord.Message):
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel_id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            return

        txt = msg.content.strip().lower()
        if txt == "none":
            self.data.setdefault("settings", {})["birthday_role_id"] = None
            return await interaction.followup.send("✅ Birthday role cleared.", ephemeral=True)

        if not msg.role_mentions:
            return await interaction.followup.send("❌ No role detected. Try again.", ephemeral=True)

        role = msg.role_mentions[0]
        self.data.setdefault("settings", {})["birthday_role_id"] = role.id
        await interaction.followup.send(f"✅ Birthday role set to {role.mention}", ephemeral=True)

    @discord.ui.button(label="Edit message", style=discord.ButtonStyle.success)
    async def edit_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        pilot = await _get_pilot_settings(interaction)
        if not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access.", ephemeral=True)

        await interaction.response.send_message(
            "Reply with the new birthday message template within 120s.\n"
            "Placeholders: `{user}`, `{username}`, `{date}`, `{timezone}`",
            ephemeral=True
        )

        def check(m: discord.Message):
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel_id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=120)
        except asyncio.TimeoutError:
            return

        self.data.setdefault("settings", {})["message"] = msg.content.strip()
        await interaction.followup.send("✅ Message template updated.", ephemeral=True)

    @discord.ui.button(label="Export all birthdays", style=discord.ButtonStyle.danger)
    async def export_birthdays(self, interaction: discord.Interaction, button: discord.ui.Button):
        pilot = await _get_pilot_settings(interaction)
        if not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access.", ephemeral=True)

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

    @birthday_group.command(name="set", description="Set a birthday (timezone required). Pilot roles can set for others.")
    @app_commands.describe(day="Day (1-31)", month="Month (1-12)", timezone="IANA timezone (e.g. Europe/London)", user="Optional: set for someone else (Pilot access required)")
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

        pilot = await _get_pilot_settings(interaction)

        target = user or interaction.user
        if user and not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access to set birthdays for others.", ephemeral=True)

        data, sha = await load_data()
        data.setdefault("birthdays", {})
        data["birthdays"][str(target.id)] = {"day": int(day), "month": int(month), "timezone": tz}
        _normalize_state_lists(data)

        await save_data(data, sha)

        who = "your" if target.id == interaction.user.id else f"{target.mention}'s"
        await interaction.response.send_message(
            f"✅ Set {who} birthday to **{day:02d}/{month:02d}** in **{tz}**.",
            ephemeral=True
        )

    @birthday_group.command(name="view", description="View a birthday. Pilot roles can view others.")
    @app_commands.describe(user="Optional: view someone else (Pilot access required)")
    async def birthday_view(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        pilot = await _get_pilot_settings(interaction)
        target = user or interaction.user
        if user and not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access to view others.", ephemeral=True)

        data, _ = await load_data()
        rec = (data.get("birthdays", {}) or {}).get(str(target.id))
        if not rec:
            if target.id == interaction.user.id:
                return await interaction.response.send_message("You haven’t set your birthday yet. Use `/birthday set`.", ephemeral=True)
            return await interaction.response.send_message("No birthday set for that user.", ephemeral=True)

        d = int(rec.get("day", 0))
        m = int(rec.get("month", 0))
        tz = str(rec.get("timezone", ""))
        await interaction.response.send_message(
            f"🎂 **{target.display_name}** — **{d:02d}/{m:02d}** (**{tz}**)",
            ephemeral=True
        )

    @birthday_group.command(name="remove", description="Remove a birthday. Pilot roles can remove others.")
    @app_commands.describe(user="Optional: remove someone else (Pilot access required)")
    async def birthday_remove(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        pilot = await _get_pilot_settings(interaction)
        target = user or interaction.user
        if user and not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access to remove others.", ephemeral=True)

        data, sha = await load_data()
        bds = data.get("birthdays", {}) or {}
        if str(target.id) not in bds:
            return await interaction.response.send_message("No birthday set to remove.", ephemeral=True)

        del bds[str(target.id)]
        data["birthdays"] = bds
        _normalize_state_lists(data)
        await save_data(data, sha)

        await interaction.response.send_message("✅ Birthday removed.", ephemeral=True)

    @tree.command(name="upcomingbirthdays", description="Show upcoming birthdays.")
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

    @tree.command(name="birthdaysettings", description="Configure birthday settings (Pilot roles only).")
    async def birthdaysettings(interaction: discord.Interaction):
        pilot = await _get_pilot_settings(interaction)
        if not _pilot_access(interaction.user, pilot):
            return await interaction.response.send_message("❌ You don’t have Pilot access.", ephemeral=True)

        data, sha = await load_data()
        view = BirthdaySettingsView(bot, data, sha)
        await interaction.response.send_message(embed=view._embed(), view=view, ephemeral=True)

    # ------------------- Background Task -------------------
    @tasks.loop(minutes=15)
    async def birthday_tick():
        # We need a guild context; if your bot is in multiple guilds, this runs per guild.
        # If you only have one server, this is fine.
        for guild in bot.guilds:
            try:
                data, sha = await load_data()
                s = data.get("settings", {}) or {}
                if not s.get("enabled", True):
                    continue

                bds: Dict[str, Any] = data.get("birthdays", {}) or {}
                if not bds:
                    continue

                _normalize_state_lists(data)
                announced = set(data["state"].get("announced_keys", []))
                role_assigned = set(data["state"].get("role_assigned_keys", []))

                channel_id = s.get("channel_id")
                role_id = s.get("birthday_role_id")
                do_announce = bool(s.get("announce", True))
                template = s.get("message", DEFAULT_DATA["settings"]["message"])

                channel = guild.get_channel(int(channel_id)) if channel_id else None
                role = guild.get_role(int(role_id)) if role_id else None

                # Keep state cleanup mild (remove very old keys by length already handled)
                now_utc = datetime.now(timezone.utc)

                for uid, rec in bds.items():
                    member = guild.get_member(int(uid))
                    if not member:
                        continue

                    tz = str(rec.get("timezone", "")).strip()
                    if not _is_valid_tz(tz):
                        continue

                    user_tz = ZoneInfo(tz)
                    now_local = now_utc.astimezone(user_tz)
                    local_d = now_local.date()

                    try:
                        d = int(rec.get("day"))
                        m = int(rec.get("month"))
                    except Exception:
                        continue

                    is_bday = (local_d.day == d and local_d.month == m)
                    key = f"{local_d.isoformat()}|{uid}"

                    # Announce once per user per local date
                    if is_bday and do_announce and channel and key not in announced:
                        text = _fmt_template(template, member=member, local_date=local_d, tz=tz)
                        try:
                            await channel.send(text)
                            announced.add(key)
                        except Exception:
                            # don’t crash loop if perms missing
                            pass

                    # Role apply/remove
                    if role:
                        if is_bday and key not in role_assigned:
                            try:
                                if role not in member.roles:
                                    await member.add_roles(role, reason="Birthday role (The Pilot)")
                                role_assigned.add(key)
                            except Exception:
                                pass
                        if (not is_bday) and (role in member.roles):
                            # Only remove if we previously assigned it at least once (avoid nuking manual assignments)
                            # If you want “always remove when not birthday”, remove this guard.
                            # Guard: if user had any role_assigned key in last 2 days, allow removal.
                            # This avoids a permanent role in case of failures.
                            allow_remove = False
                            for k in list(role_assigned):
                                if k.endswith(f"|{uid}"):
                                    try:
                                        kdate = date.fromisoformat(k.split("|")[0])
                                        if (local_d - kdate).days >= 1:
                                            allow_remove = True
                                    except Exception:
                                        continue
                            if allow_remove:
                                try:
                                    await member.remove_roles(role, reason="Birthday role expired (The Pilot)")
                                except Exception:
                                    pass

                # Persist state
                data["state"]["announced_keys"] = list(announced)
                data["state"]["role_assigned_keys"] = list(role_assigned)
                _normalize_state_lists(data)
                await save_data(data, sha)

            except Exception:
                # keep the loop alive no matter what
                continue

    @birthday_tick.before_loop
    async def before_birthday_tick():
        await bot.wait_until_ready()

    birthday_tick.start()