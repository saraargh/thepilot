from __future__ import annotations

import os
import json
import base64
import asyncio
import io
import random
from datetime import datetime, timezone, date, timedelta
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
GITHUB_FILE_PATH = "birthdays.json"
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
        "post_hour": 12,
        "post_minute": 0,
        "message_header": "🎂 Birthday Celebration!",
        "message_single": "Hope you have the best most magical day ever and all your wishes come true!!",
        "message_multiple": "Hope you all have the best most magical day ever and all your wishes come true!!",
        "image_urls": []
    },
    "birthdays": {},
    "state": {
        "announced_keys": [],
        "role_assigned_keys": []
    }
}

_lock = asyncio.Lock()
_TZ_CACHE: Optional[List[str]] = None

# =========================================================
# GitHub JSON Helpers
# =========================================================
async def _gh_get_file() -> Tuple[Optional[dict], Optional[str]]:
    if not GITHUB_TOKEN: return None, None
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
        async with session.get(url, headers=HEADERS) as r:
            if r.status == 404: return None, None
            if r.status >= 400: raise RuntimeError(f"GitHub GET failed ({r.status})")
            payload = await r.json()
            sha = payload.get("sha")
            raw = base64.b64decode(payload.get("content", "")).decode("utf-8")
            return json.loads(raw), sha

async def _gh_put_file(data: dict, sha: Optional[str]) -> Optional[str]:
    if not GITHUB_TOKEN: return None
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    raw = json.dumps(data, indent=2, ensure_ascii=False)
    body = {"message": f"Update {GITHUB_FILE_PATH}", "content": base64.b64encode(raw.encode("utf-8")).decode("utf-8"), **({"sha": sha} if sha else {})}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.put(url, headers=HEADERS, json=body) as r:
            if r.status >= 400: raise RuntimeError(f"GitHub PUT failed ({r.status})")
            payload = await r.json()
            return payload.get("content", {}).get("sha")

async def load_data() -> Tuple[dict, Optional[str]]:
    async with _lock:
        data, sha = await _gh_get_file()
        if not data: return json.loads(json.dumps(DEFAULT_DATA)), sha
        merged = json.loads(json.dumps(DEFAULT_DATA))
        merged.update(data)
        merged["settings"] = {**DEFAULT_DATA["settings"], **(data.get("settings") or {})}
        merged["state"] = {**DEFAULT_DATA["state"], **(data.get("state") or {})}
        return merged, sha

async def save_data(data: dict, sha: Optional[str]) -> Optional[str]:
    async with _lock:
        for attempt in range(3):
            try: return await _gh_put_file(data, sha)
            except RuntimeError as e:
                if "409" in str(e) and attempt < 2:
                    latest_data, latest_sha = await _gh_get_file()
                    sha = latest_sha
                    if latest_data:
                        for k in ["announced_keys", "role_assigned_keys"]:
                            data["state"][k] = list(set(data["state"].get(k, []) or []) | set(latest_data.get("state", {}).get(k, []) or []))
                    await asyncio.sleep(1); continue
                raise e
    return None

# =========================================================
# Utility & Timezones
# =========================================================
def _get_all_timezones() -> List[str]:
    global _TZ_CACHE
    if _TZ_CACHE is None:
        all_tz = available_timezones()
        filtered = [t for t in all_tz if "/" in t and not t.startswith("Etc/")]
        _TZ_CACHE = sorted(filtered)
    return _TZ_CACHE

def _is_valid_tz(tz: str) -> bool:
    try: ZoneInfo(tz); return True
    except: return False

async def timezone_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    if not current:
        priority = ["Europe/London", "America/New_York", "America/Los_Angeles", "Europe/Paris", "UTC", "Australia/Sydney"]
        return [app_commands.Choice(name=tz, value=tz) for tz in priority]
    cur = current.lower()
    tzs = _get_all_timezones()
    matches = [t for t in tzs if cur in t.lower()][:25]
    return [app_commands.Choice(name=m, value=m) for m in matches]

