# adminsettings.py
import discord
from discord import app_commands
from discord.ui import View, Button

from permissions import (
    has_global_access,
    has_app_access,
)

from joinleave import WelcomeSettingsView, LeaveSettingsView


# ======================================================
# MAIN ADMIN PANEL
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
            label="Welcome Settings",
            style=discord.ButtonStyle.secondary,
            custom_id="admin_welcome_settings"
        ))

        self.add_item(Button(
            label="Leave / Kick / Ban Settings",
            style=discord.ButtonStyle.secondary,
            custom_id="admin_leave_settings"
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await interaction.response.send_message(
                "❌ You do not have permission to access admin settings.",
                ephemeral=True
            )
            return False
        return True


# ======================================================
# BUTTON HANDLERS
# ======================================================
class PilotSettingsHandler(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(custom_id="admin_allowed_roles", label="Allowed Roles")
    async def allowed_roles(self, interaction: discord.Interaction, _):
        # existing allowed roles logic lives here
        await interaction.response.send_message(
            "Allowed Roles panel already exists.",
            ephemeral=True
        )

    @discord.ui.button(custom_id="admin_view_roles", label="View Roles")
    async def view_roles(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "View Roles panel already exists.",
            ephemeral=True
        )

    @discord.ui.button(custom_id="admin_welcome_settings", label="Welcome Settings")
    async def welcome_settings(self, interaction: discord.Interaction, _):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await interaction.response.send_message(
                "❌ You do not have permission to manage welcome settings.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        await interaction.channel.send(view=WelcomeSettingsView())

        await interaction.followup.send(
            "Opened Welcome settings.",
            ephemeral=True
        )

    @discord.ui.button(custom_id="admin_leave_settings", label="Leave / Kick / Ban Settings")
    async def leave_settings(self, interaction: discord.Interaction, _):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await interaction.response.send_message(
                "❌ You do not have permission to manage leave settings.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        await interaction.channel.send(view=LeaveSettingsView())

        await interaction.followup.send(
            "Opened Leave settings.",
            ephemeral=True
        )


# ======================================================
# SLASH COMMAND
# ======================================================
def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open the Pilot admin control panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You do not have permission to use this command.",
                ephemeral=True
            )

        await interaction.response.send_message(
            view=PilotSettingsView(),
            ephemeral=True
        )