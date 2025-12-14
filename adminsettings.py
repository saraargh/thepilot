import discord
from discord import app_commands
from permissions import has_global_access

# ======================================================
# MAIN VIEW
# ======================================================

class PilotSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Allowed Roles",
        style=discord.ButtonStyle.primary
    )
    async def allowed_roles(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "⚙️ Allowed Roles panel (hook goes here).",
            ephemeral=False
        )

    @discord.ui.button(
        label="View Roles",
        style=discord.ButtonStyle.secondary
    )
    async def view_roles(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "👀 View Roles panel (pagination later).",
            ephemeral=False
        )

    @discord.ui.button(
        label="Welcome / Leave Settings",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def welcome_leave(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "👋 Welcome / Leave settings panel.",
            ephemeral=False
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await interaction.response.send_message(
                "❌ You do not have permission.",
                ephemeral=True
            )
            return False
        return True


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
                "❌ You do not have permission.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "⚙️ **Pilot Settings**",
            view=PilotSettingsView(),
            ephemeral=False
        )