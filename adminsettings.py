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

# =========================
# Scopes (KEEP EMOJIS)
# =========================
SCOPES = {
    "global": "🔐 Global Admin Roles",
    "mute": "🔇 Mute",
    "warnings": "⚠️ Warnings",
    "poo_goat": "💩🐐 Poo / Goat",
    "welcome_leave": "👋 Welcome / Leave",
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


def welcome_status_text(cfg: Dict[str, Any]) -> str:
    """
    CHANGED per request:
    - removed Slots line
    - removed Images line
    """
    w = cfg["welcome"]
    ch = f"<#{w['welcome_channel_id']}>" if w.get("welcome_channel_id") else "*Not set*"
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
        f"**Leave:** `{m.get('log_leave')}` | **Kick:** `{m.get('log_kick')}` | **Ban:** `{m.get('log_ban')}`"
    )


def build_roles_overview_pages(guild: discord.Guild, settings: Dict[str, Any]) -> List[discord.Embed]:
    """
    Paginated overview (they liked this).
    2 sections per page.
    """
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
        embed = discord.Embed(title="⚙️ Pilot Role Permissions", color=discord.Color.blurple())
        for name, ids in sections[i:i + chunk_size]:
            embed.add_field(name=name, value=format_roles(guild, ids), inline=False)

        page_num = (i // chunk_size) + 1
        total = (len(sections) + chunk_size - 1) // chunk_size
        embed.set_footer(text=f"Page {page_num}/{total} · Server owner & override role always have access")
        pages.append(embed)

    return pages


# -------------------------
# Interaction-safe helpers
# -------------------------
async def _no_perm(interaction: discord.Interaction, msg: str = "❌ You do not have permission."):
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
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    content: Optional[str] = None
):
    """
    Edit the panel message safely, regardless of whether we already deferred.
    """
    try:
        if interaction.message:
            await interaction.message.edit(content=content, embed=embed, view=view)
        else:
            # fallback: send new message
            if interaction.channel:
                await interaction.channel.send(content=content, embed=embed, view=view)
    except Exception as e:
        if interaction.channel:
            await interaction.channel.send(f"❌ Panel update failed: `{type(e).__name__}`")


# =========================
# Panel State
# =========================
class PanelState:
    ROOT = "root"
    ROLES = "roles"
    WELCOME = "welcome"
    LEAVE = "leave"


# =========================
# Panel View
# =========================
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
            discord.SelectOption(label="⚙️ Home", value=PanelState.ROOT),
            discord.SelectOption(label="🛂 Roles", value=PanelState.ROLES),
            discord.SelectOption(label="👋 Welcome", value=PanelState.WELCOME),
            discord.SelectOption(label="📄 Leave / Logs", value=PanelState.LEAVE),
        ]
        super().__init__(placeholder="Navigate panel…", options=opts, min_values=1, max_values=1)
        self.current = current

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        target = self.values[0]

        await _safe_defer(interaction)

        if target == PanelState.ROOT:
            cfg = load_config()
            embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
            embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
            embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
            embed.add_field(
                name="🛂 Roles",
                value="Use **🛂 Roles** to manage access & view overview.",
                inline=False
            )
            await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.ROOT))
            return

        if target == PanelState.ROLES:
            embed = discord.Embed(
                title="🛂 Role Permissions",
                description="Pick a scope to manage roles, or view the overview.",
                color=discord.Color.blurple()
            )
        elif target == PanelState.WELCOME:
            cfg = load_config()
            embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status_text(cfg), color=discord.Color.blurple())
        else:  # LEAVE
            cfg = load_config()
            embed = discord.Embed(title="📄 Leave / Logs Settings", description=logs_status_text(cfg), color=discord.Color.blurple())

        await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=target))


# =========================
# Roles Overview Pagination (BACK button included)
# =========================
class RolesOverviewView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed], index: int = 0):
        super().__init__(timeout=300)
        self.pages = pages
        self.index = index
        self._sync()

    def _sync(self):
        self.prev_btn.disabled = self.index <= 0
        self.next_btn.disabled = self.index >= len(self.pages) - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _):
        self.index -= 1
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _):
        self.index += 1
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="↩ Back", style=discord.ButtonStyle.primary)
    async def back_btn(self, interaction: discord.Interaction, _):
        embed = discord.Embed(
            title="🛂 Role Permissions",
            description="Pick a scope to manage roles, or view the overview.",
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=PilotPanelView(state=PanelState.ROLES))


