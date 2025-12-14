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

# =====================================================
# SCOPES
# =====================================================

SCOPES = {
    "global": "Global Admin Roles",
    "mute": "Mute",
    "warnings": "Warnings",
    "poo_goat": "Poo / Goat",
    "welcome_leave": "Welcome / Leave",
}

# =====================================================
# HELPERS
# =====================================================

def format_roles(guild: discord.Guild, role_ids: List[int]) -> str:
    roles = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            roles.append(role.mention)
    return "\n".join(roles) if roles else "*None*"

def build_role_pages(guild: discord.Guild, settings: Dict[str, Any]) -> List[discord.Embed]:
    sections = [
        ("🔐 Global Admin", settings.get("global_allowed_roles", [])),
        ("🔇 Mute", settings["apps"].get("mute", {}).get("allowed_roles", [])),
        ("⚠️ Warnings", settings["apps"].get("warnings", {}).get("allowed_roles", [])),
        ("💩🐐 Poo / Goat", settings["apps"].get("poo_goat", {}).get("allowed_roles", [])),
        ("👋 Welcome / Leave", settings["apps"].get("welcome_leave", {}).get("allowed_roles", [])),
    ]

    pages: List[discord.Embed] = []
    chunk_size = 2

    for i in range(0, len(sections), chunk_size):
        embed = discord.Embed(
            title="⚙️ Pilot Role Permissions",
            color=discord.Color.blurple(),
        )
        for name, ids in sections[i:i + chunk_size]:
            embed.add_field(name=name, value=format_roles(guild, ids), inline=False)

        embed.set_footer(text="Server owner & override role always have access")
        pages.append(embed)

    return pages

def welcome_status_text(cfg: Dict[str, Any]) -> str:
    w = cfg["welcome"]
    ch = f"<#{w['welcome_channel_id']}>" if w.get("welcome_channel_id") else "*Not set*"
    return (
        f"**Enabled:** `{w.get('enabled')}`\n"
        f"**Channel:** {ch}\n"
        f"**Images:** `{len(w.get('arrival_images') or [])}`\n"
        f"**Slots:** `{len(w.get('channels') or {})}`\n"
        f"**Bot Add Logs:** `{w.get('bot_add', {}).get('enabled')}`"
    )

def logs_status_text(cfg: Dict[str, Any]) -> str:
    m = cfg["member_logs"]
    ch = f"<#{m['channel_id']}>" if m.get("channel_id") else "*Not set*"
    return (
        f"**Enabled:** `{m.get('enabled')}`\n"
        f"**Channel:** {ch}\n"
        f"**Leave:** `{m.get('log_leave')}` | "
        f"**Kick:** `{m.get('log_kick')}` | "
        f"**Ban:** `{m.get('log_ban')}`"
    )

# =====================================================
# INTERACTION SAFETY
# =====================================================

async def safe_defer(interaction: discord.Interaction):
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(thinking=False)
        except Exception:
            pass

async def safe_edit(interaction: discord.Interaction, *, embed, view):
    if interaction.message:
        await interaction.message.edit(embed=embed, view=view)
    else:
        await interaction.channel.send(embed=embed, view=view)

# =====================================================
# PANEL STATE
# =====================================================

class PanelState:
    ROOT = "root"
    ROLES = "roles"
    WELCOME = "welcome"
    LEAVE = "leave"

# =====================================================
# MAIN PANEL VIEW
# =====================================================

class PilotPanelView(discord.ui.View):
    def __init__(self, state: str):
        super().__init__(timeout=600)
        self.state = state
        self.build()

    def build(self):
        self.clear_items()
        self.add_item(PanelNavSelect(self.state))

        if self.state == PanelState.ROLES:
            self.add_item(RoleScopeSelect())
        elif self.state == PanelState.WELCOME:
            self.add_item(WelcomeActionSelect())
        elif self.state == PanelState.LEAVE:
            self.add_item(LeaveActionSelect())

# =====================================================
# NAVIGATION SELECT
# =====================================================

