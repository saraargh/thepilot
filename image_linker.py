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

        embed = discord.Embed(
            title="🖼️ Image link ready",
            description=(
                "Copy the link below for use.\n\n"
                "⚠️*Do not delete this message or channel — "
                "the image link may stop working if you do so.*"
            ),
            color=0x5865F2  # Discord blurple
        )

        embed.add_field(
            name="🔗 Direct CDN Link",
            value=f"```{image.url}```",
            inline=False
        )

        embed.set_footer(text="Powered by The Pilot ✈️")

        await interaction.response.send_message(
            embed=embed,
            ephemeral=False
        )