# adminsettings.py
import discord
from discord import app_commands
from discord.ui import View

from permissions import has_global_access, has_app_access
from joinleave import WelcomeLeaveTabbedView


# ======================================================
# MAIN ADMIN PANEL VIEW (PUBLIC)
# ======================================================
class PilotSettingsView(View):
    def __init__(self):
        super().__init__(timeout=None)

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
        label="Allowed Roles",
        style=discord.ButtonStyle.primary,
        custom_id="pilot_admin_allowed_roles"
    )
    async def allowed_roles(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "🔧 **Allowed Roles panel**\n(Already implemented elsewhere.)"
        )

    # ---------------- View Roles ----------------
    @discord.ui.button(
        label="View Roles",
        style=discord.ButtonStyle.secondary,
        custom_id="pilot_admin_view_roles"
    )
    async def view_roles(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "👀 **View Roles panel**\n(Already implemented elsewhere.)"
        )

    # ---------------- Welcome / Leave (Tabbed) ----------------
    @discord.ui.button(
        label="Welcome / Leave Settings",
        style=discord.ButtonStyle.secondary,
        custom_id="pilot_admin_welcome_leave"
    )
    async def welcome_leave(self, interaction: discord.Interaction, _):
        if not has_app_access(interaction.user, "welcome_leave"):
            return await interaction.response.send_message(
                "❌ You do not have permission to manage welcome / leave settings.",
                ephemeral=True
            )

        # keep it PUBLIC, just defer to avoid expiry
        await interaction.response.defer()

        await interaction.channel.send(view=WelcomeLeaveTabbedView())

        await interaction.followup.send("Opened **Welcome / Leave settings**.")


# ======================================================
# SLASH COMMAND REGISTRATION
# ======================================================
def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open the Pilot admin control panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You do not have permission to use this command.",
                ephemeral=True
            )

        # PUBLIC panel
        await interaction.response.send_message(view=PilotSettingsView())