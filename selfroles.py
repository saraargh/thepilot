from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands

from permissions import has_app_access

CONFIG_FILE = "selfroles.json"


# ======================================================
# JSON helpers
# ======================================================

def _load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        raise RuntimeError("selfroles.json missing")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _guild_me(guild: discord.Guild) -> Optional[discord.Member]:
    return guild.me or guild.get_member(guild.client.user.id) if guild.client.user else None


# ======================================================
# Guardrails
# ======================================================

def _role_assignable(role: discord.Role, me: discord.Member) -> bool:
    if role.is_default():
        return False
    if role.managed:
        return False
    if role.permissions.administrator:
        return False
    if role >= me.top_role:
        return False
    return True


def _parse_emoji(raw: str | None) -> Optional[discord.PartialEmoji]:
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw.strip())
    except Exception:
        return None


# ======================================================
# Auto roles (humans vs bots)
# ======================================================

async def apply_auto_roles(member: discord.Member) -> None:
    try:
        cfg = _load_config()
    except Exception:
        return

    me = _guild_me(member.guild)
    if not me:
        return

    target = "bots" if member.bot else "humans"
    role_ids = cfg.get("auto_roles", {}).get(target, [])

    for rid in role_ids:
        role = member.guild.get_role(int(rid))
        if not role:
            continue
        if role in member.roles:
            continue
        if not _role_assignable(role, me):
            continue
        try:
            await member.add_roles(role, reason="Auto-role")
        except Exception:
            pass


# ======================================================
# Public self-role menu (dynamic)
# ======================================================

class CategorySelect(discord.ui.Select):
    def __init__(self, key: str, data: Dict[str, Any]):
        self.key = key
        roles = data.get("roles", {}) or {}

        options: List[discord.SelectOption] = []
        for rid, meta in roles.items():
            options.append(
                discord.SelectOption(
                    label=str(meta.get("label", "Role"))[:100],
                    value=str(rid),
                    emoji=_parse_emoji(meta.get("emoji")),
                )
            )

        super().__init__(
            placeholder=str(data.get("title", key))[:150],
            min_values=0,
            max_values=len(options) if data.get("multi_select", True) else 1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return await interaction.response.send_message("❌ Member not found.", ephemeral=True)

        cfg = _load_config()
        cat = cfg.get("categories", {}).get(self.key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        me = _guild_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot role missing.", ephemeral=True)

        role_ids = {int(r) for r in cat.get("roles", {})}
        selected = {int(v) for v in self.values}

        added, removed = [], []

        for rid in role_ids:
            role = interaction.guild.get_role(rid)
            if not role or not _role_assignable(role, me):
                continue

            if rid in selected and role not in member.roles:
                await member.add_roles(role)
                added.append(role)
            elif rid not in selected and role in member.roles:
                await member.remove_roles(role)
                removed.append(role)

        msg = ["✨ **Your roles were updated**"]
        if added:
            msg.append("✅ Added: " + ", ".join(r.mention for r in added))
        if removed:
            msg.append("❌ Removed: " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            msg.append("ℹ️ No changes made.")

        await interaction.response.send_message("\n".join(msg), ephemeral=True)

        log = cfg.get("logging", {})
        if log.get("enabled") and log.get("channel_id") and (added or removed):
            ch = interaction.guild.get_channel(int(log["channel_id"]))
            if isinstance(ch, discord.TextChannel):
                emb = discord.Embed(title="🧩 Self-Role Update", colour=discord.Colour.blurple())
                emb.add_field(name="User", value=interaction.user.mention, inline=False)
                if added:
                    emb.add_field(name="Added", value=", ".join(r.mention for r in added), inline=False)
                if removed:
                    emb.add_field(name="Removed", value=", ".join(r.mention for r in removed), inline=False)
                await ch.send(embed=emb)


class SelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        cfg = _load_config()
        for key, cat in cfg.get("categories", {}).items():
            if cat.get("roles"):
                self.add_item(CategorySelect(key, cat))


async def _deploy_menu(guild: discord.Guild) -> str:
    cfg = _load_config()
    ch_id = cfg.get("selfroles_channel_id")
    if not ch_id:
        return "❌ Self-roles channel not set."

    channel = guild.get_channel(int(ch_id))
    if not isinstance(channel, discord.TextChannel):
        return "❌ Invalid self-roles channel."

    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Use the menus below to update your roles ✈️",
        colour=discord.Colour.blurple(),
    )
    view = SelfRoleView()

    msg_id = cfg.get("selfroles_message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            return "✅ Updated self-role menu."
        except Exception:
            pass

    msg = await channel.send(embed=embed, view=view)
    cfg["selfroles_message_id"] = msg.id
    _save_config(cfg)
    return "✅ Posted new self-role menu."


# ======================================================
# /rolesettings
# ======================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📌 Post / Update Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        msg = await _deploy_menu(interaction.guild)
        await interaction.response.send_message(msg, ephemeral=True)


@app_commands.command(name="rolesettings", description="Admin panel for self-roles")
async def rolesettings(interaction: discord.Interaction):
    if not has_app_access(interaction.user, "roles"):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)

    cfg = _load_config()
    desc = [
        f"📍 Channel: {f'<#{cfg.get('selfroles_channel_id')}>' if cfg.get('selfroles_channel_id') else 'Not set'}",
        f"📌 Menu posted: {'Yes' if cfg.get('selfroles_message_id') else 'No'}",
        f"🧾 Logging: {'ON' if cfg.get('logging', {}).get('enabled') else 'OFF'}",
    ]

    embed = discord.Embed(title="⚙️ Role Settings", description="\n".join(desc), colour=discord.Colour.blurple())
    await interaction.response.send_message(embed=embed, view=RoleSettingsDashboard(), ephemeral=True)


# ======================================================
# Setup
# ======================================================

def setup(tree: app_commands.CommandTree, client: discord.Client):
    tree.add_command(rolesettings)