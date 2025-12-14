# adminsettings.py
import discord
from discord import app_commands

from permissions import (
    load_settings,
    save_settings,
    has_global_access,
    has_app_access,
)

from joinleave import WelcomeSettingsView, LeaveSettingsView

# ======================================================
# SCOPES
# ======================================================
SCOPES = [
    ("global", "🔐 Global Admin"),
    ("mute", "🔇 Mute"),
    ("warnings", "⚠️ Warnings"),
    ("poo_goat", "💩🐐 Poo / Goat"),
    ("welcome_leave", "👋 Welcome / Leave"),
]

SCOPE_LABELS = dict(SCOPES)

# ======================================================
# HELPERS
# ======================================================
def format_roles(guild: discord.Guild, role_ids: list[int]) -> str:
    if not guild:
        return "*None*"
    out = []
    for rid in role_ids:
        role = guild.get_role(int(rid))
        if role:
            out.append(role.mention)
    return "\n".join(out) if out else "*None*"


def get_scope_roles(settings: dict, scope: str) -> list[int]:
    if scope == "global":
        return list(settings.get("global_allowed_roles", []))
    return list(settings.get("apps", {}).get(scope, {}).get("allowed_roles", []))


def set_scope_roles(settings: dict, scope: str, roles: list[int]):
    if scope == "global":
        settings["global_allowed_roles"] = roles
    else:
        settings.setdefault("apps", {})
        settings["apps"].setdefault(scope, {})
        settings["apps"][scope]["allowed_roles"] = roles


# ======================================================
# ROLE SELECTS
# ======================================================
class AddRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to ADD", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return

        settings = load_settings()
        roles = set(get_scope_roles(settings, self.scope))

        for role in self.values:
            roles.add(role.id)

        set_scope_roles(settings, self.scope, list(roles))
        save_settings(settings)

        await interaction.response.send_message(
            f"✅ Roles added to **{SCOPE_LABELS[self.scope]}**."
        )


class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to REMOVE", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return

        settings = load_settings()
        roles = set(get_scope_roles(settings, self.scope))

        for role in self.values:
            roles.discard(role.id)

        set_scope_roles(settings, self.scope, list(roles))
        save_settings(settings)

        await interaction.response.send_message(
            f"✅ Roles removed from **{SCOPE_LABELS[self.scope]}**."
        )


# ======================================================
# ALLOWED ROLES VIEWS
# ======================================================
class ManageRolesView(discord.ui.View):
    def __init__(self, scope: str):
        super().__init__(timeout=180)
        self.scope = scope

    @discord.ui.button(label="➕ Add Roles", style=discord.ButtonStyle.success)
    async def add_roles(self, interaction: discord.Interaction, _):
        view = discord.ui.View(timeout=180)
        view.add_item(AddRolesSelect(self.scope))
        await interaction.response.send_message(
            f"Select roles to **add** for **{SCOPE_LABELS[self.scope]}**:",
            view=view
        )

    @discord.ui.button(label="➖ Remove Roles", style=discord.ButtonStyle.danger)
    async def remove_roles(self, interaction: discord.Interaction, _):
        view = discord.ui.View(timeout=180)
        view.add_item(RemoveRolesSelect(self.scope))
        await interaction.response.send_message(
            f"Select roles to **remove** for **{SCOPE_LABELS[self.scope]}**:",
            view=view
        )


class ScopeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Which area do you want to manage?",
            options=[discord.SelectOption(label=v, value=k) for k, v in SCOPES],
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"⚙️ **{SCOPE_LABELS[self.values[0]]}** — manage roles:",
            view=ManageRolesView(self.values[0])
        )


class AllowedRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ScopeSelect())


# ======================================================
# VIEW ROLES (PUBLIC, PAGINATED)
# ======================================================
class ViewRolesPager(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.page = 0

    def embed(self, guild: discord.Guild) -> discord.Embed:
        settings = load_settings()
        key, label = SCOPES[self.page]
        embed = discord.Embed(
            title="⚙️ Pilot Role Permissions",
            description=f"**{label}**\n\n{format_roles(guild, get_scope_roles(settings, key))}",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Page {self.page + 1}/{len(SCOPES)}")
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _):
        self.page = (self.page - 1) % len(SCOPES)
        await interaction.response.edit_message(embed=self.embed(interaction.guild), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        self.page = (self.page + 1) % len(SCOPES)
        await interaction.response.edit_message(embed=self.embed(interaction.guild), view=self)


# ======================================================
# WELCOME / LEAVE TABS
# ======================================================
class WelcomeLeaveTabbedView(discord.ui.View):
    def __init__(self, active: str):
        super().__init__(timeout=None)
        self.active = active

        self.add_item(self._tab("Welcome", "welcome"))
        self.add_item(self._tab("Leave / Logs", "leave"))

        content = WelcomeSettingsView() if active == "welcome" else LeaveSettingsView()
        row = 1
        col = 0

        for btn in content.children:
            clone = discord.ui.Button(
                label=btn.label,
                style=btn.style,
                row=row
            )
            clone.callback = btn.callback
            self.add_item(clone)

            col += 1
            if col == 5:
                col = 0
                row += 1

    def _tab(self, label: str, tab: str) -> discord.ui.Button:
        style = discord.ButtonStyle.success if tab == self.active else discord.ButtonStyle.danger
        button = discord.ui.Button(label=label, style=style, row=0)

        async def callback(interaction: discord.Interaction):
            await interaction.response.edit_message(
                view=WelcomeLeaveTabbedView(tab)
            )

        button.callback = callback
        return button

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_app_access(interaction.user, "welcome_leave"):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return False
        return True


# ======================================================
# MAIN ADMIN PANEL
# ======================================================
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
            "⚙️ **Allowed Roles**",
            view=AllowedRolesView()
        )

    @discord.ui.button(label="View Roles", style=discord.ButtonStyle.secondary)
    async def view_roles(self, interaction: discord.Interaction, _):
        pager = ViewRolesPager()
        await interaction.response.send_message(
            embed=pager.embed(interaction.guild),
            view=pager
        )

    @discord.ui.button(label="Welcome / Leave Settings", style=discord.ButtonStyle.secondary)
    async def welcome_leave(self, interaction: discord.Interaction, _):
        if not has_app_access(interaction.user, "welcome_leave"):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return

        await interaction.response.send_message(
            "👋 **Welcome / Leave Settings**",
            view=WelcomeLeaveTabbedView("welcome")
        )


# ======================================================
# SLASH COMMAND
# ======================================================
def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Configure Pilot settings")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return

        await interaction.response.send_message(
            "⚙️ **Pilot Settings**",
            view=PilotSettingsView(),
            ephemeral=False
        )