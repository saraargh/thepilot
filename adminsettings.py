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

        self.add_item(PanelNavSelect())

        if state == PanelState.ROLES:
            self.add_item(RoleScopeSelect())

        elif state == PanelState.WELCOME:
            self.add_item(WelcomeActionSelect())

        elif state == PanelState.LEAVE:
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
        )

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]

        if choice == PanelState.ROOT:
            cfg = load_config()
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
            embed.add_field(name="🛂 Roles", value="Manage access & permissions", inline=False)
            await interaction.response.edit_message(embed=embed, view=PilotPanelView(PanelState.ROOT))
            return

        if choice == PanelState.ROLES:
            embed = discord.Embed(
                title="🛂 Role Permissions",
                description="Manage role access or view overview 👀",
                color=discord.Color.blurple()
            )
        elif choice == PanelState.WELCOME:
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

        await interaction.response.edit_message(embed=embed, view=PilotPanelView(choice))

# =====================================================
# ROLE OVERVIEW (PAGINATED, INSIDE PANEL)
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
# ROLES MANAGEMENT
# =====================================================

class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👀 View Roles Overview", value="__view__"),
        ] + [discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()]

        super().__init__(placeholder="Choose a role scope…", options=options)

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]

        if choice == "__view__":
            settings = load_settings()
            pages = build_role_pages(interaction.guild, settings)
            await interaction.response.edit_message(
                embed=pages[0],
                view=RolesOverviewView(pages)
            )
            return

        embed = discord.Embed(
            title=f"🛂 Editing: {SCOPES[choice]}",
            description="Add ➕ / Remove ➖ / Show 👀 roles",
            color=discord.Color.blurple()
        )
        view = PilotPanelView(PanelState.ROLES)
        view.add_item(RoleActionSelect(choice))
        await interaction.response.edit_message(embed=embed, view=view)

