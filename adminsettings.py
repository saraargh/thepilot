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

SCOPE_LABELS = {k: v for k, v in SCOPES}


# ======================================================
# HELPERS
# ======================================================
def format_roles(guild: discord.Guild, role_ids: list[int]) -> str:
    roles = []
    for rid in role_ids:
        role = guild.get_role(int(rid))
        if role:
            roles.append(role.mention)
    return "\n".join(roles) if roles else "*None*"


def get_scope_roles(settings: dict, scope: str) -> list[int]:
    if scope == "global":
        return list(settings.get("global_allowed_roles", []))
    return list(settings["apps"].get(scope, {}).get("allowed_roles", []))


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
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        settings = load_settings()
        role_set = set(get_scope_roles(settings, self.scope))

        for role in self.values:
            role_set.add(role.id)

        set_scope_roles(settings, self.scope, list(role_set))
        save_settings(settings)

        await interaction.response.send_message(
            f"✅ Added roles to **{SCOPE_LABELS[self.scope]}**."
        )


class RemoveRolesSelect(discord.ui.RoleSelect):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(placeholder="Select roles to REMOVE", min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        settings = load_settings()
        role_set = set(get_scope_roles(settings, self.scope))

        for role in self.values:
            role_set.discard(role.id)

        set_scope_roles(settings, self.scope, list(role_set))
        save_settings(settings)

        await interaction.response.send_message(
            f"✅ Removed roles from **{SCOPE_LABELS[self.scope]}**."
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
        v = discord.ui.View(timeout=180)
        v.add_item(AddRolesSelect(self.scope))
        await interaction.response.send_message(
            f"Select roles to **add** for **{SCOPE_LABELS[self.scope]}**:",
            view=v
        )

    @discord.ui.button(label="➖ Remove Roles", style=discord.ButtonStyle.danger)
    async def remove_roles(self, interaction: discord.Interaction, _):
        v = discord.ui.View(timeout=180)
        v.add_item(RemoveRolesSelect(self.scope))
        await interaction.response.send_message(
            f"Select roles to **remove** for **{SCOPE_LABELS[self.scope]}**:",
            view=v
        )


class ScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=key) for key, label in SCOPES]
        super().__init__(
            placeholder="Which area do you want to manage?",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        scope = self.values[0]
        await interaction.response.send_message(
            f"⚙️ **{SCOPE_LABELS[scope]}** — manage roles:",
            view=ManageRolesView(scope)
        )


class AllowedRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ScopeSelect())


# ======================================================
# VIEW ROLES (PUBLIC + PAGINATED)
# ======================================================
class ViewRolesPager(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=300)
        self.page = page

    def embed(self, guild: discord.Guild) -> discord.Embed:
        settings = load_settings()
        scope, label = SCOPES[self.page]

        embed = discord.Embed(
            title="⚙️ Pilot Role Permissions",
            description=f"**{label}**\n\n{format_roles(guild, get_scope_roles(settings, scope))}",
            color=discord.Color.blurple(),
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
# WELCOME / LEAVE TABBED VIEW
# ======================================================
class TabButton(discord.ui.Button):
    def __init__(self, label: str, tab: str, active: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.success if tab == active else discord.ButtonStyle.danger,
            row=0,
        )
        self.tab = tab

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            view=WelcomeLeaveTabbedView(active=self.tab)
        )


class WelcomeLeaveTabbedView(discord.ui.View):
    def __init__(self, active: str = "welcome"):
        super().__init__(timeout=None)
        self.active = active

        # Tabs
        self.add_item(TabButton("Welcome", "welcome", self.active))
        self.add_item(TabButton("Leave / Logs", "leave", self.active))

        # Content
        src = WelcomeSettingsView() if self.active == "welcome" else LeaveSettingsView()
        row = 1
        col = 0

        for item in src.children:
            btn = discord.ui.Button(
                label=item.label,
                style=item.style,
                row=row,
            )
            btn.callback = item.callback
            self.add_item(btn)

            col += 1
            if col == 5:
                col = 0
                row += 1

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