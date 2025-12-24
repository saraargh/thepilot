from __future__ import annotations

import os
import json
import base64
import asyncio
import io
import random
import time
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, Optional, List, Tuple

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from zoneinfo import ZoneInfo, available_timezones

from permissions import has_app_access

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
# GitHub Logic (Robust Saving)
# =========================================================
async def _gh_get_file() -> Tuple[Optional[dict], Optional[str]]:
    if not GITHUB_TOKEN: return None, None
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as r:
            if r.status == 404: return None, None
            payload = await r.json()
            sha = payload.get("sha")
            raw = base64.b64decode(payload.get("content", "")).decode("utf-8")
            return json.loads(raw), sha

async def _gh_put_file(data: dict, sha: Optional[str]) -> Optional[str]:
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    raw = json.dumps(data, indent=2, ensure_ascii=False)
    body = {"message": "Update birthdays", "content": base64.b64encode(raw.encode("utf-8")).decode("utf-8"), **({"sha": sha} if sha else {})}
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=HEADERS, json=body) as r:
            res = await r.json()
            return res.get("content", {}).get("sha")

async def load_data():
    async with _lock:
        data, sha = await _gh_get_file()
        if not data: return json.loads(json.dumps(DEFAULT_DATA)), sha
        return data, sha

async def save_data(data, sha):
    async with _lock: return await _gh_put_file(data, sha)

# =========================================================
# Helper Utilities
# =========================================================
def _fmt(tpl: str, members: List[discord.Member]) -> str:
    if not tpl: return ""
    mentions = ", ".join(m.mention for m in members)
    names = ", ".join(m.display_name for m in members)
    return tpl.replace("{mention}", mentions).replace("{mentions}", mentions).replace("{username}", names).replace("{usernames}", names).replace("{count}", str(len(members)))

async def _send_announcement_like(*, channel, settings, members, local_date, tz_label, test_mode, force_multiple=False):
    if not members: return False
    is_multi = force_multiple or len(members) > 1
    pings = ", ".join(m.mention for m in members)
    header = _fmt(settings.get("message_header", "Birthday!"), members)
    body = _fmt(settings.get("message_multiple" if is_multi else "message_single", ""), members)
    
    embed = discord.Embed(title=header, description=body, color=0xff69b4)
    if test_mode: embed.set_author(name="PREVIEW MODE")
    
    imgs = settings.get("image_urls", [])
    if imgs:
        url = random.choice(imgs).strip()
        embed.set_image(url=f"{url}{'&' if '?' in url else '?'}cb={int(time.time())}")
    
    embed.set_footer(text=f"The Pilot • {local_date.strftime('%-d %B')} • {tz_label}")
    
    try:
        await channel.send(content=pings if not test_mode else f"🔔 *Preview Pings:* {pings}", embed=embed)
        return True
    except Exception: return False

# =========================================================
# UI Components (Modals & Panels)
# =========================================================
class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Card Text"):
    header = discord.ui.TextInput(label="Embed Title", placeholder="Happy Birthday {username}!")
    single = discord.ui.TextInput(label="Single Member Message", style=discord.TextStyle.paragraph)
    multi = discord.ui.TextInput(label="Multiple Members Message", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, view):
        super().__init__(); self.view_ref = view; s = view.data["settings"]
        self.header.default = s.get("message_header")
        self.single.default = s.get("message_single")
        self.multi.default = s.get("message_multiple")

    async def on_submit(self, it):
        s = self.view_ref.data["settings"]
        s["message_header"] = str(self.header.value)
        s["message_single"] = str(self.single.value)
        s["message_multiple"] = str(self.multi.value) or str(self.single.value)
        await self.view_ref._save_and_refresh(it, "✅ Updated card text.")

