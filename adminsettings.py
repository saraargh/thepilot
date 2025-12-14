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

# ======================================================
# CONSTANTS
# ======================================================

SCOPES = {
    "global": "Global Admin Roles",
    "mute": "Mute",
    "warnings": "Warnings",
    "poo_goat": "Poo / Goat",
    "welcome_leave": "Welcome / Leave",
}

# ======================================================
# SAFE INTERACTION HELPERS (NO CRASHES)
# ======================================================

async def safe_defer(interaction: discord.Interaction):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=False)
    except Exception:
        pass

async def safe_edit(interaction: discord.Interaction, *, embed=None, view=None):
    try:
        if interaction.message:
            await interaction.message.edit(embed=embed, view=view)
        elif interaction.channel:
            await interaction.channel.send(embed=embed, view=view)
    except Exception:
        pass

async def no_perm(interaction: discord.Interaction):
    if interaction.channel:
        await interaction.channel.send("❌ You do not have permission.")

# ======================================================
# ROLE HELPERS
# ======================================================

def format_roles(guild: discord.Guild, role_ids: List[int]) -> str:
    roles = [guild.get_role(r) for r in role_ids if guild.get_role(r)]
    return "\n".join(r.mention for r in roles) if roles else "*None*"

def build_role_pages(guild: discord.Guild, settings: Dict[str, Any]) -> List[discord.Embed]:
    sections = [
        ("🔐 Global Admin", settings.get("global_allowed_roles", [])),
        ("🔇 Mute", settings["apps"].get("mute", {}).get("allowed_roles", [])),
        ("⚠️ Warnings", settings["apps"].get("warnings", {}).get("allowed_roles", [])),
        ("💩🐐 Poo / Goat", settings["apps"].get("poo_goat", {}).get("allowed_roles", [])),
        ("👋 Welcome / Leave", settings["apps"].get("welcome_leave", {}).get("allowed_roles", [])),
    ]

    pages = []
    for name, ids in sections:
        embed = discord.Embed(
            title="👀 Current Role Access",
            color=discord.Color.blurple()
        )
        embed.add_field(name=name, value=format_roles(guild, ids), inline=False)
        embed.set_footer(text="Server owner & override role always have access")
        pages.append(embed)

    return pages

# ======================================================
# STATUS TEXT
# ======================================================

def welcome_status(cfg: Dict[str, Any]) -> str:
    w = cfg["welcome"]
    ch = f"<#{w['welcome_channel_id']}>" if w.get("welcome_channel_id") else "*Not set*"
    return (
        f"Enabled: `{w.get('enabled')}`\n"
        f"Channel: {ch}\n"
        f"Images: `{len(w.get('arrival_images') or [])}`\n"
        f"Slots: `{len(w.get('channels') or {})}`\n"
        f"Bot Add Logs: `{w.get('bot_add', {}).get('enabled')}`"
    )

def logs_status(cfg: Dict[str, Any]) -> str:
    m = cfg["member_logs"]
    ch = f"<#{m['channel_id']}>" if m.get("channel_id") else "*Not set*"
    return (
        f"Enabled: `{m.get('enabled')}`\n"
        f"Channel: {ch}\n"
        f"Leave: `{m.get('log_leave')}` | Kick: `{m.get('log_kick')}` | Ban: `{m.get('log_ban')}`"
    )

# ======================================================
# PANEL STATE
# ======================================================

class PanelState:
    ROOT = "root"
    ROLES = "roles"
    WELCOME = "welcome"
    LEAVE = "leave"

# ======================================================
# MAIN PANEL VIEW
# ======================================================

class PilotPanelView(discord.ui.View):
    def __init__(self, state=PanelState.ROOT):
        super().__init__(timeout=600)
        self.state = state
        self.build()

    def build(self):
        self.clear_items()
        self.add_item(NavSelect(self.state))

        if self.state == PanelState.ROLES:
            self.add_item(RoleScopeSelect())
        elif self.state == PanelState.WELCOME:
            self.add_item(WelcomeActionSelect())
        elif self.state == PanelState.LEAVE:
            self.add_item(LeaveActionSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await no_perm(interaction)
            return False
        return True

# ======================================================
# NAVIGATION
# ======================================================

class NavSelect(discord.ui.Select):
    def __init__(self, current):
        super().__init__(
            placeholder="Navigate panel…",
            options=[
                discord.SelectOption(label="Home", value=PanelState.ROOT),
                discord.SelectOption(label="Roles", value=PanelState.ROLES),
                discord.SelectOption(label="Welcome", value=PanelState.WELCOME),
                discord.SelectOption(label="Leave / Logs", value=PanelState.LEAVE),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        await safe_defer(interaction)

        cfg = load_config()

        if self.values[0] == PanelState.ROOT:
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status(cfg), inline=False)
            embed.add_field(name="🛂 Roles", value="Manage role access here.", inline=False)
            await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.ROOT))

        elif self.values[0] == PanelState.ROLES:
            embed = discord.Embed(title="🛂 Role Permissions", description="Choose a scope or view overview.")
            await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.ROLES))

        elif self.values[0] == PanelState.WELCOME:
            embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status(cfg))
            await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.WELCOME))

        else:
            embed = discord.Embed(title="📄 Leave / Logs", description=logs_status(cfg))
            await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.LEAVE))

# ======================================================
# ROLES
# ======================================================

