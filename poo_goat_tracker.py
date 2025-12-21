# poo_goat_tracker.py
# Tracks POO / GOAT history based ONLY on official Pilot announcements

from __future__ import annotations

import json
import os
import asyncio
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

POO_ROLE_ID = 1452316099541471233
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
    base = _default_data()

    if not os.path.exists(DATA_FILE):
        save_data(base)
        return base

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # normalise (handles empty {})
    data.setdefault("scores", {})
    data["scores"].setdefault("goat", {})
    data["scores"].setdefault("poo", {})
    data.setdefault("dates", {})
    data.setdefault("poo_milestones", {})
    data.setdefault("poo_role_until", {})

    return data


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

    total_pages = max(1, (len(sorted_scores) + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE)

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

    embed.set_footer(text=f"Page {page + 1} / {total_pages}")
    return embed


# ==============================
# PAGINATION VIEW
# ==============================

class LeaderboardDropdown(discord.ui.Select):
    def __init__(self, guild, board, data):
        self.guild = guild
        self.board = board
        self.data = data

        total_pages = max(
            1,
            (len(data["scores"][board]) + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE
        )

        options = [
            discord.SelectOption(
                label=f"Page {i + 1}",
                description=f"Ranks {i * ENTRIES_PER_PAGE + 1}–{min((i + 1) * ENTRIES_PER_PAGE, len(data['scores'][board]))}"
            )
            for i in range(total_pages)
        ]

        super().__init__(placeholder="Select a page", options=options)

    async def callback(self, interaction: discord.Interaction):
        page = int(self.values[0].split(" ")[1]) - 1
        embed = build_leaderboard_embed(self.guild, self.board, page, self.data)
        await interaction.response.edit_message(embed=embed)


class LeaderboardView(discord.ui.View):
    def __init__(self, guild, board, data):
        super().__init__(timeout=None)
        self.add_item(LeaderboardDropdown(guild, board, data))


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
        data["dates"].setdefault(date, {"goat": False, "poo": False})

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

    bot.on_message = on_message

    # -------- ROLE CLEANUP TASK --------
    @tasks.loop(hours=1)
    async def poo_cleanup():
        data = load_data()
        now = datetime.now(UK_TZ)
        changed = False

        for uid, until in list(data["poo_role_until"].items()):
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
            embed=build_leaderboard_embed(interaction.guild, "poo", 0, data),
            view=LeaderboardView(interaction.guild, "poo", data)
        )

    @app_commands.command(name="goatboard", description="View the GOAT leaderboard")
    async def goatboard(interaction: discord.Interaction):
        data = load_data()
        await interaction.response.send_message(
            embed=build_leaderboard_embed(interaction.guild, "goat", 0, data),
            view=LeaderboardView(interaction.guild, "goat", data)
        )

    # -------- REBUILD COMMAND --------
    @app_commands.command(
        name="rebuild_poo_goat",
        description="Rebuild POO / GOAT history from announcements"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def rebuild_poo_goat(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not channel:
            await interaction.followup.send("❌ Announcement channel not found.")
            return

        data = load_data()

        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.id != PILOT_BOT_ID:
                continue
            if not message.mentions:
                continue

            content = message.content.lower()
            is_poo = "is today’s poo" in content
            is_goat = "is today’s goat" in content

            if not is_poo and not is_goat:
                continue

            date = date_str(message.created_at)
            data["dates"].setdefault(date, {"poo": False, "goat": False})

            if data["dates"][date]["poo"] and data["dates"][date]["goat"]:
                continue

            uid = str(message.mentions[0].id)

            if is_poo and not data["dates"][date]["poo"]:
                count = data["scores"]["poo"].get(uid, 0) + 1
                data["scores"]["poo"][uid] = count
                data["dates"][date]["poo"] = True
                data.setdefault("poo_milestones", {}).setdefault(uid, [])
                if count in POO_MILESTONES:
                    data["poo_milestones"][uid].append(count)

            if is_goat and not data["dates"][date]["goat"]:
                data["scores"]["goat"][uid] = data["scores"]["goat"].get(uid, 0) + 1
                data["dates"][date]["goat"] = True

            await asyncio.sleep(0.25)

        save_data(data)
        await interaction.followup.send("✅ POO / GOAT history rebuilt.")

    bot.tree.add_command(pooboard)
    bot.tree.add_command(goatboard)
    bot.tree.add_command(rebuild_poo_goat)

    print("🐐💩 poo_goat_tracker registered")