def _fmt(tpl: str, members: List[discord.Member]) -> str:
    mentions = ", ".join(m.mention for m in members)
    names = ", ".join(m.display_name for m in members)
    return (tpl or "").replace("{mention}", mentions).replace("{username}", names).replace("{users}", mentions)

def _next_occurrence(day: int, month: int, now_local: date) -> date:
    year = now_local.year
    try: candidate = date(year, month, day)
    except: candidate = date(year, month, 1) # Fallback for Feb 29
    if candidate < now_local:
        try: candidate = date(year + 1, month, day)
        except: candidate = date(year + 1, month, 1)
    return candidate

# =========================================================
# Announcement Helper
# =========================================================
async def _send_announcement_like(*, channel, settings, members, local_date, tz_label, test_mode):
    if not members: return
    pings = ", ".join(m.mention for m in members)
    header = _fmt(settings.get("message_header", "Happy Birthday!"), members)
    body_tpl = settings.get("message_single" if len(members) == 1 else "message_multiple", "")
    body = _fmt(body_tpl, members)
    embed = discord.Embed(title=header, description=body, color=discord.Color.from_rgb(255, 105, 180))
    if test_mode: embed.set_author(name="PREVIEW MODE")
    img_urls = settings.get("image_urls", [])
    if img_urls: embed.set_image(url=random.choice(img_urls))
    embed.set_footer(text=f"The Pilot • {local_date.strftime('%-d %B')} • {tz_label}")
    await channel.send(content=pings if not test_mode else f"🔔 *Ping Preview:* {pings}", embed=embed)

# =========================================================
# UI Modals & Views
# =========================================================
class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Message Card"):
    header_text = discord.ui.TextInput(label="Embed Header (Title)", placeholder="e.g. 🎂 Happy Birthday {username}!", max_length=100)
    single_message = discord.ui.TextInput(label="Message Body", style=discord.TextStyle.paragraph, max_length=1500)
    def __init__(self, view: BirthdaySettingsView):
        super().__init__(); self.view_ref = view; s = view.data.get("settings", {})
        self.header_text.default = s.get("message_header"); self.single_message.default = s.get("message_single")
    async def on_submit(self, interaction: discord.Interaction):
        s = self.view_ref.data["settings"]
        s["message_header"] = str(self.header_text.value); s["message_single"] = str(self.single_message.value); s["message_multiple"] = str(self.single_message.value)
        await self.view_ref._save_and_refresh(interaction, note="✅ Card design updated.")

class PostTimeModal(discord.ui.Modal, title="Set Birthday Post Time"):
    hour = discord.ui.TextInput(label="Hour (0-23)", max_length=2)
    minute = discord.ui.TextInput(label="Minute (0-59)", max_length=2)
    def __init__(self, view):
        super().__init__(); self.view_ref = view; s = view.data.get("settings", {})
        self.hour.default = str(s.get("post_hour", 12)); self.minute.default = str(s.get("post_minute", 0))
    async def on_submit(self, it):
        try:
            h, m = int(self.hour.value), int(self.minute.value)
            if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError()
            self.view_ref.data["settings"].update({"post_hour": h, "post_minute": m})
            await self.view_ref._save_and_refresh(it, note=f"⏰ Time set to {h:02d}:{m:02d}.")
        except: await it.response.send_message("❌ Invalid numbers.", ephemeral=True)

class AddImageModal(discord.ui.Modal, title="Add Image URL"):
    url = discord.ui.TextInput(label="Direct Image URL", placeholder="https://.../image.gif")
    def __init__(self, view): super().__init__(); self.view_ref = view
    async def on_submit(self, it):
        u = str(self.url.value).strip()
        if not u.startswith("http"): return await it.response.send_message("❌ Invalid URL.", ephemeral=True)
        self.view_ref.data["settings"].setdefault("image_urls", []).append(u)
        await self.view_ref._save_and_refresh(it)

