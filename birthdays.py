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
# Utility
# =========================================================
def _is_valid_tz(tz: str) -> bool:
    try: ZoneInfo(tz); return True
    except: return False

async def timezone_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    tzs = sorted(list(available_timezones()))
    matches = [t for t in tzs if current.lower() in t.lower()][:25]
    return [app_commands.Choice(name=m, value=m) for m in matches]

def _next_occurrence(day: int, month: int, now_local: date) -> date:
    year = now_local.year
    try: candidate = date(year, month, day)
    except: candidate = date(year, month, 1)
    if candidate < now_local:
        try: candidate = date(year + 1, month, day)
        except: candidate = date(year + 1, month, 1)
    return candidate

def _fmt(tpl: str, members: List[discord.Member]) -> str:
    mentions = ", ".join(m.mention for m in members)
    names = ", ".join(m.display_name for m in members)
    return (tpl or "").replace("{mention}", mentions).replace("{username}", names).replace("{users}", mentions)

# =========================================================
# Announcement Helper (NOW WITH EMBEDS)
# =========================================================
async def _send_announcement_like(*, channel, settings, members, local_date, tz_label, test_mode):
    if not members: return
    if test_mode: await channel.send("🧪 **TEST MODE**")

    # The Ping (Outside the embed)
    pings = ", ".join(m.mention for m in members)
    
    # The Content
    header = _fmt(settings.get("message_header", "Happy Birthday!"), members)
    body_tpl = settings.get("message_single" if len(members) == 1 else "message_multiple", "")
    body = _fmt(body_tpl, members)

    embed = discord.Embed(title=header, description=body, color=discord.Color.from_rgb(255, 105, 180)) # Pink
    
    img_url = random.choice(settings.get("image_urls", [])) if settings.get("image_urls") else None
    if img_url:
        embed.set_image(url=img_url)
    
    embed.set_footer(text=f"The Pilot • {local_date.strftime('%d %B')} • {tz_label}")
    
    await channel.send(content=pings, embed=embed)

# =========================================================
# UI Modals & Views
# =========================================================
class BirthdayMessageModal(discord.ui.Modal, title="Edit Birthday Message Card"):
    header_text = discord.ui.TextInput(label="Embed Header (Title)", placeholder="e.g. 🎂 Happy Birthday {username}!", max_length=100)
    single_message = discord.ui.TextInput(label="Message Body (Single)", style=discord.TextStyle.paragraph, max_length=1500)
    multiple_message = discord.ui.TextInput(label="Message Body (Multiple)", style=discord.TextStyle.paragraph, max_length=1500)

    def __init__(self, view: BirthdaySettingsView):
        super().__init__()
        self.view_ref = view
        s = view.data.get("settings", {})
        self.header_text.default = s.get("message_header")
        self.single_message.default = s.get("message_single")
        self.multiple_message.default = s.get("message_multiple")

    async def on_submit(self, interaction: discord.Interaction):
        s = self.view_ref.data["settings"]
        s["message_header"] = str(self.header_text.value)
        s["message_single"] = str(self.single_message.value)
        s["message_multiple"] = str(self.multiple_message.value)
        await self.view_ref._save_and_refresh(interaction, note="✅ Card design updated.")

# (Other Modals and Views remain similar but updated to support settings structure)
class PostTimeModal(discord.ui.Modal, title="Set Birthday Post Time"):
    hour = discord.ui.TextInput(label="Hour (0-23)", max_length=2)
    minute = discord.ui.TextInput(label="Minute (0-59)", max_length=2)
    def __init__(self, view): super().__init__(); self.view_ref = view; s = view.data.get("settings", {}); self.hour.default = str(s.get("post_hour", 12)); self.minute.default = str(s.get("post_minute", 0))
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
        ch = f"<#{s['channel_id']}>" if s['channel_id'] else "None"
        rl = f"<@&{s['birthday_role_id']}>" if s['birthday_role_id'] else "None"
        e = discord.Embed(title="🎂 Birthday Config", color=0xff69b4)
        e.description = f"**Enabled:** {s['enabled']}\n**Channel:** {ch}\n**Role:** {rl}\n**Time:** {s['post_hour']:02d}:{s['post_minute']:02d}\n**Images:** {len(s.get('image_urls', []))}"
        e.add_field(name="Header", value=f"```{s.get('message_header')}```", inline=False)
        e.add_field(name="Message", value=f"```{s.get('message_single')}```", inline=False)
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
    @discord.ui.button(label="Time", style=discord.ButtonStyle.secondary)
    async def ed_t(self, it, bt): await it.response.send_modal(PostTimeModal(self))
    @discord.ui.button(label="Images", style=discord.ButtonStyle.secondary)
    async def ed_i(self, it, bt): v = ImageSettingsView(self); await it.response.edit_message(embed=v._embed(), view=v)

