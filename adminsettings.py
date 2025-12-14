# adminsettings.py
import discord
from discord import app_commands

from permissions import load_settings, save_settings, has_global_access, has_app_access
from joinleave import WelcomeSettingsView, LeaveSettingsView

# =========================
# Scopes
# =========================
SCOPES = [
    ("global", "🔐 Global Admin"),
    ("mute", "🔇 Mute"),
    ("warnings", "⚠️ Warnings"),
    ("poo_goat", "💩🐐 Poo / Goat"),
    ("welcome_leave", "👋 Welcome / Leave"),
]

SCOPE_LABELS = {k: v for k, v in SCOPES}


# =========================
# Helpers
# =========================
def _format_roles(guild: discord.Guild, role_ids: list[int]) -> str:
    if not guild:
        return "*None*"
    roles = []
    for rid in role_ids:
        role = guild.get_role(int(rid))
        if role:
            roles.append(role.mention)
    return "\n".join(roles) if roles else "*None*"


def _get_scope_role_ids(settings: dict, scope_key: str) -> list[int]:
    if scope_key == "global":
        return list(settings.get("global_allowed_roles", []))
    return list(settings.get("apps", {}).get(scope_key, {}).get("allowed_roles", []))


def _set_scope_role_ids(settings: dict, scope_key: str, ids: list[int]) -> None:
    if scope_key == "global":
        settings["global_allowed_roles"] = ids
    else:
        settings.setdefault("apps", {})
        settings["apps"].setdefault(scope_key, {})
        settings["apps"][scope_key].setdefault("allowed_roles", [])
        settings["apps"][scope_key]["allowed_roles"] = ids


# =========================
# Allowed Roles - Selects
# =========================
class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope_key: str):
        self.scope_key = scope_key
        super().__init__(
            placeholder="Select roles to ADD",
            min_values=1,
            max_values=10
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You don’t have permission to edit Pilot settings.",
                ephemeral=True
            )

        settings = load_settings()
        role_set = set(_get_scope_role_ids(settings, self.scope_key))

        for role in self.values:
            role_set.add(role.id)

        _set_scope_role_ids(settings, self.scope_key, list(role_set))
        save_settings(settings)

        await interaction.response.send_message(
            f"✅ Added roles to **{SCOPE_LABELS[self.scope_key]}**.",
            ephemeral=True
        )


class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope_key: str):
        self.scope_key = scope_key
        super().__init__(
            placeholder="Select roles to REMOVE",
            min_values=1,
            max_values=10
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You don’t have permission to edit Pilot settings.",
                ephemeral=True
            )

        settings = load_settings()
        role_set = set(_get_scope_role_ids(settings, self.scope_key))

        for role in self.values:
            role_set.discard(role.id)

        _set_scope_role_ids(settings, self.scope_key, list(role_set))
        save_settings(settings)

        await interaction.response.send_message(
            f"✅ Removed roles from **{SCOPE_LABELS[self.scope_key]}**.",
            ephemeral=True
        )


# =========================
# Allowed Roles - Views
# =========================
class ManageRolesView(discord.ui.View):
    def __init__(self, scope_key: str):
        super().__init__(timeout=180)
        self.scope_key = scope_key

    @discord.ui.button(label="➕ Add Roles", style=discord.ButtonStyle.success)
    async def add_roles(self, interaction: discord.Interaction, _):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        v = discord.ui.View(timeout=180)
        v.add_item(AddRolesSelect(self.scope_key))
        await interaction.response.send_message(
            f"Select roles to **add** for **{SCOPE_LABELS[self.scope_key]}**:",
            view=v,
            ephemeral=True
        )

    @discord.ui.button(label="➖ Remove Roles", style=discord.ButtonStyle.danger)
    async def remove_roles(self, interaction: discord.Interaction, _):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        v = discord.ui.View(timeout=180)
        v.add_item(RemoveRolesSelect(self.scope_key))
        await interaction.response.send_message(
            f"Select roles to **remove** for **{SCOPE_LABELS[self.scope_key]}**:",
            view=v,
            ephemeral=True
        )


class ScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=key) for key, label in SCOPES]
        super().__init__(
            placeholder="Which area would you like to change?",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        scope_key = self.values[0]
        await interaction.response.send_message(
            f"⚙️ **{SCOPE_LABELS[scope_key]}** — manage roles:",
            view=ManageRolesView(scope_key),
            ephemeral=True
        )


class AllowedRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ScopeSelect())


# =========================
# View Roles - Pagination (PUBLIC)
# =========================
class ViewRolesPager(discord.ui.View):
    def __init__(self, page_index: int = 0):
        super().__init__(timeout=300)
        self.page_index = page_index

    def _embed(self, guild: discord.Guild) -> discord.Embed:
        settings = load_settings()

        scope_key, scope_title = SCOPES[self.page_index]
        role_ids = _get_scope_role_ids(settings, scope_key)

        embed = discord.Embed(
            title="⚙️ Pilot Role Permissions",
            description=f"**{scope_title}**\n\n{_format_roles(guild, role_ids)}",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Page {self.page_index + 1}/{len(SCOPES)} • Server owner & override role always have access")
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, _):
        self.page_index = (self.page_index - 1) % len(SCOPES)
        await interaction.response.edit_message(embed=self._embed(interaction.guild), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, _):
        self.page_index = (self.page_index + 1) % len(SCOPES)
        await interaction.response.edit_message(embed=self._embed(interaction.guild), view=self)


# =========================
# Welcome/Leave Tabs (Row 0, Blue/Green)
# =========================
class TabButton(discord.ui.Button):
    def __init__(self, label: str, tab: str, active: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary if tab == active else discord.ButtonStyle.success,
            custom_id=f"pilot_tab_{tab}",
            row=0
        )
        self.tab = tab

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=WelcomeLeaveTabbedView(active=self.tab))


class WelcomeLeaveTabbedView(discord.ui.View):
    """
    Tabs are always on row 0.
    Content buttons start on row 1+.
    """
    def __init__(self, active: str = "welcome"):
        super().__init__(timeout=None)
        self.active = active

        # Tabs row
        self.add_item(TabButton("Welcome", "welcome", self.active))
        self.add_item(TabButton("Leave / Logs", "leave", self.active))

        # Build content below tabs with explicit rows
        self._add_content_rows()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_app_access(interaction.user, "welcome_leave"):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return False
        return True

    def _add_content_rows(self):
        # Pull children from existing views, and force their row >= 1
        src_view = WelcomeSettingsView() if self.active == "welcome" else LeaveSettingsView()

        # Copy items and set rows so they don't end up beside tabs
        row = 1
        col = 0
        for item in src_view.children:
            # Only buttons in these views
            if isinstance(item, discord.ui.Button):
                # clone button so we can change row without mutating original view instance
                btn = discord.ui.Button(
                    label=item.label,
                    style=item.style,
                    disabled=item.disabled,
                    emoji=item.emoji,
                    row=row
                )
                btn.callback = item.callback

                self.add_item(btn)

                col += 1
                if col >= 5:
                    col = 0
                    row += 1


# =========================
# Main Admin Panel
# =========================
class PilotSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Allowed Roles", style=discord.ButtonStyle.primary)
    async def allowed_roles(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "⚙️ **Allowed Roles**\nSelect which area you want to manage:",
            view=AllowedRolesView(),
            ephemeral=True
        )

    @discord.ui.button(label="View Roles", style=discord.ButtonStyle.secondary)
    async def view_roles(self, interaction: discord.Interaction, _):
        # PUBLIC + paginated
        pager = ViewRolesPager(page_index=0)
        await interaction.response.send_message(
            embed=pager._embed(interaction.guild),
            view=pager
        )

    @discord.ui.button(label="Welcome / Leave Settings", style=discord.ButtonStyle.secondary)
    async def welcome_leave(self, interaction: discord.Interaction, _):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        # Ack privately (so the click always responds quickly)
        await interaction.response.send_message("Opened Welcome / Leave settings below.", ephemeral=True)

        # Post panel publicly
        await interaction.channel.send(
            "👋 **Welcome / Leave Settings**",
            view=WelcomeLeaveTabbedView(active="welcome")
        )


# =========================
# Slash Command Registration
# =========================
def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Configure Pilot settings")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        await interaction.response.send_message(
            "⚙️ **Pilot Settings**",
            view=PilotSettingsView(),
            ephemeral=True
        )