class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot, data, sha):
        super().__init__(timeout=300); self.bot = bot; self.data = data; self.sha = sha
        self.add_item(BirthdayChannelSelect())
        self.add_item(BirthdayRoleSelect())

    def _embed(self):
        s = self.data["settings"]
        e = discord.Embed(title="🎂 Birthday Admin Panel", color=0xff69b4)
        e.add_field(name="Bot Status", value="✅ Enabled" if s['enabled'] else "❌ Disabled")
        e.add_field(name="Channel", value=f"<#{s['channel_id']}>" if s['channel_id'] else "Not Set")
        e.add_field(name="Role", value=f"<@&{s['birthday_role_id']}>" if s['birthday_role_id'] else "Not Set")
        e.add_field(name="Time", value=f"{s['post_hour']:02d}:{s['post_minute']:02d}")
        return e

    async def _save_and_refresh(self, it, note=None):
        new_sha = await save_data(self.data, self.sha)
        if new_sha: self.sha = new_sha
        await it.response.edit_message(embed=self._embed(), view=self)
        if note: await it.followup.send(note, ephemeral=True)

    @discord.ui.button(label="Toggle Bot", style=discord.ButtonStyle.primary, row=1)
    async def toggle(self, it, bt):
        self.data["settings"]["enabled"] = not self.data["settings"]["enabled"]
        await self._save_and_refresh(it)

    @discord.ui.button(label="Edit Text", style=discord.ButtonStyle.secondary, row=1)
    async def edit_txt(self, it, bt): await it.response.send_modal(BirthdayMessageModal(self))

    @discord.ui.button(label="Export Data", style=discord.ButtonStyle.secondary, row=1)
    async def export_json(self, it, bt):
        file_data = io.BytesIO(json.dumps(self.data, indent=2).encode())
        await it.response.send_message("📂 Current Birthday JSON:", file=discord.File(file_data, "birthdays_export.json"), ephemeral=True)

    @discord.ui.button(label="Preview Single", style=discord.ButtonStyle.success, row=2)
    async def prev_s(self, it, bt):
        chan = self.bot.get_channel(self.data["settings"]["channel_id"])
        if not chan: return await it.response.send_message("❌ Set channel first.", ephemeral=True)
        await _send_announcement_like(channel=chan, settings=self.data["settings"], members=[it.user], local_date=date.today(), tz_label="Test-Zone", test_mode=True)
        await it.response.send_message("✨ Preview sent.", ephemeral=True)

    @discord.ui.button(label="Preview Multi", style=discord.ButtonStyle.success, row=2)
    async def prev_m(self, it, bt):
        chan = self.bot.get_channel(self.data["settings"]["channel_id"])
        if not chan: return await it.response.send_message("❌ Set channel first.", ephemeral=True)
        await _send_announcement_like(channel=chan, settings=self.data["settings"], members=[it.user, it.guild.me], local_date=date.today(), tz_label="Test-Zone", test_mode=True, force_multiple=True)
        await it.response.send_message("✨ Multiple Preview sent.", ephemeral=True)

class BirthdayChannelSelect(discord.ui.ChannelSelect):
    def __init__(self): super().__init__(placeholder="Choose Announcement Channel", row=3)
    async def callback(self, it): self.view.data["settings"]["channel_id"] = self.values[0].id; await self.view._save_and_refresh(it)

class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(self): super().__init__(placeholder="Choose Birthday Role", row=4)
    async def callback(self, it): self.view.data["settings"]["birthday_role_id"] = self.values[0].id; await self.view._save_and_refresh(it)

