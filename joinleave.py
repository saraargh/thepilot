# joinleave.py
import discord
import asyncio
import random
import os
import json
import base64
import requests
from typing import Dict, Any

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "welcome_config.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Default Config -------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "welcome": {
        "enabled": True,
        "welcome_channel_id": None,
        "title": "Welcome to the server, {user}! 👋🏼",
        "description": "",
        "channels": {},
        "arrival_images": [],
        "bot_add": {
            "enabled": True,
            "channel_id": None
        }
    },
    "member_logs": {
        "enabled": True,
        "channel_id": None,
        "log_leave": True,
        "log_kick": True,
        "log_ban": True
    },
    "boost": {
        "enabled": True,
        "channel_id": None,
        "messages": {
            "single": "💎 {user} just boosted the server! 💎",
            "double": "🔥 {user} just used **both boosts**! 🔥",
            "tier": "🚀 **NEW BOOST TIER UNLOCKED!** 🚀\nThanks to {user}!"
        },
        "images": []
    }
}

# ======================================================
# CONFIG IO
# ======================================================

def _gh_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

def ensure_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg.setdefault("welcome", DEFAULT_CONFIG["welcome"])
    cfg.setdefault("member_logs", DEFAULT_CONFIG["member_logs"])
    cfg.setdefault("boost", DEFAULT_CONFIG["boost"])

    cfg["welcome"].setdefault("channels", {})
    cfg["welcome"].setdefault("arrival_images", [])
    cfg["welcome"].setdefault("bot_add", {"enabled": True, "channel_id": None})

    b = cfg["boost"]
    b.setdefault("enabled", True)
    b.setdefault("channel_id", None)
    b.setdefault("messages", DEFAULT_CONFIG["boost"]["messages"])
    b.setdefault("images", [])

    return cfg

def load_config() -> Dict[str, Any]:
    try:
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            raw = base64.b64decode(r.json()["content"]).decode()
            cfg = json.loads(raw) if raw.strip() else DEFAULT_CONFIG.copy()
            return ensure_config(cfg)
        save_config(DEFAULT_CONFIG.copy())
        return ensure_config(DEFAULT_CONFIG.copy())
    except Exception:
        return ensure_config(DEFAULT_CONFIG.copy())

def save_config(cfg: Dict[str, Any]) -> None:
    cfg = ensure_config(cfg)
    try:
        sha = None
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": "Update welcome configuration",
            "content": base64.b64encode(json.dumps(cfg, indent=2).encode()).decode()
        }
        if sha:
            payload["sha"] = sha

        requests.put(_gh_url(), headers=HEADERS, json=payload, timeout=10)
    except Exception:
        pass

# ======================================================
# HELPERS
# ======================================================

def human_member_number(guild: discord.Guild) -> int:
    return len([m for m in guild.members if not m.bot])

def render(text: str, *, user, guild, member_count: int, channels: Dict[str, int]) -> str:
    if not text:
        return ""
    out = (
        text.replace("{user}", getattr(user, "mention", ""))
            .replace("{mention}", getattr(user, "mention", ""))
            .replace("{server}", guild.name)
            .replace("{member_count}", str(member_count))
    )
    for name, cid in (channels or {}).items():
        out = out.replace(f"{{channel:{name}}}", f"<#{cid}>")
    return out

# ======================================================
# RUNTIME SYSTEM
# ======================================================

