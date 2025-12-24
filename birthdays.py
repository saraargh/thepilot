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
# GitHub Logic
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
# Helpers
# =========================================================
def _fmt(tpl: str, members: List[discord.Member]) -> str:
    if not tpl: return ""
    mentions = ", ".join(m.mention for m in members)
    names = ", ".join(m.display_name for m in members)
    return tpl.replace("{mention}", mentions).replace("{mentions}", mentions).replace("{username}", names).replace("{usernames}", names).replace("{count}", str(len(members)))

async def _send_announcement_like(*, channel, settings, members, local_date, tz_label, test_mode, force_multiple=False):
    if not members or not channel: return False
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
    except: return False

# =========================================================
# Modals (Time, Card, Images)
# =========================================================
class BirthdayTimeModal(discord.ui.Modal, title="Edit Announcement Time"):
    hour = discord.ui.TextInput(label="Hour (0-23)", placeholder="15", min_length=1, max_length=2)
    minute = discord.ui.TextInput(label="Minute (0-59)", placeholder="00", min_length=1, max_length=2)
    def __init__(self, view):
        super().__init__(); self.view_ref = view; s = view.data["settings"]
        self.hour.default = str(s.get("post_hour", 15))
        self.minute.default = str(s.get("post_minute", 0))
    async def on_submit(self, it):
        try:
            h, m = int(self.hour.value), int(self.minute.value)
            if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError()
            self.view_ref.data["settings"]["post_hour"] = h
            self.view_ref.data["settings"]["post_minute"] = m
            await self.view_ref._save_and_refresh(it, f"🕒 {it.user.mention} updated announcement time to **{h:02d}:{m:02d}**", is_ephemeral=False)
        except: await it.response.send_message("❌ Invalid time format.", ephemeral=False)

class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Card"):
    header = discord.ui.TextInput(label="Title", placeholder="Happy Birthday {username}!")
    single = discord.ui.TextInput(label="Single Message", style=discord.TextStyle.paragraph)
    multi = discord.ui.TextInput(label="Multiple Message", style=discord.TextStyle.paragraph, required=False)
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
        await self.view_ref._save_and_refresh(it, f"📝 {it.user.mention} updated the birthday card templates.", is_ephemeral=False)

class AddImageModal(discord.ui.Modal, title="Add Birthday GIF/Image"):
    url = discord.ui.TextInput(label="Image URL", placeholder="https://media.giphy.com/...", style=discord.TextStyle.paragraph)
    def __init__(self, view): super().__init__(); self.view_ref = view
    async def on_submit(self, it):
        url = str(self.url.value).strip()
        if not url.startswith("http"): return await it.response.send_message("❌ Invalid URL.", ephemeral=True)
        self.view_ref.data["settings"].setdefault("image_urls", []).append(url)
        await self.view_ref._save_and_refresh(it, f"🖼️ {it.user.mention} added a new birthday image.", is_ephemeral=False)

# =========================================================
# Paginated List View
# =========================================================
class BirthdayListView(discord.ui.View):
    def __init__(self, items: list, page: int = 0):
        super().__init__(timeout=60); self.items = items; self.page = page
        self.pages = [items[i:i + 10] for i in range(0, len(items), 10)]

    def _make_embed(self):
        desc = "\n".join([f"• **{n}**: {d}" for n, d in self.pages[self.page]])
        e = discord.Embed(title="🎂 Server Birthdays (Jan-Dec)", description=desc, color=0xff69b4)
        e.set_footer(text=f"Page {self.page + 1}/{len(self.pages)} • Total: {len(self.items)}")
        return e

    @discord.ui.button(label="<", style=discord.ButtonStyle.gray)
    async def prev(self, it, bt):
        if self.page > 0: self.page -= 1; await it.response.edit_message(embed=self._make_embed(), view=self)
        else: await it.response.defer()

    @discord.ui.button(label=">", style=discord.ButtonStyle.gray)
    async def next(self, it, bt):
        if self.page < len(self.pages) - 1: self.page += 1; await it.response.edit_message(embed=self._make_embed(), view=self)
        else: await it.response.defer()