# =========================================================
# Slash Commands Setup
# =========================================================
def setup(bot: discord.Client):
    tree = bot.tree
    group = app_commands.Group(name="birthday", description="Manage server birthdays")
    try: tree.add_command(group)
    except: pass

    async def timezone_autocomplete(it, current: str):
        tzs = sorted([t for t in available_timezones() if "/" in t])
        return [app_commands.Choice(name=t, value=t) for t in tzs if current.lower() in t.lower()][:25]

    @group.command(name="set", description="Register or update your birthday")
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def b_set(it, day: int, month: int, timezone: str, user: Optional[discord.Member] = None):
        target = user or it.user; data, sha = await load_data()
        data["birthdays"][str(target.id)] = {"day": day, "month": month, "timezone": timezone}
        await save_data(data, sha); await it.response.send_message(f"✅ Birthday for {target.display_name} set to {day}/{month}.", ephemeral=True)

    @group.command(name="remove", description="Remove your birthday from the bot")
    async def b_remove(it, user: Optional[discord.Member] = None):
        target = user or it.user; data, sha = await load_data()
        if str(target.id) in data["birthdays"]:
            del data["birthdays"][str(target.id)]
            await save_data(data, sha); await it.response.send_message(f"🗑️ Removed birthday for {target.display_name}.", ephemeral=True)
        else: await it.response.send_message("❌ No birthday found.", ephemeral=True)

    @group.command(name="upcoming", description="List birthdays in the server")
    async def b_upcoming(it):
        data, _ = await load_data(); bdays = data.get("birthdays", {})
        if not bdays: return await it.response.send_message("No birthdays saved.", ephemeral=True)
        lines = []
        for uid, rec in bdays.items():
            m = it.guild.get_member(int(uid))
            name = m.display_name if m else f"User {uid}"
            lines.append(f"• **{name}**: {rec['day']}/{rec['month']}")
        await it.response.send_message(f"**🎂 Server Birthdays:**\n" + "\n".join(lines), ephemeral=True)

    @group.command(name="help", description="How to use the birthday bot")
    async def b_help(it):
        e = discord.Embed(title="🎂 Birthday Bot Help", color=0xff69b4)
        e.add_field(name="Commands", value=(
            "`/birthday set` - Add your birthday and timezone\n"
            "`/birthday upcoming` - See all birthdays\n"
            "`/birthday remove` - Remove your birthday\n"
            "`/birthday settings` - (Admins Only) Manage bot config"
        ))
        await it.response.send_message(embed=e, ephemeral=True)

    @group.command(name="settings", description="Admin: Configure the birthday bot")
    async def b_settings(it):
        if not has_app_access(it.user, "birthdays"): return await it.response.send_message("No perm.", ephemeral=True)
        data, sha = await load_data(); view = BirthdaySettingsView(bot, data, sha)
        await it.response.send_message(embed=view._embed(), view=view, ephemeral=True)

    # =========================================================
    # Background Clock Loop
    # =========================================================
    @tasks.loop(minutes=1)
    async def birthday_tick():
        now_utc = datetime.now(timezone.utc); curr_year = now_utc.year
        data, sha = await load_data(); s = data["settings"]
        if not s.get("enabled"): return
        
        dirty = False
        announced_set = {k for k in data["state"].get("announced_keys", []) if k.startswith(str(curr_year))}
        
        for guild in bot.guilds:
            chan = guild.get_channel(s.get("channel_id"))
            role = guild.get_role(s.get("birthday_role_id"))
            
            for uid, rec in data["birthdays"].items():
                member = guild.get_member(int(uid)) or await (lambda: guild.fetch_member(int(uid)) if True else None)()
                if not member: continue
                
                try: loc_now = now_utc.astimezone(ZoneInfo(rec.get("timezone", "Europe/London")))
                except: loc_now = now_utc.astimezone(UK_TZ)
                
                is_bday = (rec['day'] == loc_now.day and rec['month'] == loc_now.month)
                
                if role:
                    if is_bday and role not in member.roles: await member.add_roles(role)
                    elif not is_bday and role in member.roles: await member.remove_roles(role)
                
                if is_bday and chan and (loc_now.hour > s['post_hour'] or (loc_now.hour == s['post_hour'] and loc_now.minute >= s['post_minute'])):
                    a_key = f"{loc_now.date().isoformat()}|{uid}|ann"
                    if a_key not in announced_set:
                        if await _send_announcement_like(channel=chan, settings=s, members=[member], local_date=loc_now.date(), tz_label=rec.get("timezone"), test_mode=False):
                            announced_set.add(a_key); dirty = True

        if dirty:
            data["state"]["announced_keys"] = list(announced_set)
            await save_data(data, sha)

    @birthday_tick.before_loop
    async def b4(): await bot.wait_until_ready()
    if not hasattr(bot, "_birthday_tick_started"):
        birthday_tick.start(); bot._birthday_tick_started = True
