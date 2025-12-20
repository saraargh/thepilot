# selfroles.py
import json
import os
import discord
from discord import app_commands
from typing import Dict

CONFIG_FILE = "selfroles.json"

# =========================================================
# CONFIG HELPERS
# =========================================================

def load_config() -> Dict:
    if not os.path.exists(CONFIG_FILE):
        raise RuntimeError("selfroles.json missing")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(data: Dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =========================================================
# PERMISSIONS (reuse Pilot roles)
# =========================================================

def has_admin_access(member: discord.Member) -> bool:
    from botslash import ALLOWED_ROLE_IDS
    return any(role.id in ALLOWED_ROLE_IDS for role in member.roles)

# =========================================================
# AUTO ROLES (JOIN HANDLER)
# =========================================================

async def apply_auto_roles(member: discord.Member):
    cfg = load_config()
    role_ids = cfg["auto_roles"]["bots" if member.bot else "humans"]

    for rid in role_ids:
        role = member.guild.get_role(int(rid))
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason="Auto role assignment")
            except discord.Forbidden:
                pass

# =========================================================
# PUBLIC SELF-ROLE MENUS
# =========================================================

class CategorySelect(discord.ui.Select):
    def __init__(self, key: str, data: Dict):
        self.key = key
        self.data = data

        options = [
            discord.SelectOption(
                label=v["label"],
                emoji=v.get("emoji"),
                value=r
            )
            for r, v in data["roles"].items()
        ]

        super().__init__(
            placeholder=data["title"],
            min_values=0,
            max_values=len(options) if data["multi_select"] else 1,
            options=options,
            custom_id=f"selfroles:{key}"
        )

    async def callback(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(interaction.user.id)
        selected = {int(v) for v in self.values}
        role_ids = {int(r) for r in self.data["roles"]}

        added, removed = [], []

        for rid in role_ids:
            role = interaction.guild.get_role(rid)
            if not role:
                continue

            if rid in selected and role not in member.roles:
                await member.add_roles(role)
                added.append(role)

            elif rid not in selected and role in member.roles:
                await member.remove_roles(role)
                removed.append(role)

        # Ephemeral confirmation
        msg = []
        if added:
            msg.append("✅ **Added:** " + ", ".join(r.mention for r in added))
        if removed:
            msg.append("❌ **Removed:** " + ", ".join(r.mention for r in removed))
        if not msg:
            msg.append("ℹ️ No changes made.")

        await interaction.response.send_message("\n".join(msg), ephemeral=True)

        # Optional logging
        cfg = load_config()
        log = cfg["logging"]
        if log["enabled"] and log["channel_id"] and (added or removed):
            channel = interaction.guild.get_channel(int(log["channel_id"]))
            if channel:
                embed = discord.Embed(
                    title="🧩 Self-Role Update",
                    colour=discord.Colour.blurple()
                )
                embed.add_field(name="User", value=interaction.user.mention, inline=False)
                embed.add_field(name="Category", value=self.data["title"], inline=False)
                if added:
                    embed.add_field(name="Added", value=", ".join(r.mention for r in added), inline=False)
                if removed:
                    embed.add_field(name="Removed", value=", ".join(r.mention for r in removed), inline=False)
                await channel.send(embed=embed)

# =========================================================
# VIEW (PERSISTENT)
# =========================================================

class SelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        cfg = load_config()

        for key, cat in cfg["categories"].items():
            if cat.get("roles"):
                self.add_item(CategorySelect(key, cat))

# =========================================================
# DEPLOY PUBLIC MENU
# =========================================================

async def post_selfroles_menu(guild: discord.Guild):
    cfg = load_config()
    channel_id = cfg.get("selfroles_channel_id")

    if not channel_id:
        raise RuntimeError("Self-roles channel not set")

    channel = guild.get_channel(int(channel_id))
    if not channel:
        raise RuntimeError("Configured channel does not exist")

    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Use the menus below to update your roles.\nYou can change these at any time ✈️",
        colour=discord.Colour.blurple()
    )

    await channel.send(embed=embed, view=SelfRoleView())

# =========================================================
# ADMIN SETTINGS UI
# =========================================================

class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select self-roles channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        channel = self.values[0]
        cfg["selfroles_channel_id"] = channel.id
        save_config(cfg)

        await interaction.response.send_message(
            f"📍 Self-roles channel set to {channel.mention}",
            ephemeral=True
        )

class RoleSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Set Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View()
        view.add_item(ChannelSelect())
        await interaction.response.send_message(
            "Select the channel where the self-role menu should live:",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="📌 Post / Update Self-Roles", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await post_selfroles_menu(interaction.guild)
            await interaction.response.send_message(
                "✅ Self-role menu deployed.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Deployment failed:\n`{e}`",
                ephemeral=True
            )

# =========================================================
# COMMAND
# =========================================================

@app_commands.command(name="rolesettings", description="Admin role & self-role settings")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_admin_access(interaction.user):
        await interaction.response.send_message(
            "❌ You do not have permission to use this.",
            ephemeral=True
        )
        return

    cfg = load_config()
    channel = cfg.get("selfroles_channel_id")

    embed = discord.Embed(
        title="⚙️ Role Settings",
        description=(
            "Configure self-roles and deployment.\n\n"
            f"📍 **Self-roles channel:** {f'<#{channel}>' if channel else 'Not set'}"
        ),
        colour=discord.Colour.blurple()
    )

    await interaction.response.send_message(
        embed=embed,
        view=RoleSettingsView(),
        ephemeral=True
    )

# =========================================================
# SETUP
# =========================================================

def setup(tree: app_commands.CommandTree, client: discord.Client):
    tree.add_command(rolesettings)
    client.add_view(SelfRoleView())