class BirthdayChannelSelect(discord.ui.ChannelSelect):
    def __init__(self): super().__init__(placeholder="Select Channel", channel_types=[discord.ChannelType.text], row=3)
    async def callback(self, it): self.view.data["settings"]["channel_id"] = self.values[0].id; await self.view._save_and_refresh(it)

class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(self): super().__init__(placeholder="Select Birthday Role", row=4)
    async def callback(self, it): self.view.data["settings"]["birthday_role_id"] = self.values[0].id; await self.view._save_and_refresh(it)

# =========================================================
# Commands & Task
# =========================================================
def setup(bot: discord.Client):
    tree = bot.tree
    group = app_commands.Group(name="birthday", description="Birthdays")
    try: tree.add_command(group)
    except: pass

    @group.command(name="set")
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def b_set(it, day: int, month: int, timezone: str, user: Optional[discord.Member] = None):
        if not _is_valid_tz(timezone): return await it.response.send_message("❌ Bad Timezone.", ephemeral=True)
        target = user or it.user
        if user and not has_app_access(it.user, "birthdays"): return await it.response.send_message("❌ No perm.", ephemeral=True)
        data, sha = await load_data()
        data["birthdays"][str(target.id)] = {"day": day, "month": month, "timezone": timezone}
        await save_data(data, sha)
        await it.response.send_message(f"✅ Set {target.display_name}'s birthday to {day}/{month}.")

    @group.command(name="settings")
    async def b_settings(it):
        if not has_app_access(it.user, "birthdays"): return await it.response.send_message("❌ No permission.", ephemeral=True)
        data, sha = await load_data()
        view = BirthdaySettingsView(bot, data, sha)
        await it.response.send_message(embed=view._embed(), view=view)

    @tasks.loop(minutes=1)
    async def birthday_tick():
        now_utc = datetime.now(timezone.utc)
        data, sha = await load_data()
        s = data["settings"]
        if not s.get("enabled"): return

        dirty = False
        announced = set(data["state"].get("announced_keys", []))
        roles_set = set(data["state"].get("role_assigned_keys", []))

        for guild in bot.guilds:
            chan = guild.get_channel(s.get("channel_id"))
            role = guild.get_role(s.get("birthday_role_id"))
            buckets = {}

            for uid, rec in data["birthdays"].items():
                member = guild.get_member(int(uid))
                if not member: continue
                tz_str = rec.get("timezone", "Europe/London")
                loc_now = now_utc.astimezone(ZoneInfo(tz_str))
                loc_date = loc_now.date()
                is_bday = (rec['day'] == loc_date.day and rec['month'] == loc_date.month)

                if role:
                    r_key = f"{loc_date.isoformat()}|{uid}"
                    if is_bday and r_key not in roles_set:
                        try: await member.add_roles(role); roles_set.add(r_key); dirty = True
                        except: pass
                    elif not is_bday and role in member.roles:
                        try: await member.remove_roles(role)
                        except: pass

                if is_bday and s.get("announce") and chan:
                    if loc_now.hour == s['post_hour'] and loc_now.minute == s['post_minute']:
                        dk = loc_date.isoformat()
                        buckets.setdefault(dk, []).append(member)

            for d_key, mems in buckets.items():
                a_key = f"{d_key}|announce"
                if a_key not in announced:
                    try:
                        await _send_announcement_like(channel=chan, settings=s, members=mems, local_date=date.fromisoformat(d_key), tz_label="Local Time", test_mode=False)
                        announced.add(a_key); dirty = True
                    except: pass

        if dirty:
            data["state"]["announced_keys"] = list(announced)
            data["state"]["role_assigned_keys"] = list(roles_set)
            await save_data(data, sha)

    @birthday_tick.before_loop
    async def before_tick(): await bot.wait_until_ready()
    if not getattr(bot, "_birthday_tick_started", False):
        birthday_tick.start()
        setattr(bot, "_birthday_tick_started", True)
