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
        if image.content_type and not image.content_type.startswith("image"):
            await interaction.response.send_message(
                "❌ Please upload an image or GIF.",
                ephemeral=True
            )
            return

        # Download the image
        image_bytes = await image.read()

        # Re-upload it so we get a REAL CDN attachment
        file = discord.File(
            fp=discord.BytesIO(image_bytes),
            filename=image.filename
        )

        await interaction.response.send_message(
            "**Please copy the link below for use.**\n"
            "⚠️⚠️ Do not delete this message or channel – the image link may no longer be valid if you do so.",
            file=file
        )

        # Get the message we just sent
        msg = await interaction.original_response()

        # The real CDN link (non-ephemeral)
        real_url = msg.attachments[0].url

        # Edit message to add links (outside + inside box)
        await msg.edit(
            content=(
                "**Please copy the link below for use.**\n"
                "⚠️⚠️ Do not delete this message or channel – the image link may no longer be valid if you do so.\n\n"
                f"{real_url}\n\n"
                f"```{real_url}```"
            )
        )