import discord
from discord import app_commands

async def setup(tree: app_commands.CommandTree):

    @tree.command(
        name="imagelink",
        description="Upload an image or GIF to get a Discord CDN link"
    )
    async def imagelink(
        interaction: discord.Interaction,
        image: discord.Attachment
    ):
        # Optional safety check
        if image.content_type and not image.content_type.startswith("image"):
            await interaction.response.send_message(
                "❌ Please upload an image or GIF.",
                ephemeral=True
            )
            return

        message = (
            "✅ **Please copy the link below for use.**\n\n"
            "⚠️ *Note: Do not delete this message or channel — "
            "the image link may no longer be valid if you do so.*\n\n"
            f"{image.url}"
        )

        await interaction.response.send_message(
            message,
            ephemeral=False
        )