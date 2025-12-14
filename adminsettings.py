# adminsettings.py
import discord
from discord import app_commands
from discord.ui import View, Button

from permissions import has_global_access, has_app_access
from joinleave import WelcomeLeaveTabbedView


# ======================================================
# MAIN ADMIN PANEL VIEW (PUBLIC)
# ======================================================
class PilotSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(Button(
            label="Allowed Roles",
            style=discord.ButtonStyle.primary,
            custom_id="admin_allowed_roles"
        ))

        self.add_item(Button(
            label="View Roles",
            style=discord.ButtonStyle.secondary,
            custom_id="admin_view_roles"
        ))

        self.add_item(Button(
            label="Welcome / Leave Settings",
            style=discord.ButtonStyle.secondary,
            custom_id="admin_welcome_leave"
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await interaction.response.send_message(
                "❌ You do not have permission to access admin settings.",
                ephemeral=True
            )
            return False
        return True

    # ---------------- Allowed Roles ----------------
    @discord.ui.button(
        custom_id="admin_allowed_roles",
        label="Allowed Roles",
        style=discord.ButtonStyle.primary
    )
    async def allowed_roles(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "🔧 **Allowed Roles panel**\n(Already implemented elsewhere.)"
        )

    # ---------------- View Roles ----------------
    @discord.ui.button(
        custom_id="admin_view_roles",
        label="View Roles",
        style=discord.ButtonStyle.secondary
    )
    async def view_roles(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "👀 **View Roles panel**\n(Already implemented elsewhere.)"
        )

    # ---------------- Welcome / Leave (Tabbed) ----------------
    @discord.ui.button(
        custom_id="admin_welcome_leave",
        label="Welcome / Leave Settings",
        style=discord.ButtonStyle.secondary
    )
    async def welcome_leave(self, interaction: discord.Interaction, _):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await interaction.response.send_message(
                "❌ You do not have permission to manage welcome / leave settings.",
                ephemeral=True
            )

        # Defer to avoid timeout, but keep it PUBLIC
        await interaction.response.defer()

        await interaction.channel.send(
            view=WelcomeLeaveTabbedView()
        )

        await interaction.followup.send(
            "Opened **Welcome / Leave settings**."
        )


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
                "❌ You do not have permission to use this command.",
                ephemeral=True
            )

        # PUBLIC admin panel
        await interaction.response.send_message(
            view=PilotSettingsView()
        )