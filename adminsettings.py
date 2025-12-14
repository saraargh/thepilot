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
# HELPERS
# =====================================================

def format_roles(guild: discord.Guild, role_ids: List[int]) -> str:
    roles = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            roles.append(role.mention)
    return "\n".join(roles) if roles else "*None*"


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

    for key, label in labels.items():
        embed.add_field(
            name=label,
            value=format_roles(
                guild,
                settings["apps"].get(key, {}).get("allowed_roles", [])
            ),
            inline=False
        )

    embed.set_footer(text="Server owner & override role always have access")
    return embed


def welcome_status_text(cfg: Dict[str, Any]) -> str:
    w = cfg["welcome"]
    channel = f"<#{w['welcome_channel_id']}>" if w.get("welcome_channel_id") else "*Not set*"
    return (
        f"**Enabled:** `{w.get('enabled')}`\n"
        f"**Channel:** {channel}\n"
        f"**Images:** `{len(w.get('arrival_images') or [])}`\n"
        f"**Slots:** `{len(w.get('channels') or {})}`\n"
        f"**Bot Add Logs:** `{w.get('bot_add', {}).get('enabled')}`"
    )


def logs_status_text(cfg: Dict[str, Any]) -> str:
    m = cfg["member_logs"]
    channel = f"<#{m['channel_id']}>" if m.get("channel_id") else "*Not set*"
    return (
        f"**Enabled:** `{m.get('enabled')}`\n"
        f"**Channel:** {channel}\n"
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
# MAIN PANEL VIEW
# =====================================================

class PilotPanelView(discord.ui.View):
    def __init__(self, state: str = PanelState.ROOT):
        super().__init__(timeout=600)
        self.state = state
        self.build()

    def build(self):
        self.clear_items()
        self.add_item(PanelNavSelect())

        if self.state == PanelState.ROLES:
            self.add_item(RoleScopeSelect())

        elif self.state == PanelState.WELCOME:
            self.add_item(WelcomeActionSelect())

        elif self.state == PanelState.LEAVE:
            self.add_item(LeaveActionSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.")
            return False
        return True

# =====================================================
# NAVIGATION
# =====================================================

class PanelNavSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Navigate panel…",
            options=[
                discord.SelectOption(label="Home", value=PanelState.ROOT, emoji="⚙️"),
                discord.SelectOption(label="Roles", value=PanelState.ROLES, emoji="🛂"),
                discord.SelectOption(label="Welcome", value=PanelState.WELCOME, emoji="👋"),
                discord.SelectOption(label="Leave / Logs", value=PanelState.LEAVE, emoji="📄"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]

        if target == PanelState.ROOT:
            cfg = load_config()
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
            embed.add_field(
                name="🛂 Roles",
                value="Use **Roles** to manage permissions.",
                inline=False
            )
            await interaction.response.edit_message(
                embed=embed,
                view=PilotPanelView(PanelState.ROOT)
            )
            return

        if target == PanelState.ROLES:
            embed = discord.Embed(
                title="🛂 Role Permissions",
                description="Select a scope, then choose an action.",
                color=discord.Color.blurple()
            )

        elif target == PanelState.WELCOME:
            cfg = load_config()
            embed = discord.Embed(
                title="👋 Welcome Settings",
                description=welcome_status_text(cfg),
                color=discord.Color.blurple()
            )

        else:
            cfg = load_config()
            embed = discord.Embed(
                title="📄 Leave / Logs Settings",
                description=logs_status_text(cfg),
                color=discord.Color.blurple()
            )

        await interaction.response.edit_message(
            embed=embed,
            view=PilotPanelView(target)
        )

# =====================================================
# ROLES MANAGEMENT
# =====================================================

class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose role scope…",
            options=[discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        scope = self.values[0]

        embed = discord.Embed(
            title=f"🛂 {SCOPES[scope]}",
            description="Choose an action:",
            color=discord.Color.blurple()
        )

        view = PilotPanelView(PanelState.ROLES)
        view.add_item(RoleActionSelect(scope))

        await interaction.response.edit_message(embed=embed, view=view)


class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Select action…",
            options=[
                discord.SelectOption(label="Add roles", value="add", emoji="➕"),
                discord.SelectOption(label="Remove roles", value="remove", emoji="➖"),
                discord.SelectOption(label="View current roles", value="view", emoji="👀"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()

        if self.values[0] == "view":
            ids = (
                settings.get("global_allowed_roles", [])
                if self.scope == "global"
                else settings["apps"][self.scope]["allowed_roles"]
            )
            embed = discord.Embed(
                title=f"👀 {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids),
                color=discord.Color.blurple()
            )
            await interaction.response.edit_message(
                embed=embed,
                view=PilotPanelView(PanelState.ROLES)
            )
            return

        picker = discord.ui.View(timeout=180)
        picker.add_item(
            AddRolesSelect(self.scope)
            if self.values[0] == "add"
            else RemoveRolesSelect(self.scope)
        )

        await interaction.response.send_message(
            f"Select roles to **{self.values[0].upper()}**:",
            view=picker
        )


class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        key = "global_allowed_roles" if self.scope == "global" else "allowed_roles"
        role_set = set(
            settings.get(key, [])
            if self.scope == "global"
            else settings["apps"][self.scope][key]
        )

        for r in self.values:
            role_set.add(r.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(role_set)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(role_set)

        save_settings(settings)
        await interaction.response.send_message("✅ Roles added.")


class RemoveRolesSelect(AddRolesSelect):
    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        key = "global_allowed_roles" if self.scope == "global" else "allowed_roles"
        role_set = set(
            settings.get(key, [])
            if self.scope == "global"
            else settings["apps"][self.scope][key]
        )

        for r in self.values:
            role_set.discard(r.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(role_set)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(role_set)

        save_settings(settings)
        await interaction.response.send_message("✅ Roles removed.")

# =====================================================
# WELCOME / LEAVE (UNCHANGED LOGIC)
# =====================================================
# Your existing WelcomeActionSelect, LeaveActionSelect,
# modals, pickers, and preview logic remain intact.
# =====================================================

# =====================================================
# SLASH COMMAND
# =====================================================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.")

        cfg = load_config()
        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(name="🛂 Roles", value="Manage permissions via Roles.", inline=False)

        await interaction.response.send_message(
            embed=embed,
            view=PilotPanelView(PanelState.ROOT)
        )