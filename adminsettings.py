# adminsettings.py
import discord
from discord import app_commands
from permissions import has_global_access
from joinleave import WelcomeActionSelect, LeaveActionSelect

# ======================================================
# ROOT VIEW
# ======================================================

class PilotSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(SectionSelect())


class SectionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a settings section",
            options=[
                discord.SelectOption(label="Welcome Settings", value="welcome", emoji="👋"),
                discord.SelectOption(label="Leave / Log Settings", value="leave", emoji="📄"),
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You do not have permission.",
                ephemeral=True
            )

        section = self.values[0]

        view = discord.ui.View(timeout=180)
        if section == "welcome":
            view.add_item(WelcomeActionSelect())
            await interaction.response.send_message(
                "👋 **Welcome Settings**",
                view=view
            )
        else:
            view.add_item(LeaveActionSelect())
            await interaction.response.send_message(
                "📄 **Leave / Log Settings**",
                view=view
            )


# ======================================================
# SLASH COMMAND
# ======================================================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(
        name="pilotsettings",
        description="Open the Pilot admin settings panel"
    )
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You do not have permission.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "⚙️ **Pilot Settings**",
            view=PilotSettingsView()
        )