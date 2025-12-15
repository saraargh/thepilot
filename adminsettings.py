# adminsettings.py
import discord
from discord import app_commands
from typing import List, Dict, Any, Optional
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
# Helpers
# ======================================================

def format_roles(guild: discord.Guild, role_ids: List[int]) -> str:
    mentions = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            mentions.append(role.mention)
    return "\n".join(mentions) if mentions else "*None*"


def welcome_status_text(cfg: Dict[str, Any]) -> str:
    w = cfg["welcome"]
    ch = f"<#{w['welcome_channel_id']}>" if w.get("welcome_channel_id") else "*Not set*"
    slots = w.get("channels") or {}
    imgs = w.get("arrival_images") or []
    bot_add = w.get("bot_add") or {}
    return (
        f"**Welcome Enabled:** `{w.get('enabled')}`\n"
        f"**Welcome Channel:** {ch}\n"
        f"**Slots:** `{len(slots)}`\n"
        f"**Images:** `{len(imgs)}`\n"
        f"**Bot Add Logs:** `{bot_add.get('enabled')}`"
    )


def logs_status_text(cfg: Dict[str, Any]) -> str:
    m = cfg["member_logs"]
    ch = f"<#{m['channel_id']}>" if m.get("channel_id") else "*Not set*"
    return (
        f"**Logs Enabled:** `{m.get('enabled')}`\n"
        f"**Log Channel:** {ch}\n"
        f"**Leave:** `{m.get('log_leave')}` | **Kick:** `{m.get('log_kick')}` | **Ban:** `{m.get('log_ban')}`"
    )


def build_role_pages(guild: discord.Guild, settings: Dict[str, Any]) -> List[discord.Embed]:
    sections = [
        ("🔐 Global Admin", settings.get("global_allowed_roles", [])),
        ("🔇 Mute", settings["apps"].get("mute", {}).get("allowed_roles", [])),
        ("⚠️ Warnings", settings["apps"].get("warnings", {}).get("allowed_roles", [])),
        ("💩🐐 Poo / Goat", settings["apps"].get("poo_goat", {}).get("allowed_roles", [])),
        ("👋 Welcome / Leave", settings["apps"].get("welcome_leave", {}).get("allowed_roles", [])),
    ]

    pages: List[discord.Embed] = []
    chunk_size = 2  # sections per page

    for i in range(0, len(sections), chunk_size):
        e = discord.Embed(title="⚙️ Pilot Role Permissions", color=discord.Color.blurple())
        for name, ids in sections[i:i + chunk_size]:
            e.add_field(name=name, value=format_roles(guild, ids), inline=False)
        e.set_footer(text="Server owner & override role always have access")
        pages.append(e)

    return pages


# ======================================================
# Interaction-safe helpers (NO ephemerals)
# ======================================================

async def _send_public(interaction: discord.Interaction, content: Optional[str] = None, **kwargs):
    """
    Always post publicly, and always ACK within the interaction window.
    """
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(content=content, **kwargs)
        return await interaction.response.send_message(content=content, **kwargs)
    except Exception:
        if interaction.channel:
            return await interaction.channel.send(content or "", **kwargs)


