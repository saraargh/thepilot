from __future__ import annotations

import json
import os
from typing import Dict, Any, List, Optional, Tuple

import discord
from discord import app_commands

from permissions import has_app_access

# =========================================================
# CONFIG
# =========================================================

CONFIG_FILE = "selfroles.json"

# =========================================================
# JSON HELPERS (HOT RELOAD – NO REDEPLOY NEEDED)
# =========================================================

def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        return {
            "selfroles_channel_id": None,
            "selfroles_message_id": None,
            "logging": {"enabled": False, "channel_id": None},
            "auto_roles": {"humans": [], "bots": []},
            "categories": {},
        }
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# =========================================================
# UTIL
# =========================================================

def get_bot_member(guild: discord.Guild) -> Optional[discord.Member]:
    return guild.me or guild.get_member(guild.client.user.id)


def can_manage_role(role: discord.Role, bot: discord.Member) -> bool:
    if role.is_default():
        return False
    if role.managed:
        return False
    if role.permissions.administrator:
        return False
    if role >= bot.top_role:
        return False
    return True


def parse_emoji(raw: Optional[str]) -> Optional[discord.PartialEmoji]:
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except Exception:
        return None


# =========================================================
# PUBLIC SELF-ROLE FLOW (USERS)
# =========================================================

class RolePicker(discord.ui.Select):
    def __init__(self, category_key: str, category: Dict[str, Any]):
        self.category_key = category_key
        self.category = category

        options: List[discord.SelectOption] = []

        for rid, meta in category.get("roles", {}).items():
            options.append(
                discord.SelectOption(
                    label=meta.get("label", "Role")[:100],
                    value=rid,
                    emoji=parse_emoji(meta.get("emoji")),
                )
            )

        multi = bool(category.get("multi_select", True))

        super().__init__(
            placeholder="Pick your roles…",
            min_values=0,
            max_values=len(options) if multi else 1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return

        cfg = load_config()
        cat = cfg["categories"].get(self.category_key)
        if not cat:
            return await interaction.response.send_message(
                "❌ That category no longer exists.",
                ephemeral=True,
            )

        bot = get_bot_member(interaction.guild)
        if not bot:
            return

        valid_role_ids = {int(rid) for rid in cat.get("roles", {}).keys()}
        selected = {int(v) for v in self.values}

        added, removed = [], []

        for rid in valid_role_ids:
            role = interaction.guild.get_role(rid)
            if not role or not can_manage_role(role, bot):
                continue

            if rid in selected and role not in member.roles:
                await member.add_roles(role, reason="Self-role menu")
                added.append(role)

            if rid not in selected and role in member.roles:
                await member.remove_roles(role, reason="Self-role menu")
                removed.append(role)

        lines = ["✨ **Your roles have been updated**"]
        if added:
            lines.append("✅ Added: " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("❌ Removed: " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("ℹ️ No changes made.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


class CategoryButton(discord.ui.Button):
    def __init__(self, key: str, cat: Dict[str, Any]):
        super().__init__(
            label=cat.get("title", key)[:80],
            emoji=parse_emoji(cat.get("emoji")),
            style=discord.ButtonStyle.secondary,
        )
        self.key = key
        self.cat = cat

    async def callback(self, interaction: discord.Interaction):
        picker = RolePicker(self.key, self.cat)
        view = discord.ui.View(timeout=180)
        view.add_item(picker)

        await interaction.response.send_message(
            f"**{self.cat.get('title', self.key)}**\nSelect your roles:",
            view=view,
            ephemeral=True,
        )


class PublicSelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        cfg = load_config()

        for key, cat in cfg.get("categories", {}).items():
            if cat.get("roles"):
                self.add_item(CategoryButton(key, cat))


async def build_public_message() -> Tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Pick a category, then pick your roles.\nYou can change these any time ✈️",
        colour=discord.Colour.blurple(),
    )
    return embed, PublicSelfRoleView()


async def deploy_public_menu(guild: discord.Guild) -> Tuple[bool, str]:
    cfg = load_config()
    cid = cfg.get("selfroles_channel_id")
    if not cid:
        return False, "Self-roles channel not set."

    channel = guild.get_channel(int(cid))
    if not isinstance(channel, discord.TextChannel):
        return False, "Configured channel is invalid."

    embed, view = await build_public_message()

    msg_id = cfg.get("selfroles_message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            return True, "Updated existing self-role menu."
        except Exception:
            pass

    msg = await channel.send(embed=embed, view=view)
    cfg["selfroles_message_id"] = msg.id
    save_config(cfg)
    return True, "Posted new self-role menu."


# =========================================================
# AUTO ROLES (JOIN)
# =========================================================

async def apply_auto_roles(member: discord.Member):
    cfg = load_config()
    bot = get_bot_member(member.guild)
    if not bot:
        return

    target = "bots" if member.bot else "humans"
    for rid in cfg.get("auto_roles", {}).get(target, []):
        role = member.guild.get_role(int(rid))
        if role and can_manage_role(role, bot):
            await member.add_roles(role, reason="Auto-role")


# =========================================================
# SLASH COMMAND ENTRY (ADMIN)
# =========================================================

@app_commands.command(name="rolesettings", description="Manage self roles")
async def rolesettings(interaction: discord.Interaction):
    if not has_app_access(interaction.user, "roles"):
        return await interaction.response.send_message(
            "❌ You do not have permission to manage role settings.",
            ephemeral=True,
        )

    cfg = load_config()

    desc = [
        f"📍 Channel: {f'<#{cfg.get('selfroles_channel_id')}>' if cfg.get('selfroles_channel_id') else 'Not set'}",
        f"📌 Menu posted: {'Yes' if cfg.get('selfroles_message_id') else 'No'}",
        f"🧾 Logging: {'ON' if cfg.get('logging', {}).get('enabled') else 'OFF'}",
    ]

    embed = discord.Embed(
        title="⚙️ Role Settings",
        description="\n".join(desc),
        colour=discord.Colour.blurple(),
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)