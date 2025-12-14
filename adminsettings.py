# adminsettings.py
import discord
from discord import app_commands
from typing import List, Dict, Any
import random

from permissions import (
    has_global_access,
    has_app_access,
    load_settings,
    save_settings,
)
from joinleave import (
    load_config,
    save_config,
    render,
    human_member_number,
    EditWelcomeTitleModal,
    EditWelcomeTextModal,
    AddChannelSlotNameModal,
    AddArrivalImageModal,
    WelcomeChannelPickerView,
    BotAddChannelPickerView,
    LogChannelPickerView,
)

SCOPES = {
    "global": "Global Admin Roles",
    "mute": "Mute",
    "warnings": "Warnings",
    "poo_goat": "Poo / Goat",
    "welcome_leave": "Welcome / Leave",
}

# =========================
# Helpers
# =========================

def format_roles(guild: discord.Guild, role_ids: List[int]) -> str:
    mentions = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            mentions.append(role.mention)
    return "\n".join(mentions) if mentions else "*None*"


def roles_embed(guild: discord.Guild, settings: Dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title="⚙️ Pilot Role Permissions",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🔐 Global Admin",
        value=format_roles(guild, settings.get("global_allowed_roles", [])),
        inline=False
    )

    labels = {
        "mute": "🔇 Mute",
        "warnings": "⚠️ Warnings",
        "poo_goat": "💩🐐 Poo / Goat",
        "welcome_leave": "👋 Welcome / Leave",
    }

    for k, label in labels.items():
        embed.add_field(
            name=label,
            value=format_roles(
                guild,
                settings["apps"].get(k, {}).get("allowed_roles", [])
            ),
            inline=False
        )

    embed.set_footer(text="Server owner & override role always have access")
    return embed


def build_role_pages(
    guild: discord.Guild,
    settings: Dict[str, Any]
) -> List[discord.Embed]:
    pages: List[discord.Embed] = []

    sections = [
        ("🔐 Global Admin", settings.get("global_allowed_roles", [])),
        ("🔇 Mute", settings["apps"].get("mute", {}).get("allowed_roles", [])),
        ("⚠️ Warnings", settings["apps"].get("warnings", {}).get("allowed_roles", [])),
        ("💩🐐 Poo / Goat", settings["apps"].get("poo_goat", {}).get("allowed_roles", [])),
        ("👋 Welcome / Leave", settings["apps"].get("welcome_leave", {}).get("allowed_roles", [])),
    ]

    CHUNK_SIZE = 2

    for i in range(0, len(sections), CHUNK_SIZE):
        embed = discord.Embed(
            title="⚙️ Pilot Role Permissions",
            color=discord.Color.blurple()
        )

        for name, ids in sections[i:i + CHUNK_SIZE]:
            embed.add_field(
                name=name,
                value=format_roles(guild, ids),
                inline=False
            )

        embed.set_footer(text="Server owner & override role always have access")
        pages.append(embed)

    return pages


def welcome_status_text(cfg: Dict[str, Any]) -> str:
    w = cfg["welcome"]
    ch = f"<#{w['welcome_channel_id']}>" if w.get("welcome_channel_id") else "*Not set*"
    return (
        f"**Welcome Enabled:** `{w.get('enabled')}`\n"
        f"**Welcome Channel:** {ch}\n"
        f"**Images:** `{len(w.get('arrival_images') or [])}`\n"
        f"**Slots:** `{len(w.get('channels') or {})}`\n"
        f"**Bot Add Logs:** `{w.get('bot_add', {}).get('enabled')}`"
    )


def logs_status_text(cfg: Dict[str, Any]) -> str:
    m = cfg["member_logs"]
    ch = f"<#{m['channel_id']}>" if m.get("channel_id") else "*Not set*"
    return (
        f"**Logs Enabled:** `{m.get('enabled')}`\n"
        f"**Log Channel:** {ch}\n"
        f"**Leave:** `{m.get('log_leave')}` | "
        f"**Kick:** `{m.get('log_kick')}` | "
        f"**Ban:** `{m.get('log_ban')}`"
    )

# -------------------------
# Interaction-safe helpers
# -------------------------

async def _no_perm(interaction: discord.Interaction, msg="❌ You do not have permission."):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg)
        else:
            await interaction.response.send_message(msg)
    except Exception:
        if interaction.channel:
            await interaction.channel.send(msg)


async def _safe_defer(interaction: discord.Interaction):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=False)
    except Exception:
        pass


async def _safe_edit_panel_message(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed,
    view: discord.ui.View
):
    try:
        if interaction.message:
            await interaction.message.edit(embed=embed, view=view)
        elif interaction.channel:
            await interaction.channel.send(embed=embed, view=view)
    except Exception as e:
        if interaction.channel:
            await interaction.channel.send(f"❌ Panel update failed: `{type(e).__name__}`")

# =========================
# Panel / Roles (FIXED PART)
# =========================

class RolesOverviewView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed], index: int = 0):
        super().__init__(timeout=300)
        self.pages = pages
        self.index = index
        self.prev.disabled = index == 0
        self.next.disabled = index >= len(pages) - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _):
        self.index -= 1
        await interaction.response.edit_message(
            embed=self.pages[self.index],
            view=RolesOverviewView(self.pages, self.index)
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        self.index += 1
        await interaction.response.edit_message(
            embed=self.pages[self.index],
            view=RolesOverviewView(self.pages, self.index)
        )


class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Add / remove / view roles…",
            options=[
                discord.SelectOption(label="Add roles", value="add", emoji="➕"),
                discord.SelectOption(label="Remove roles", value="remove", emoji="➖"),
                discord.SelectOption(label="Show current roles", value="show", emoji="👀"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        action = self.values[0]
        settings = load_settings()

        if action == "show":
            pages = build_role_pages(interaction.guild, settings)

            if not pages:
                await interaction.response.send_message("No roles configured.")
                return

            await interaction.channel.send(
                embed=pages[0],
                view=RolesOverviewView(pages)
            )
            return

        picker = discord.ui.View(timeout=180)

        if action == "add":
            picker.add_item(AddRolesSelect(self.scope))
            await interaction.response.send_message(
                "Select roles to **ADD**:",
                view=picker
            )
        else:
            picker.add_item(RemoveRolesSelect(self.scope))
            await interaction.response.send_message(
                "Select roles to **REMOVE**:",
                view=picker
            )

# =========================
# Slash Command
# =========================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ You do not have permission.")

        await interaction.response.defer(thinking=False)

        cfg = load_config()
        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(
            name="🛂 Roles",
            value="Navigate → Roles to manage scopes or view overview.",
            inline=False
        )

        view = PilotPanelView(state="root")
        await interaction.followup.send(embed=embed, view=view)