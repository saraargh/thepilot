# snipe.py
import discord
from discord import app_commands
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Optional

MAX_HISTORY = 10
EXPIRE_AFTER = 600  # 5 minutes

DELETED = defaultdict(lambda: deque(maxlen=MAX_HISTORY))
EDITED = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


# ---------------- HELPERS ----------------
def expired(ts: datetime) -> bool:
    return datetime.utcnow() - ts > timedelta(seconds=EXPIRE_AFTER)


def clean(q: deque):
    while q and expired(q[0]["logged_at"]):
        q.popleft()


def resolve_channel(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel]
) -> discord.TextChannel:
    return channel if channel else interaction.channel


# ---------------- PAGINATED VIEW (ISNIPE ONLY) ----------------
class ISnipeView(discord.ui.View):
    def __init__(self, entries: list[dict]):
        super().__init__(timeout=EXPIRE_AFTER)
        self.entries = entries
        self.index = 0

    def build_embed(self) -> discord.Embed:
        e = self.entries[self.index]

        colour = discord.Colour.red() if e["type"] == "delete" else discord.Colour.orange()

        embed = discord.Embed(
            title=f"✈️ Incident Log ({self.index + 1}/{len(self.entries)})",
            colour=colour,
            timestamp=e["time"]
        )

        embed.set_author(
            name=str(e["author"]),
            icon_url=e["author"].display_avatar.url
        )

        if e["type"] == "delete":
            embed.add_field(
                name="🗑️ Deleted Message",
                value=e["content"] or "*[No content]*",
                inline=False
            )
        else:
            embed.add_field(
                name="✏️ Before",
                value=e["before"] or "*[Empty]*",
                inline=False
            )
            embed.add_field(
                name="After",
                value=e["after"] or "*[Empty]*",
                inline=False
            )

        embed.set_footer(text="Auto-purges in 5 minutes")
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _):
        self.index = max(0, self.index - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        self.index = min(len(self.entries) - 1, self.index + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ---------------- SETUP ----------------
def setup(client: discord.Client, tree: app_commands.CommandTree):

    # ---------- DELETE ----------
    @client.event
    async def on_message_delete(message: discord.Message):
        if not message.guild or message.author.bot:
            return

        DELETED[message.channel.id].append({
            "author": message.author,
            "content": message.content,
            "time": message.created_at,
            "logged_at": datetime.utcnow()
        })

    # ---------- EDIT ----------
    @client.event
    async def on_message_edit(before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return

        EDITED[before.channel.id].append({
            "author": before.author,
            "before": before.content,
            "after": after.content,
            "time": after.edited_at or datetime.utcnow(),
            "logged_at": datetime.utcnow()
        })

    # ---------- /SNIPE ----------
    @tree.command(name="snipe", description="✈️ Snipe a deleted message")
    @app_commands.describe(
        channel="Channel to snipe (defaults to current)",
        num_back="How far back (1 = most recent, max 10)",
        ephemeral="Only visible to you?"
    )
    async def snipe(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        num_back: int = 1,
        ephemeral: bool = False
    ):
        target = resolve_channel(interaction, channel)
        q = DELETED[target.id]
        clean(q)

        if not q:
            await interaction.response.send_message(
                "🛬 Nothing to snipe in that channel.",
                ephemeral=True
            )
            return

        num_back = max(1, min(num_back, len(q)))
        s = q[-num_back]

        embed = discord.Embed(
            title="✈️ Black Box — Deleted Message",
            description=s["content"] or "*[No content]*",
            colour=discord.Colour.red(),
            timestamp=s["time"]
        )
        embed.set_author(
            name=str(s["author"]),
            icon_url=s["author"].display_avatar.url
        )
        embed.set_footer(text=f"{target.name} • {num_back} back")

        await interaction.response.send_message(
            embed=embed,
            ephemeral=ephemeral,
            delete_after=None if ephemeral else EXPIRE_AFTER
        )

    # ---------- /ESNIPE ----------
    @tree.command(name="esnipe", description="✈️ Snipe an edited message")
    @app_commands.describe(
        channel="Channel to snipe (defaults to current)",
        num_back="How far back (1 = most recent, max 10)",
        ephemeral="Only visible to you?"
    )
    async def esnipe(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        num_back: int = 1,
        ephemeral: bool = False
    ):
        target = resolve_channel(interaction, channel)
        q = EDITED[target.id]
        clean(q)

        if not q:
            await interaction.response.send_message(
                "🛬 No edits detected in that channel.",
                ephemeral=True
            )
            return

        num_back = max(1, min(num_back, len(q)))
        s = q[-num_back]

        embed = discord.Embed(
            title="✈️ Flight Recorder — Edited Message",
            colour=discord.Colour.orange(),
            timestamp=s["time"]
        )
        embed.set_author(
            name=str(s["author"]),
            icon_url=s["author"].display_avatar.url
        )
        embed.add_field(name="✏️ Before", value=s["before"] or "*[Empty]*", inline=False)
        embed.add_field(name="After", value=s["after"] or "*[Empty]*", inline=False)
        embed.set_footer(text=f"{target.name} • {num_back} back")

        await interaction.response.send_message(
            embed=embed,
            ephemeral=ephemeral,
            delete_after=None if ephemeral else EXPIRE_AFTER
        )

    # ---------- /ISNIPE (PAGINATED) ----------
    @tree.command(name="isnipe", description="✈️ Browse deleted + edited messages")
    @app_commands.describe(
        channel="Channel to inspect (defaults to current)",
        ephemeral="Only visible to you?"
    )
    async def isnipe(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        ephemeral: bool = False
    ):
        target = resolve_channel(interaction, channel)

        dq = DELETED[target.id]
        eq = EDITED[target.id]
        clean(dq)
        clean(eq)

        entries: list[dict] = []

        for d in dq:
            entries.append({
                "type": "delete",
                "author": d["author"],
                "content": d["content"],
                "time": d["time"]
            })

        for e in eq:
            entries.append({
                "type": "edit",
                "author": e["author"],
                "before": e["before"],
                "after": e["after"],
                "time": e["time"]
            })

        if not entries:
            await interaction.response.send_message(
                "🛬 No incidents logged in that channel.",
                ephemeral=True
            )
            return

        entries = sorted(entries, key=lambda x: x["time"], reverse=True)[:MAX_HISTORY]

        view = ISnipeView(entries)

        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=ephemeral,
            delete_after=None if ephemeral else EXPIRE_AFTER
        )