# =========================================================
# Settings View
# =========================================================
class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot, data, sha):
        super().__init__(timeout=300); self.bot = bot; self.data = data; self.sha = sha
        self.add_item(BirthdayChannelSelect()); self.add_item(BirthdayRoleSelect())
    def _embed(self):
        s = self.data["settings"]
        e = discord.Embed(title="🎂 Birthday Admin Panel", color=0xff69b4)
        e.add_field(name="Bot", value="✅ ON" if s['enabled'] else "❌ OFF")
        e.add_field(name="Channel", value=f"<#{s['channel_id']}>" if s['channel_id'] else "None")
        e.add_field(name="Role", value=f"<@&{s['birthday_role_id']}>" if s['birthday_role_id'] else "None")
        e.add_field(name="Time", value=f"{s['post_hour']:02d}:{s['post_minute']:02d}")
        e.add_field(name="Images", value=f"{len(s.get('image_urls', []))} loaded")
        return e
    async def _save_and_refresh(self, it, note=None, is_ephemeral=True):
        new_sha = await save_data(self.data, self.sha)
        if new_sha: self.sha = new_sha
        await it.response.edit_message(embed=self._embed(), view=self)
        if note: await it.followup.send(note, ephemeral=is_ephemeral)

    @discord.ui.button(label="Toggle Bot", style=discord.ButtonStyle.primary, row=1)
    async def toggle(self, it, bt):
        self.data["settings"]["enabled"] = not self.data["settings"]["enabled"]
        await self._save_and_refresh(it, f"⚙️ {it.user.mention} toggled bot.", is_ephemeral=False)

    @discord.ui.button(label="Edit Card", style=discord.ButtonStyle.secondary, row=1)
    async def ed_txt(self, it, bt): await it.response.send_modal(BirthdayMessageModal(self))
    @discord.ui.button(label="Edit Time", style=discord.ButtonStyle.secondary, row=1)
    async def ed_time(self, it, bt): await it.response.send_modal(BirthdayTimeModal(self))

    @discord.ui.button(label="Add Image", style=discord.ButtonStyle.secondary, row=2)
    async def add_img(self, it, bt): await it.response.send_modal(AddImageModal(self))

    @discord.ui.button(label="Clear Images", style=discord.ButtonStyle.danger, row=2)
    async def clear_img(self, it, bt):
        self.data["settings"]["image_urls"] = []
        await self._save_and_refresh(it, f"🗑️ {it.user.mention} cleared all birthday images.", is_ephemeral=False)

    @discord.ui.button(label="Export TXT", style=discord.ButtonStyle.secondary, row=1)
    async def exp(self, it, bt):
        txt = "USER ID | BIRTHDAY | TIMEZONE\n" + "-"*35 + "\n"
        for uid, rec in self.data.get("birthdays", {}).items():
            txt += f"{uid} | {rec['day']}/{rec['month']} | {rec['timezone']}\n"
        f = io.BytesIO(txt.encode())
        await it.response.send_message(f"📂 {it.user.mention} exported database to TXT.", file=discord.File(f, "birthdays.txt"), ephemeral=False)

    @discord.ui.button(label="Preview Single", style=discord.ButtonStyle.success, row=3)
    async def p1(self, it, bt):
        chan = self.bot.get_channel(self.data["settings"]["channel_id"])
        await _send_announcement_like(channel=chan, settings=self.data["settings"], members=[it.user], local_date=date.today(), tz_label="Test", test_mode=True)
        await it.response.send_message(f"✨ {it.user.mention} triggered preview.", ephemeral=False)

    @discord.ui.button(label="Preview Multi", style=discord.ButtonStyle.success, row=3)
    async def p2(self, it, bt):
        chan = self.bot.get_channel(self.data["settings"]["channel_id"])
        await _send_announcement_like(channel=chan, settings=self.data["settings"], members=[it.user, it.guild.me], local_date=date.today(), tz_label="Test", test_mode=True, force_multiple=True)
        await it.response.send_message(f"✨ {it.user.mention} triggered multi-preview.", ephemeral=False)

class BirthdayChannelSelect(discord.ui.ChannelSelect):
    def __init__(self): super().__init__(placeholder="Select Channel", row=4)
    async def callback(self, it): 
        self.view.data["settings"]["channel_id"] = self.values[0].id
        await self.view._save_and_refresh(it, f"📍 {it.user.mention} set channel to <#{self.values[0].id}>", is_ephemeral=False)

class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(self): super().__init__(placeholder="Select Role", row=5)
    async def callback(self, it): 
        self.view.data["settings"]["birthday_role_id"] = self.values[0].id
        await self.view._save_and_refresh(it, f"🏷️ {it.user.mention} set role to <@&{self.values[0].id}>", is_ephemeral=False)

