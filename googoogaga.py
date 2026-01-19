from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Set, Dict, Any, List

import discord
from discord import app_commands
from discord.ext import tasks

# =========================================================
# HARD-CODED CONFIG (YOUR IDS)
# =========================================================
ANNOUNCE_CHANNEL_ID = 1398508734506078240

GOO_ROLE_ID = 1462642673042325629        # Goo Goo Ga Ga
PARENT_ROLE_ID = 1462642845575024671     # Parent
PASSENGERS_ROLE_ID = 1404100554807971971 # Passengers

STATE_PATH = "googoo.json"
UK = ZoneInfo("Europe/London")

# Cutoffs
FINAL_PARENT_TIME = time(22, 30)  # 10:30pm: final parent chosen (one message)
HARD_STOP_TIME = time(23, 30)     # 11:30pm: no more actions/rotations/messages


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


def save_state(st: GooState) -> None:
    st.day = today_key()
    if st.tried_parent_ids is None:
        st.tried_parent_ids = set()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st.to_json(), f, indent=2, ensure_ascii=False)


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


def hard_reset_state_file() -> GooState:
    """
    Overwrites googoo.json with a fresh tiny state (so it never 'gets busy').
    """
    st = _default_state()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st.to_json(), f, indent=2, ensure_ascii=False)
    return st


# =========================================================
# ADMIN CHECK (tries Pilot adminsettings, falls back to admin perms)
# =========================================================
async def is_global_admin(member: discord.Member) -> bool:
    try:
        import adminsettings  # your Pilot module
        cfg = await adminsettings.load_config()  # type: ignore
        role_ids: List[int] = (cfg.get("global_admin_roles") or cfg.get("admin_roles") or [])
        if role_ids:
            return any(r.id in set(role_ids) for r in member.roles)
    except Exception:
        pass

    return member.guild_permissions.administrator


# =========================================================
# CORE HELPERS
# =========================================================
def start_time_passed() -> bool:
    now = datetime.now(UK)
    start = datetime.combine(now.date(), time(13, 30), tzinfo=UK)
    return now >= start


def window_end(st: GooState) -> Optional[datetime]:
    if not st.window_end_iso:
        return None
    try:
        return datetime.fromisoformat(st.window_end_iso).astimezone(UK)
    except Exception:
        return None


def set_window_end(st: GooState, dt: datetime) -> None:
    st.window_end_iso = dt.astimezone(UK).isoformat()


async def announce(guild: discord.Guild, msg: str) -> None:
    ch = guild.get_channel(ANNOUNCE_CHANNEL_ID)
    if isinstance(ch, discord.TextChannel):
        try:
            await ch.send(msg)
        except Exception:
            pass


async def add_role(member: discord.Member, role_id: int) -> None:
    role = member.guild.get_role(role_id)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="GooGooGaGa")
        except Exception:
            pass


async def remove_role(member: discord.Member, role_id: int) -> None:
    role = member.guild.get_role(role_id)
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="GooGooGaGa")
        except Exception:
            pass


def eligible_parents(guild: discord.Guild, st: GooState) -> list[discord.Member]:
    passengers = guild.get_role(PASSENGERS_ROLE_ID)
    parent_role = guild.get_role(PARENT_ROLE_ID)
    if not passengers or not parent_role:
        return []

    tried = st.tried_parent_ids or set()

    return [
        m for m in passengers.members
        if not m.bot
        and parent_role not in m.roles
        and m.id not in tried
    ]


async def clear_roles_in_guild(guild: discord.Guild) -> None:
    goo_role = guild.get_role(GOO_ROLE_ID)
    parent_role = guild.get_role(PARENT_ROLE_ID)
    if not goo_role or not parent_role:
        return

    for m in guild.members:
        if parent_role in m.roles:
            await remove_role(m, PARENT_ROLE_ID)
        if goo_role in m.roles:
            await remove_role(m, GOO_ROLE_ID)


async def revoke_current_parent(guild: discord.Guild, st: GooState) -> str:
    """
    Revokes current parent, adds them to tried list, returns mention for messaging.
    """
    if not st.current_parent_id:
        return "Someone"

    old_id = st.current_parent_id
    old_member = guild.get_member(old_id)

    if old_member:
        await remove_role(old_member, PARENT_ROLE_ID)

    if st.tried_parent_ids is None:
        st.tried_parent_ids = set()
    st.tried_parent_ids.add(old_id)

    st.current_parent_id = None
    st.window_end_iso = None
    save_state(st)

    return old_member.mention if old_member else f"<@{old_id}>"


async def assign_new_parent(guild: discord.Guild, st: GooState, *, announce_standard: bool = True) -> Optional[discord.Member]:
    choices = eligible_parents(guild, st)
    if not choices:
        if announce_standard:
            await announce(guild, "🍼 No eligible Passengers left to be **Parent** today.")
        return None

    parent = random.choice(choices)
    await add_role(parent, PARENT_ROLE_ID)

    st.current_parent_id = parent.id
    set_window_end(st, datetime.now(UK) + timedelta(hours=1))
    st.started = True
    save_state(st)

    if announce_standard:
        await announce(
            guild,
            f"🫃 {parent.mention} is **Parent of the day:** - You have **1 hour** to use `/give_googoogaga` or a new parent will be chosen!."
        )

    return parent