# =========================
# ROLES MANAGEMENT
# =========================
class RoleScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👀 View Roles Overview", value="__view__"),
            discord.SelectOption(label=SCOPES["global"], value="global"),
            discord.SelectOption(label=SCOPES["mute"], value="mute"),
            discord.SelectOption(label=SCOPES["warnings"], value="warnings"),
            discord.SelectOption(label=SCOPES["poo_goat"], value="poo_goat"),
            discord.SelectOption(label=SCOPES["welcome_leave"], value="welcome_leave"),
        ]
        super().__init__(placeholder="Choose a role scope…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        choice = self.values[0]
        await _safe_defer(interaction)

        if choice == "__view__":
            settings = load_settings()
            pages = build_roles_overview_pages(interaction.guild, settings)
            if not pages:
                embed = discord.Embed(title="⚙️ Pilot Role Permissions", description="No roles configured.", color=discord.Color.blurple())
                await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.ROLES))
                return

            # IMPORTANT: overview replaces panel message, with back button.
            await _safe_edit_panel_message(interaction, embed=pages[0], view=RolesOverviewView(pages, 0))
            return

        scope = choice
        embed = discord.Embed(
            title=f"🛂 Editing: {SCOPES[scope]}",
            description="Choose add/remove/show.",
            color=discord.Color.blurple()
        )
        view = PilotPanelView(state=PanelState.ROLES)
        view.add_item(RoleActionSelect(scope))
        await _safe_edit_panel_message(interaction, embed=embed, view=view)