class WelcomeSystem:
    def __init__(self, client: discord.Client):
        self.client = client
        self._recent_boosts: Dict[int, float] = {}
        self._last_tier: Dict[int, int] = {}
        self._pending_boost_counts: Dict[tuple, int] = {} # Helper for double boost detection

    # ---------------- MEMBER JOIN ----------------

    async def on_member_join(self, member: discord.Member):
        cfg = load_config()

        # ---- BOT ADD ----
        if member.bot:
            b = (cfg.get("welcome", {}) or {}).get("bot_add", {}) or {}
            if not b.get("enabled") or not b.get("channel_id"):
                return

            channel = self.client.get_channel(b["channel_id"])
            if not channel:
                return

            await asyncio.sleep(1.5)

            async for entry in member.guild.audit_logs(
                limit=5, action=discord.AuditLogAction.bot_add
            ):
                if entry.target and entry.target.id == member.id:
                    await channel.send(
                        f"🤖 {entry.user.mention} added a bot (**{member.name}**)"
                    )
                    return
            return

        # ---- WELCOME ----
        w = cfg.get("welcome", {}) or {}
        if not w.get("enabled") or not w.get("welcome_channel_id"):
            return

        channel = self.client.get_channel(w["welcome_channel_id"])
        if not channel:
            return

        count = human_member_number(member.guild)
        now = discord.utils.utcnow().strftime("%H:%M")

        embed = discord.Embed(
            title=render(
                w.get("title", ""),
                user=member,
                guild=member.guild,
                member_count=count,
                channels=w.get("channels", {}),
            ),
            description=render(
                w.get("description", ""),
                user=member,
                guild=member.guild,
                member_count=count,
                channels=w.get("channels", {}),
            ),
            color=discord.Color.blurple(),
        )

        embed.set_footer(
            text=f"You landed as passenger #{count} ✈️ | Today at {now}"
        )

        imgs = w.get("arrival_images") or []
        if imgs:
            embed.set_image(url=random.choice(imgs))

        await channel.send(content=member.mention, embed=embed)

    # ---------------- MEMBER REMOVE ----------------

    async def on_member_remove(self, member: discord.Member):
        cfg = load_config()
        m = cfg.get("member_logs", {}) or {}

        if not m.get("enabled") or not m.get("channel_id"):
            return

        channel = self.client.get_channel(m["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)

        async for entry in member.guild.audit_logs(
            limit=5, action=discord.AuditLogAction.kick
        ):
            if entry.target and entry.target.id == member.id:
                if m.get("log_kick", True):
                    await channel.send(
                        f"🥾 **{member.name}** was kicked by {entry.user.mention}"
                    )
                return

        if m.get("log_leave", True):
            await channel.send(f"👋 **{member.name}** left the server")

    # ---------------- MEMBER BAN ----------------

    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        cfg = load_config()
        m = cfg.get("member_logs", {}) or {}

        if not m.get("enabled") or not m.get("log_ban") or not m.get("channel_id"):
            return

        channel = self.client.get_channel(m["channel_id"])
        if not channel:
            return

        await asyncio.sleep(1.5)

        async for entry in guild.audit_logs(
            limit=5, action=discord.AuditLogAction.ban
        ):
            if entry.target and entry.target.id == user.id:
                await channel.send(
                    f"⛔ **{user.name}** was banned by {entry.user.mention}"
                )
                return

    # ---------------- BOOST EVENT (LISTENER) ----------------

    async def on_message(self, message: discord.Message):
        boost_types = [
            discord.MessageType.premium_guild_subscription,
            discord.MessageType.premium_guild_tier_1,
            discord.MessageType.premium_guild_tier_2,
            discord.MessageType.premium_guild_tier_3,
        ]

        if message.type not in boost_types:
            return

        # Config Check
        cfg = load_config()
        b = cfg.get("boost", {}) or {}
        if not b.get("enabled") or not b.get("channel_id"):
            return

        guild = message.guild
        user = message.author
        key = (guild.id, user.id)

        # Immediate Action for Tiers
        if message.type != discord.MessageType.premium_guild_subscription:
            await self._execute_boost_embed(message, b["messages"]["tier"])
            return

        # Logic for Single vs Double
        if key in self._pending_boost_counts:
            self._pending_boost_counts[key] += 1
            return
        
        self._pending_boost_counts[key] = 1
        await asyncio.sleep(30) # Your requested wait time
        
        final_count = self._pending_boost_counts.pop(key, 1)
        msg_template = b["messages"]["double"] if final_count > 1 else b["messages"]["single"]
        
        await self._execute_boost_embed(message, msg_template)

    async def _execute_boost_embed(self, message, text_template):
        cfg = load_config()
        b = cfg.get("boost", {}) or {}
        channel = self.client.get_channel(int(b["channel_id"]))
        if not channel: return

        guild = message.guild
        user = message.author
        total_boosts = guild.premium_subscription_count or 0
        now = discord.utils.utcnow().strftime("%H:%M")

        embed = discord.Embed(
            description=render(
                text_template,
                user=user,
                guild=guild,
                member_count=total_boosts,
                channels={}
            ),
            color=discord.Color.blurple(),
        )

        embed.set_footer(
            text=f"{total_boosts} boosts total | Today at {now}"
        )

        imgs = b.get("images") or []
        if imgs:
            embed.set_image(url=random.choice(imgs))

        await channel.send(content=user.mention, embed=embed)
