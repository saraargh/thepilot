from __future__ import annotations

import os
import json
import base64
import asyncio
import io
import random
import time
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional, List, Tuple

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from zoneinfo import ZoneInfo, available_timezones

# =========================================================
# GitHub Config & Defaults
# =========================================================

GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "birthdays.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_BASE = "https://api.github.com"
UK_TZ = ZoneInfo("Europe/London")

HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

DEFAULT_DATA: Dict[str, Any] = {
    "settings": {
        "enabled": True,
        "announce": True,
        "channel_id": None,
        "birthday_role_id": None,
        "post_hour": 15,
        "post_minute": 0,
        "message_header": "🎂 Birthday Celebration!",
        "message_single": "Happy Birthday {username}! Hope you have a magical day! 🎂",
        "message_multiple": "We have {count} birthdays today! Happy Birthday to {usernames}! 🎂🎉",
        "image_urls": []
    },
    "birthdays": {},
    "state": {"announced_keys": []}
}

_lock = asyncio.Lock()

# =========================================================
# GitHub Logic
# =========================================================

async def _gh_get_file() -> Tuple[Optional[dict], Optional[str]]:
    if not GITHUB_TOKEN:
        return None, None

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as r:
            if r.status == 404:
                return None, None
            payload = await r.json()
            sha = payload.get("sha")
            raw = base64.b64decode(payload.get("content", "")).decode("utf-8")
            return json.loads(raw), sha


async def _gh_put_file(data: dict, sha: Optional[str]) -> Optional[str]:
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    raw = json.dumps(data, indent=2, ensure_ascii=False)
    body = {
        "message": "Update birthdays",
        "content": base64.b64encode(raw.encode("utf-8")).decode("utf-8"),
        **({"sha": sha} if sha else {})
    }

    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=HEADERS, json=body) as r:
            res = await r.json()
            return res.get("content", {}).get("sha")


async def load_data():
    async with _lock:
        data, sha = await _gh_get_file()
        if not data:
            return json.loads(json.dumps(DEFAULT_DATA)), sha
        return data, sha


async def save_data(data, sha):
    async with _lock:
        return await _gh_put_file(data, sha)

# =========================================================
# Helpers
# =========================================================

def _fmt(tpl: str, members: List[discord.Member]) -> str:
    if not tpl:
        return ""
    mentions = ", ".join(m.mention for m in members)
    names = ", ".join(m.display_name for m in members)
    return (
        tpl.replace("{mention}", mentions)
           .replace("{mentions}", mentions)
           .replace("{username}", names)
           .replace("{usernames}", names)
           .replace("{count}", str(len(members)))
    )


async def _send_announcement_like(
    *,
    channel: discord.TextChannel,
    settings: Dict[str, Any],
    members: List[discord.Member],
    local_date: date,
    tz_label: str,
    test_mode: bool,
    force_multiple: bool = False
) -> bool:
    if not members or not channel:
        return False

    is_multi = force_multiple or len(members) > 1
    pings = ", ".join(m.mention for m in members)

    header = _fmt(settings.get("message_header", "Birthday!"), members)
    body = _fmt(
        settings.get("message_multiple" if is_multi else "message_single", ""),
        members
    )

    embed = discord.Embed(title=header, description=body, color=0xff69b4)

    if test_mode:
        embed.set_author(name="PREVIEW MODE")

    imgs = settings.get("image_urls", []) or []
    if imgs:
        url = random.choice(imgs).strip()
        embed.set_image(url=f"{url}{'&' if '?' in url else '?'}cb={int(time.time())}")

    embed.set_footer(text=f"The Pilot • {local_date.strftime('%-d %B')} • {tz_label}")

    try:
        await channel.send(
            content=pings if not test_mode else f"🔔 *Preview Pings:* {pings}",
            embed=embed
        )
        return True
    except Exception:
        return False

# =========================================================
# Setup & Commands
# =========================================================

