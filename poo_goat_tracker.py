# poo_goat_tracker.py
# Tracks POO / GOAT history based ONLY on official Pilot announcements

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List

import discord
from discord import app_commands
from discord.ext import commands, tasks
from zoneinfo import ZoneInfo


# ==============================
# CONFIG
# ==============================

UK_TZ = ZoneInfo("Europe/London")

ANNOUNCEMENT_CHANNEL_ID = 1398508734506078240
PILOT_BOT_ID = 1429920180632293388

GOAT_EMOJI = "<:goated:1448995506234851408>"
POO_EMOJI = "💩"

POO_ROLE_ID = 1429934009550373059  # 🔴 SET THIS

POO_MILESTONES = {10, 20, 30, 40, 50, 60, 70, 80, 90, 100}
POO_ROLE_DURATION_DAYS = 14

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


def date_str_from_dt(dt: datetime) -> str:
    return dt.astimezone(UK_TZ).strftime("%Y-%m-%d")


def ensure_date_entry(data: Dict, date: str):
    if date not in data["dates"]:
        data["dates"][date] = {"goat": False, "poo": False}


def ensure_poo_milestones(data: Dict, uid: str):
    if uid not in data["poo_milestones"]:
        data["poo_milestones"][uid] = []


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

    embed = discord.Embed(
        title="🐐 GOAT Leaderboard" if board_type == "goat" else "💩 POO Leaderboard",
        description="\n".join(lines),
        colour=0xF5C542 if board_type == "goat" else 0x8B5A2B
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

        options = [
            discord.SelectOption(
                label=f"Page {i + 1}",
                description=f"Ranks {i * ENTRIES_PER_PAGE + 1}–{min((i + 1) * ENTRIES_PER_PAGE, len(scores))}"
            )
            for i in range(total_pages)
        ]

        self.add_item(LeaderboardSelect(self, options))


class LeaderboardSelect(discord.ui.Select):
    def __init__(self, view: LeaderboardView, options: List[discord.SelectOption]):
        super().__init__(placeholder="Select a page", options=options)
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
        self.poo_role_cleanup.start()

    # ---------------- MESSAGE LISTENER ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
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
        date = date_str_from_dt(message.created_at)
        ensure_date_entry(data, date)

        uid = str(message.mentions[0].id)

        # 💩 POO
        if "is today’s poo" in content and not data["dates"][date]["poo"]:
            current = data["scores"]["poo"].get(uid, 0) + 1
            data["scores"]["poo"][uid] = current
            data["dates"][date]["poo"] = True

            ensure_poo_milestones(data, uid)

            if current in POO_MILESTONES and current not in data["poo_milestones"][uid]:
                data["poo_milestones"][uid].append(current)

                if current == 50:
                    until = datetime.now(UK_TZ) + timedelta(days=POO_ROLE_DURATION_DAYS)
                    data["poo_role_until"][uid] = until.isoformat()

                    await message.channel.send(
                        f"💩🚨 **POO LEVEL 50 ACHIEVED** 🚨💩\n\n"
                        f"<@{uid}> has reached **50 total poos**.\n\n"
                        f"This is a milestone.\n"
                        f"This is also deeply concerning.\n\n"
                        f"They have been sentenced to **14 days of public shame.**"
                    )

                    role = message.guild.get_role(POO_ROLE_ID)
                    member = message.guild.get_member(int(uid))
                    if role and member and role not in member.roles:
                        await member.add_roles(role, reason="50 POO milestone")
                else:
                    await message.channel.send(
                        f"💩 **POO MILESTONE** 💩\n\n"
                        f"<@{uid}> has reached **{current} total poos**."
                    )

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

    # ---------------- ROLE CLEANUP ----------------

    @tasks.loop(hours=1)
    async def poo_role_cleanup(self):
        data = load_data()
        now = datetime.now(UK_TZ)

        changed = False
        for uid, until_str in list(data.get("poo_role_until", {}).items()):
            if now >= datetime.fromisoformat(until_str):
                for guild in self.bot.guilds:
                    member = guild.get_member(int(uid))
                    role = guild.get_role(POO_ROLE_ID)
                    if member and role and role in member.roles:
                        await member.remove_roles(role, reason="50 POO duration expired")
                del data["poo_role_until"][uid]
                changed = True

        if changed:
            save_data(data)

    # ---------------- LEADERBOARDS ----------------

    @app_commands.command(name="pooboard", description="View the POO leaderboard")
    async def pooboard(self, interaction: discord.Interaction):
        data = load_data()
        await interaction.response.send_message(
            embed=build_leaderboard_embed(interaction.guild, "poo", 0, data),
            view=LeaderboardView(interaction.guild, "poo", data)
        )

    @app_commands.command(name="goatboard", description="View the GOAT leaderboard")
    async def goatboard(self, interaction: discord.Interaction):
        data = load_data()
        await interaction.response.send_message(
            embed=build_leaderboard_embed(interaction.guild, "goat", 0, data),
            view=LeaderboardView(interaction.guild, "goat", data)
        )


# ==============================
# SETUP
# ==============================

async def setup(bot: commands.Bot):
    await bot.add_cog(PooGoatTracker(bot))