class PanelNavSelect(discord.ui.Select):
    def __init__(self, current: str):
        super().__init__(
            placeholder="Navigate panel…",
            options=[
                discord.SelectOption(label="Home", value=PanelState.ROOT),
                discord.SelectOption(label="Roles", value=PanelState.ROLES),
                discord.SelectOption(label="Welcome", value=PanelState.WELCOME),
                discord.SelectOption(label="Leave / Logs", value=PanelState.LEAVE),
            ],
            min_values=1,
            max_values=1,
        )
        self.current = current

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return

        await safe_defer(interaction)
        cfg = load_config()

        if self.values[0] == PanelState.ROOT:
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
            embed.add_field(name="🛂 Roles", value="Manage role access via the Roles tab.", inline=False)
            return await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.ROOT))

        if self.values[0] == PanelState.ROLES:
            embed = discord.Embed(title="🛂 Role Permissions", color=discord.Color.blurple())
            return await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.ROLES))

        if self.values[0] == PanelState.WELCOME:
            embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status_text(cfg))
            return await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.WELCOME))

        embed = discord.Embed(title="📄 Leave / Logs Settings", description=logs_status_text(cfg))
        await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.LEAVE))

# =====================================================
# ROLE MANAGEMENT
# =====================================================

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
        await interaction.response.edit_message(embed=self.pages[self.index], view=RolesOverviewView(self.pages, self.index))

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        self.index += 1
        await interaction.response.edit_message(embed=self.pages[self.index], view=RolesOverviewView(self.pages, self.index))

class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a role scope…",
            options=[
                discord.SelectOption(label="👀 View Roles Overview", value="__view__"),
                *[discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()],
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        await safe_defer(interaction)

        if self.values[0] == "__view__":
            pages = build_role_pages(interaction.guild, load_settings())
            return await interaction.channel.send(embed=pages[0], view=RolesOverviewView(pages))

# =====================================================
# WELCOME MANAGEMENT
# =====================================================

class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Welcome action…",
            options=[
                discord.SelectOption(label="Toggle Welcome", value="toggle"),
                discord.SelectOption(label="Set Channel", value="set_channel"),
                discord.SelectOption(label="Edit Title", value="edit_title"),
                discord.SelectOption(label="Edit Text", value="edit_text"),
                discord.SelectOption(label="Add Slot", value="slot"),
                discord.SelectOption(label="Add Image", value="add_img"),
                discord.SelectOption(label="Remove Image", value="rm_img"),
                discord.SelectOption(label="Preview", value="preview"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        w = cfg["welcome"]

        if self.values[0] == "edit_title":
            return await interaction.response.send_modal(EditWelcomeTitleModal())

        if self.values[0] == "edit_text":
            return await interaction.response.send_modal(EditWelcomeTextModal())

        await safe_defer(interaction)

        if self.values[0] == "preview":
            count = human_member_number(interaction.guild)
            embed = discord.Embed(
                title=render(
                    w["title"],
                    user=interaction.user,
                    guild=interaction.guild,
                    member_count=count,
                    channels=w.get("channels", {}),
                ),
                description=render(
                    w["description"],
                    user=interaction.user,
                    guild=interaction.guild,
                    member_count=count,
                    channels=w.get("channels", {}),
                ),
            )
            if w.get("arrival_images"):
                embed.set_image(url=random.choice(w["arrival_images"]))
            return await interaction.channel.send(embed=embed)

# =====================================================
# LEAVE MANAGEMENT (unchanged logic)
# =====================================================

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Leave / logs action…",
            options=[
                discord.SelectOption(label="Toggle Logs", value="toggle"),
                discord.SelectOption(label="Set Log Channel", value="set_channel"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        await safe_defer(interaction)

# =====================================================
# SLASH COMMAND
# =====================================================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return

        await interaction.response.defer(thinking=False)

        cfg = load_config()
        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(name="🛂 Roles", value="Manage role permissions via the Roles tab.", inline=False)

        await interaction.followup.send(embed=embed, view=PilotPanelView(PanelState.ROOT))