# =========================================================
# Main Setup & Commands
# =========================================================
def setup(bot: discord.Client):
    tree = bot.tree; group = app_commands.Group(name="birthday", description="Birthday management")
    try: tree.add_command(group)
    except: pass

    async def tz_autocomplete(it: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return [app_commands.Choice(name=t, value=t) for t in sorted(available_timezones()) if current.lower() in t.lower()][:25]

    @group.command(name="set", description="Add your birthday")
    @app_commands.autocomplete(timezone=tz_autocomplete)
    async def b_set(it, day: int, month: int, timezone: str, user: Optional[discord.Member] = None):
        target = user or it.user; data, sha = await load_data()
        data["birthdays"][str(target.id)] = {"day": day, "month": month, "timezone": timezone}
        await save_data(data, sha)
        await it.response.send_message(f"✅ Birthday for **{target.display_name}** set to **{day}/{month}**.", ephemeral=False)

    @group.command(name="remove", description="Remove a birthday")
    async def b_rem(it, user: Optional[discord.Member] = None):
        target = user or it.user; data, sha = await load_data()
        if str(target.id) in data["birthdays"]:
            del data["birthdays"][str(target.id)]; await save_data(data, sha)
            await it.response.send_message(f"🗑️ {it.user.mention} removed **{target.display_name}**.", ephemeral=False)
        else: await it.response.send_message("❌ Not found.", ephemeral=False)

    @group.command(name="list", description="List all birthdays (Jan-Dec)")
    async def b_list(it):
        data, _ = await load_data(); bdays = data.get("birthdays", {})
        if not bdays: return await it.response.send_message("No data.", ephemeral=False)
        # Chronological Sort: Sort by Month then Day
        raw_items = []
        for uid, rec in bdays.items():
            m = it.guild.get_member(int(uid)); name = m.display_name if m else f"User {uid}"
            raw_items.append({"name": name, "day": rec['day'], "month": rec['month']})
        
        sorted_items = sorted(raw_items, key=lambda x: (x['month'], x['day']))
        formatted_list = [ (i['name'], f"{i['day']}/{i['month']}") for i in sorted_items]
        
        view = BirthdayListView(formatted_list)
        await it.response.send_message(embed=view._make_embed(), view=view, ephemeral=False)

    @group.command(name="upcoming", description="Show the next 5 upcoming birthdays")
    async def b_up(it):
        data, _ = await load_data(); bdays = data.get("birthdays", {}); today = date.today()
        if not bdays: return await it.response.send_message("No birthdays found.", ephemeral=False)
        sorted_bdays = []
        for uid, rec in bdays.items():
            try: bday_this_year = date(today.year, rec['month'], rec['day'])
            except ValueError: bday_this_year = date(today.year, 3, 1)
            if bday_this_year < today: bday_this_year = bday_this_year.replace(year=today.year + 1)
            sorted_bdays.append((uid, bday_this_year))
        sorted_bdays.sort(key=lambda x: x[1])
        lines = []
        for uid, d in sorted_bdays[:5]:
            m = it.guild.get_member(int(uid)); name = m.display_name if m else f"User {uid}"
            lines.append(f"**{name}** - {d.strftime('%-d %B')}")
        e = discord.Embed(title="📅 Upcoming Birthdays", description="\n".join(lines), color=0xff69b4)
        await it.response.send_message(embed=e, ephemeral=False)

    @group.command(name="help", description="How to use birthday commands")
    async def b_help(it):
        e = discord.Embed(title="🎂 Birthday Help", color=0xff69b4)
        e.add_field(name="Commands", value="`/birthday set` - Add yours\n`/birthday list` - See all\n`/birthday upcoming` - See next 5\n`/birthday settings` - Admin Panel")
        await it.response.send_message(embed=e, ephemeral=False)

    @group.command(name="settings", description="Admin settings")
    async def b_setts(it):
        if not has_app_access(it.user, "birthdays"): return await it.response.send_message("No perm.", ephemeral=False)
        data, sha = await load_data(); await it.response.send_message(embed=BirthdaySettingsView(bot, data, sha)._embed(), view=BirthdaySettingsView(bot, data, sha), ephemeral=True)

    @tasks.loop(minutes=1)
    async def birthday_tick():
        now_utc = datetime.now(timezone.utc); curr_year = now_utc.year
        data, sha = await load_data(); s = data["settings"]
        if not s.get("enabled"): return
        dirty = False; announced = {k for k in data["state"].get("announced_keys", []) if k.startswith(str(curr_year))}
        for guild in bot.guilds:
            chan, role = guild.get_channel(s.get("channel_id")), guild.get_role(s.get("birthday_role_id"))
            for uid, rec in data["birthdays"].items():
                member = guild.get_member(int(uid)) or await (lambda: guild.fetch_member(int(uid)) if True else None)()
                if not member: continue
                try: loc = now_utc.astimezone(ZoneInfo(rec.get("timezone", "Europe/London")))
                except: loc = now_utc.astimezone(UK_TZ)
                is_bday = (rec['day'] == loc.day and rec['month'] == loc.month)
                if role:
                    if is_bday and role not in member.roles: await member.add_roles(role)
                    elif not is_bday and role in member.roles: await member.remove_roles(role)
                if is_bday and chan and (loc.hour > s['post_hour'] or (loc.hour == s['post_hour'] and loc.minute >= s['post_minute'])):
                    k = f"{loc.date().isoformat()}|{uid}|ann"
                    if k not in announced:
                        if await _send_announcement_like(channel=chan, settings=s, members=[member], local_date=loc.date(), tz_label=rec.get("timezone"), test_mode=False):
                            announced.add(k); dirty = True
        if dirty: data["state"]["announced_keys"] = list(announced); await save_data(data, sha)

    @birthday_tick.before_loop
    async def b4(): await bot.wait_until_ready()
    if not hasattr(bot, "_birthday_tick_started"): birthday_tick.start(); bot._birthday_tick_started = True
