# poo_goat_tracker.py
# Tracks POO / GOAT history based ONLY on official Pilot announcements

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List

import discord
from discord import app_commands
from discord.ext import tasks
from zoneinfo import ZoneInfo


# ==============================
# CONFIG
# ==============================

UK_TZ = ZoneInfo("Europe/London")

ANNOUNCEMENT_CHANNEL_ID = 1398508734506078240
PILOT_BOT_ID = 1429920180632293388

GOAT_EMOJI = "<:goated:1448995506234851408>"
POO_EMOJI = "💩"

POO_ROLE_ID = 1429934009550373059
POO_MILESTONES = {10, 20, 30, 40, 50, 60, 70, 80, 90, 100}
POO_ROLE_DURATION_DAYS = 14

DATA_FILE = "poo_goat_data.json"
ENTRIES_PER_PAGE = 10


# ==============================
# DATA HELPERS
# ==============================

def _default_data() -> Dict:
    return {
        "scores": {"goat": {}, "poo": {}},
        "dates": {},
        "poo_milestones": {},
        "poo_role_until": {}
    }


def load_data() -> Dict:
    if not os.path.exists(DATA_FILE):
        save_data(_default_data())
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: Dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def date_str(dt: datetime) -> str:
    return dt.astimezone(UK_TZ).strftime("%Y-%m-%d")


# ==============================
# LEADERBOARD EMBED
# ==============================

def build_leaderboard_embed(guild, board, page, data):
    scores = data["scores"][board]
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    start = page * ENTRIES_PER_PAGE
    end = start + ENTRIES_PER_PAGE
    chunk = sorted_scores[start:end]

    lines = []
    for i, (uid, score) in enumerate(chunk, start=start + 1):
        member = guild.get_member(int(uid))
        lines.append(f"**{i}.** {member.mention if member else f'<@{uid}>'} — `{score}`")

    if not lines:
        lines = ["*No data yet.*"]

    embed = discord.Embed(
        title="🐐 GOAT Leaderboard" if board == "goat" else "💩 POO Leaderboard",
        description="\n".join(lines),
        colour=0xF5C542 if board == "goat" else 0x8B5A2B
    )
    embed.set_footer(text=f"Page {page + 1}")
    return embed


# ==============================
# SETUP
# ==============================

def setup(bot: discord.Client):

    # -------- MESSAGE LISTENER --------
    async def on_message(message: discord.Message):
        if not message.author.bot:
            return
        if message.author.id != PILOT_BOT_ID:
            return
        if message.channel.id != ANNOUNCEMENT_CHANNEL_ID:
            return
        if not message.mentions:
            return

        content = message.content.lower()
        data = load_data()
        date = date_str(message.created_at)
        data.setdefault("dates", {}).setdefault(date, {"goat": False, "poo": False})

        uid = str(message.mentions[0].id)

        # 💩 POO
        if "is today’s poo" in content and not data["dates"][date]["poo"]:
            current = data["scores"]["poo"].get(uid, 0) + 1
            data["scores"]["poo"][uid] = current
            data["dates"][date]["poo"] = True
            data.setdefault("poo_milestones", {}).setdefault(uid, [])

            if current in POO_MILESTONES and current not in data["poo_milestones"][uid]:
                data["poo_milestones"][uid].append(current)

                if current == 50:
                    until = datetime.now(UK_TZ) + timedelta(days=POO_ROLE_DURATION_DAYS)
                    data["poo_role_until"][uid] = until.isoformat()

                    await message.channel.send(
                        f"💩 **POO MILESTONE** 💩\n\n"
                        f"<@{uid}> has reached **50 total poos**.\n"
                        f"The POO role will remain for **14 days**."
                    )

                    role = message.guild.get_role(POO_ROLE_ID)
                    member = message.guild.get_member(int(uid))
                    if role and member and role not in member.roles:
                        await member.add_roles(role)

                else:
                    await message.channel.send(
                        f"💩 **POO MILESTONE** 💩\n\n"
                        f"<@{uid}> has reached **{current} total poos**."
                    )

            await message.add_reaction(POO_EMOJI)
            save_data(data)

        # 🐐 GOAT
        if "is today’s goat" in content and not data["dates"][date]["goat"]:
            data["scores"]["goat"][uid] = data["scores"]["goat"].get(uid, 0) + 1
            data["dates"][date]["goat"] = True
            await message.add_reaction(GOAT_EMOJI)
            save_data(data)

    bot.add_listener(on_message)

    # -------- ROLE CLEANUP TASK --------
    @tasks.loop(hours=1)
    async def poo_cleanup():
        data = load_data()
        now = datetime.now(UK_TZ)
        changed = False

        for uid, until in list(data.get("poo_role_until", {}).items()):
            if now >= datetime.fromisoformat(until):
                for guild in bot.guilds:
                    member = guild.get_member(int(uid))
                    role = guild.get_role(POO_ROLE_ID)
                    if member and role and role in member.roles:
                        await member.remove_roles(role)
                del data["poo_role_until"][uid]
                changed = True

        if changed:
            save_data(data)

    poo_cleanup.start()

    # -------- SLASH COMMANDS --------
    @app_commands.command(name="pooboard", description="View the POO leaderboard")
    async def pooboard(interaction: discord.Interaction):
        data = load_data()
        await interaction.response.send_message(
            embed=build_leaderboard_embed(interaction.guild, "poo", 0, data)
        )

    @app_commands.command(name="goatboard", description="View the GOAT leaderboard")
    async def goatboard(interaction: discord.Interaction):
        data = load_data()
        await interaction.response.send_message(
            embed=build_leaderboard_embed(interaction.guild, "goat", 0, data)
        )

    bot.tree.add_command(pooboard)
    bot.tree.add_command(goatboard)

    print("🐐💩 poo_goat_tracker registered")