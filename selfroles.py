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


def _get_me(guild: discord.Guild) -> Optional[discord.Member]:
    return guild.me or guild.get_member(guild.client.user.id) if guild.client.user else None


# =========================================================
# Permissions
# =========================================================

def _can_manage(interaction: discord.Interaction) -> bool:
    return (
        isinstance(interaction.user, discord.Member)
        and has_app_access(interaction.user, "roles")
    )


# =========================================================
# Role safety
# =========================================================

def _is_assignable(role: discord.Role, bot: discord.Member) -> bool:
    if role.is_default():
        return False
    if role.managed:
        return False
    if role.permissions.administrator:
        return False
    if role >= bot.top_role:
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
# Auto roles
# =========================================================

async def apply_auto_roles(member: discord.Member) -> None:
    try:
        cfg = _load_config()
    except Exception:
        return

    auto = cfg.get("auto_roles", {})
    role_ids = auto.get("bots" if member.bot else "humans", [])

    me = _get_me(member.guild)
    if not me:
        return

    for rid in role_ids:
        role = member.guild.get_role(int(rid))
        if not role or role in member.roles:
            continue
        if not _is_assignable(role, me):
            continue
        try:
            await member.add_roles(role, reason="Auto role")
        except Exception:
            pass


# =========================================================
# Public self-role menus
# =========================================================

class CategorySelect(discord.ui.Select):
    def __init__(self, key: str, data: Dict[str, Any]):
        self.key = key
        self.data = data

        options = []
        for rid, meta in (data.get("roles") or {}).items():
            options.append(
                discord.SelectOption(
                    label=str(meta.get("label", "Role"))[:100],
                    value=str(rid),
                    emoji=_parse_emoji(meta.get("emoji")),
                    description=str(meta.get("description"))[:100] if meta.get("description") else None,
                )
            )

        multi = bool(data.get("multi_select", True))
        super().__init__(
            placeholder=str(data.get("title", key))[:150],
            min_values=0,
            max_values=len(options) if multi else 1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return await interaction.response.send_message("Member not found.", ephemeral=True)

        cfg = _load_config()
        cat = cfg.get("categories", {}).get(self.key)
        if not cat:
            return await interaction.response.send_message("Category missing.", ephemeral=True)

        me = _get_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("Bot missing.", ephemeral=True)

        allowed_ids = {int(r) for r in cat.get("roles", {})}
        chosen = {int(v) for v in self.values}

        added, removed = [], []

        for rid in allowed_ids:
            role = interaction.guild.get_role(rid)
            if not role or not _is_assignable(role, me):
                continue

            if rid in chosen and role not in member.roles:
                await member.add_roles(role, reason="Self-role")
                added.append(role)
            elif rid not in chosen and role in member.roles:
                await member.remove_roles(role, reason="Self-role")
                removed.append(role)

        lines = ["✨ **Roles updated**"]
        if added:
            lines.append("➕ " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("➖ " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("No changes.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


class SelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        cfg = _load_config()
        for key, cat in (cfg.get("categories") or {}).items():
            if cat.get("roles"):
                self.add_item(CategorySelect(key, cat))


async def _deploy_menu(guild: discord.Guild) -> Tuple[bool, str]:
    cfg = _load_config()
    cid = cfg.get("selfroles_channel_id")
    if not cid:
        return False, "Channel not set."

    channel = guild.get_channel(int(cid))
    if not isinstance(channel, discord.TextChannel):
        return False, "Invalid channel."

    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Use the menus below to update your roles.",
        colour=discord.Colour.blurple(),
    )

    view = SelfRoleView()
    mid = cfg.get("selfroles_message_id")

    try:
        if mid:
            msg = await channel.fetch_message(int(mid))
            await msg.edit(embed=embed, view=view)
            return True, "Updated menu."
        sent = await channel.send(embed=embed, view=view)
        cfg["selfroles_message_id"] = sent.id
        _save_config(cfg)
        return True, "Posted menu."
    except Exception as e:
        return False, str(e)


# =========================================================
# Admin dashboard
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Set Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def set_channel(self, interaction: discord.Interaction, _):
        if not _can_manage(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        async def pick(i: discord.Interaction):
            ch = select.values[0]
            cfg = _load_config()
            cfg["selfroles_channel_id"] = ch.id
            _save_config(cfg)
            await i.response.send_message(f"Channel set to {ch.mention}", ephemeral=True)

        select = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text])
        select.callback = pick
        await interaction.response.send_message("Pick a channel:", view=discord.ui.View().add_item(select), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _):
        if not _can_manage(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        ok, msg = await _deploy_menu(interaction.guild)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=True)


@app_commands.command(name="rolesettings", description="Manage self roles")
async def rolesettings(interaction: discord.Interaction):
    if not _can_manage(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)

    cfg = _load_config()
    embed = discord.Embed(
        title="⚙️ Self Roles",
        description=f"Channel: {f'<#{cfg.get('selfroles_channel_id')}>' if cfg.get('selfroles_channel_id') else 'Not set'}",
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