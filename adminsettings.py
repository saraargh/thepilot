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

# ======================================================
# SCOPES
# ======================================================

SCOPES = {
    "global": "Global Admin Roles",
    "mute": "Mute",
    "warnings": "Warnings",
    "poo_goat": "Poo / Goat",
    "welcome_leave": "Welcome / Leave",
}

# ======================================================
# HELPERS
# ======================================================

def format_roles(guild: discord.Guild, role_ids: List[int]) -> str:
    mentions = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            mentions.append(role.mention)
    return "\n".join(mentions) if mentions else "*None*"

def roles_embed(guild: discord.Guild, settings: Dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(title="⚙️ Pilot Role Permissions", color=discord.Color.blurple())
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

# ======================================================
# NAVIGATION SELECT
# ======================================================

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
                value="Use **Roles** to edit scopes or **View Roles** below.",
                inline=False
            )

            view = PilotPanelView(PanelState.ROOT)
            view.add_item(ViewRolesButton())
            await interaction.response.edit_message(embed=embed, view=view)
            return

        if target == PanelState.ROLES:
            embed = discord.Embed(
                title="🛂 Role Permissions",
                description="Pick a scope to manage roles.",
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

        await interaction.response.edit_message(embed=embed, view=PilotPanelView(target))

# ======================================================
# VIEW ROLES BUTTON
# ======================================================

class ViewRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="View Roles", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        embed = roles_embed(interaction.guild, load_settings())
        await interaction.channel.send(embed=embed)

# ======================================================
# ROLE MANAGEMENT
# ======================================================

class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a role scope…",
            options=[discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        scope = self.values[0]

        embed = discord.Embed(
            title=f"🛂 Editing: {SCOPES[scope]}",
            description="Choose add/remove, then select roles.",
            color=discord.Color.blurple()
        )

        view = PilotPanelView(PanelState.ROLES)
        view.add_item(RoleActionSelect(scope))
        await interaction.response.edit_message(embed=embed, view=view)

class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Add or remove roles…",
            options=[
                discord.SelectOption(label="Add roles", value="add", emoji="➕"),
                discord.SelectOption(label="Remove roles", value="remove", emoji="➖"),
                discord.SelectOption(label="Show current roles", value="show", emoji="👀"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        action = self.values[0]

        if action == "show":
            ids = (
                settings.get("global_allowed_roles", [])
                if self.scope == "global"
                else settings["apps"][self.scope]["allowed_roles"]
            )
            embed = discord.Embed(
                title=f"👀 Current roles — {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids),
                color=discord.Color.blurple()
            )
            view = PilotPanelView(PanelState.ROLES)
            view.add_item(RoleActionSelect(self.scope))
            await interaction.response.edit_message(embed=embed, view=view)
            return

        picker = discord.ui.View(timeout=180)
        picker.add_item(
            AddRolesSelect(self.scope)
            if action == "add"
            else RemoveRolesSelect(self.scope)
        )

        await interaction.response.send_message(
            f"Select roles to **{action.upper()}**:",
            view=picker
        )

class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to ADD", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        roles = set(
            settings.get("global_allowed_roles", [])
            if self.scope == "global"
            else settings["apps"][self.scope]["allowed_roles"]
        )

        for role in self.values:
            roles.add(role.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(roles)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(roles)

        save_settings(settings)
        await interaction.response.send_message(f"✅ Roles added to **{SCOPES[self.scope]}**.")

class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to REMOVE", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        roles = set(
            settings.get("global_allowed_roles", [])
            if self.scope == "global"
            else settings["apps"][self.scope]["allowed_roles"]
        )

        for role in self.values:
            roles.discard(role.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(roles)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(roles)

        save_settings(settings)
        await interaction.response.send_message(f"✅ Roles removed from **{SCOPES[self.scope]}**.")

# ======================================================
# WELCOME MANAGEMENT (FIXED)
# ======================================================

class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a welcome action…",
            options=[
                discord.SelectOption(label="Toggle Welcome On/Off", value="toggle"),
                discord.SelectOption(label="Set Welcome Channel", value="set_channel"),
                discord.SelectOption(label="Edit Title", value="edit_title"),
                discord.SelectOption(label="Edit Text", value="edit_text"),
                discord.SelectOption(label="Add/Edit Channel Slot", value="slot"),
                discord.SelectOption(label="Add Arrival Image", value="add_img"),
                discord.SelectOption(label="Remove Arrival Image", value="rm_img"),
                discord.SelectOption(label="Toggle Bot Add Logs", value="toggle_bot"),
                discord.SelectOption(label="Set Bot Add Channel", value="bot_channel"),
                discord.SelectOption(label="Preview Welcome", value="preview"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            await interaction.response.send_message("❌ No permission.")
            return

        cfg = load_config()
        w = cfg["welcome"]
        choice = self.values[0]

        if choice in ("toggle", "toggle_bot", "rm_img", "preview"):
            await interaction.response.defer(thinking=False)

        if choice == "toggle":
            w["enabled"] = not w["enabled"]
            save_config(cfg)

        elif choice == "set_channel":
            await interaction.response.send_message(
                "Select welcome channel:",
                view=WelcomeChannelPickerView()
            )
            return

        elif choice == "edit_title":
            await interaction.response.send_modal(EditWelcomeTitleModal())
            return

        elif choice == "edit_text":
            await interaction.response.send_modal(EditWelcomeTextModal())
            return

        elif choice == "slot":
            await interaction.response.send_modal(AddChannelSlotNameModal())
            return

        elif choice == "add_img":
            await interaction.response.send_modal(AddArrivalImageModal())
            return

        elif choice == "rm_img":
            imgs = w.get("arrival_images") or []
            if not imgs:
                await interaction.followup.send("No arrival images to remove.")
                return
            await interaction.followup.send(
                "Select an image to remove:",
                view=RemoveImageView(imgs)
            )
            return

        elif choice == "toggle_bot":
            w["bot_add"]["enabled"] = not w["bot_add"].get("enabled", True)
            save_config(cfg)

        elif choice == "bot_channel":
            await interaction.response.send_message(
                "Select bot-add log channel:",
                view=BotAddChannelPickerView()
            )
            return

        elif choice == "preview":
            await send_welcome_preview(interaction)
            return

        cfg2 = load_config()
        embed = discord.Embed(
            title="👋 Welcome Settings",
            description=welcome_status_text(cfg2),
            color=discord.Color.blurple()
        )
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            embed=embed,
            view=PilotPanelView(PanelState.WELCOME)
        )

# ======================================================
# REMOVE IMAGE
# ======================================================

class RemoveImageSelect(discord.ui.Select):
    def __init__(self, imgs: List[str]):
        super().__init__(
            placeholder="Pick image to remove…",
            options=[
                discord.SelectOption(label=f"Image {i+1}", value=str(i))
                for i in range(min(len(imgs), 25))
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        idx = int(self.values[0])
        imgs = cfg["welcome"]["arrival_images"]

        imgs.pop(idx)
        save_config(cfg)
        await interaction.response.send_message("✅ Image removed.")

class RemoveImageView(discord.ui.View):
    def __init__(self, imgs: List[str]):
        super().__init__(timeout=180)
        self.add_item(RemoveImageSelect(imgs))

async def send_welcome_preview(interaction: discord.Interaction):
    cfg = load_config()
    w = cfg["welcome"]

    count = human_member_number(interaction.guild)
    now = discord.utils.utcnow().strftime("%H:%M")

    embed = discord.Embed(
        title=render(
            w["title"],
            user=interaction.user,
            guild=interaction.guild,
            member_count=count,
            channels=w.get("channels", {})
        ),
        description=render(
            w["description"],
            user=interaction.user,
            guild=interaction.guild,
            member_count=count,
            channels=w.get("channels", {})
        ),
    )
    embed.set_footer(text=f"You landed as passenger #{count} ✈️ | Today at {now}")

    if w.get("arrival_images"):
        embed.set_image(url=random.choice(w["arrival_images"]))

    await interaction.followup.send(embed=embed)

# ======================================================
# LEAVE / LOGS
# ======================================================

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a leave/log action…",
            options=[
                discord.SelectOption(label="Toggle Logs On/Off", value="toggle_logs"),
                discord.SelectOption(label="Set Log Channel", value="set_log_channel"),
                discord.SelectOption(label="Toggle Leave Logs", value="toggle_leave"),
                discord.SelectOption(label="Toggle Kick Logs", value="toggle_kick"),
                discord.SelectOption(label="Toggle Ban Logs", value="toggle_ban"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            await interaction.response.send_message("❌ No permission.")
            return

        cfg = load_config()
        m = cfg["member_logs"]
        choice = self.values[0]

        if choice == "set_log_channel":
            await interaction.response.send_message(
                "Select member log channel:",
                view=LogChannelPickerView()
            )
            return

        await interaction.response.defer(thinking=False)

        if choice == "toggle_logs":
            m["enabled"] = not m["enabled"]
        elif choice == "toggle_leave":
            m["log_leave"] = not m["log_leave"]
        elif choice == "toggle_kick":
            m["log_kick"] = not m["log_kick"]
        elif choice == "toggle_ban":
            m["log_ban"] = not m["log_ban"]

        save_config(cfg)

        embed = discord.Embed(
            title="📄 Leave / Logs Settings",
            description=logs_status_text(load_config()),
            color=discord.Color.blurple()
        )

        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            embed=embed,
            view=PilotPanelView(PanelState.LEAVE)
        )

# ======================================================
# SLASH COMMAND
# ======================================================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.")
            return

        cfg = load_config()
        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(
            name="🛂 Roles",
            value="Use **Navigate panel…** → Roles to edit scopes.\nUse **View Roles** to display current access.",
            inline=False
        )

        view = PilotPanelView(PanelState.ROOT)
        view.add_item(ViewRolesButton())

        await interaction.response.send_message(embed=embed, view=view)