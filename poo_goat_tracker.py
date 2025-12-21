# poo_goat_tracker.py
# Tracks POO / GOAT history based ONLY on official Pilot announcements

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List

import discord
from discord import app_commands
from discord.ext import commands
from zoneinfo import ZoneInfo


# ==============================
# CONFIG
# ==============================

UK_TZ = ZoneInfo("Europe/London")

ANNOUNCEMENT_CHANNEL_ID = 1398508734506078240
PILOT_BOT_ID = 1429920180632293388  # ← SET THIS to The Pilot bot user ID

GOAT_EMOJI = "<:goated:1448995506234851408>"
POO_EMOJI = "💩"

DATA_FILE = "poo_goat_data.json"

ENTRIES_PER_PAGE = 10


# ==============================
# DATA HELPERS
# ==============================

def _default_data() -> Dict:
    return {
        "scores": {
            "goat": {},
            "poo": {}
        },
        "dates": {}
    }


def load_data() -> Dict:
    if not os.path.exists(DATA_FILE):
        save_data(_default_data())
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: Dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def date_str_from_dt(dt: datetime) -> str:
    return dt.astimezone(UK_TZ).strftime("%Y-%m-%d")


def ensure_date_entry(data: Dict, date: str):
    if date not in data["dates"]:
        data["dates"][date] = {
            "goat": False,
            "poo": False
        }


# ==============================
# LEADERBOARD EMBED BUILDER
# ==============================

def build_leaderboard_embed(
    guild: discord.Guild,
    board_type: str,
    page: int,
    data: Dict
) -> discord.Embed:

    scores = data["scores"][board_type]
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    total_pages = max(1, (len(sorted_scores) + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE)

    start = page * ENTRIES_PER_PAGE
    end = start + ENTRIES_PER_PAGE
    chunk = sorted_scores[start:end]

    lines = []
    for i, (uid, score) in enumerate(chunk, start=start + 1):
        member = guild.get_member(int(uid))
        name = member.mention if member else f"<@{uid}>"
        lines.append(f"**{i}.** {name} — `{score}`")

    if not lines:
        lines.append("*No data yet.*")

    title = "🐐 GOAT Leaderboard" if board_type == "goat" else "💩 POO Leaderboard"
    colour = 0xF5C542 if board_type == "goat" else 0x8B5A2B

    embed = discord.Embed(
        title=title,
        description="\n".join(lines),
        colour=colour
    )

    embed.set_footer(text=f"Page {page + 1} / {total_pages} • All-time")

    return embed


# ==============================
# DROPDOWN VIEW
# ==============================

class LeaderboardView(discord.ui.View):
    def __init__(self, guild: discord.Guild, board_type: str, data: Dict):
        super().__init__(timeout=None)
        self.guild = guild
        self.board_type = board_type
        self.data = data

        scores = data["scores"][board_type]
        total_pages = max(1, (len(scores) + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE)

        options = []
        for i in range(total_pages):
            start = i * ENTRIES_PER_PAGE + 1
            end = min((i + 1) * ENTRIES_PER_PAGE, len(scores))
            options.append(
                discord.SelectOption(
                    label=f"Page {i + 1}",
                    description=f"Ranks {start}–{end}"
                )
            )

        self.add_item(LeaderboardSelect(self, options))


class LeaderboardSelect(discord.ui.Select):
    def __init__(self, view: LeaderboardView, options: List[discord.SelectOption]):
        super().__init__(
            placeholder="Select a page",
            options=options
        )
        self.lb_view = view

    async def callback(self, interaction: discord.Interaction):
        page = int(self.values[0].split(" ")[1]) - 1
        embed = build_leaderboard_embed(
            self.lb_view.guild,
            self.lb_view.board_type,
            page,
            self.lb_view.data
        )
        await interaction.response.edit_message(embed=embed, view=self.lb_view)


# ==============================
# COG
# ==============================

class PooGoatTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- MESSAGE LISTENER ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot is False:
            return

        if PILOT_BOT_ID and message.author.id != PILOT_BOT_ID:
            return

        if message.channel.id != ANNOUNCEMENT_CHANNEL_ID:
            return

        if not message.mentions:
            return

        content = message.content.lower()
        data = load_data()
        date = date_str_from_dt(message.created_at)
        ensure_date_entry(data, date)

        uid = str(message.mentions[0].id)

        # 💩 POO
        if "is today’s poo" in content and not data["dates"][date]["poo"]:
            data["scores"]["poo"][uid] = data["scores"]["poo"].get(uid, 0) + 1
            data["dates"][date]["poo"] = True
            await message.add_reaction(POO_EMOJI)
            save_data(data)
            return

        # 🐐 GOAT
        if "is today’s goat" in content and not data["dates"][date]["goat"]:
            data["scores"]["goat"][uid] = data["scores"]["goat"].get(uid, 0) + 1
            data["dates"][date]["goat"] = True
            await message.add_reaction(GOAT_EMOJI)
            save_data(data)
            return

    # ---------------- LEADERBOARDS ----------------

    @app_commands.command(name="pooboard", description="View the POO leaderboard")
    async def pooboard(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_leaderboard_embed(interaction.guild, "poo", 0, data)
        view = LeaderboardView(interaction.guild, "poo", data)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="goatboard", description="View the GOAT leaderboard")
    async def goatboard(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_leaderboard_embed(interaction.guild, "goat", 0, data)
        view = LeaderboardView(interaction.guild, "goat", data)
        await interaction.response.send_message(embed=embed, view=view)

    # ---------------- BACKFILL ----------------

    @app_commands.command(name="rebuild_poo_goat", description="Rebuild POO/GOAT history from announcements")
    @app_commands.checks.has_permissions(administrator=True)
    async def rebuild(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not channel:
            await interaction.followup.send("Announcement channel not found.")
            return

        data = _default_data()

        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.bot is False:
                continue

            if PILOT_BOT_ID and message.author.id != PILOT_BOT_ID:
                continue

            if not message.mentions:
                continue

            content = message.content.lower()
            date = date_str_from_dt(message.created_at)
            ensure_date_entry(data, date)
            uid = str(message.mentions[0].id)

            if "is today’s poo" in content and not data["dates"][date]["poo"]:
                data["scores"]["poo"][uid] = data["scores"]["poo"].get(uid, 0) + 1
                data["dates"][date]["poo"] = True
                await message.add_reaction(POO_EMOJI)

            if "is today’s goat" in content and not data["dates"][date]["goat"]:
                data["scores"]["goat"][uid] = data["scores"]["goat"].get(uid, 0) + 1
                data["dates"][date]["goat"] = True
                await message.add_reaction(GOAT_EMOJI)

        save_data(data)
        await interaction.followup.send("Rebuild complete ✅")


# ==============================
# SETUP
# ==============================

async def setup(bot: commands.Bot):
    await bot.add_cog(PooGoatTracker(bot))