# adminsettings.py
import discord
from discord import app_commands

from permissions import (
    load_settings,
    save_settings,
    has_global_access,
)

# =========================
# Scopes
# =========================

SCOPES = {
    "global": "Global Admin Roles",
    "mute": "Mute",
    "warnings": "Warnings",
    "poo_goat": "Poo / Goat",
    "welcome_leave": "Welcome / Leave"
}

# =========================
# Helpers
# =========================

def format_roles(guild: discord.Guild, role_ids: list[int]) -> str:
    roles = [
        guild.get_role(rid).mention
        for rid in role_ids
        if guild.get_role(rid)
    ]
    return "\n".join(roles) if roles else "*None*"

# =========================
# Role Selects
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

        if self.scope_key == "global":
            role_set = set(settings.get("global_allowed_roles", []))
        else:
            role_set = set(settings["apps"][self.scope_key]["allowed_roles"])

        for role in self.values:
            role_set.add(role.id)

        if self.scope_key == "global":
            settings["global_allowed_roles"] = list(role_set)
        else:
            settings["apps"][self.scope_key]["allowed_roles"] = list(role_set)

        save_settings(settings)

        await interaction.response.send_message(
            f"✅ Roles added to **{SCOPES[self.scope_key]}**.",
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

        if self.scope_key == "global":
            role_set = set(settings.get("global_allowed_roles", []))
        else:
            role_set = set(settings["apps"][self.scope_key]["allowed_roles"])

        for role in self.values:
            role_set.discard(role.id)

        if self.scope_key == "global":
            settings["global_allowed_roles"] = list(role_set)
        else:
            settings["apps"][self.scope_key]["allowed_roles"] = list(role_set)

        save_settings(settings)

        await interaction.response.send_message(
            f"✅ Roles removed from **{SCOPES[self.scope_key]}**.",
            ephemeral=True
        )

# =========================
# Views
# =========================

class ManageRolesView(discord.ui.View):
    def __init__(self, scope_key: str):
        super().__init__(timeout=180)
        self.scope_key = scope_key

    @discord.ui.button(label="➕ Add Roles", style=discord.ButtonStyle.success)
    async def add_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View()
        view.add_item(AddRolesSelect(self.scope_key))
        await interaction.response.send_message(
            "Select roles to **add**:",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="➖ Remove Roles", style=discord.ButtonStyle.danger)
    async def remove_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View()
        view.add_item(RemoveRolesSelect(self.scope_key))
        await interaction.response.send_message(
            "Select roles to **remove**:",
            view=view,
            ephemeral=True
        )

class ScopeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=key)
            for key, label in SCOPES.items()
        ]

        super().__init__(
            placeholder="Which application would you like to change?",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        scope_key = self.values[0]

        await interaction.response.send_message(
            f"⚙️ **{SCOPES[scope_key]} Settings**",
            view=ManageRolesView(scope_key),
            ephemeral=True
        )

class AllowedRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ScopeSelect())

class PilotSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Allowed Roles", style=discord.ButtonStyle.primary)
    async def allowed_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "⚙️ **Allowed Roles**\nSelect which area you want to manage:",
            view=AllowedRolesView(),
            ephemeral=True
        )

    @discord.ui.button(label="View Roles", style=discord.ButtonStyle.secondary)
    async def view_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = load_settings()
        guild = interaction.guild

        embed = discord.Embed(
            title="⚙️ Pilot Role Permissions",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="🔐 Global Admin",
            value=format_roles(guild, settings.get("global_allowed_roles", [])),
            inline=False
        )

        for key, label in {
            "mute": "🔇 Mute",
            "warnings": "⚠️ Warnings",
            "poo_goat": "💩🐐 Poo / Goat",
            "welcome_leave": "👋 Welcome / Leave"
        }.items():
            embed.add_field(
                name=label,
                value=format_roles(
                    guild,
                    settings["apps"].get(key, {}).get("allowed_roles", [])
                ),
                inline=False
            )

        embed.set_footer(
            text="Server owner & override role always have access"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

# =========================
# Slash Command Registration
# =========================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(
        name="pilotsettings",
        description="Configure Pilot role permissions"
    )
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You don’t have permission to access Pilot settings.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "⚙️ **Pilot Settings**",
            view=PilotSettingsView(),
            ephemeral=True
        )