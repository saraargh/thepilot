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

# =========================
# CONSTANTS
# =========================

SCOPES = {
    "global": "Global Admin Roles",
    "mute": "Mute",
    "warnings": "Warnings",
    "poo_goat": "Poo / Goat",
    "welcome_leave": "Welcome / Leave",
}

# =========================
# HELPERS
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
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="🔐 Global Admin",
        value=format_roles(guild, settings.get("global_allowed_roles", [])),
        inline=False,
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
                settings["apps"].get(key, {}).get("allowed_roles", []),
            ),
            inline=False,
        )

    embed.set_footer(text="Server owner & override role always have access")
    return embed


def welcome_status_text(cfg: Dict[str, Any]) -> str:
    w = cfg["welcome"]
    ch = f"<#{w['welcome_channel_id']}>" if w.get("welcome_channel_id") else "*Not set*"

    # ✅ Slots REMOVED
    # ✅ Images count REMOVED

    return (
        f"**Welcome Enabled:** `{w.get('enabled')}`\n"
        f"**Welcome Channel:** {ch}\n"
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

# =========================
# PANEL STATE
# =========================

class PanelState:
    ROOT = "root"
    ROLES = "roles"
    WELCOME = "welcome"
    LEAVE = "leave"

# =========================
# ARRIVAL IMAGE PREVIEW
# =========================

class ArrivalImagesPreviewView(discord.ui.View):
    def __init__(self, images: List[str], index: int = 0):
        super().__init__(timeout=300)
        self.images = images
        self.index = index

        self.prev.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.images) - 1

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🖼️ Arrival Image {self.index + 1}",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=self.images[self.index])
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=ArrivalImagesPreviewView(self.images, self.index),
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=ArrivalImagesPreviewView(self.images, self.index),
        )

# =========================
# PANEL VIEW
# =========================

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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.")
            return False
        return True

# =========================
# NAVIGATION
# =========================

class PanelNavSelect(discord.ui.Select):
    def __init__(self, current: str):
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
        target = self.values[0]
        cfg = load_config()

        if target == PanelState.ROOT:
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
            embed.add_field(
                name="🛂 Roles",
                value="Use **Roles** to manage permissions.",
                inline=False,
            )
        elif target == PanelState.ROLES:
            embed = discord.Embed(
                title="🛂 Role Permissions",
                description="Choose a role scope or view overview.",
                color=discord.Color.blurple(),
            )
        elif target == PanelState.WELCOME:
            embed = discord.Embed(
                title="👋 Welcome Settings",
                description=welcome_status_text(cfg),
                color=discord.Color.blurple(),
            )
        else:
            embed = discord.Embed(
                title="📄 Leave / Logs Settings",
                description=logs_status_text(cfg),
                color=discord.Color.blurple(),
            )

        await interaction.response.edit_message(
            embed=embed,
            view=PilotPanelView(target),
        )

# =========================
# ROLES
# =========================

