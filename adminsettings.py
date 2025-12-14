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
    for k, label in labels.items():
        embed.add_field(
            name=label,
            value=format_roles(guild, settings["apps"].get(k, {}).get("allowed_roles", [])),
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
        f"**Leave:** `{m.get('log_leave')}` | **Kick:** `{m.get('log_kick')}` | **Ban:** `{m.get('log_ban')}`"
    )

# =========================
# Single Message Panel
# =========================

class PanelState:
    ROOT = "root"
    ROLES = "roles"
    WELCOME = "welcome"
    LEAVE = "leave"

class PilotPanelView(discord.ui.View):
    def __init__(self, state: str = PanelState.ROOT):
        super().__init__(timeout=600)
        self.state = state
        self.build()

    def build(self):
        self.clear_items()
        # top navigation (lists)
        self.add_item(PanelNavSelect(current=self.state))

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

class PanelNavSelect(discord.ui.Select):
    def __init__(self, current: str):
        opts = [
            discord.SelectOption(label="Home", value=PanelState.ROOT, emoji="⚙️"),
            discord.SelectOption(label="Roles", value=PanelState.ROLES, emoji="🛂"),
            discord.SelectOption(label="Welcome", value=PanelState.WELCOME, emoji="👋"),
            discord.SelectOption(label="Leave / Logs", value=PanelState.LEAVE, emoji="📄"),
        ]
        super().__init__(placeholder="Navigate panel…", options=opts, min_values=1, max_values=1)
        self.current = current

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]

        # Build content
        if target == PanelState.ROOT:
            cfg = load_config()
            settings = load_settings()
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
            embed.add_field(name="🛂 Roles", value="Use **Roles** to edit scopes or **View Roles** below.", inline=False)

            view = PilotPanelView(state=PanelState.ROOT)
            view.add_item(ViewRolesButton())
            await interaction.response.edit_message(content=None, embed=embed, view=view)
            return

        # Switch panel
        embed = None
        if target == PanelState.ROLES:
            embed = discord.Embed(title="🛂 Role Permissions", description="Pick a scope to manage roles.", color=discord.Color.blurple())
        elif target == PanelState.WELCOME:
            cfg = load_config()
            embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status_text(cfg), color=discord.Color.blurple())
        elif target == PanelState.LEAVE:
            cfg = load_config()
            embed = discord.Embed(title="📄 Leave / Logs Settings", description=logs_status_text(cfg), color=discord.Color.blurple())

        await interaction.response.edit_message(embed=embed, view=PilotPanelView(state=target))

# =========================
# View Roles (Paginated, Public)
# =========================

class ViewRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="View Roles", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        embed = roles_embed(interaction.guild, settings)
        await interaction.channel.send(embed=embed)

# =========================
# ROLES MANAGEMENT
# =========================

class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()]
        super().__init__(placeholder="Choose a role scope to edit…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        scope = self.values[0]
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.")

        embed = discord.Embed(
            title=f"🛂 Editing: {SCOPES[scope]}",
            description="Choose add/remove, then pick roles.",
            color=discord.Color.blurple()
        )
        view = PilotPanelView(state=PanelState.ROLES)
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
        action = self.values[0]
        settings = load_settings()

        if action == "show":
            ids = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]
            embed = discord.Embed(
                title=f"👀 Current roles — {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids),
                color=discord.Color.blurple()
            )
            view = PilotPanelView(state=PanelState.ROLES)
            view.add_item(RoleActionSelect(self.scope))
            return await interaction.response.edit_message(embed=embed, view=view)

        # RoleSelect UI
        picker = discord.ui.View(timeout=180)
        if action == "add":
            picker.add_item(AddRolesSelect(self.scope))
            await interaction.response.send_message("Select roles to **ADD**:", view=picker)
        else:
            picker.add_item(RemoveRolesSelect(self.scope))
            await interaction.response.send_message("Select roles to **REMOVE**:", view=picker)

