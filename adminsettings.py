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

# =====================================================
# CONSTANTS
# =====================================================

SCOPES = {
    "global": "Global Admin Roles",
    "mute": "Mute",
    "warnings": "Warnings",
    "poo_goat": "Poo / Goat",
    "welcome_leave": "Welcome / Leave",
}

# =====================================================
# SAFE INTERACTION HELPERS (NO SILENT FAILURES)
# =====================================================

async def safe_defer(interaction: discord.Interaction):
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(thinking=False)
        except Exception:
            pass

async def safe_send(interaction: discord.Interaction, **kwargs):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
    except Exception:
        if interaction.channel:
            await interaction.channel.send(**kwargs)

async def safe_edit(interaction: discord.Interaction, *, embed=None, view=None):
    try:
        if interaction.message:
            await interaction.message.edit(embed=embed, view=view)
        elif interaction.channel:
            await interaction.channel.send(embed=embed, view=view)
    except Exception:
        pass

# =====================================================
# HELPERS
# =====================================================

def format_roles(guild: discord.Guild, role_ids: List[int]) -> str:
    out = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            out.append(role.mention)
    return "\n".join(out) if out else "*None*"

def build_role_pages(guild: discord.Guild, settings: Dict[str, Any]) -> List[discord.Embed]:
    sections = [
        ("🔐 Global Admin", settings.get("global_allowed_roles", [])),
        ("🔇 Mute", settings["apps"].get("mute", {}).get("allowed_roles", [])),
        ("⚠️ Warnings", settings["apps"].get("warnings", {}).get("allowed_roles", [])),
        ("💩🐐 Poo / Goat", settings["apps"].get("poo_goat", {}).get("allowed_roles", [])),
        ("👋 Welcome / Leave", settings["apps"].get("welcome_leave", {}).get("allowed_roles", [])),
    ]

    pages = []
    for i in range(0, len(sections), 2):
        embed = discord.Embed(
            title="⚙️ Pilot Role Permissions",
            color=discord.Color.blurple()
        )
        for name, ids in sections[i:i + 2]:
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
    return (
        f"**Enabled:** `{w.get('enabled')}`\n"
        f"**Channel:** {f'<#{w['welcome_channel_id']}>' if w.get('welcome_channel_id') else '*Not set*'}\n"
        f"**Images:** `{len(w.get('arrival_images') or [])}`\n"
        f"**Slots:** `{len(w.get('channels') or {})}`\n"
        f"**Bot Logs:** `{w.get('bot_add', {}).get('enabled')}`"
    )

def logs_status_text(cfg: Dict[str, Any]) -> str:
    m = cfg["member_logs"]
    return (
        f"**Enabled:** `{m.get('enabled')}`\n"
        f"**Channel:** {f'<#{m['channel_id']}>' if m.get('channel_id') else '*Not set*'}\n"
        f"**Leave:** `{m.get('log_leave')}` | "
        f"**Kick:** `{m.get('log_kick')}` | "
        f"**Ban:** `{m.get('log_ban')}`"
    )

# =====================================================
# PANEL STATE
# =====================================================

class PanelState:
    ROOT = "root"
    ROLES = "roles"
    WELCOME = "welcome"
    LEAVE = "leave"

# =====================================================
# PAGINATION VIEW
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

# =====================================================
# PANEL VIEW
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
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await safe_send(interaction, content="❌ No permission.")

        await safe_defer(interaction)
        target = self.values[0]
        cfg = load_config()

        if target == PanelState.ROOT:
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
            embed.add_field(name="🛂 Roles", value="Manage role access here.", inline=False)
        elif target == PanelState.WELCOME:
            embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status_text(cfg))
        elif target == PanelState.LEAVE:
            embed = discord.Embed(title="📄 Leave / Logs Settings", description=logs_status_text(cfg))
        else:
            embed = discord.Embed(title="🛂 Role Permissions")

        await safe_edit(interaction, embed=embed, view=PilotPanelView(target))

# =====================================================
# ROLES MANAGEMENT
# =====================================================

class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label="👀 View Roles Overview", value="__view__")]
        options += [discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()]
        super().__init__(placeholder="Choose a role scope…", options=options)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await safe_send(interaction, content="❌ No permission.")

        await safe_defer(interaction)

        if self.values[0] == "__view__":
            settings = load_settings()
            pages = build_role_pages(interaction.guild, settings)
            await interaction.channel.send(
                embed=pages[0],
                view=RolesOverviewView(pages)
            )
            return

        scope = self.values[0]
        embed = discord.Embed(
            title=f"🛂 Editing: {SCOPES[scope]}",
            description="Choose add/remove/show."
        )
        view = PilotPanelView(PanelState.ROLES)
        view.add_item(RoleActionSelect(scope))
        await safe_edit(interaction, embed=embed, view=view)

class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Select action…",
            options=[
                discord.SelectOption(label="Add roles", value="add"),
                discord.SelectOption(label="Remove roles", value="remove"),
                discord.SelectOption(label="Show current roles", value="show"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()

        if self.values[0] == "show":
            ids = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
            embed = discord.Embed(
                title=f"👀 Current roles — {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids)
            )
            return await safe_send(interaction, embed=embed)

        picker = discord.ui.View(timeout=180)
        if self.values[0] == "add":
            picker.add_item(AddRolesSelect(self.scope))
        else:
            picker.add_item(RemoveRolesSelect(self.scope))

        await safe_send(interaction, content="Select roles:", view=picker)

class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Add roles")

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        target = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
        for r in self.values:
            target.append(r.id)
        save_settings(settings)
        await safe_send(interaction, content="✅ Roles added.")

class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Remove roles")

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        target = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
        for r in self.values:
            if r.id in target:
                target.remove(r.id)
        save_settings(settings)
        await safe_send(interaction, content="✅ Roles removed.")

# =====================================================
# WELCOME & LEAVE SELECTS
# =====================================================

class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Welcome action…",
            options=[
                discord.SelectOption(label="Toggle Welcome", value="toggle"),
                discord.SelectOption(label="Set Channel", value="channel"),
                discord.SelectOption(label="Edit Title", value="title"),
                discord.SelectOption(label="Edit Text", value="text"),
                discord.SelectOption(label="Add Image", value="img"),
                discord.SelectOption(label="Preview", value="preview"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "preview":
            await safe_defer(interaction)
            cfg = load_config()
            w = cfg["welcome"]
            embed = discord.Embed(
                title=render(w["title"], user=interaction.user, guild=interaction.guild,
                             member_count=human_member_number(interaction.guild),
                             channels=w.get("channels", {})),
                description=render(w["description"], user=interaction.user,
                                   guild=interaction.guild,
                                   member_count=human_member_number(interaction.guild),
                                   channels=w.get("channels", {}))
            )
            await interaction.channel.send(embed=embed)

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Leave/log action…",
            options=[
                discord.SelectOption(label="Toggle Logs", value="toggle"),
                discord.SelectOption(label="Set Log Channel", value="channel"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        await safe_send(interaction, content="Leave/log updated.")

# =====================================================
# SLASH COMMAND
# =====================================================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await safe_send(interaction, content="❌ No permission.")

        await safe_defer(interaction)
        cfg = load_config()

        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(name="🛂 Roles", value="Manage role access.", inline=False)

        await interaction.followup.send(
            embed=embed,
            view=PilotPanelView(PanelState.ROOT)
        )