def setup(bot: discord.Client):
    tree = bot.tree
    group = app_commands.Group(name="birthday", description="Birthday commands")

    try:
        tree.add_command(group)
    except Exception:
        pass

    async def tz_autocomplete(
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=t, value=t)
            for t in sorted(available_timezones())
            if current.lower() in t.lower()
        ][:25]

    @group.command(name="set", description="Add or update a birthday")
    @app_commands.autocomplete(timezone=tz_autocomplete)
    async def b_set(
        interaction: discord.Interaction,
        day: int,
        month: int,
        timezone: str,
        user: Optional[discord.Member] = None
    ):
        target = user or interaction.user
        data, sha = await load_data()

        data["birthdays"][str(target.id)] = {
            "day": day,
            "month": month,
            "timezone": timezone
        }

        await save_data(data, sha)
        await interaction.response.send_message(
            f"✅ Birthday for **{target.display_name}** set to **{day}/{month}**.",
            ephemeral=False
        )

    @group.command(name="remove", description="Remove a birthday")
    async def b_remove(
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None
    ):
        target = user or interaction.user
        data, sha = await load_data()

        if str(target.id) in data["birthdays"]:
            del data["birthdays"][str(target.id)]
            await save_data(data, sha)
            await interaction.response.send_message(
                f"🗑️ Removed birthday for **{target.display_name}**.",
                ephemeral=False
            )
        else:
            await interaction.response.send_message("❌ Birthday not found.", ephemeral=False)

    @group.command(name="list", description="List all server birthdays")
    async def b_list(interaction: discord.Interaction):
        data, _ = await load_data()
        bdays = data.get("birthdays", {})

        if not bdays:
            return await interaction.response.send_message("No birthdays recorded.", ephemeral=False)

        rows = []
        for uid, rec in bdays.items():
            m = interaction.guild.get_member(int(uid))
            name = m.display_name if m else f"User {uid}"
            rows.append((name, rec["day"], rec["month"]))

        rows.sort(key=lambda x: (x[2], x[1]))

        text = "\n".join(f"• **{n}** — {d}/{m}" for n, d, m in rows)
        embed = discord.Embed(title="🎂 Birthday List", description=text, color=0xff69b4)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @group.command(name="upcoming", description="Show the next 5 birthdays")
    async def b_upcoming(interaction: discord.Interaction):
        data, _ = await load_data()
        bdays = data.get("birthdays", {})
        today = date.today()

        upcoming = []
        for uid, rec in bdays.items():
            try:
                bday = date(today.year, rec["month"], rec["day"])
            except Exception:
                continue
            if bday < today:
                bday = bday.replace(year=today.year + 1)
            upcoming.append((uid, bday))

        upcoming.sort(key=lambda x: x[1])
        lines = []

        for uid, d in upcoming[:5]:
            m = interaction.guild.get_member(int(uid))
            name = m.display_name if m else uid
            lines.append(f"**{name}** — {d.strftime('%-d %B')}")

        embed = discord.Embed(
            title="📅 Upcoming Birthdays",
            description="\n".join(lines) if lines else "No upcoming birthdays.",
            color=0xff69b4
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @group.command(name="help", description="Birthday commands help")
    async def b_help(interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎂 Birthday Help",
            description=(
                "`/birthday set` — Add or update a birthday\n"
                "`/birthday remove` — Remove a birthday\n"
                "`/birthday list` — List all birthdays\n"
                "`/birthday upcoming` — Next 5 birthdays"
            ),
            color=0xff69b4
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # =====================================================
    # Birthday Announcement Loop
    # =====================================================

    @tasks.loop(minutes=1)
    async def birthday_tick():
        now = datetime.now(timezone.utc)
        data, sha = await load_data()
        s = data.get("settings", {})

        if not s.get("enabled", True):
            return

        announced = set(data.get("state", {}).get("announced_keys", []))
        dirty = False

        for guild in bot.guilds:
            channel = guild.get_channel(s.get("channel_id"))
            role = guild.get_role(s.get("birthday_role_id"))

            for uid, rec in data.get("birthdays", {}).items():
                member = guild.get_member(int(uid))
                if not member:
                    continue

                try:
                    local = now.astimezone(ZoneInfo(rec.get("timezone", "Europe/London")))
                except Exception:
                    local = now.astimezone(UK_TZ)

                is_birthday = (
                    rec["day"] == local.day and
                    rec["month"] == local.month
                )

                # role assignment
                if role:
                    if is_birthday and role not in member.roles:
                        await member.add_roles(role)
                    elif not is_birthday and role in member.roles:
                        await member.remove_roles(role)

                # announcement
                if (
                    s.get("announce", True)
                    and is_birthday
                    and channel
                    and (
                        local.hour > s["post_hour"]
                        or (local.hour == s["post_hour"] and local.minute >= s["post_minute"])
                    )
                ):
                    key = f"{local.date().isoformat()}|{uid}|ann"
                    if key not in announced:
                        sent = await _send_announcement_like(
                            channel=channel,
                            settings=s,
                            members=[member],
                            local_date=local.date(),
                            tz_label=rec.get("timezone", "UTC"),
                            test_mode=False
                        )
                        if sent:
                            announced.add(key)
                            dirty = True

        if dirty:
            data["state"]["announced_keys"] = list(announced)
            await save_data(data, sha)

    @birthday_tick.before_loop
    async def before():
        await bot.wait_until_ready()

    if not hasattr(bot, "_birthday_tick_started"):
        birthday_tick.start()
        bot._birthday_tick_started = True