class RolesPager(discord.ui.View):
    def __init__(self, pages, index=0):
        super().__init__(timeout=300)
        self.pages = pages
        self.index = index

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, i, b):
        self.index -= 1
        await i.response.edit_message(embed=self.pages[self.index], view=RolesPager(self.pages, self.index))

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, i, b):
        self.index += 1
        await i.response.edit_message(embed=self.pages[self.index], view=RolesPager(self.pages, self.index))

class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose role scope…",
            options=[discord.SelectOption(label="👀 View Roles Overview", value="__view__")]
            + [discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()]
        )

    async def callback(self, interaction: discord.Interaction):
        await safe_defer(interaction)
        settings = load_settings()

        if self.values[0] == "__view__":
            pages = build_role_pages(interaction.guild, settings)
            await interaction.channel.send(embed=pages[0], view=RolesPager(pages))
            await safe_edit(
                interaction,
                embed=discord.Embed(title="🛂 Role Permissions", description="Overview posted above."),
                view=PilotPanelView(PanelState.ROLES),
            )
            return

        scope = self.values[0]
        embed = discord.Embed(
            title=f"🛂 Editing: {SCOPES[scope]}",
            description="Choose add / remove / show."
        )
        view = PilotPanelView(PanelState.ROLES)
        view.add_item(RoleActionSelect(scope))
        await safe_edit(interaction, embed=embed, view=view)

class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope):
        self.scope = scope
        super().__init__(
            placeholder="Action…",
            options=[
                discord.SelectOption(label="Add roles", value="add"),
                discord.SelectOption(label="Remove roles", value="remove"),
                discord.SelectOption(label="Show current roles", value="show"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        await safe_defer(interaction)
        settings = load_settings()

        ids = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]

        if self.values[0] == "show":
            embed = discord.Embed(
                title=f"👀 Current roles — {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids)
            )
            view = PilotPanelView(PanelState.ROLES)
            view.add_item(RoleActionSelect(self.scope))
            await safe_edit(interaction, embed=embed, view=view)
            return

        picker = discord.ui.View(timeout=180)
        picker.add_item(AddRolesSelect(self.scope) if self.values[0] == "add" else RemoveRolesSelect(self.scope))
        await interaction.channel.send("Select roles:", view=picker)

class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope):
        self.scope = scope
        super().__init__(placeholder="Add roles")

    async def callback(self, interaction):
        settings = load_settings()
        target = settings.get("global_allowed_roles") if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
        for r in self.values:
            target.append(r.id)
        save_settings(settings)
        await interaction.channel.send("✅ Roles added.")

class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope):
        self.scope = scope
        super().__init__(placeholder="Remove roles")

    async def callback(self, interaction):
        settings = load_settings()
        target = settings.get("global_allowed_roles") if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
        for r in self.values:
            if r.id in target:
                target.remove(r.id)
        save_settings(settings)
        await interaction.channel.send("✅ Roles removed.")

# ======================================================
# WELCOME / LEAVE
# ======================================================

class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Welcome action…",
            options=[
                discord.SelectOption(label="Toggle Welcome", value="toggle"),
                discord.SelectOption(label="Set Channel", value="channel"),
                discord.SelectOption(label="Edit Title", value="title"),
                discord.SelectOption(label="Edit Text", value="text"),
                discord.SelectOption(label="Add Slot", value="slot"),
                discord.SelectOption(label="Add Image", value="image"),
                discord.SelectOption(label="Preview", value="preview"),
            ]
        )

    async def callback(self, interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await no_perm(interaction)

        if self.values[0] == "title":
            return await interaction.response.send_modal(EditWelcomeTitleModal())
        if self.values[0] == "text":
            return await interaction.response.send_modal(EditWelcomeTextModal())

        await safe_defer(interaction)
        cfg = load_config()
        w = cfg["welcome"]

        if self.values[0] == "toggle":
            w["enabled"] = not w["enabled"]
            save_config(cfg)

        elif self.values[0] == "preview":
            count = human_member_number(interaction.guild)
            embed = discord.Embed(
                title=render(w["title"], interaction.user, interaction.guild, count, w.get("channels", {})),
                description=render(w["description"], interaction.user, interaction.guild, count, w.get("channels", {}))
            )
            if w.get("arrival_images"):
                embed.set_image(url=random.choice(w["arrival_images"]))
            await interaction.channel.send(embed=embed)
            return

        embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status(cfg))
        await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.WELCOME))

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Leave / log action…",
            options=[
                discord.SelectOption(label="Toggle Logs", value="toggle"),
                discord.SelectOption(label="Set Log Channel", value="channel"),
            ]
        )

    async def callback(self, interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await no_perm(interaction)

        if self.values[0] == "channel":
            return await interaction.response.send_message("Pick channel:", view=LogChannelPickerView())

        await safe_defer(interaction)
        cfg = load_config()
        cfg["member_logs"]["enabled"] = not cfg["member_logs"]["enabled"]
        save_config(cfg)

        embed = discord.Embed(title="📄 Leave / Logs", description=logs_status(cfg))
        await safe_edit(interaction, embed=embed, view=PilotPanelView(PanelState.LEAVE))

# ======================================================
# SLASH COMMAND
# ======================================================

def setup_admin_settings(tree: app_commands.CommandTree):
    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await no_perm(interaction)

        await interaction.response.defer(thinking=False)

        cfg = load_config()
        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status(cfg), inline=False)
        embed.add_field(name="🛂 Roles", value="Manage access.", inline=False)

        await interaction.followup.send(embed=embed, view=PilotPanelView())