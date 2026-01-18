# goat.py
import discord
from discord import app_commands
import random
import datetime
import pytz
from discord.ext import tasks

from permissions import has_app_access

# ===== CONFIG =====
UK_TZ = pytz.timezone("Europe/London")

GOAT_ROLE_ID = 1448995127636000788
POO_ROLE_ID = 1429934009550373059
PASSENGERS_ROLE_ID = 1404104881098195015
GENERAL_CHANNEL_ID = 1398508734506078240


# ===== Helpers =====
async def clear_goat_role(guild: discord.Guild):
    goat_role = guild.get_role(GOAT_ROLE_ID)
    if not goat_role:
        return

    for member in goat_role.members:
        await member.remove_roles(goat_role)


async def assign_random_goat(guild: discord.Guild):
    goat_role = guild.get_role(GOAT_ROLE_ID)
    poo_role = guild.get_role(POO_ROLE_ID)
    passengers_role = guild.get_role(PASSENGERS_ROLE_ID)
    general_channel = guild.get_channel(GENERAL_CHANNEL_ID)

    if not all([goat_role, poo_role, passengers_role, general_channel]):
        return

    eligible = [
        m for m in passengers_role.members
        if poo_role not in m.roles
    ]

    if not eligible:
        await general_channel.send("No passengers available to assign goat!")
        return

    chosen = random.choice(eligible)
    await chosen.add_roles(goat_role)
    await general_channel.send(f"🎉 {chosen.mention} is today’s goat!")


async def test_goat(guild: discord.Guild):
    await assign_random_goat(guild)


# ============================================================
#  SETUP COMMANDS + RETURN DAILY TASK
# ============================================================
def setup_goat_commands(tree: app_commands.CommandTree, client: discord.Client):

    @tasks.loop(minutes=1)
    async def daily_goat_task():
        now = datetime.datetime.now(UK_TZ)
        guild = client.guilds[0] if client.guilds else None
        if not guild:
            return

        # 🕚 11am — clear ALL goats (daily reset)
        if now.hour == 11 and now.minute == 0:
            await clear_goat_role(guild)

        # 🕐 13:00 — ADD a goat (do NOT clear)
        if now.hour == 13 and now.minute == 0:
            await assign_random_goat(guild)

    @daily_goat_task.before_loop
    async def before_goat():
        await client.wait_until_ready()

    # ===== Slash Commands =====
    @tree.command(name="cleargoat", description="Clear the goat role from everyone")
    async def cleargoat(interaction: discord.Interaction):
        if not has_app_access(interaction.user, "poo_goat"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        await interaction.response.defer()
        await clear_goat_role(interaction.guild)
        await interaction.followup.send("✅ Cleared goat role from everyone.")

    @tree.command(name="assigngoat", description="Manually assign the goat role to a member")
    async def assigngoat(interaction: discord.Interaction, member: discord.Member):
        if not has_app_access(interaction.user, "poo_goat"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        await interaction.response.defer()
        role = interaction.guild.get_role(GOAT_ROLE_ID)
        if role:
            await member.add_roles(role)

        await interaction.followup.send(f"🎉 {member.mention} has been assigned the goat role.")

    @tree.command(name="removegoat", description="Remove the goat role from a member")
    async def removegoat(interaction: discord.Interaction, member: discord.Member):
        if not has_app_access(interaction.user, "poo_goat"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        await interaction.response.defer()
        role = interaction.guild.get_role(GOAT_ROLE_ID)
        if role:
            await member.remove_roles(role)

        await interaction.followup.send(f"❌ {member.mention} has had the goat role removed.")

    @tree.command(name="testgoat", description="Test the goat automation")
    async def testgoat_command(interaction: discord.Interaction):
        if not has_app_access(interaction.user, "poo_goat"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        await interaction.response.defer()
        await test_goat(interaction.guild)
        await interaction.followup.send("🧪 Test goat completed!")

    return daily_goat_task