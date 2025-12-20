from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands

from permissions import has_app_access, has_global_access

CONFIG_FILE = "selfroles.json"


# =========================================================
# JSON helpers
# =========================================================

def _ensure_default_shape(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg.setdefault("selfroles_channel_id", None)
    cfg.setdefault("selfroles_message_id", None)
    cfg.setdefault("logging", {})
    cfg["logging"].setdefault("enabled", False)
    cfg["logging"].setdefault("channel_id", None)
    cfg.setdefault("auto_roles", {})
    cfg["auto_roles"].setdefault("humans", [])
    cfg["auto_roles"].setdefault("bots", [])
    cfg.setdefault("categories", {})
    return cfg


def _load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        raise RuntimeError("selfroles.json missing")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f) if f.readable() else {}
    return _ensure_default_shape(data or {})


def _save_config(cfg: Dict[str, Any]) -> None:
    cfg = _ensure_default_shape(cfg)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# =========================================================
# Permissions
# =========================================================

def _can_manage_roles(member: discord.Member) -> bool:
    # Uses Pilot permissions system (dynamic)
    # If you add an app key "roles" in pilot_settings, it works per-app.
    # If not, global roles still work.
    try:
        if has_app_access(member, "roles"):
            return True
    except Exception:
        pass
    return has_global_access(member)


# =========================================================
# Discord helpers / guardrails
# =========================================================

def _cid(v) -> int:
    return v.id if hasattr(v, "id") else int(v)


def _get_me(guild: discord.Guild) -> Optional[discord.Member]:
    try:
        return guild.me or guild.get_member(guild.client.user.id)  # type: ignore
    except Exception:
        return None


def _is_role_assignable(role: discord.Role, me: discord.Member) -> bool:
    # guardrails agreed:
    if role.is_default():  # @everyone
        return False
    if role.managed:  # integration / bot role
        return False
    if role.permissions.administrator:  # admin roles blocked
        return False
    if role >= me.top_role:  # bot must be above
        return False
    return True


def _parse_emoji(raw: Optional[str]) -> Optional[discord.PartialEmoji]:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return discord.PartialEmoji.from_str(s)
    except Exception:
        return None


def _format_role_list(guild: discord.Guild, ids: List[int]) -> str:
    out = []
    for rid in ids:
        role = guild.get_role(int(rid))
        if role:
            out.append(role.mention)
    return ", ".join(out) if out else "*None*"


# =========================================================
# Auto roles (humans vs bots)
# =========================================================

async def apply_auto_roles(member: discord.Member) -> None:
    try:
        cfg = _load_config()
    except Exception:
        return

    me = _get_me(member.guild)
    if not me:
        return

    arr = cfg.get("auto_roles", {}).get("bots" if member.bot else "humans", []) or []
    for rid in arr:
        try:
            rid_int = int(rid)
        except Exception:
            continue
        role = member.guild.get_role(rid_int)
        if not role:
            continue
        if role in member.roles:
            continue
        if not _is_role_assignable(role, me):
            continue
        try:
            await member.add_roles(role, reason="Auto role assignment")
        except Exception:
            pass


# =========================================================
# Public self-role menu (multi select menus, one per category)
# =========================================================

