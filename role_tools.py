# role_tools.py
import discord
from discord import app_commands

from permissions import has_global_access


def setup(tree: app_commands.CommandTree):

    # =====================================================
    # /rolepull
    # =====================================================
    @tree.command(
        name="rolepull",
        description="List all server roles with their IDs"
    )
    async def rolepull(interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You do not have permission to use this.",
                ephemeral=True
            )

        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message(
                "❌ Guild not found.",
                ephemeral=True
            )

        roles = sorted(
            [r for r in guild.roles if not r.is_default()],
            key=lambda r: r.position,
            reverse=True
        )

        if not roles:
            return await interaction.response.send_message(
                "ℹ️ No roles found.",
                ephemeral=True
            )

        lines = [
            f"{role.mention} — `{role.name}` — `{role.id}`"
            for role in roles
        ]

        chunks, current = [], ""
        for line in lines:
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current:
            chunks.append(current)

        await interaction.response.send_message(
            f"📋 **Server Roles ({len(roles)})**\n\n{chunks[0]}",
            ephemeral=True
        )

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

    # =====================================================
    # /emojipull
    # =====================================================
    @tree.command(
        name="emojipull",
        description="List all custom server emojis with their IDs"
    )
    async def emojipull(interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You do not have permission to use this.",
                ephemeral=True
            )

        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message(
                "❌ Guild not found.",
                ephemeral=True
            )

        emojis = guild.emojis
        if not emojis:
            return await interaction.response.send_message(
                "ℹ️ No custom emojis in this server.",
                ephemeral=True
            )

        lines = []
        for e in emojis:
            tag = f"<a:{e.name}:{e.id}>" if e.animated else f"<:{e.name}:{e.id}>"
            lines.append(
                f"{tag} — `{e.name}` — `{e.id}` — {'animated' if e.animated else 'static'}"
            )

        chunks, current = [], ""
        for line in lines:
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current:
            chunks.append(current)

        await interaction.response.send_message(
            f"😀 **Server Emojis ({len(emojis)})**\n\n{chunks[0]}",
            ephemeral=True
        )

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)
