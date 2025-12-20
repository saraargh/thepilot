from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands

from permissions import has_app_access

CONFIG_FILE = "selfroles.json"

# =========================================================
# Config helpers
# =========================================================

def _load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        raise RuntimeError("selfroles.json missing")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _get_guild_me(guild: discord.Guild) -> Optional[discord.Member]:
    return guild.me or guild.get_member(guild.client.user.id) if guild.client.user else None


# =========================================================
# Permissions / safety
# =========================================================

def _is_role_assignable(role: discord.Role, bot_member: discord.Member) -> bool:
    if role.is_default():  # @everyone
        return False
    if role.managed:  # integration/bot roles
        return False
    if role.permissions.administrator:  # admin permission roles blocked
        return False
    if role >= bot_member.top_role:  # above bot (or equal)
        return False
    return True


def _parse_emoji(s: str) -> Optional[discord.PartialEmoji]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return discord.PartialEmoji.from_str(s)
    except Exception:
        return None


# =========================================================
# Auto roles (humans vs bots)
# =========================================================

async def apply_auto_roles(member: discord.Member) -> None:
    try:
        cfg = _load_config()
    except Exception:
        return

    auto = cfg.get("auto_roles", {})
    role_ids = auto.get("bots" if member.bot else "humans", [])

    me = _get_guild_me(member.guild)
    if not me:
        return

    for rid in role_ids:
        try:
            rid_int = int(rid)
        except Exception:
            continue
        role = member.guild.get_role(rid_int)
        if not role or role in member.roles:
            continue
        if not _is_role_assignable(role, me):
            continue
        try:
            await member.add_roles(role, reason="Auto role assignment")
        except Exception:
            pass


# =========================================================
# Public self-role view
# =========================================================

class CategorySelect(discord.ui.Select):
    def __init__(self, category_key: str, category_data: Dict[str, Any]):
        self.category_key = category_key
        self.category_data = category_data

        options: List[discord.SelectOption] = []
        roles: Dict[str, Any] = category_data.get("roles", {}) or {}

        for role_id_str, meta in roles.items():
            options.append(
                discord.SelectOption(
                    label=str(meta.get("label") or "Role")[:100],
                    emoji=_parse_emoji(meta.get("emoji")),
                    value=str(role_id_str),
                    description=(str(meta.get("description"))[:100] if meta.get("description") else None),
                )
            )

        multi = bool(category_data.get("multi_select", True))
        max_values = len(options) if multi else 1

        super().__init__(
            placeholder=str(category_data.get("title") or category_key)[:150],
            min_values=0,
            max_values=max_values if max_values > 0 else 1,
            options=options[:25],
            custom_id=f"selfroles:cat:{category_key}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return await interaction.response.send_message("⚠️ Member not found.", ephemeral=True)

        cfg = _load_config()
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("⚠️ Category missing.", ephemeral=True)

        roles_cfg = cat.get("roles", {}) or {}
        role_ids = {int(r) for r in roles_cfg if str(r).isdigit()}
        selected = {int(v) for v in self.values if str(v).isdigit()}

        me = _get_guild_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("⚠️ Bot member missing.", ephemeral=True)

        added, removed = [], []

        for rid in role_ids:
            role = interaction.guild.get_role(rid)
            if not role or not _is_role_assignable(role, me):
                continue

            if rid in selected and role not in member.roles:
                await member.add_roles(role, reason="Self-role menu")
                added.append(role)
            elif rid not in selected and role in member.roles:
                await member.remove_roles(role, reason="Self-role menu")
                removed.append(role)

        lines = ["✨ **Your roles have been updated.**"]
        if added:
            lines.append("✅ **Added:** " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("❌ **Removed:** " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("ℹ️ No changes made.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        log = cfg.get("logging", {}) or {}
        if log.get("enabled") and log.get("channel_id") and (added or removed):
            chan = interaction.guild.get_channel(int(log["channel_id"]))
            if isinstance(chan, discord.TextChannel):
                embed = discord.Embed(title="🧩 Self-Role Update", colour=discord.Colour.blurple())
                embed.add_field(name="User", value=interaction.user.mention, inline=False)
                embed.add_field(name="Category", value=str(cat.get("title") or self.category_key), inline=False)
                if added:
                    embed.add_field(name="Added", value=", ".join(r.mention for r in added), inline=False)
                if removed:
                    embed.add_field(name="Removed", value=", ".join(r.mention for r in removed), inline=False)
                await chan.send(embed=embed)


class SelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        cfg = _load_config()
        for key, cat in (cfg.get("categories", {}) or {}).items():
            if cat.get("roles"):
                self.add_item(CategorySelect(key, cat))


# =========================================================
# Deployment helpers
# =========================================================

async def _deploy_or_update_selfroles_menu(guild: discord.Guild) -> Tuple[bool, str]:
    cfg = _load_config()
    channel_id = cfg.get("selfroles_channel_id")
    if not channel_id:
        return False, "Self-roles channel not set."

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False, "Configured channel is missing or invalid."

    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Use the menus below to update your roles.\nYou can change these at any time ✈️",
        colour=discord.Colour.blurple(),
    )

    view = SelfRoleView()

    try:
        msg_id = cfg.get("selfroles_message_id")
        if msg_id:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            return True, "✅ Updated existing self-role menu."
    except Exception:
        pass

    sent = await channel.send(embed=embed, view=view)
    cfg["selfroles_message_id"] = sent.id
    _save_config(cfg)
    return True, "✅ Posted new self-role menu."


# =========================================================
# /rolesettings
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_app_access(interaction.user, "roles"):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📌 Post / Update Public Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        ok, msg = await _deploy_or_update_selfroles_menu(interaction.guild)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=True)


@app_commands.command(name="rolesettings", description="Admin panel for roles & self-roles")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_app_access(interaction.user, "roles"):
        return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

    cfg = _load_config()
    embed = discord.Embed(
        title="⚙️ Role Settings",
        description=f"📍 Channel: {f'<#{cfg.get('selfroles_channel_id')}>' if cfg.get('selfroles_channel_id') else 'Not set'}",
        colour=discord.Colour.blurple(),
    )

    await interaction.response.send_message(embed=embed, view=RoleSettingsDashboard(), ephemeral=True)


# =========================================================
# Setup
# =========================================================

def setup(tree: app_commands.CommandTree, client: discord.Client):
    tree.add_command(rolesettings)
    try:
        client.add_view(SelfRoleView())
    except Exception:
        pass