import json
import os
import discord
from discord import app_commands

WARNINGS_FILE = 'warnings.json'

# Ensure the warnings file exists
if not os.path.exists(WARNINGS_FILE):
    with open(WARNINGS_FILE, 'w') as f:
        json.dump({}, f, indent=4)

def load_warnings():
    with open(WARNINGS_FILE, 'r') as f:
        return json.load(f)

def save_warnings(warnings):
    with open(WARNINGS_FILE, 'w') as f:
        json.dump(warnings, f, indent=4)

def add_warning(user_id, reason=None):
    warnings = load_warnings()
    if str(user_id) not in warnings:
        warnings[str(user_id)] = []
    warnings[str(user_id)].append(reason if reason else "No reason provided")
    save_warnings(warnings)
    return len(warnings[str(user_id)])

def remove_warning(user_id, index=None):
    warnings = load_warnings()
    user_warnings = warnings.get(str(user_id), [])
    if not user_warnings:
        return False
    if index is None:
        user_warnings.pop()
    else:
        if 0 <= index < len(user_warnings):
            user_warnings.pop(index)
        else:
            return False
    if user_warnings:
        warnings[str(user_id)] = user_warnings
    else:
        del warnings[str(user_id)]
    save_warnings(warnings)
    return True

def get_warnings(user_id):
    warnings = load_warnings()
    return warnings.get(str(user_id), [])

def clear_warnings(user_id):
    warnings = load_warnings()
    if str(user_id) in warnings:
        del warnings[str(user_id)]
        save_warnings(warnings)
        return True
    return False

def get_all_warnings():
    return load_warnings()


# ------------------ Setup Function ------------------ #
def setup_warnings_commands(tree: app_commands.CommandTree, allowed_role_ids=None):
    ALLOWED_ROLES_IDS = allowed_role_ids or []
    PASSENGERS_ROLE_ID = 1404100554807971971
    WILLIAM_ROLE_ID = 1413545658006110401
    SAZZLES_ROLE_ID = 1404104881098195015

    def can_warn(interaction: discord.Interaction, target_member: discord.Member):
        if any(role.id == SAZZLES_ROLE_ID for role in target_member.roles):
            return False
        author_role_ids = [role.id for role in interaction.user.roles]
        target_role_ids = [role.id for role in target_member.roles]

        if any(role_id in ALLOWED_ROLES_IDS for role_id in author_role_ids):
            return True
        if PASSENGERS_ROLE_ID in author_role_ids and WILLIAM_ROLE_ID in target_role_ids:
            return True
        return False

    @tree.command(name="warn", description="Warn a user")
    @app_commands.describe(member="Member to warn", reason="Reason for warning (optional)")
    async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = None):
        if any(role.id == SAZZLES_ROLE_ID for role in member.roles):
            await interaction.response.send_message(
                "⚠️ You cannot warn this user as she is the best and made this so you could all warn William 🖤"
            )
            return

        if not can_warn(interaction, member):
            await interaction.response.send_message(
                f"❌ You do not have permission to warn {member.mention}.", ephemeral=True
            )
            return

        count = add_warning(member.id, reason)
        msg = f"⚠️ {member.mention} was warned"
        if reason:
            msg += f" for {reason}"
        msg += f", this is their {count}{'st' if count==1 else 'nd' if count==2 else 'rd' if count==3 else 'th'} warning."
        await interaction.response.send_message(msg)

    @tree.command(name="warnings_list", description="List warnings for a user")
    @app_commands.describe(member="Member to see warnings for")
    async def warnings_list(interaction: discord.Interaction, member: discord.Member):
        user_warnings = get_warnings(member.id)
        if not user_warnings:
            await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)
        else:
            msg = "\n".join([f"{i+1}. {w}" for i, w in enumerate(user_warnings)])
            await interaction.response.send_message(f"{member.mention} warnings:\n{msg}", ephemeral=True)

    @tree.command(name="server_warnings", description="List all warnings on the server")
    async def server_warnings(interaction: discord.Interaction):
        all_warnings = get_all_warnings()
        if not all_warnings:
            await interaction.response.send_message("No warnings on this server.", ephemeral=True)
            return

        msg_list = []
        for user_id, warns in all_warnings.items():
            user = interaction.guild.get_member(int(user_id))
            if user:
                warns_text = ", ".join(warns)
                msg_list.append(f"{user.display_name}: {warns_text}")
        await interaction.response.send_message("\n".join(msg_list) if msg_list else "No warnings found.", ephemeral=True)

    @tree.command(name="remove_warn", description="Remove a warning from a user")
    @app_commands.describe(member="Member to remove warning from", index="Index of warning to remove (optional)")
    async def remove_warn(interaction: discord.Interaction, member: discord.Member, index: int = None):
        success = remove_warning(member.id, index-1 if index else None)
        if success:
            await interaction.response.send_message(f"✅ Warning removed from {member.mention}.")
        else:
            await interaction.response.send_message(f"❌ Could not remove warning from {member.mention}.")

    @tree.command(name="clear_warns", description="Clear all warnings for a user")
    @app_commands.describe(member="Member to clear warnings for")
    async def clear_warns(interaction: discord.Interaction, member: discord.Member):
        success = clear_warnings(member.id)
        if success:
            await interaction.response.send_message(f"✅ All warnings cleared for {member.mention}.")
        else:
            await interaction.response.send_message(f"{member.mention} has no warnings to clear.")