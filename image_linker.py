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

        # ACK the interaction silently (THIS IS CRITICAL)
        await interaction.response.defer()

        # Download the image
        data = await image.read()

        # Upload ONCE
        file = discord.File(
            fp=io.BytesIO(data),
            filename=image.filename
        )

        # Send ONE clean message (no edits)
        msg = await interaction.followup.send(
            content=(
                "✅ **please copy the link below for use.**\n"
                "_note: do not delete this message or channel – "
                "the image link may no longer be valid if you do so._\n\n"
                "{link}\n\n"
                "```{link}```"
            ),
            file=file,
            wait=True
        )

        # Get the real CDN link
        real_url = msg.attachments[0].url

        # Replace placeholder text ONCE (safe edit, no attachment change)
        await msg.edit(
            content=(
                "✅ **please copy the link below for use.**\n"
                "_note: do not delete this message or channel – "
                "the image link may no longer be valid if you do so._\n\n"
                f"{real_url}\n\n"
                f"```{real_url}```"
            )
        )