class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Role action…",
            options=[
                discord.SelectOption(label="➕ Add roles", value="add"),
                discord.SelectOption(label="➖ Remove roles", value="remove"),
                discord.SelectOption(label="👀 Show roles", value="show"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()

        if self.values[0] == "show":
            ids = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
            embed = discord.Embed(
                title=f"👀 {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids),
                color=discord.Color.blurple()
            )
            await interaction.channel.send(embed=embed)
            return

        picker = discord.ui.View()
        picker.add_item(
            AddRolesSelect(self.scope)
            if self.values[0] == "add"
            else RemoveRolesSelect(self.scope)
        )
        await interaction.response.send_message("Select roles:", view=picker)

class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to ADD")

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        target = settings.setdefault("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
        for r in self.values:
            if r.id not in target:
                target.append(r.id)
        save_settings(settings)
        await interaction.response.send_message("✅ Roles added.")

class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to REMOVE")

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        target = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
        for r in self.values:
            if r.id in target:
                target.remove(r.id)
        save_settings(settings)
        await interaction.response.send_message("✅ Roles removed.")

# =====================================================
# REMOVE IMAGE SELECT
# =====================================================

class RemoveArrivalImageSelect(discord.ui.Select):
    def __init__(self, images: List[str]):
        self.images = images
        options = [
            discord.SelectOption(label=f"🖼 Image {i+1}", value=str(i))
            for i in range(len(images))
        ]
        super().__init__(placeholder="Select image to remove…", options=options)

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        cfg = load_config()
        cfg["welcome"]["arrival_images"].pop(idx)
        save_config(cfg)
        await interaction.response.send_message("🗑 Image removed.")

# =====================================================
# WELCOME ACTIONS
# =====================================================

class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Welcome action…",
            options=[
                discord.SelectOption(label="Toggle Welcome", value="toggle", emoji="🔁"),
                discord.SelectOption(label="Set Welcome Channel", value="set_channel", emoji="📍"),
                discord.SelectOption(label="Edit Title", value="edit_title", emoji="✏️"),
                discord.SelectOption(label="Edit Text", value="edit_text", emoji="📝"),
                discord.SelectOption(label="Add/Edit Channel Slot", value="slot", emoji="➕"),
                discord.SelectOption(label="Add Arrival Image", value="add_img", emoji="🖼"),
                discord.SelectOption(label="Remove Arrival Image", value="rm_img", emoji="🗑"),
                discord.SelectOption(label="Toggle Bot Add Logs", value="toggle_bot", emoji="🤖"),
                discord.SelectOption(label="Set Bot Add Channel", value="bot_channel", emoji="📍"),
                discord.SelectOption(label="Preview Welcome", value="preview", emoji="👀"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await interaction.response.send_message("❌ No permission.")

        choice = self.values[0]

        if choice == "edit_title":
            return await interaction.response.send_modal(EditWelcomeTitleModal())
        if choice == "edit_text":
            return await interaction.response.send_modal(EditWelcomeTextModal())
        if choice == "slot":
            return await interaction.response.send_modal(AddChannelSlotNameModal())
        if choice == "add_img":
            return await interaction.response.send_modal(AddArrivalImageModal())
        if choice == "set_channel":
            return await interaction.response.send_message("Select channel:", view=WelcomeChannelPickerView())
        if choice == "bot_channel":
            return await interaction.response.send_message("Select channel:", view=BotAddChannelPickerView())

        cfg = load_config()
        w = cfg["welcome"]

        if choice == "toggle":
            w["enabled"] = not w["enabled"]
        elif choice == "toggle_bot":
            w["bot_add"]["enabled"] = not w["bot_add"]["enabled"]
        elif choice == "rm_img":
            imgs = w.get("arrival_images", [])
            if not imgs:
                return await interaction.response.send_message("No images to remove.")
            view = discord.ui.View()
            view.add_item(RemoveArrivalImageSelect(imgs))
            return await interaction.response.send_message("Choose image:", view=view)
        elif choice == "preview":
            await send_welcome_preview(interaction)
            return

        save_config(cfg)

        embed = discord.Embed(
            title="👋 Welcome Settings",
            description=welcome_status_text(load_config()),
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=PilotPanelView(PanelState.WELCOME))

async def send_welcome_preview(interaction: discord.Interaction):
    cfg = load_config()
    w = cfg["welcome"]
    count = human_member_number(interaction.guild)

    embed = discord.Embed(
        title=render(w["title"], user=interaction.user, guild=interaction.guild, member_count=count, channels=w.get("channels", {})),
        description=render(w["description"], user=interaction.user, guild=interaction.guild, member_count=count, channels=w.get("channels", {})),
    )
    embed.set_footer(text=f"You landed as passenger #{count} ✈️")
    if w.get("arrival_images"):
        embed.set_image(url=random.choice(w["arrival_images"]))

    await interaction.channel.send(embed=embed)

# =====================================================
# LEAVE / LOGS
# =====================================================

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Leave / log action…",
            options=[
                discord.SelectOption(label="Toggle Logs", value="toggle_logs", emoji="🔁"),
                discord.SelectOption(label="Set Log Channel", value="set_channel", emoji="📍"),
                discord.SelectOption(label="Toggle Leave Logs", value="leave", emoji="👋"),
                discord.SelectOption(label="Toggle Kick Logs", value="kick", emoji="🥾"),
                discord.SelectOption(label="Toggle Ban Logs", value="ban", emoji="⛔"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await interaction.response.send_message("❌ No permission.")

        cfg = load_config()
        m = cfg["member_logs"]

        if self.values[0] == "set_channel":
            return await interaction.response.send_message("Select channel:", view=LogChannelPickerView())

        if self.values[0] == "toggle_logs":
            m["enabled"] = not m["enabled"]
        elif self.values[0] == "leave":
            m["log_leave"] = not m["log_leave"]
        elif self.values[0] == "kick":
            m["log_kick"] = not m["log_kick"]
        elif self.values[0] == "ban":
            m["log_ban"] = not m["log_ban"]

        save_config(cfg)

        embed = discord.Embed(
            title="📄 Leave / Logs Settings",
            description=logs_status_text(load_config()),
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=PilotPanelView(PanelState.LEAVE))

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
        embed.add_field(name="🛂 Roles", value="Manage access & permissions", inline=False)

        await interaction.response.send_message(embed=embed, view=PilotPanelView(PanelState.ROOT))