# =========================================================
# TASK LOOPS (started from botslash.py)
# =========================================================
@tasks.loop(seconds=30)
async def goo_guard_loop(bot: discord.Client):
    st = load_state()
    now = datetime.now(UK)

    # Hard stop after 11:30pm
    if now.time() >= HARD_STOP_TIME:
        return

    # If already picked, nothing to do
    if st.picked:
        return

    # If it's before 13:30 and there is no active parent, do nothing.
    # (If a parent exists in JSON for any reason, we allow the day to function.)
    if not start_time_passed() and not st.current_parent_id:
        return

    for guild in bot.guilds:
        # 🕥 Final parent logic (10:30pm+):
        # - If no parent exists yet and still not picked, choose ONE final parent and announce final message.
        # - After 10:30pm, we do NOT rotate parents anymore (no timeouts, no new picks), just wait for /give_googoogaga.
        if now.time() >= FINAL_PARENT_TIME:
            if not st.current_parent_id and not st.picked:
                final_parent = await assign_new_parent(guild, st, announce_standard=False)
                if final_parent:
                    await announce(
                        guild,
                        f"🕥 **FINAL PARENT CHOSEN: {final_parent.mention} - This is the **final chance** to pick today’s Goo Goo Ga Ga. If `/give_googoogaga` is **not used**, there will be **no Goo Goo Ga Ga of the day**."
                    )
                else:
                    await announce(guild, "🍼 No eligible Passengers left to be **Parent** today.")
            return  # after 10:30pm, we stop rotating/announcing further

        # Normal rotation (before 10:30pm)
        if st.current_parent_id:
            we = window_end(st)
            if we and now > we:
                old_parent = await revoke_current_parent(guild, st)
                new_parent = await assign_new_parent(guild, st, announce_standard=False)
                if new_parent:
                    await announce(
                        guild,
                        f"⏰ {old_parent} - you did not pick a **Goo Goo Ga Ga** in time. {new_parent.mention} — you are now the Parent and have **1 hour** to use `/give_googoogaga` or a new Parent will be chosen."
                    )
                else:
                    await announce(
                        guild,
                        f"⏰ {old_parent} did not pick a **Goo Goo Ga Ga** in time.\n"
                        f"🍼 No eligible Passengers left to be Parent today."
                    )
        else:
            await assign_new_parent(guild, st, announce_standard=True)


@tasks.loop(time=time(11, 0, tzinfo=UK))
async def goo_daily_reset(bot: discord.Client):
    for guild in bot.guilds:
        await clear_roles_in_guild(guild)
        await announce(guild, "🍼 Goo Goo Ga Ga reset complete. Ready for **13:30**.")
    hard_reset_state_file()


# =========================================================
# COMMAND REGISTRATION (Pilot-style)
# =========================================================
def setup_googoogaga_commands(tree: app_commands.CommandTree, bot: discord.Client):
    """
    Registers commands onto The Pilot's CommandTree and returns the 2 tasks to start.
    """

    @tree.command(name="give_googoogaga", description="(Parent only) Pick the Goo Goo Ga Ga of the day!")
    @app_commands.describe(member="Who is Goo Goo Ga Ga today?")
    async def give_googoogaga(interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Guild only.", ephemeral=True)

        st = load_state()

        # Before 13:30, only allow if a parent is already set (e.g., testing/admin set state)
        if not start_time_passed() and not st.current_parent_id:
            return await interaction.response.send_message("❌ Not started yet (starts 13:30).", ephemeral=True)

        if st.picked:
            return await interaction.response.send_message("❌ Already picked today.", ephemeral=True)

        if interaction.user.id != st.current_parent_id:
            return await interaction.response.send_message("❌ Only the current **Parent** can use this.", ephemeral=True)

        we = window_end(st)
        if not we or datetime.now(UK) > we:
            # Note: after 10:30pm we stop rotating, but parent still only has their window
            return await interaction.response.send_message("❌ Your 1-hour window expired.", ephemeral=True)

        # Remove goo from previous holder
        if st.goo_id:
            prev = interaction.guild.get_member(st.goo_id)
            if prev:
                await remove_role(prev, GOO_ROLE_ID)

        # Assign goo + remove parent
        await add_role(member, GOO_ROLE_ID)
        if isinstance(interaction.user, discord.Member):
            await remove_role(interaction.user, PARENT_ROLE_ID)

        # Lock in pick
        st.picked = True
        st.goo_id = member.id
        st.current_parent_id = None
        st.window_end_iso = None
        save_state(st)

        await interaction.response.send_message(f"🍼 {member.mention} is today’s **Goo Goo Ga Ga**!")

    @tree.command(name="assigngoogoogaga", description="(Admin) Force assign Goo Goo Ga Ga role")
    @app_commands.describe(member="Member to assign")
    async def assigngoogoogaga(interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Guild only.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member) or not await is_global_admin(interaction.user):
            return await interaction.response.send_message("❌ Admins only.", ephemeral=True)

        await add_role(member, GOO_ROLE_ID)

        st = load_state()
        st.goo_id = member.id
        save_state(st)

        await interaction.response.send_message("✅ Assigned Goo Goo Ga Ga.", ephemeral=True)

    @tree.command(name="removegoogoogaga", description="(Admin) Remove Goo Goo Ga Ga role")
    @app_commands.describe(member="Member to remove from")
    async def removegoogoogaga(interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Guild only.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member) or not await is_global_admin(interaction.user):
            return await interaction.response.send_message("❌ Admins only.", ephemeral=True)

        await remove_role(member, GOO_ROLE_ID)

        st = load_state()
        if st.goo_id == member.id:
            st.goo_id = None
            save_state(st)

        await interaction.response.send_message("✅ Removed Goo Goo Ga Ga.", ephemeral=True)

    # Return tasks so botslash can start them like poo/goat
    return goo_guard_loop, goo_daily_reset