class RemoveImageModal(discord.ui.Modal, title="Remove Image"):
    num = discord.ui.TextInput(label="Image # to remove")
    def __init__(self, view): super().__init__(); self.view_ref = view
    async def on_submit(self, it):
        imgs = self.view_ref.data["settings"].get("image_urls", [])
        try: idx = int(self.num.value) - 1; imgs.pop(idx); await self.view_ref._save_and_refresh(it)
        except: await it.response.send_message("❌ Invalid number.", ephemeral=True)

class ImageSettingsView(discord.ui.View):
    def __init__(self, parent): super().__init__(timeout=300); self.parent = parent; self.data = parent.data; self.sha = parent.sha
    def _embed(self):
        imgs = self.data["settings"].get("image_urls", [])
        desc = "\n".join(f"{i+1}. {u}" for i, u in enumerate(imgs[:15])) or "No images."
        return discord.Embed(title="🖼️ Birthday Images", description=desc, color=0x9b59b6)
    async def _save_and_refresh(self, it, note=None):
        new_sha = await save_data(self.data, self.sha)
        if new_sha: self.sha = self.parent.sha = new_sha
        await it.response.edit_message(embed=self._embed(), view=self)
    @discord.ui.button(label="Add URL", style=discord.ButtonStyle.green)
    async def add(self, it, bt): await it.response.send_modal(AddImageModal(self))
    @discord.ui.button(label="Remove #", style=discord.ButtonStyle.red)
    async def rem(self, it, bt): await it.response.send_modal(RemoveImageModal(self))
    @discord.ui.button(label="Back")
    async def back(self, it, bt): await it.response.edit_message(embed=self.parent._embed(), view=self.parent)

class BirthdaySettingsView(discord.ui.View):
    def __init__(self, bot, data, sha):
        super().__init__(timeout=300); self.bot = bot; self.data = data; self.sha = sha
        self.add_item(BirthdayChannelSelect()); self.add_item(BirthdayRoleSelect())
    def _embed(self):
        s = self.data["settings"]
        ch = f"<#{s['channel_id']}>" if s['channel_id'] else "Not Set"
        rl = f"<@&{s['birthday_role_id']}>" if s['birthday_role_id'] else "Not Set"
        e = discord.Embed(title="🎂 Birthday Configuration", color=0xff69b4)
        e.add_field(name="Bot Status", value="✅ Enabled" if s['enabled'] else "❌ Disabled", inline=True)
        e.add_field(name="Announcements", value=ch, inline=True)
        e.add_field(name="Birthday Role", value=rl, inline=True)
        e.add_field(name="Post Time", value=f"{s['post_hour']:02d}:{s['post_minute']:02d} (Local)", inline=True)
        e.add_field(name="Gallery", value=f"{len(s.get('image_urls', []))} Images", inline=True)
        return e
    async def _save_and_refresh(self, it, note=None):
        new_sha = await save_data(self.data, self.sha)
        if new_sha: self.sha = new_sha
        await it.response.edit_message(embed=self._embed(), view=self)
        if note: await it.followup.send(note, ephemeral=True)
    @discord.ui.button(label="Toggle Bot", style=discord.ButtonStyle.primary)
    async def t_en(self, it, bt): self.data["settings"]["enabled"] = not self.data["settings"]["enabled"]; await self._save_and_refresh(it)
    @discord.ui.button(label="Edit Card", style=discord.ButtonStyle.secondary)
    async def ed_m(self, it, bt): await it.response.send_modal(BirthdayMessageModal(self))
    @discord.ui.button(label="Set Time", style=discord.ButtonStyle.secondary)
    async def ed_t(self, it, bt): await it.response.send_modal(PostTimeModal(self))
    @discord.ui.button(label="Images", style=discord.ButtonStyle.secondary)
    async def ed_i(self, it, bt): v = ImageSettingsView(self); await it.response.edit_message(embed=v._embed(), view=v)
    @discord.ui.button(label="Preview Card", style=discord.ButtonStyle.success)
    async def preview(self, it, bt):
        s = self.data["settings"]; chan = self.bot.get_channel(s.get("channel_id"))
        if not chan: return await it.response.send_message("❌ Set a channel first!", ephemeral=True)
        await it.response.send_message("✨ Preview sent.", ephemeral=True)
        await _send_announcement_like(channel=chan, settings=s, members=[it.user], local_date=date.today(), tz_label="Preview Zone", test_mode=True)
    @discord.ui.button(label="Export .txt", style=discord.ButtonStyle.blurple)
    async def export(self, it, bt):
        bds = self.data.get("birthdays", {})
        if not bds: return await it.response.send_message("❌ No data to export.", ephemeral=True)
        lines = [f"USER_ID: {uid} | DATE: {r['day']}/{r['month']} | TZ: {r['timezone']}" for uid, r in bds.items()]
        buf = io.BytesIO("\n".join(lines).encode("utf-8"))
        await it.response.send_message("📁 Here is your birthday data export:", file=discord.File(buf, filename="birthday_export.txt"), ephemeral=True)