class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a role scope…",
            options=[
                discord.SelectOption(label="👀 View Roles Overview", value="__view__"),
                *[
                    discord.SelectOption(label=v, value=k)
                    for k, v in SCOPES.items()
                ],
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()

        if self.values[0] == "__view__":
            embed = roles_embed(interaction.guild, settings)
            await interaction.response.edit_message(
                embed=embed,
                view=PilotPanelView(PanelState.ROLES),
            )
            return

        scope = self.values[0]
        embed = discord.Embed(
            title=f"🛂 Editing: {SCOPES[scope]}",
            description="Choose add/remove/show.",
            color=discord.Color.blurple(),
        )

        view = PilotPanelView(PanelState.ROLES)
        view.add_item(RoleActionSelect(scope))

        await interaction.response.edit_message(embed=embed, view=view)

class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Role action…",
            options=[
                discord.SelectOption(label="➕ Add roles", value="add"),
                discord.SelectOption(label="➖ Remove roles", value="remove"),
                discord.SelectOption(label="👀 Show current roles", value="show"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()

        if self.values[0] == "show":
            ids = (
                settings.get("global_allowed_roles", [])
                if self.scope == "global"
                else settings["apps"][self.scope]["allowed_roles"]
            )

            embed = discord.Embed(
                title=f"👀 Current roles — {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids),
                color=discord.Color.blurple(),
            )

            await interaction.response.edit_message(
                embed=embed,
                view=PilotPanelView(PanelState.ROLES),
            )
            return

        picker = discord.ui.View()
        if self.values[0] == "add":
            picker.add_item(AddRolesSelect(self.scope))
        else:
            picker.add_item(RemoveRolesSelect(self.scope))

        await interaction.response.send_message(
            "Select roles:",
            view=picker,
        )

class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to add", max_values=10)

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        roles = (
            set(settings.get("global_allowed_roles", []))
            if self.scope == "global"
            else set(settings["apps"][self.scope]["allowed_roles"])
        )

        for r in self.values:
            roles.add(r.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(roles)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(roles)

        save_settings(settings)
        await interaction.response.send_message("✅ Roles added.")

class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to remove", max_values=10)

    async def callback(self, interaction: discord.Interaction):
        settings = load_settings()
        roles = (
            set(settings.get("global_allowed_roles", []))
            if self.scope == "global"
            else set(settings["apps"][self.scope]["allowed_roles"])
        )

        for r in self.values:
            roles.discard(r.id)

        if self.scope == "global":
            settings["global_allowed_roles"] = list(roles)
        else:
            settings["apps"][self.scope]["allowed_roles"] = list(roles)

        save_settings(settings)
        await interaction.response.send_message("✅ Roles removed.")

# =========================
# WELCOME ACTIONS
# =========================

class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Welcome action…",
            options=[
                discord.SelectOption(label="Toggle Welcome", value="toggle", emoji="🔁"),
                discord.SelectOption(label="Set Welcome Channel", value="set_channel", emoji="📍"),
                discord.SelectOption(label="Edit Title", value="edit_title", emoji="✏️"),
                discord.SelectOption(label="Edit Text", value="edit_text", emoji="📝"),
                discord.SelectOption(label="Add Channel Slot", value="slot", emoji="➕"),
                discord.SelectOption(label="Add Arrival Image", value="add_img", emoji="🖼️"),
                discord.SelectOption(label="View Arrival Images", value="view_imgs", emoji="👀"),
                discord.SelectOption(label="Remove Arrival Image", value="rm_img", emoji="🗑️"),
                discord.SelectOption(label="Toggle Bot Add Logs", value="toggle_bot", emoji="🤖"),
                discord.SelectOption(label="Set Bot Add Channel", value="bot_channel", emoji="📢"),
                discord.SelectOption(label="Preview Welcome", value="preview", emoji="🔍"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        w = cfg["welcome"]
        choice = self.values[0]

        if choice == "view_imgs":
            imgs = w.get("arrival_images") or []
            if not imgs:
                await interaction.response.send_message("No arrival images yet.")
            else:
                view = ArrivalImagesPreviewView(imgs)
                await interaction.response.send_message(
                    embed=view.build_embed(),
                    view=view,
                )
            return

        if choice == "preview":
            count = human_member_number(interaction.guild)
            now = discord.utils.utcnow().strftime("%H:%M")

            embed = discord.Embed(
                title=render(w["title"], user=interaction.user, guild=interaction.guild, member_count=count, channels=w.get("channels", {})),
                description=render(w["description"], user=interaction.user, guild=interaction.guild, member_count=count, channels=w.get("channels", {})),
            )
            embed.set_footer(
                text=f"You landed as passenger #{count} 🛬 | Today at {now}"
            )

            imgs = w.get("arrival_images") or []
            if imgs:
                embed.set_image(url=random.choice(imgs))

            await interaction.response.send_message(embed=embed)
            return

        # Existing logic untouched
        if choice == "toggle":
            w["enabled"] = not w.get("enabled", True)
            save_config(cfg)

        elif choice == "set_channel":
            await interaction.response.send_message(
                "Select welcome channel:",
                view=WelcomeChannelPickerView(),
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
                await interaction.response.send_message("No images to remove.")
            else:
                await interaction.response.send_message(
                    "Select image to remove:",
                    view=RemoveImageView(imgs),
                )
            return

        elif choice == "toggle_bot":
            w["bot_add"]["enabled"] = not w["bot_add"].get("enabled", True)
            save_config(cfg)

        elif choice == "bot_channel":
            await interaction.response.send_message(
                "Select bot-add channel:",
                view=BotAddChannelPickerView(),
            )
            return

        embed = discord.Embed(
            title="👋 Welcome Settings",
            description=welcome_status_text(load_config()),
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=PilotPanelView(PanelState.WELCOME),
        )

class RemoveImageSelect(discord.ui.Select):
    def __init__(self, imgs: List[str]):
        super().__init__(
            placeholder="Choose image to remove…",
            options=[
                discord.SelectOption(label=f"Image {i+1}", value=str(i))
                for i in range(len(imgs))
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        idx = int(self.values[0])
        imgs = cfg["welcome"]["arrival_images"]

        imgs.pop(idx)
        cfg["welcome"]["arrival_images"] = imgs
        save_config(cfg)

        await interaction.response.send_message("✅ Image removed.")

class RemoveImageView(discord.ui.View):
    def __init__(self, imgs: List[str]):
        super().__init__()
        self.add_item(RemoveImageSelect(imgs))

# =========================
# LEAVE / LOGS
# =========================

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Leave / log action…",
            options=[
                discord.SelectOption(label="Toggle Logs", value="toggle_logs", emoji="🔁"),
                discord.SelectOption(label="Set Log Channel", value="set_log_channel", emoji="📍"),
                discord.SelectOption(label="Toggle Leave Logs", value="toggle_leave", emoji="🚪"),
                discord.SelectOption(label="Toggle Kick Logs", value="toggle_kick", emoji="🥾"),
                discord.SelectOption(label="Toggle Ban Logs", value="toggle_ban", emoji="⛔"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        m = cfg["member_logs"]
        choice = self.values[0]

        if choice == "set_log_channel":
            await interaction.response.send_message(
                "Select log channel:",
                view=LogChannelPickerView(),
            )
            return

        if choice == "toggle_logs":
            m["enabled"] = not m.get("enabled", True)
        elif choice == "toggle_leave":
            m["log_leave"] = not m.get("log_leave", True)
        elif choice == "toggle_kick":
            m["log_kick"] = not m.get("log_kick", True)
        elif choice == "toggle_ban":
            m["log_ban"] = not m.get("log_ban", True)

        save_config(cfg)

        embed = discord.Embed(
            title="📄 Leave / Logs Settings",
            description=logs_status_text(load_config()),
            color=discord.Color.blurple(),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=PilotPanelView(PanelState.LEAVE),
        )

# =========================
# SLASH COMMAND
# =========================

def setup_admin_settings(tree: app_commands.CommandTree):
    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        cfg = load_config()

        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(
            name="🛂 Roles",
            value="Manage permissions via the Roles panel.",
            inline=False,
        )

        await interaction.response.send_message(
            embed=embed,
            view=PilotPanelView(PanelState.ROOT),
        )