# adminsettings.py
import discord
from discord import app_commands

from permissions import load_settings, has_global_access, has_app_access
from joinleave import WelcomeSettingsView, LeaveSettingsView


# ======================================================
# TAB VIEW (WELCOME / LEAVE)
# ======================================================

class WelcomeLeaveTabbedView(discord.ui.View):
    def __init__(self, active: str = "welcome"):
        super().__init__(timeout=None)
        self.active = active

        # --- Tabs row ---
        self.add_item(TabButton("Welcome", "welcome", self.active))
        self.add_item(TabButton("Leave / Logs", "leave", self.active))

        # --- Content rows ---
        if self.active == "welcome":
            for item in WelcomeSettingsView().children:
                self.add_item(item)
        else:
            for item in LeaveSettingsView().children:
                self.add_item(item)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_app_access(interaction.user, "welcome_leave"):
            await interaction.response.send_message(
                "❌ You do not have permission to manage Welcome / Leave settings.",
                ephemeral=True
            )
            return False
        return True


class TabButton(discord.ui.Button):
    def __init__(self, label: str, tab: str, active: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary if tab == active else discord.ButtonStyle.secondary,
            custom_id=f"tab_{tab}"
        )
        self.tab = tab

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            view=WelcomeLeaveTabbedView(active=self.tab)
        )


# ======================================================
# ADMIN PANEL VIEW
# ======================================================

class PilotSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Allowed Roles", style=discord.ButtonStyle.primary)
    async def allowed_roles(self, interaction: discord.Interaction, _):
        # Uses your existing Allowed Roles flow
        from adminsettings_roles import AllowedRolesView  # if you have this split
        await interaction.response.send_message(
            "⚙️ **Allowed Roles**",
            view=AllowedRolesView(),
            ephemeral=True
        )

    @discord.ui.button(label="View Roles", style=discord.ButtonStyle.secondary)
    async def view_roles(self, interaction: discord.Interaction, _):
        settings = load_settings()
        guild = interaction.guild

        embed = discord.Embed(
            title="⚙️ Pilot Role Permissions",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="🔐 Global Admin",
            value=_format_roles(guild, settings.get("global_allowed_roles", [])),
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
                value=_format_roles(
                    guild,
                    settings["apps"].get(key, {}).get("allowed_roles", [])
                ),
                inline=False
            )

        embed.set_footer(text="Server owner & override role always have access")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Welcome / Leave Settings", style=discord.ButtonStyle.secondary)
    async def welcome_leave(self, interaction: discord.Interaction, _):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await interaction.response.send_message(
                "❌ You do not have permission to manage Welcome / Leave settings.",
                ephemeral=True
            )

        # ACK the button
        await interaction.response.send_message(
            "📌 Welcome / Leave settings opened below.",
            ephemeral=True
        )

        # POST PUBLIC PANEL
        await interaction.channel.send(
            "👋 **Welcome / Leave Settings**",
            view=WelcomeLeaveTabbedView()
        )


# ======================================================
# HELPERS
# ======================================================

def _format_roles(guild: discord.Guild, role_ids: list[int]) -> str:
    roles = [
        guild.get_role(rid).mention
        for rid in role_ids
        if guild.get_role(rid)
    ]
    return "\n".join(roles) if roles else "*None*"


# ======================================================
# SLASH COMMAND REGISTRATION
# ======================================================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(
        name="pilotsettings",
        description="Open the Pilot admin control panel"
    )
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You do not have permission to access Pilot settings.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "⚙️ **Pilot Settings**",
            view=PilotSettingsView(),
            ephemeral=True
        )