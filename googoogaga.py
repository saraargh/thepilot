from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Set, Dict, Any, Tuple

import discord
from discord import app_commands
from discord.ext import tasks, commands

# =========================================================
# HARD-CODED CONFIG (YOUR IDS)
# =========================================================
ANNOUNCE_CHANNEL_ID = 1398508734506078240

GOO_ROLE_ID = 1462642673042325629        # Goo Goo Ga Ga
PARENT_ROLE_ID = 1462642845575024671     # Parent
PASSENGERS_ROLE_ID = 1404100554807971971 # Passengers

STATE_PATH = "googoo.json"
UK = ZoneInfo("Europe/London")

# =========================================================
# STATE
# =========================================================
@dataclass
class GooState:
    day: str
    started: bool = False
    picked: bool = False
    current_parent_id: Optional[int] = None
    window_end_iso: Optional[str] = None
    tried_parent_ids: Set[int] = None
    goo_id: Optional[int] = None

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tried_parent_ids"] = list(self.tried_parent_ids or [])
        return d

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> "GooState":
        return cls(
            day=d.get("day", ""),
            started=bool(d.get("started", False)),
            picked=bool(d.get("picked", False)),
            current_parent_id=d.get("current_parent_id"),
            window_end_iso=d.get("window_end_iso"),
            tried_parent_ids=set(d.get("tried_parent_ids", []) or []),
            goo_id=d.get("goo_id"),
        )


def today_key() -> str:
    return datetime.now(UK).date().isoformat()


def _default_state() -> GooState:
    return GooState(
        day=today_key(),
        started=False,
        picked=False,
        current_parent_id=None,
        window_end_iso=None,
        tried_parent_ids=set(),
        goo_id=None,
    )


def load_state() -> GooState:
    if not os.path.exists(STATE_PATH):
        st = _default_state()
        save_state(st)
        return st

    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        st = GooState.from_json(data)
    except Exception:
        st = _default_state()
        save_state(st)
        return st

    if st.day != today_key():
        st = _default_state()
        save_state(st)

    if st.tried_parent_ids is None:
        st.tried_parent_ids = set()

    return st


def save_state(st: GooState) -> None:
    st.day = today_key()
    if st.tried_parent_ids is None:
        st.tried_parent_ids = set()

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st.to_json(), f, indent=2, ensure_ascii=False)


def hard_reset_state_file() -> GooState:
    st = _default_state()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st.to_json(), f, indent=2, ensure_ascii=False)
    return st


