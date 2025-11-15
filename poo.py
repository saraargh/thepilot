# poo.py
import discord
from discord import app_commands
from discord.ext import tasks
import datetime
import pytz

UK_TZ = pytz.timezone("Europe/London")
POO_ROLE_ID = 1421926940873752598  # your role ID

# -------- Daily Scheduled Task --------

async def daily_poo_run(client, allowed_role_ids):
    now = datetime.datetime.now(UK_TZ)
    hour = now.hour
    minute = now.minute

    # RUN AT 14:30 (2:30 PM UK)
    if hour == 14 and minute == 30:
        for guild in client.guilds:
            role = guild.get_role(POO_ROLE_ID)
            if not role:
                continue

            members = [m for m in guild.members if not m.bot]
            if not members:
                continue

            import random
            target = random.choice(members)
            await target.add_roles(role, reason="Daily poo assignment")
            print(f"[Daily Poo] Assigned to {target} in {guild.name}")

# -------- Commands --------

def setup_poo_commands(tree: app_commands.CommandTree, client: discord.Client, allowed_role_ids):

    @tree.command(name="assignpoo", description="Assign the poo role to a member")
    @app_commands.describe(member="The member to give poo")
    async def assignpoo(interaction, member: discord.Member):
        if not any(r.id in allowed_role_ids for r in interaction.user.roles):
            return await interaction.response.send_message("You can't use this.", ephemeral=True)

        role = interaction.guild.get_role(POO_ROLE_ID)
        await member.add_roles(role)
        await interaction.response.send_message(f"{member.mention} now has the poo role 💩")

    @tree.command(name="removepoo", description="Remove the poo role from a member")
    @app_commands.describe(member="Member to remove poo from")
    async def removepoo(interaction, member: discord.Member):
        if not any(r.id in allowed_role_ids for r in interaction.user.roles):
            return await interaction.response.send_message("You can't use this.", ephemeral=True)

        role = interaction.guild.get_role(POO_ROLE_ID)
        await member.remove_roles(role)
        await interaction.response.send_message(f"Poo removed from {member.mention} 💨")

    return client  # just for consistency