async def _safe_defer(interaction: discord.Interaction):
    """
    Defer ONLY if not already responded.
    Never call this before a modal.
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=False)
    except Exception:
        pass


async def _edit_panel_message(interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View):
    """
    Always edit the original panel message in-place.
    (Avoid response.edit_message after defers.)
    """
    try:
        if interaction.message:
            await interaction.message.edit(content=None, embed=embed, view=view)
            return
    except Exception:
        pass

    # fallback (rare)
    if interaction.channel:
        await interaction.channel.send(embed=embed, view=view)


async def _no_perm(interaction: discord.Interaction, msg: str = "❌ You do not have permission."):
    await _send_public(interaction, msg)


# ======================================================
# Single Message Panel State
# ======================================================

class PanelState:
    ROOT = "root"
    ROLES = "roles"
    WELCOME = "welcome"
    LEAVE = "leave"


def _root_embed() -> discord.Embed:
    cfg = load_config()
    e = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
    e.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
    e.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
    e.add_field(
        name="🛂 Roles",
        value="Use **Navigate panel…** → Roles to manage access.\n"
              "Inside Roles you can also use **👀 View Roles Overview**.",
        inline=False,
    )
    return e


def _roles_home_embed() -> discord.Embed:
    return discord.Embed(
        title="🛂 Role Permissions",
        description="Pick a scope to manage roles (or view overview).",
        color=discord.Color.blurple(),
    )


def _welcome_embed() -> discord.Embed:
    cfg = load_config()
    return discord.Embed(
        title="👋 Welcome Settings",
        description=welcome_status_text(cfg),
        color=discord.Color.blurple(),
    )


def _leave_embed() -> discord.Embed:
    cfg = load_config()
    return discord.Embed(
        title="📄 Leave / Logs Settings",
        description=logs_status_text(cfg),
        color=discord.Color.blurple(),
    )


# ======================================================
# Main Panel View
# ======================================================

class PilotPanelView(discord.ui.View):
    def __init__(self, state: str = PanelState.ROOT):
        super().__init__(timeout=600)
        self.state = state
        self.build()

    def build(self):
        self.clear_items()
        self.add_item(PanelNavSelect(current=self.state))

        if self.state == PanelState.ROLES:
            self.add_item(RoleScopeSelect())

        elif self.state == PanelState.WELCOME:
            self.add_item(WelcomeActionSelect())

        elif self.state == PanelState.LEAVE:
            self.add_item(LeaveActionSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await _no_perm(interaction)
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
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        target = self.values[0]

        # load_config hits GitHub; always defer, then edit the panel message.
        await _safe_defer(interaction)

        if target == PanelState.ROOT:
            await _edit_panel_message(interaction, embed=_root_embed(), view=PilotPanelView(state=PanelState.ROOT))
            return

        if target == PanelState.ROLES:
            await _edit_panel_message(interaction, embed=_roles_home_embed(), view=PilotPanelView(state=PanelState.ROLES))
            return

        if target == PanelState.WELCOME:
            await _edit_panel_message(interaction, embed=_welcome_embed(), view=PilotPanelView(state=PanelState.WELCOME))
            return

        await _edit_panel_message(interaction, embed=_leave_embed(), view=PilotPanelView(state=PanelState.LEAVE))


# ======================================================
# ROLES MANAGEMENT (ALL inside the panel)
# ======================================================

class RolesOverviewPanelView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed], index: int = 0):
        super().__init__(timeout=600)
        self.pages = pages
        self.index = index

        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _safe_defer(interaction)
        self.index = max(0, self.index - 1)
        await _edit_panel_message(interaction, embed=self.pages[self.index], view=RolesOverviewPanelView(self.pages, self.index))

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _safe_defer(interaction)
        self.index = min(len(self.pages) - 1, self.index + 1)
        await _edit_panel_message(interaction, embed=self.pages[self.index], view=RolesOverviewPanelView(self.pages, self.index))

    @discord.ui.button(label="↩ Back to Roles", style=discord.ButtonStyle.primary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _safe_defer(interaction)
        await _edit_panel_message(interaction, embed=_roles_home_embed(), view=PilotPanelView(state=PanelState.ROLES))


class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👀 View Roles Overview", value="__overview__"),
        ] + [discord.SelectOption(label=v, value=k) for k, v in SCOPES.items()]

        super().__init__(placeholder="Role scope / overview…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        choice = self.values[0]
        await _safe_defer(interaction)

        if choice == "__overview__":
            settings = load_settings()
            pages = build_role_pages(interaction.guild, settings)
            if not pages:
                await _edit_panel_message(
                    interaction,
                    embed=discord.Embed(title="⚙️ Pilot Role Permissions", description="*None*", color=discord.Color.blurple()),
                    view=PilotPanelView(state=PanelState.ROLES),
                )
                return

            await _edit_panel_message(interaction, embed=pages[0], view=RolesOverviewPanelView(pages, 0))
            return

        scope = choice
        e = discord.Embed(
            title=f"🛂 Editing: {SCOPES[scope]}",
            description="Choose add/remove/show, then pick roles.",
            color=discord.Color.blurple(),
        )
        v = PilotPanelView(state=PanelState.ROLES)
        v.add_item(RoleActionSelect(scope))
        await _edit_panel_message(interaction, embed=e, view=v)


class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Add / remove / show…",
            options=[
                discord.SelectOption(label="➕ Add roles", value="add"),
                discord.SelectOption(label="➖ Remove roles", value="remove"),
                discord.SelectOption(label="👀 Show current roles", value="show"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        action = self.values[0]
        await _safe_defer(interaction)

        settings = load_settings()
        ids = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"][self.scope]["allowed_roles"]

        if action == "show":
            e = discord.Embed(
                title=f"👀 Current roles — {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids),
                color=discord.Color.blurple(),
            )
            v = PilotPanelView(state=PanelState.ROLES)
            v.add_item(RoleActionSelect(self.scope))
            await _edit_panel_message(interaction, embed=e, view=v)
            return

        # Role picker must be sent as a separate public message
        picker = discord.ui.View(timeout=180)
        if action == "add":
            picker.add_item(AddRolesSelect(self.scope))
            await _send_public(interaction, "Select roles to **ADD**:", view=picker)
        else:
            picker.add_item(RemoveRolesSelect(self.scope))
            await _send_public(interaction, "Select roles to **REMOVE**:", view=picker)


class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to ADD", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

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
        await _send_public(interaction, f"✅ Added roles to **{SCOPES[self.scope]}**.")


class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to REMOVE", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

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
        await _send_public(interaction, f"✅ Removed roles from **{SCOPES[self.scope]}**.")


# ======================================================
# WELCOME MANAGEMENT
# ======================================================

class EditExistingSlotSelect(discord.ui.Select):
    def __init__(self, slots: Dict[str, int]):
        self._slot_names = list(slots.keys())
        opts = []
        for name in self._slot_names[:25]:
            opts.append(discord.SelectOption(label=name, value=name))
        super().__init__(placeholder="Pick a slot to edit…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave settings.")

        slot = self.values[0]
        await _send_public(interaction, f"Select a channel for `{slot}`:", view=ChannelSlotPickerView(slot))


class ChannelSlotPickerView(discord.ui.View):
    def __init__(self, slot_name: str):
        super().__init__(timeout=180)
        self.slot_name = slot_name
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave settings.")

        await _safe_defer(interaction)

        # interaction.data["values"][0] is channel id (as str)
        cid = int(interaction.data["values"][0])
        cfg = load_config()
        cfg["welcome"].setdefault("channels", {})
        cfg["welcome"]["channels"][self.slot_name] = cid
        save_config(cfg)

        # public confirmation
        if interaction.channel:
            await interaction.channel.send(f"✅ Saved `{self.slot_name}` → <#{cid}>")

        # keep panel consistent (if they picked from a panel context)
        if interaction.message:
            await interaction.message.edit(view=None)


class RemoveImageSelect(discord.ui.Select):
    def __init__(self, imgs: List[str]):
        opts = []
        for i, _url in enumerate(imgs[:25]):
            opts.append(discord.SelectOption(label=f"Image {i+1}", value=str(i)))
        super().__init__(placeholder="Pick an image to remove…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave settings.")

        await _safe_defer(interaction)

        cfg = load_config()
        imgs = cfg["welcome"].get("arrival_images") or []
        idx = int(self.values[0])

        if 0 <= idx < len(imgs):
            imgs.pop(idx)
            cfg["welcome"]["arrival_images"] = imgs
            save_config(cfg)
            if interaction.channel:
                await interaction.channel.send("✅ Removed that arrival image.")
        else:
            if interaction.channel:
                await interaction.channel.send("❌ Couldn’t remove that image (index mismatch).")


class RemoveImageView(discord.ui.View):
    def __init__(self, imgs: List[str]):
        super().__init__(timeout=180)
        self.add_item(RemoveImageSelect(imgs))


async def send_welcome_preview(interaction: discord.Interaction):
    """
    Always ACK first in the calling handler (defer),
    then send preview publicly here.
    """
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

    # ✅ EXACT footer format requested:
    embed.set_footer(text=f"You landed as passenger #{count} 🛬 | Today at {now}")

    imgs = w.get("arrival_images") or []
    if imgs:
        embed.set_image(url=random.choice(imgs))

    if interaction.channel:
        await interaction.channel.send(embed=embed)


class WelcomeActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Welcome action…",
            options=[
                discord.SelectOption(label="Toggle Welcome On/Off", value="toggle", emoji="👋"),
                discord.SelectOption(label="Set Welcome Channel", value="set_channel", emoji="📍"),
                discord.SelectOption(label="Edit Title", value="edit_title", emoji="✏️"),
                discord.SelectOption(label="Edit Text", value="edit_text", emoji="📝"),
                discord.SelectOption(label="Add Channel Slot", value="add_slot", emoji="➕"),
                discord.SelectOption(label="Edit Existing Slot", value="edit_slot", emoji="🛠️"),
                discord.SelectOption(label="Add Arrival Image", value="add_img", emoji="🖼️"),
                discord.SelectOption(label="Remove Arrival Image", value="rm_img", emoji="🗑️"),
                discord.SelectOption(label="Toggle Bot Add Logs", value="toggle_bot", emoji="🤖"),
                discord.SelectOption(label="Set Bot Add Channel", value="bot_channel", emoji="📌"),
                discord.SelectOption(label="Preview Welcome", value="preview", emoji="👀"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave settings.")

        choice = self.values[0]

        # Actions that MUST be first response (no defer before modals / picker messages)
        if choice == "set_channel":
            return await _send_public(interaction, "Select the welcome channel:", view=WelcomeChannelPickerView())

        if choice == "edit_title":
            return await interaction.response.send_modal(EditWelcomeTitleModal())

        if choice == "edit_text":
            return await interaction.response.send_modal(EditWelcomeTextModal())

        if choice == "add_slot":
            return await interaction.response.send_modal(AddChannelSlotNameModal())

        if choice == "add_img":
            return await interaction.response.send_modal(AddArrivalImageModal())

        if choice == "bot_channel":
            return await _send_public(interaction, "Select the bot-add log channel:", view=BotAddChannelPickerView())

        # Everything else can touch GitHub (load/save) -> defer first
        await _safe_defer(interaction)

        cfg = load_config()
        w = cfg["welcome"]

        if choice == "toggle":
            w["enabled"] = not w.get("enabled", True)
            save_config(cfg)

        elif choice == "toggle_bot":
            w.setdefault("bot_add", {})
            w["bot_add"]["enabled"] = not w["bot_add"].get("enabled", True)
            save_config(cfg)

        elif choice == "edit_slot":
            slots = w.get("channels") or {}
            if not slots:
                if interaction.channel:
                    await interaction.channel.send("No channel slots exist yet.")
            else:
                # send a public selector to pick which slot to edit
                v = discord.ui.View(timeout=180)
                v.add_item(EditExistingSlotSelect(slots))
                if interaction.channel:
                    await interaction.channel.send("Pick a slot to edit:", view=v)

        elif choice == "rm_img":
            imgs = w.get("arrival_images") or []
            if not imgs:
                if interaction.channel:
                    await interaction.channel.send("No arrival images to remove.")
            else:
                if interaction.channel:
                    await interaction.channel.send("Select an image to remove:", view=RemoveImageView(imgs))

        elif choice == "preview":
            # IMPORTANT: because we deferred, we can safely do work and send publicly
            await send_welcome_preview(interaction)

        # Refresh panel (unless we just previewed — still refresh, harmless)
        await _edit_panel_message(interaction, embed=_welcome_embed(), view=PilotPanelView(state=PanelState.WELCOME))


# ======================================================
# LEAVE / LOGS MANAGEMENT
# ======================================================

class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Leave/log action…",
            options=[
                discord.SelectOption(label="Toggle Logs On/Off", value="toggle_logs", emoji="📄"),
                discord.SelectOption(label="Set Log Channel", value="set_log_channel", emoji="📍"),
                discord.SelectOption(label="Toggle Leave Logs", value="toggle_leave", emoji="🚪"),
                discord.SelectOption(label="Toggle Kick Logs", value="toggle_kick", emoji="🥾"),
                discord.SelectOption(label="Toggle Ban Logs", value="toggle_ban", emoji="⛔"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave settings.")

        choice = self.values[0]

        # Must be first response (no defer)
        if choice == "set_log_channel":
            return await _send_public(interaction, "Select the member log channel:", view=LogChannelPickerView())

        await _safe_defer(interaction)

        cfg = load_config()
        m = cfg["member_logs"]

        if choice == "toggle_logs":
            m["enabled"] = not m.get("enabled", True)
        elif choice == "toggle_leave":
            m["log_leave"] = not m.get("log_leave", True)
        elif choice == "toggle_kick":
            m["log_kick"] = not m.get("log_kick", True)
        elif choice == "toggle_ban":
            m["log_ban"] = not m.get("log_ban", True)

        save_config(cfg)

        await _edit_panel_message(interaction, embed=_leave_embed(), view=PilotPanelView(state=PanelState.LEAVE))


# ======================================================
# Slash Command registration
# ======================================================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _send_public(interaction, "❌ You do not have permission.")

        # load_config may hit GitHub -> defer then followup send
        await interaction.response.defer(thinking=False)

        embed = _root_embed()
        view = PilotPanelView(state=PanelState.ROOT)

        # Public panel message
        await interaction.followup.send(embed=embed, view=view)