# =========================================================
# CORE
# =========================================================
class GooGooGaGa(commands.Cog):
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.state = load_state()

        self.guard_loop.start()
        self.daily_reset.start()

    # -----------------------
    # Helpers
    # -----------------------
    def _start_time_passed(self) -> bool:
        now = datetime.now(UK)
        start = datetime.combine(now.date(), time(13, 30), tzinfo=UK)
        return now >= start

    def window_end(self) -> Optional[datetime]:
        if not self.state.window_end_iso:
            return None
        try:
            dt = datetime.fromisoformat(self.state.window_end_iso)
            return dt.astimezone(UK)
        except Exception:
            return None

    def set_window_end(self, dt: datetime) -> None:
        self.state.window_end_iso = dt.astimezone(UK).isoformat()

    async def announce(self, guild: discord.Guild, msg: str) -> None:
        ch = guild.get_channel(ANNOUNCE_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.send(msg)
            except Exception:
                pass

    async def add_role(self, member: discord.Member, role_id: int) -> None:
        role = member.guild.get_role(role_id)
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason="GooGooGaGa")
            except Exception:
                pass

    async def remove_role(self, member: discord.Member, role_id: int) -> None:
        role = member.guild.get_role(role_id)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="GooGooGaGa")
            except Exception:
                pass

    def eligible_parents(self, guild: discord.Guild) -> list[discord.Member]:
        passengers = guild.get_role(PASSENGERS_ROLE_ID)
        parent_role = guild.get_role(PARENT_ROLE_ID)
        if not passengers or not parent_role:
            return []

        tried = self.state.tried_parent_ids or set()

        return [
            m for m in passengers.members
            if not m.bot
            and parent_role not in m.roles
            and m.id not in tried
        ]

    async def clear_roles_in_guild(self, guild: discord.Guild) -> None:
        goo_role = guild.get_role(GOO_ROLE_ID)
        parent_role = guild.get_role(PARENT_ROLE_ID)
        if not goo_role or not parent_role:
            return

        for m in guild.members:
            if parent_role in m.roles:
                await self.remove_role(m, PARENT_ROLE_ID)
            if goo_role in m.roles:
                await self.remove_role(m, GOO_ROLE_ID)

    async def revoke_current_parent(self, guild: discord.Guild) -> str:
        """
        Revokes current parent and returns a display name/mention for announcement.
        Also adds them to tried_parent_ids so they can't be picked again today.
        """
        if not self.state.current_parent_id:
            return "Someone"

        old_id = self.state.current_parent_id
        old_member = guild.get_member(old_id)

        if old_member:
            await self.remove_role(old_member, PARENT_ROLE_ID)

        if self.state.tried_parent_ids is None:
            self.state.tried_parent_ids = set()
        self.state.tried_parent_ids.add(old_id)

        self.state.current_parent_id = None
        self.state.window_end_iso = None
        save_state(self.state)

        return old_member.mention if old_member else f"<@{old_id}>"

    async def assign_new_parent(self, guild: discord.Guild, *, announce: bool = True) -> Optional[discord.Member]:
        """
        Picks a new parent (not tried today), gives role, sets 1-hour window.
        If announce=False, it will not post the standard "Parent of the day" message.
        """
        choices = self.eligible_parents(guild)
        if not choices:
            if announce:
                await self.announce(guild, "🍼 No eligible Passengers left to be **Parent** today.")
            return None

        parent = random.choice(choices)
        await self.add_role(parent, PARENT_ROLE_ID)

        self.state.current_parent_id = parent.id
        self.set_window_end(datetime.now(UK) + timedelta(hours=1))
        self.state.started = True
        save_state(self.state)

        if announce:
            await self.announce(
                guild,
                f"🍼 **Parent of the day:** {parent.mention}\n"
                f"You have **1 hour** to use `/give_googoogaga` (ONLY ONE pick today)."
            )
        return parent

    # -----------------------
    # Loops
    # -----------------------
    @tasks.loop(seconds=30)
    async def guard_loop(self):
        self.state = load_state()

        if self.state.picked:
            return
        if not self._start_time_passed():
            return

        now = datetime.now(UK)

        for guild in self.bot.guilds:
            # If parent exists but expired -> ONE combined message + new parent chosen (no duplicate standard announcement)
            if self.state.current_parent_id:
                we = self.window_end()
                if we and now > we:
                    old_parent_mention = await self.revoke_current_parent(guild)
                    new_parent = await self.assign_new_parent(guild, announce=False)

                    if new_parent:
                        await self.announce(
                            guild,
                            f"⏰ {old_parent_mention} did not pick a **Goo Goo Ga Ga** in time.\n"
                            f"🍼 New Parent chosen: {new_parent.mention} — you have **1 hour** to use `/give_googoogaga` "
                            f"or a new Parent will be chosen."
                        )
                    else:
                        await self.announce(
                            guild,
                            f"⏰ {old_parent_mention} did not pick a **Goo Goo Ga Ga** in time.\n"
                            f"🍼 No eligible Passengers left to be Parent today."
                        )

            else:
                # No parent currently -> normal announcement
                await self.assign_new_parent(guild, announce=True)

    @guard_loop.before_loop
    async def before_guard_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(11, 0, tzinfo=UK))
    async def daily_reset(self):
        for guild in self.bot.guilds:
            await self.clear_roles_in_guild(guild)
            await self.announce(guild, "🍼 Goo Goo Ga Ga reset complete. Ready for **13:30**.")

        self.state = hard_reset_state_file()

    @daily_reset.before_loop
    async def before_daily_reset(self):
        await self.bot.wait_until_ready()

    # -----------------------
    # Commands
    # -----------------------
    @app_commands.command(name="give_googoogaga", description="(Parent only) Pick the Goo Goo Ga Ga of the day!")
    @app_commands.describe(member="Who is Goo Goo Ga Ga today?")
    async def give_googoogaga(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Guild only.", ephemeral=True)

        self.state = load_state()

        if not self._start_time_passed():
            return await interaction.response.send_message("❌ Not started yet (starts 13:30).", ephemeral=True)

        if self.state.picked:
            return await interaction.response.send_message("❌ Already picked today.", ephemeral=True)

        if interaction.user.id != self.state.current_parent_id:
            return await interaction.response.send_message("❌ Only the current **Parent** can use this.", ephemeral=True)

        we = self.window_end()
        if not we or datetime.now(UK) > we:
            return await interaction.response.send_message("❌ Your 1-hour window expired.", ephemeral=True)

        # Remove goo from previous holder (if any)
        if self.state.goo_id:
            prev = interaction.guild.get_member(self.state.goo_id)
            if prev:
                await self.remove_role(prev, GOO_ROLE_ID)

        # Assign goo + remove parent
        await self.add_role(member, GOO_ROLE_ID)
        if isinstance(interaction.user, discord.Member):
            await self.remove_role(interaction.user, PARENT_ROLE_ID)

        # Lock in pick
        self.state.picked = True
        self.state.goo_id = member.id
        self.state.current_parent_id = None
        self.state.window_end_iso = None
        save_state(self.state)

        await interaction.response.send_message(f"🍼 {member.mention} is today’s **Goo Goo Ga Ga**!")

    @app_commands.command(name="assigngoogoogaga", description="(Admin) Force assign Goo Goo Ga Ga role")
    @app_commands.describe(member="Member to assign")
    async def assigngoogoogaga(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Guild only.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admins only.", ephemeral=True)

        await self.add_role(member, GOO_ROLE_ID)

        self.state = load_state()
        self.state.goo_id = member.id
        save_state(self.state)

        await interaction.response.send_message("✅ Assigned Goo Goo Ga Ga.", ephemeral=True)

    @app_commands.command(name="removegoogoogaga", description="(Admin) Remove Goo Goo Ga Ga role")
    @app_commands.describe(member="Member to remove from")
    async def removegoogoogaga(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Guild only.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admins only.", ephemeral=True)

        await self.remove_role(member, GOO_ROLE_ID)

        self.state = load_state()
        if self.state.goo_id == member.id:
            self.state.goo_id = None
            save_state(self.state)

        await interaction.response.send_message("✅ Removed Goo Goo Ga Ga.", ephemeral=True)


# =========================================================
# SETUP
# =========================================================
async def setup(bot: discord.Client):
    """
    Use: await googoogaga.setup(bot) from your botslash.py / setup_hook.
    """
    cog = GooGooGaGa(bot)

    if hasattr(bot, "add_cog"):
        maybe = bot.add_cog(cog)
        if hasattr(maybe, "__await__"):
            await maybe

    bot.tree.add_command(cog.give_googoogaga)
    bot.tree.add_command(cog.assigngoogoogaga)
    bot.tree.add_command(cog.removegoogoogaga)

    print("🍼 Goo Goo Ga Ga loaded.")
