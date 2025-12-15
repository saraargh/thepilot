import discord
from discord import app_commands

async def setup(tree: app_commands.CommandTree):

    @tree.command(
        name="imagelink",
        description="Get the direct CDN link for an image"
    )
    async def imagelink(
        interaction: discord.Interaction,
        image: discord.Attachment
    ):
        # Validate image
        if image.content_type and not image.content_type.startswith("image"):
            await interaction.response.send_message(
                "❌ Please select an image or GIF.",
                ephemeral=True
            )
            return

        url = image.url

        # SEND TEXT ONLY — THIS IS THE KEY
        await interaction.response.send_message(
            content=(
                "✅ **please copy the link below for use.**\n"
                "_note: do not delete this message or channel – "
                "the image link may no longer be valid if you do so._\n\n"
                f"{url}\n\n"
                f"```{url}```"
            ),
            ephemeral=False
        )