class CategorySelect(discord.ui.Select):
    def __init__(self, category_key: str, category_data: Dict[str, Any]):
        self.category_key = category_key

        roles: Dict[str, Any] = category_data.get("roles", {}) or {}
        options: List[discord.SelectOption] = []

        for rid_str, meta in roles.items():
            label = str(meta.get("label") or "Role")
            emoji_raw = meta.get("emoji")
            desc = meta.get("description")
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(rid_str),
                    emoji=_parse_emoji(emoji_raw),
                    description=(str(desc)[:100] if desc else None),
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
        cat = (cfg.get("categories", {}) or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("⚠️ That category no longer exists.", ephemeral=True)

        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}
        role_ids = {int(rid) for rid in roles_cfg.keys() if str(rid).isdigit()}
        selected = {int(v) for v in self.values if str(v).isdigit()}

        me = _get_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("⚠️ Bot member not found.", ephemeral=True)

        added: List[discord.Role] = []
        removed: List[discord.Role] = []

        # Apply within category only
        for rid in role_ids:
            role = interaction.guild.get_role(rid)
            if not role:
                continue
            if not _is_role_assignable(role, me):
                continue

            if rid in selected and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Self-role menu")
                    added.append(role)
                except Exception:
                    pass
            elif rid not in selected and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Self-role menu")
                    removed.append(role)
                except Exception:
                    pass

        # Ephemeral confirmation (requested)
        lines: List[str] = ["✨ **Your roles have been updated.**"]
        if added:
            lines.append("✅ **Added:** " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("❌ **Removed:** " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("ℹ️ No changes made.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        # Optional logging
        log_cfg = cfg.get("logging", {}) or {}
        if log_cfg.get("enabled") and log_cfg.get("channel_id") and (added or removed):
            chan = interaction.guild.get_channel(int(log_cfg["channel_id"]))
            if isinstance(chan, discord.TextChannel):
                embed = discord.Embed(title="🧩 Self-Role Update", colour=discord.Colour.blurple())
                embed.add_field(name="User", value=interaction.user.mention, inline=False)
                embed.add_field(name="Category", value=str(cat.get("title") or self.category_key), inline=False)
                if added:
                    embed.add_field(name="Added", value=", ".join(r.mention for r in added), inline=False)
                if removed:
                    embed.add_field(name="Removed", value=", ".join(r.mention for r in removed), inline=False)
                try:
                    await chan.send(embed=embed)
                except Exception:
                    pass


class SelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        cfg = _load_config()
        categories: Dict[str, Any] = cfg.get("categories", {}) or {}

        # one menu per category (users wanted this layout)
        for key, cat in categories.items():
            roles = cat.get("roles", {}) or {}
            if not roles:
                continue
            self.add_item(CategorySelect(key, cat))


async def _build_selfroles_embed_and_view() -> Tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Use the menus below to update your roles.\nYou can change these at any time ✈️",
        colour=discord.Colour.blurple(),
    )
    return embed, SelfRoleView()


async def _deploy_or_update_selfroles_menu(guild: discord.Guild) -> Tuple[bool, str]:
    cfg = _load_config()
    channel_id = cfg.get("selfroles_channel_id")
    if not channel_id:
        return False, "Self-roles channel not set."

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False, "Configured self-roles channel is missing or not a text channel."

    embed, view = await _build_selfroles_embed_and_view()

    msg_id = cfg.get("selfroles_message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            return True, "Updated existing self-role menu."
        except Exception:
            pass

    try:
        sent = await channel.send(embed=embed, view=view)
        cfg["selfroles_message_id"] = sent.id
        _save_config(cfg)
        return True, "Posted new self-role menu."
    except Exception as e:
        return False, f"Failed to post menu: {e}"


async def refresh_menu_on_startup_if_possible(client: discord.Client) -> None:
    # optional: on restart, try to ensure the stored message has a fresh view
    try:
        cfg = _load_config()
        if not cfg.get("selfroles_channel_id") or not cfg.get("selfroles_message_id"):
            return
        if not client.guilds:
            return
        guild = client.guilds[0]
        ok, _ = await _deploy_or_update_selfroles_menu(guild)
        return
    except Exception:
        return


# =========================================================
# Admin UI: channel pickers
# =========================================================

class _SetSelfRolesChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.ChannelSelect(
            placeholder="Select the channel for the public self-role menu",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        sel.callback = self._on_select  # type: ignore
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        cid = _cid(interaction.data["values"][0])
        cfg = _load_config()
        cfg["selfroles_channel_id"] = cid
        _save_config(cfg)
        await interaction.response.send_message(f"📍 Self-roles channel set to <#{cid}>", ephemeral=True)


class _SetLogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.ChannelSelect(
            placeholder="Select the log channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        sel.callback = self._on_select  # type: ignore
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        cid = _cid(interaction.data["values"][0])
        cfg = _load_config()
        cfg.setdefault("logging", {})
        cfg["logging"]["channel_id"] = cid
        _save_config(cfg)
        await interaction.response.send_message(f"🧾 Log channel set to <#{cid}>", ephemeral=True)


# =========================================================
# Admin UI: category editor
# =========================================================

class CategoryModal(discord.ui.Modal):
    def __init__(self, mode: str, existing_key: Optional[str] = None, existing: Optional[Dict[str, Any]] = None):
        super().__init__(title="Category Settings")
        self.mode = mode
        self.existing_key = existing_key

        self.key = discord.ui.TextInput(
            label="Category key (unique, no spaces) e.g. games_pings",
            required=True,
            max_length=50,
            default=existing_key or "",
        )
        self.title_in = discord.ui.TextInput(
            label="Title (shows on the menu) e.g. 🎮 Games Pings",
            required=True,
            max_length=150,
            default=(existing.get("title") if existing else "") or "",
        )
        self.desc = discord.ui.TextInput(
            label="Description (optional)",
            required=False,
            max_length=200,
            default=(existing.get("description") if existing else "") or "",
        )
        self.multi = discord.ui.TextInput(
            label="Multi-select? (yes/no)",
            required=True,
            max_length=5,
            default=("yes" if (existing.get("multi_select", True) if existing else True) else "no"),
        )

        self.add_item(self.key)
        self.add_item(self.title_in)
        self.add_item(self.desc)
        self.add_item(self.multi)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = _load_config()
        categories = cfg.get("categories", {}) or {}

        key = self.key.value.strip().lower().replace(" ", "_")
        if not key:
            return await interaction.response.send_message("❌ Category key is required.", ephemeral=True)

        multi_raw = self.multi.value.strip().lower()
        multi_select = multi_raw in ("yes", "y", "true", "1", "on")

        if self.mode == "add":
            if key in categories:
                return await interaction.response.send_message("❌ That category key already exists.", ephemeral=True)
            categories[key] = {
                "title": self.title_in.value.strip(),
                "description": self.desc.value.strip(),
                "multi_select": multi_select,
                "roles": {},
            }
        else:
            if not self.existing_key or self.existing_key not in categories:
                return await interaction.response.send_message("❌ Category no longer exists.", ephemeral=True)

            if key != self.existing_key:
                if key in categories:
                    return await interaction.response.send_message("❌ New key already exists.", ephemeral=True)
                categories[key] = categories.pop(self.existing_key)

            categories[key]["title"] = self.title_in.value.strip()
            categories[key]["description"] = self.desc.value.strip()
            categories[key]["multi_select"] = multi_select
            categories[key].setdefault("roles", {})

        cfg["categories"] = categories
        _save_config(cfg)
        await interaction.response.send_message("✅ Category saved.", ephemeral=True)


class CategoryPicker(discord.ui.Select):
    def __init__(self, placeholder: str, custom_id: str):
        cfg = _load_config()
        cats: Dict[str, Any] = cfg.get("categories", {}) or {}

        options: List[discord.SelectOption] = []
        if not cats:
            options.append(discord.SelectOption(label="(No categories yet)", value="__none__", default=True))

        for key, cat in list(cats.items())[:25]:
            options.append(
                discord.SelectOption(
                    label=str(cat.get("title") or key)[:100],
                    value=key,
                    description=(str(cat.get("description"))[:100] if cat.get("description") else None),
                )
            )

        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options[:25], custom_id=custom_id)


class CategoryManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.selected_key: Optional[str] = None

        sel = CategoryPicker("Select a category to edit/delete", "rolesettings:cat_select")
        sel.callback = self._on_select  # type: ignore
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        key = interaction.data["values"][0]
        if key == "__none__":
            self.selected_key = None
            return await interaction.response.send_message("ℹ️ No categories to select yet.", ephemeral=True)
        self.selected_key = key
        await interaction.response.send_message(f"✅ Selected category: `{key}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Category", style=discord.ButtonStyle.success)
    async def add_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(CategoryModal(mode="add"))

    @discord.ui.button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary)
    async def edit_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = _load_config()
        cat = (cfg.get("categories", {}) or {}).get(self.selected_key)
        if not cat:
            return await interaction.response.send_message("❌ Category not found.", ephemeral=True)
        await interaction.response.send_modal(CategoryModal(mode="edit", existing_key=self.selected_key, existing=cat))

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def delete_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = _load_config()
        cats = cfg.get("categories", {}) or {}
        if self.selected_key not in cats:
            return await interaction.response.send_message("❌ Category not found.", ephemeral=True)
        del cats[self.selected_key]
        cfg["categories"] = cats
        _save_config(cfg)
        self.selected_key = None
        await interaction.response.send_message("✅ Category deleted.", ephemeral=True)


# =========================================================
# Admin UI: role editor + emoji/label
# =========================================================

class RoleDisplayModal(discord.ui.Modal):
    def __init__(self, category_key: str, role_id: int, existing: Dict[str, Any]):
        super().__init__(title="Role Display Settings")
        self.category_key = category_key
        self.role_id = role_id

        self.label_in = discord.ui.TextInput(
            label="Label (what users see)",
            required=True,
            max_length=100,
            default=str(existing.get("label") or "Role"),
        )
        self.emoji_in = discord.ui.TextInput(
            label="Emoji (unicode or <:name:id> / <a:name:id>) - optional",
            required=False,
            max_length=80,
            default=str(existing.get("emoji") or ""),
        )
        self.desc_in = discord.ui.TextInput(
            label="Description (optional)",
            required=False,
            max_length=100,
            default=str(existing.get("description") or ""),
        )

        self.add_item(self.label_in)
        self.add_item(self.emoji_in)
        self.add_item(self.desc_in)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = _load_config()
        cat = (cfg.get("categories", {}) or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category not found.", ephemeral=True)

        roles = cat.get("roles", {}) or {}
        role_key = str(self.role_id)
        if role_key not in roles:
            return await interaction.response.send_message("❌ Role not found in that category.", ephemeral=True)

        emoji_str = self.emoji_in.value.strip()
        if emoji_str and not _parse_emoji(emoji_str):
            return await interaction.response.send_message("❌ That emoji format looks invalid.", ephemeral=True)

        roles[role_key]["label"] = self.label_in.value.strip()
        roles[role_key]["emoji"] = emoji_str or None
        roles[role_key]["description"] = self.desc_in.value.strip() or None
        cat["roles"] = roles
        _save_config(cfg)

        await interaction.response.send_message("✅ Role display updated.", ephemeral=True)


class RoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.category_key: Optional[str] = None

        sel = CategoryPicker("Select a category to manage roles", "rolesettings:role_cat_select")
        sel.callback = self._on_cat  # type: ignore
        self.add_item(sel)

    async def _on_cat(self, interaction: discord.Interaction):
        key = interaction.data["values"][0]
        if key == "__none__":
            self.category_key = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.category_key = key
        await interaction.response.send_message(f"✅ Selected category: `{key}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Role to Category", style=discord.ButtonStyle.success)
    async def add_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        assert interaction.guild is not None
        me = _get_me(interaction.guild)
        if