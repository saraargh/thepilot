import discord
from discord import app_commands
import io

async def setup(tree: app_commands.CommandTree):

    @tree.command(
        name="imagelink",
        description="Upload an image or GIF to get a Discord CDN link"
    )
    async def imagelink(
        interaction: discord.Interaction,
        image: discord.Attachment
    ):
        if image.content_type and not image.content_type.startswith("image"):
            await interaction.response.send_message(
                "❌ Please upload an image or GIF.",
                ephemeral=True
            )
            return

        # Download the uploaded image
        image_bytes = await image.read()

        # Re-upload it to get a REAL (non-ephemeral) CDN attachment
        file = discord.File(
            fp=io.BytesIO(image_bytes),
            filename=image.filename
        )

        await interaction.response.send_message(
            "✅ **please copy the link below for use.**\n"
            "_note: do not delete this message or channel – the image link may no longer be valid if you do so._",
            file=file
        )

        # Get the message we just sent
        msg = await interaction.original_response()

        # Real permanent CDN link
        real_url = msg.attachments[0].url

        # Edit message to include link outside + inside box
        await msg.edit(
            content=(
                "✅ **please copy the link below for use.**\n"
                "_note: do not delete this message or channel – the image link may no longer be valid if you do so._\n\n"
                f"{real_url}\n\n"
                f"```{real_url}```"
            )
        )