class BirthdayChannelSelect(discord.ui.ChannelSelect):
    def __init__(self): super().__init__(placeholder="Select Announcement Channel", channel_types=[discord.ChannelType.text], row=3)
    async def callback(self, it): self.view.data["settings"]["channel_id"] = self.values[0].id; await self.view._save_and_refresh(it)

class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(self): super().__init__(placeholder="Select Auto-Role", row=4)
    async def callback(self, it): self.view.data["settings"]["birthday_role_id"] = self.values[0].id; await self.view._save_and_refresh(it)

# =========================================================
# Commands & Task
# =========================================================
def setup(bot: discord.Client):
    tree = bot.tree
    group = app_commands.Group(name="birthday", description="Manage server birthdays")
    try: tree.add_command(group)
    except: pass

    @group.command(name="help", description="How to use the birthday commands")
    async def b_help(it: discord.Interaction):
        embed = discord.Embed(
            title="🎂 Birthday Help", 
            description="Use these commands to manage your birthday reminders!",
            color=discord.Color.from_rgb(255, 105, 180)
        )
        embed.add_field(
            name="`/birthday set`", 
            value="Register your birthday.\n**Timezone:** Start typing your city/country (e.g., 'London' or 'New York') in the timezone field and select from the list.", 
            inline=False
        )
        embed.add_field(
            name="`/birthday remove`", 
            value="Remove your birthday from the system.", 
            inline=False
        )
        embed.add_field(
            name="`/birthday upcoming`", 
            value="See who has a birthday coming up in the next 31 days.", 
            inline=False
        )
        embed.set_footer(text="The Pilot • Management System")
        await it.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="set", description="Register a birthday")
    @app_commands.describe(day="Day of the month (1-31)", month="Month number (1-12)", timezone="Search and select your local timezone", user="Admin only: User to set birthday for")
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def b_set(it, day: int, month: int, timezone: str, user: Optional[discord.Member] = None):
        if not _is_valid_tz(timezone): return await it.response.send_message("❌ Invalid Timezone.", ephemeral=True)
        target = user or it.user
        if user and user.id != it.user.id:
            if not has_app_access(it.user, "birthdays"):
                return await it.response.send_message("❌ You do not have permission to set other users' birthdays.", ephemeral=True)
        
        data, sha = await load_data()
        data["birthdays"][str(target.id)] = {"day": day, "month": month, "timezone": timezone}
        await save_data(data, sha)
        await it.response.send_message(f"✅ Set {target.display_name}'s birthday to {day}/{month} ({timezone}).")

    @group.command(name="remove", description="Remove a registered birthday")
    @app_commands.describe(user="Admin only: User to remove birthday for")
    async def b_remove(it: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or it.user
        if target.id != it.user.id:
            if not has_app_access(it.user, "birthdays"):
                return await it.response.send_message("❌ You do not have permission to remove other users' birthdays.", ephemeral=True)
        
        data, sha = await load_data()
        uid_str = str(target.id)
        if uid_str not in data.get("birthdays", {}):
            return await it.response.send_message(f"❌ No birthday found for {target.display_name}.", ephemeral=True)
        
        del data["birthdays"][uid_str]
        await save_data(data, sha)
        await it.response.send_message(f"🗑️ Removed birthday record for {target.display_name}.")

    @group.command(name="upcoming", description="Show birthdays in the next 31 days")
    async def b_upcoming(it):
        data, _ = await load_data()
        bds = data.get("birthdays", {})
        today = datetime.now(UK_TZ).date()
        found = []
        for uid, r in bds.items():
            nxt = _next_occurrence(r['day'], r['month'], today)
            diff = (nxt - today).days
            if 0 <= diff <= 31: found.append((diff, nxt, uid))
        if not found: return await it.response.send_message("No birthdays in the next 31 days.")
        found.sort()
        lines = [f"• **{d.strftime('%d %b')}** (in {diff} days) - <@{u}>" for diff, d, u in found]
        await it.response.send_message(embed=discord.Embed(title="📅 Upcoming Birthdays (Next 31 Days)", description="\n".join(lines), color=0x3498db))

    @group.command(name="settings", description="Admin only: Configure birthday announcement settings")
    async def b_settings(it):
        if not has_app_access(it.user, "birthdays"): return await it.response.send_message("❌ No perm.", ephemeral=True)
        data, sha = await load_data()
        view = BirthdaySettingsView(bot, data, sha)
        await it.response.send_message(embed=view._embed(), view=view)

    @tasks.loop(minutes=1)
    async def birthday_tick():
        now_utc = datetime.now(timezone.utc); data, sha = await load_data(); s = data["settings"]
        if not s or not s.get("enabled"): return
        dirty = False; announced = set(data["state"].get("announced_keys", [])); roles_set = set(data["state"].get("role_assigned_keys", []))
        for guild in bot.guilds:
            chan = guild.get_channel(s.get("channel_id")); role = guild.get_role(s.get("birthday_role_id")); buckets = {}; bucket_tz = {}
            for uid, rec in data["birthdays"].items():
                member = guild.get_member(int(uid))
                if not member: continue
                tz_str = rec.get("timezone", "Europe/London"); loc_now = now_utc.astimezone(ZoneInfo(tz_str)); loc_date = loc_now.date()
                is_bday = (rec['day'] == loc_date.day and rec['month'] == loc_date.month)
                
                # Logic: Give role only at post time, Remove at local midnight
                if role:
                    r_key = f"{loc_date.isoformat()}|{uid}"
                    # Add role when announcement happens
                    if is_bday and loc_now.hour == s['post_hour'] and loc_now.minute == s['post_minute']:
                        if r_key not in roles_set and role not in member.roles:
                            try: await member.add_roles(role); roles_set.add(r_key); dirty = True
                            except: pass
                    # Remove role when it is no longer their birthday in their local time (Midnight)
                    elif not is_bday and role in member.roles:
                        try: await member.remove_roles(role)
                        except: pass

                if is_bday and s.get("announce") and chan:
                    if loc_now.hour == s['post_hour'] and loc_now.minute == s['post_minute']:
                        dk = loc_date.isoformat(); buckets.setdefault(dk, []).append(member); bucket_tz[dk] = tz_str
            
            for d_key, mems in buckets.items():
                a_key = f"{d_key}|announce"
                if a_key not in announced:
                    try: await _send_announcement_like(channel=chan, settings=s, members=mems, local_date=date.fromisoformat(d_key), tz_label=bucket_tz[d_key], test_mode=False)
                    except: pass
                    announced.add(a_key); dirty = True
        if dirty:
            data["state"]["announced_keys"] = list(announced); data["state"]["role_assigned_keys"] = list(roles_set)
            await save_data(data, sha)

    @birthday_tick.before_loop
    async def before_tick(): await bot.wait_until_ready()
    if not getattr(bot, "_birthday_tick_started", False):
        birthday_tick.start(); setattr(bot, "_birthday_tick_started", True)