class RoleActionSelect(discord.ui.Select):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(
            placeholder="Choose add/remove/show…",
            options=[
                discord.SelectOption(label="➕ Add roles", value="add"),
                discord.SelectOption(label="➖ Remove roles", value="remove"),
                discord.SelectOption(label="👀 Show current roles", value="show"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        action = self.values[0]
        settings = load_settings()

        if action == "show":
            ids = settings.get("global_allowed_roles", []) if self.scope == "global" else settings["apps"].get(self.scope, {}).get("allowed_roles", [])
            embed = discord.Embed(
                title=f"👀 Current roles — {SCOPES[self.scope]}",
                description=format_roles(interaction.guild, ids),
                color=discord.Color.blurple()
            )
            view = PilotPanelView(state=PanelState.ROLES)
            view.add_item(RoleActionSelect(self.scope))

            await _safe_defer(interaction)
            await _safe_edit_panel_message(interaction, embed=embed, view=view)
            return

        picker = discord.ui.View(timeout=180)
        if action == "add":
            picker.add_item(AddRolesSelect(self.scope))
            if interaction.response.is_done():
                await interaction.followup.send("Select roles to **ADD**:", view=picker)
            else:
                await interaction.response.send_message("Select roles to **ADD**:", view=picker)
        else:
            picker.add_item(RemoveRolesSelect(self.scope))
            if interaction.response.is_done():
                await interaction.followup.send("Select roles to **REMOVE**:", view=picker)
            else:
                await interaction.response.send_message("Select roles to **REMOVE**:", view=picker)


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
            role_set = set(settings["apps"].get(self.scope, {}).get("allowed_roles", []))

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
        if not has_global_access(interaction.user):
            return await _no_perm(interaction)

        settings = load_settings()
        if self.scope == "global":
            role_set = set(settings.get("global_allowed_roles", []))
        else:
            role_set = set(settings["apps"].get(self.scope, {}).get("allowed_roles", []))

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
            placeholder="Welcome action…",
            options=[
                discord.SelectOption(label="✅ Toggle Welcome On/Off", value="toggle"),
                discord.SelectOption(label="📍 Set Welcome Channel", value="set_channel"),
                discord.SelectOption(label="✏️ Edit Title", value="edit_title"),
                discord.SelectOption(label="📝 Edit Text", value="edit_text"),
                discord.SelectOption(label="➕ Add Channel Slot", value="slot_add"),
                discord.SelectOption(label="🛠️ Edit Existing Slot", value="slot_edit"),
                discord.SelectOption(label="🖼️ Add Arrival Image", value="add_img"),
                discord.SelectOption(label="🗑️ Remove Arrival Image", value="rm_img"),
                discord.SelectOption(label="🤖 Toggle Bot Add Logs", value="toggle_bot"),
                discord.SelectOption(label="📌 Set Bot Add Channel", value="bot_channel"),
                discord.SelectOption(label="🛬 Preview Welcome", value="preview"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave settings.")

        choice = self.values[0]

        # NEVER defer before modals or pickers
        if choice == "set_channel":
            return await interaction.response.send_message("Select the welcome channel:", view=WelcomeChannelPickerView())

        if choice == "edit_title":
            return await interaction.response.send_modal(EditWelcomeTitleModal())

        if choice == "edit_text":
            return await interaction.response.send_modal(EditWelcomeTextModal())

        if choice == "slot_add":
            return await interaction.response.send_modal(AddChannelSlotNameModal())

        if choice == "slot_edit":
            cfg = load_config()
            slots = list((cfg.get("welcome", {}).get("channels") or {}).keys())
            if not slots:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ No slots exist yet.")
                else:
                    await interaction.response.send_message("❌ No slots exist yet.")
                return
            return await interaction.response.send_message("Select a slot to edit:", view=EditSlotPickerView(slots))

        if choice == "add_img":
            return await interaction.response.send_modal(AddArrivalImageModal())

        if choice == "bot_channel":
            return await interaction.response.send_message("Select the bot-add log channel:", view=BotAddChannelPickerView())

        # From here: may hit GitHub -> defer
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

        elif choice == "rm_img":
            imgs = w.get("arrival_images") or []
            if not imgs:
                if interaction.channel:
                    await interaction.channel.send("❌ No arrival images to remove.")
            else:
                # second list: View Images or Remove Image
                if interaction.channel:
                    await interaction.channel.send("Choose what you want to do:", view=RemoveImageMenuView(imgs))

        elif choice == "preview":
            await send_welcome_preview(interaction)
            return

        cfg2 = load_config()
        embed = discord.Embed(title="👋 Welcome Settings", description=welcome_status_text(cfg2), color=discord.Color.blurple())
        await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.WELCOME))


# --- Slot editing ---
class EditSlotSelect(discord.ui.Select):
    def __init__(self, slots: List[str]):
        options = [discord.SelectOption(label=f"#{s}" if s.startswith("#") else s, value=s) for s in slots][:25]
        super().__init__(placeholder="Pick a slot to edit…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        slot = self.values[0]
        await interaction.response.send_message(
            f"Select a channel for `{slot}`:",
            view=SlotChannelPickerView(slot)
        )


class EditSlotPickerView(discord.ui.View):
    def __init__(self, slots: List[str]):
        super().__init__(timeout=180)
        self.add_item(EditSlotSelect(slots))


class SlotChannelPickerView(discord.ui.View):
    def __init__(self, slot: str):
        super().__init__(timeout=180)
        self.slot = slot
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cid = int(interaction.data["values"][0])
        cfg = load_config()
        cfg.setdefault("welcome", {}).setdefault("channels", {})
        cfg["welcome"]["channels"][self.slot] = cid
        save_config(cfg)
        await interaction.response.edit_message(content=f"✅ Saved `{self.slot}` → <#{cid}>", view=None)


# --- Remove image menu (View images OR Remove) ---
class RemoveImageMenuSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose…",
            options=[
                discord.SelectOption(label="📸 View Images", value="view"),
                discord.SelectOption(label="❌ Remove an Image", value="remove"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        imgs = cfg.get("welcome", {}).get("arrival_images") or []
        if not imgs:
            return await interaction.response.send_message("❌ No arrival images found.")

        choice = self.values[0]
        if choice == "view":
            pages = build_image_pages(imgs)
            await interaction.response.send_message(embed=pages[0], view=ImagePagerView(pages))
        else:
            await interaction.response.send_message("Select an image to remove:", view=RemoveImageView(imgs))


class RemoveImageMenuView(discord.ui.View):
    def __init__(self, imgs: List[str]):
        super().__init__(timeout=180)
        self.add_item(RemoveImageMenuSelect())


def build_image_pages(imgs: List[str]) -> List[discord.Embed]:
    pages = []
    for i, url in enumerate(imgs):
        e = discord.Embed(title=f"📸 Arrival Image {i+1}", color=discord.Color.blurple())
        e.set_image(url=url)
        e.set_footer(text=f"Image {i+1}/{len(imgs)}")
        pages.append(e)
    return pages


class ImagePagerView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed], index: int = 0):
        super().__init__(timeout=300)
        self.pages = pages
        self.index = index
        self._sync()

    def _sync(self):
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.pages) - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _):
        self.index -= 1
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        self.index += 1
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)


class RemoveImageSelect(discord.ui.Select):
    def __init__(self, imgs: List[str]):
        opts = [discord.SelectOption(label=f"Image {i+1}", value=str(i)) for i in range(min(25, len(imgs)))]
        super().__init__(placeholder="Pick an image to remove…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        imgs = cfg.get("welcome", {}).get("arrival_images") or []
        idx = int(self.values[0])

        if 0 <= idx < len(imgs):
            imgs.pop(idx)
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

    # IMPORTANT: render() uses keyword-only args in your joinleave.py
    title = render(
        w.get("title", ""),
        user=interaction.user,
        guild=interaction.guild,
        member_count=count,
        channels=w.get("channels", {}),
    )
    desc = render(
        w.get("description", ""),
        user=interaction.user,
        guild=interaction.guild,
        member_count=count,
        channels=w.get("channels", {}),
    )

    embed = discord.Embed(title=title, description=desc)
    embed.set_footer(text=f"You landed as passenger #{count} 🛬 | Today at {now}")

    imgs = w.get("arrival_images") or []
    if imgs:
        embed.set_image(url=random.choice(imgs))

    if interaction.channel:
        await interaction.channel.send(embed=embed)


# =========================
# LEAVE / LOGS MANAGEMENT
# =========================
class LeaveActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Leave / Logs action…",
            options=[
                discord.SelectOption(label="✅ Toggle Logs On/Off", value="toggle_logs"),
                discord.SelectOption(label="📍 Set Log Channel", value="set_log_channel"),
                discord.SelectOption(label="👋 Toggle Leave Logs", value="toggle_leave"),
                discord.SelectOption(label="🥾 Toggle Kick Logs", value="toggle_kick"),
                discord.SelectOption(label="⛔ Toggle Ban Logs", value="toggle_ban"),
            ],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await _no_perm(interaction, "❌ You don’t have permission for Welcome/Leave settings.")

        choice = self.values[0]

        if choice == "set_log_channel":
            return await interaction.response.send_message("Select the member log channel:", view=LogChannelPickerView())

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

        cfg2 = load_config()
        embed = discord.Embed(title="📄 Leave / Logs Settings", description=logs_status_text(cfg2), color=discord.Color.blurple())
        await _safe_edit_panel_message(interaction, embed=embed, view=PilotPanelView(state=PanelState.LEAVE))


# =========================
# Slash Command Setup
# =========================
def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot admin panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ You do not have permission.")

        # load_config can be GitHub -> defer first, then followup send
        await interaction.response.defer(thinking=False)

        cfg = load_config()
        embed = discord.Embed(title="⚙️ Pilot Settings", color=discord.Color.blurple())
        embed.add_field(name="👋 Welcome", value=welcome_status_text(cfg), inline=False)
        embed.add_field(name="📄 Leave / Logs", value=logs_status_text(cfg), inline=False)
        embed.add_field(
            name="🛂 Roles",
            value="Use **Navigate panel…** → 🛂 Roles to edit scopes.\nUse **👀 View Roles Overview** inside Roles.",
            inline=False
        )

        view = PilotPanelView(state=PanelState.ROOT)
        await interaction.followup.send(embed=embed, view=view)