class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to ADD", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        if self.scope == "global":
            role_set = set(settings.get("global_allowed_roles", []))
        else:
            role_set = set(settings["apps"][self.scope]["allowed_roles"])

        for r in self.values:
            role_set.add(r.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(role_set)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(role_set)

        save_settings(settings)
        await interaction.response.send_message(f"✅ Added roles to **{SCOPES[self.scope]}**.")

class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to REMOVE", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        if self.scope == "global":
            role_set = set(settings.get("global_allowed_roles", []))
        else:
            role_set = set(settings["apps"][self.scope]["allowed_roles"])

        for r in self.values:
            role_set.discard(r.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(role_set)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(role_set)

        save_settings(settings)
        await interaction.response.send_message(f"✅ Removed roles from **{SCOPES[self.scope]}**.")

# =========================
# WELCOME MANAGEMENT
# =========================

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
            return await interaction.response.send_message("❌ You don’t have permission for Welcome/Leave settings.")

        cfg = load_config()
        w = cfg["welcome"]
        choice = self.values[0]

        # fast ACK if we do network-ish work
        if choice in ("toggle", "toggle_bot", "rm_img", "preview"):
            await interaction.response.defer(thinking=False)

        if choice == "toggle":
            w["enabled"] = not w["enabled"]
            save_config(cfg)

        elif choice == "set_channel":
            return await interaction.response.send_message("Select the welcome channel:", view=WelcomeChannelPickerView())

        elif choice == "edit_title":
            return await interaction.response.send_modal(EditWelcomeTitleModal())

        elif choice == "edit_text":
            return await interaction.response.send_modal(EditWelcomeTextModal())

        elif choice == "slot":
            return await interaction.response.send_modal(AddChannelSlotNameModal())

        elif choice == "add_img":
            return await interaction.response.send_modal(AddArrivalImageModal())

        elif choice == "rm_img":
            imgs = w.get("arrival_images") or []
            if not imgs:
                return await interaction.followup.send("No arrival images to remove.")
            await interaction.followup.send("Select an image to remove:", view=RemoveImageView(imgs))

        elif choice == "toggle_bot":
            w["bot_add"]["enabled"] = not w["bot_add"].get("enabled", True)
            save_config(cfg)

        elif choice == "bot_channel":
            return await interaction.response.send_message("Select the bot-add log channel:", view=BotAddChannelPickerView())

        elif choice == "preview":
            await send_welcome_preview(interaction)

        # update panel message
        cfg2 = load_config()
        embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status_text(cfg2), color=discord.Color.blurple())
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=PilotPanelView(state=PanelState.WELCOME))

class RemoveImageSelect(discord.ui.Select):
    def __init__(self, imgs: List[str]):
        self.imgs = imgs
        opts = []
        # show first 25 max per discord
        for i, url in enumerate(imgs[:25]):
            label = f"Image {i+1}"
            opts.append(discord.SelectOption(label=label, value=str(i)))
        super().__init__(placeholder="Pick an image to remove…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        imgs = cfg["welcome"].get("arrival_images") or []
        idx = int(self.values[0])
        if 0 <= idx < len(imgs):
            removed = imgs.pop(idx)
            cfg["welcome"]["arrival_images"] = imgs
            save_config(cfg)
            await interaction.response.send_message("✅ Removed that arrival image.")
        else:
            await interaction.response.send_message("❌ Couldn’t remove that image (index mismatch).")

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
        title=render(w["title"], user=interaction.user, guild=interaction.guild, member_count=count, channels=w.get("channels", {})),
        description=render(w["description"], user=interaction.user, guild=interaction.guild, member_count=count, channels=w.get("channels", {})),
    )
    embed.set_footer(text=f"You landed as passenger #{count} ✈️ | Today at {now}")
    imgs = w.get("arrival_images") or []
    if imgs:
        embed.set_image(url=random.choice(imgs))

    await interaction.followup.send(embed=embed)

# =========================
# LEAVE / LOGS MANAGEMENT
# =========================

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
            return await interaction.response.send_message("❌ You don’t have permission for Welcome/Leave settings.")

        cfg = load_config()
        m = cfg["member_logs"]
        choice = self.values[0]

        if choice == "set_log_channel":
            return await interaction.response.send_message("Select the member log channel:", view=LogChannelPickerView())

        await interaction.response.defer(thinking=False)

        if choice == "toggle_logs":
            m["enabled"] = not m.get("enabled", True)
        elif choice == "toggle_leave":
            m["log_leave"] = not m.get("log_leave", True)
        elif choice == "toggle_kick":
            m["log_kick"] = not m.get("log_kick", True)
        elif choice == "toggle_ban":
            m["log_ban"] = not m.get("log_ban", True)

        save_config(cfg)

        cfg2 = load_config()
        embed = discord.Embed(title="📄 Leave / Logs Settings", description=logs_status_text(cfg2), color=discord.Color.blurple())
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=PilotPanelView(state=PanelState.LEAVE))

# =========================
# Slash Command
# =========================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ You do not have permission.")

        cfg = load_config()
        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(name="🛂 Roles", value="Use **Navigate panel…** → Roles to edit scopes.\nUse **View Roles** to display current access.", inline=False)

        view = PilotPanelView(state=PanelState.ROOT)
        view.add_item(ViewRolesButton())

        await interaction.response.send_message(embed=embed, view=view)