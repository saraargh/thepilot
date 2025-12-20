# selfroles.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands

CONFIG_FILE = "selfroles.json"

# This gets set from botslash.py setup() to avoid circular imports
_ALLOWED_ROLE_IDS: List[int] = []


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

def _has_admin_access(member: discord.Member) -> bool:
    # Uses the same roles you already treat as allowed in Pilot
    return any(r.id in _ALLOWED_ROLE_IDS for r in member.roles)


def _is_role_assignable(role: discord.Role, bot_member: discord.Member) -> bool:
    # Hard blocks we agreed
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
        # If it's a unicode emoji, from_str still usually works; if not, treat as invalid
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
        if not role:
            continue
        if role in member.roles:
            continue
        if not _is_role_assignable(role, me):
            continue
        try:
            await member.add_roles(role, reason="Auto role assignment")
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass


# =========================================================
# Public self-role view (multiple select menus)
# =========================================================

class CategorySelect(discord.ui.Select):
    def __init__(self, category_key: str, category_data: Dict[str, Any]):
        self.category_key = category_key
        self.category_data = category_data

        options: List[discord.SelectOption] = []
        roles: Dict[str, Any] = category_data.get("roles", {}) or {}

        for role_id_str, meta in roles.items():
            label = str(meta.get("label") or "Role")
            emoji_str = meta.get("emoji")
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    emoji=_parse_emoji(emoji_str) if emoji_str else None,
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
            options=options[:25],  # Discord hard limit
            custom_id=f"selfroles:cat:{category_key}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        member = interaction.guild.get_member(interaction.user.id)
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("⚠️ Could not resolve your member object.", ephemeral=True)
            return

        cfg = _load_config()
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            await interaction.response.send_message("⚠️ That category no longer exists.", ephemeral=True)
            return

        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}
        role_ids = {int(rid) for rid in roles_cfg.keys() if str(rid).isdigit()}
        selected = {int(v) for v in self.values if str(v).isdigit()}

        me = _get_guild_me(interaction.guild)
        if not me:
            await interaction.response.send_message("⚠️ Bot member not found.", ephemeral=True)
            return

        added: List[discord.Role] = []
        removed: List[discord.Role] = []

        # Apply changes only within this category
        for rid in role_ids:
            role = interaction.guild.get_role(rid)
            if not role:
                continue
            # don't let self-role touch roles bot cannot manage
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

        # Ephemeral confirmation
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
                embed = discord.Embed(
                    title="🧩 Self-Role Update",
                    colour=discord.Colour.blurple(),
                )
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

        for key, cat in categories.items():
            roles = cat.get("roles", {}) or {}
            if not roles:
                continue
            # If >25 roles in a category, we still create the menu but it’ll cap options at 25
            self.add_item(CategorySelect(key, cat))


async def _build_selfroles_embed_and_view() -> Tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Use the menus below to update your roles.\nYou can change these at any time ✈️",
        colour=discord.Colour.blurple(),
    )
    return embed, SelfRoleView()


async def _deploy_or_update_selfroles_menu(guild: discord.Guild) -> Tuple[bool, str]:
    """
    Returns (success, message)
    """
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
            return True, "✅ Updated existing self-role menu."
        except Exception:
            # Fall through and post a new one
            pass

    try:
        sent = await channel.send(embed=embed, view=view)
        cfg["selfroles_message_id"] = sent.id
        _save_config(cfg)
        return True, "✅ Posted a new self-role menu."
    except Exception as e:
        return False, f"Failed to post menu: {e}"


# =========================================================
# Admin UI: /rolesettings
# =========================================================

class _SetSelfRolesChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

        self.channel_select = discord.ui.ChannelSelect(
            placeholder="Select the channel for the public self-role menu",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.channel_select.callback = self._on_select  # type: ignore
        self.add_item(self.channel_select)

    async def _on_select(self, interaction: discord.Interaction):
        channel = self.channel_select.values[0]
        cfg = _load_config()
        cfg["selfroles_channel_id"] = channel.id
        _save_config(cfg)
        await interaction.response.send_message(f"📍 Self-roles channel set to {channel.mention}", ephemeral=True)


class _SetLogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

        self.channel_select = discord.ui.ChannelSelect(
            placeholder="Select the log channel for role updates",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.channel_select.callback = self._on_select  # type: ignore
        self.add_item(self.channel_select)

    async def _on_select(self, interaction: discord.Interaction):
        channel = self.channel_select.values[0]
        cfg = _load_config()
        cfg["logging"]["channel_id"] = channel.id
        _save_config(cfg)
        await interaction.response.send_message(f"🧾 Log channel set to {channel.mention}", ephemeral=True)


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
            label="Description (optional, for admins / future)",
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
            await interaction.response.send_message("❌ Category key is required.", ephemeral=True)
            return

        multi_raw = self.multi.value.strip().lower()
        multi_select = multi_raw in ("yes", "y", "true", "1", "on")

        if self.mode == "add":
            if key in categories:
                await interaction.response.send_message("❌ That category key already exists.", ephemeral=True)
                return
            categories[key] = {
                "title": self.title_in.value.strip(),
                "description": self.desc.value.strip(),
                "multi_select": multi_select,
                "roles": {},
            }
        else:
            # edit
            if self.existing_key is None or self.existing_key not in categories:
                await interaction.response.send_message("❌ Category no longer exists.", ephemeral=True)
                return

            # If key changed, rename
            if key != self.existing_key:
                if key in categories:
                    await interaction.response.send_message("❌ New key already exists.", ephemeral=True)
                    return
                categories[key] = categories.pop(self.existing_key)
            categories[key]["title"] = self.title_in.value.strip()
            categories[key]["description"] = self.desc.value.strip()
            categories[key]["multi_select"] = multi_select
            categories[key].setdefault("roles", {})

        cfg["categories"] = categories
        _save_config(cfg)
        await interaction.response.send_message("✅ Category saved.", ephemeral=True)


class EmojiLabelModal(discord.ui.Modal):
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

        self.add_item(self.label_in)
        self.add_item(self.emoji_in)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = _load_config()
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            await interaction.response.send_message("❌ Category not found.", ephemeral=True)
            return

        roles = cat.get("roles", {}) or {}
        role_key = str(self.role_id)
        if role_key not in roles:
            await interaction.response.send_message("❌ Role not found in that category.", ephemeral=True)
            return

        emoji_str = self.emoji_in.value.strip()
        if emoji_str:
            if not _parse_emoji(emoji_str):
                await interaction.response.send_message("❌ That emoji format looks invalid.", ephemeral=True)
                return

        roles[role_key]["label"] = self.label_in.value.strip()
        roles[role_key]["emoji"] = emoji_str or None
        cat["roles"] = roles
        _save_config(cfg)

        await interaction.response.send_message("✅ Role display updated.", ephemeral=True)


class CategoryPicker(discord.ui.Select):
    def __init__(self, placeholder: str, custom_id: str, include_empty: bool = True):
        cfg = _load_config()
        cats: Dict[str, Any] = cfg.get("categories", {}) or {}

        options: List[discord.SelectOption] = []
        if include_empty and not cats:
            options.append(discord.SelectOption(label="(No categories yet)", value="__none__", default=True))

        for key, cat in list(cats.items())[:25]:
            options.append(
                discord.SelectOption(
                    label=str(cat.get("title") or key)[:100],
                    value=key,
                    description=(str(cat.get("description"))[:100] if cat.get("description") else None),
                )
            )

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id=custom_id,
        )


class CategoryManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.selected_key: Optional[str] = None

        self.cat_select = CategoryPicker("Select a category to edit/delete", "rolesettings:cat_select", include_empty=True)
        self.cat_select.callback = self._on_select  # type: ignore
        self.add_item(self.cat_select)

    async def _on_select(self, interaction: discord.Interaction):
        key = self.cat_select.values[0]
        if key == "__none__":
            self.selected_key = None
            await interaction.response.send_message("ℹ️ No categories to select yet.", ephemeral=True)
            return
        self.selected_key = key
        await interaction.response.send_message(f"✅ Selected category: `{key}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Category", style=discord.ButtonStyle.success)
    async def add_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(CategoryModal(mode="add"))

    @discord.ui.button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary)
    async def edit_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected_key:
            await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
            return
        cfg = _load_config()
        cat = cfg.get("categories", {}).get(self.selected_key)
        if not cat:
            await interaction.response.send_message("❌ Category not found.", ephemeral=True)
            return
        await interaction.response.send_modal(CategoryModal(mode="edit", existing_key=self.selected_key, existing=cat))

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def delete_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected_key:
            await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
            return
        cfg = _load_config()
        cats = cfg.get("categories", {}) or {}
        if self.selected_key not in cats:
            await interaction.response.send_message("❌ Category not found.", ephemeral=True)
            return
        del cats[self.selected_key]
        cfg["categories"] = cats
        _save_config(cfg)
        self.selected_key = None
        await interaction.response.send_message("✅ Category deleted.", ephemeral=True)


class RoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.category_key: Optional[str] = None
        self.role_id: Optional[int] = None

        self.cat_select = CategoryPicker("Select a category to manage roles", "rolesettings:role_cat_select", include_empty=True)
        self.cat_select.callback = self._on_cat  # type: ignore
        self.add_item(self.cat_select)

    async def _on_cat(self, interaction: discord.Interaction):
        key = self.cat_select.values[0]
        if key == "__none__":
            self.category_key = None
            await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
            return
        self.category_key = key
        await interaction.response.send_message(f"✅ Selected category: `{key}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Role to Category", style=discord.ButtonStyle.success)
    async def add_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
            return

        view = discord.ui.View(timeout=180)
        role_select = discord.ui.RoleSelect(
            placeholder="Pick a role to add",
            min_values=1,
            max_values=1,
        )

        async def on_pick(i: discord.Interaction):
            assert i.guild is not None
            me = _get_guild_me(i.guild)
            if not me:
                await i.response.send_message("❌ Bot member missing.", ephemeral=True)
                return

            role: discord.Role = role_select.values[0]
            if not _is_role_assignable(role, me):
                await i.response.send_message("❌ That role can’t be managed by the bot (or is blocked).", ephemeral=True)
                return

            cfg = _load_config()
            cat = cfg.get("categories", {}).get(self.category_key)
            if not cat:
                await i.response.send_message("❌ Category missing.", ephemeral=True)
                return

            roles = cat.get("roles", {}) or {}
            rid = str(role.id)
            if rid in roles:
                await i.response.send_message("ℹ️ That role is already in this category.", ephemeral=True)
                return

            roles[rid] = {"label": role.name, "emoji": None}
            cat["roles"] = roles
            _save_config(cfg)

            await i.response.send_message(f"✅ Added {role.mention} to `{self.category_key}`.", ephemeral=True)

        role_select.callback = on_pick  # type: ignore
        view.add_item(role_select)
        await interaction.response.send_message("Select a role to add:", view=view, ephemeral=True)

    @discord.ui.button(label="➖ Remove Role from Category", style=discord.ButtonStyle.danger)
    async def remove_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
            return

        cfg = _load_config()
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            await interaction.response.send_message("❌ Category missing.", ephemeral=True)
            return
        roles: Dict[str, Any] = cat.get("roles", {}) or {}
        if not roles:
            await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)
            return

        options: List[discord.SelectOption] = []
        for rid_str, meta in list(roles.items())[:25]:
            options.append(
                discord.SelectOption(
                    label=str(meta.get("label") or rid_str)[:100],
                    value=rid_str,
                    emoji=_parse_emoji(meta.get("emoji") or "") if meta.get("emoji") else None,
                )
            )

        select = discord.ui.Select(placeholder="Pick a role to remove", min_values=1, max_values=1, options=options)

        async def on_remove(i: discord.Interaction):
            rid_str = select.values[0]
            cfg2 = _load_config()
            cat2 = cfg2.get("categories", {}).get(self.category_key)
            if not cat2:
                await i.response.send_message("❌ Category missing.", ephemeral=True)
                return
            roles2 = cat2.get("roles", {}) or {}
            if rid_str in roles2:
                del roles2[rid_str]
            cat2["roles"] = roles2
            _save_config(cfg2)
            await i.response.send_message("✅ Role removed from category.", ephemeral=True)

        select.callback = on_remove  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(select)
        await interaction.response.send_message("Select a role to remove:", view=v, ephemeral=True)

    @discord.ui.button(label="😀 Edit Role Label/Emoji", style=discord.ButtonStyle.primary)
    async def edit_display(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
            return

        cfg = _load_config()
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            await interaction.response.send_message("❌ Category missing.", ephemeral=True)
            return
        roles: Dict[str, Any] = cat.get("roles", {}) or {}
        if not roles:
            await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)
            return

        options: List[discord.SelectOption] = []
        for rid_str, meta in list(roles.items())[:25]:
            options.append(
                discord.SelectOption(
                    label=str(meta.get("label") or rid_str)[:100],
                    value=rid_str,
                    emoji=_parse_emoji(meta.get("emoji") or "") if meta.get("emoji") else None,
                )
            )

        select = discord.ui.Select(placeholder="Pick a role to edit", min_values=1, max_values=1, options=options)

        async def on_pick(i: discord.Interaction):
            rid_str = select.values[0]
            cfg2 = _load_config()
            cat2 = cfg2.get("categories", {}).get(self.category_key)
            if not cat2:
                await i.response.send_message("❌ Category missing.", ephemeral=True)
                return
            role_meta = (cat2.get("roles", {}) or {}).get(rid_str)
            if not role_meta:
                await i.response.send_message("❌ Role missing.", ephemeral=True)
                return
            await i.response.send_modal(EmojiLabelModal(self.category_key, int(rid_str), role_meta))

        select.callback = on_pick  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(select)
        await interaction.response.send_message("Select a role to edit:", view=v, ephemeral=True)


class AutoRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ Add Human Auto-Role", style=discord.ButtonStyle.success)
    async def add_human(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._pick_auto_role(interaction, target="humans")

    @discord.ui.button(label="➕ Add Bot Auto-Role", style=discord.ButtonStyle.success)
    async def add_bot(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._pick_auto_role(interaction, target="bots")

    @discord.ui.button(label="➖ Remove Human Auto-Role", style=discord.ButtonStyle.danger)
    async def rem_human(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._remove_auto_role(interaction, target="humans")

    @discord.ui.button(label="➖ Remove Bot Auto-Role", style=discord.ButtonStyle.danger)
    async def rem_bot(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._remove_auto_role(interaction, target="bots")

    async def _pick_auto_role(self, interaction: discord.Interaction, target: str):
        assert interaction.guild is not None
        me = _get_guild_me(interaction.guild)
        if not me:
            await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)
            return

        view = discord.ui.View(timeout=180)
        role_select = discord.ui.RoleSelect(placeholder="Pick an auto-role", min_values=1, max_values=1)

        async def on_pick(i: discord.Interaction):
            role: discord.Role = role_select.values[0]
            if not _is_role_assignable(role, me):
                await i.response.send_message("❌ That role can’t be managed by the bot (or is blocked).", ephemeral=True)
                return

            cfg = _load_config()
            arr = cfg.get("auto_roles", {}).get(target, [])
            rid = str(role.id)
            if rid not in arr:
                arr.append(rid)
            cfg["auto_roles"][target] = arr
            _save_config(cfg)
            await i.response.send_message(f"✅ Added {role.mention} to auto-roles ({target}).", ephemeral=True)

        role_select.callback = on_pick  # type: ignore
        view.add_item(role_select)
        await interaction.response.send_message("Select a role:", view=view, ephemeral=True)

    async def _remove_auto_role(self, interaction: discord.Interaction, target: str):
        cfg = _load_config()
        arr = cfg.get("auto_roles", {}).get(target, [])
        if not arr:
            await interaction.response.send_message("ℹ️ None set.", ephemeral=True)
            return

        options: List[discord.SelectOption] = []
        for rid_str in arr[:25]:
            role = interaction.guild.get_role(int(rid_str)) if interaction.guild else None
            options.append(discord.SelectOption(label=(role.name if role else rid_str), value=rid_str))

        select = discord.ui.Select(placeholder="Pick one to remove", min_values=1, max_values=1, options=options)

        async def on_remove(i: discord.Interaction):
            rid_str = select.values[0]
            cfg2 = _load_config()
            arr2 = cfg2.get("auto_roles", {}).get(target, [])
            if rid_str in arr2:
                arr2.remove(rid_str)
            cfg2["auto_roles"][target] = arr2
            _save_config(cfg2)
            await i.response.send_message("✅ Removed.", ephemeral=True)

        select.callback = on_remove  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(select)
        await interaction.response.send_message("Select one to remove:", view=v, ephemeral=True)


class LoggingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔁 Toggle Logging", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = _load_config()
        cfg["logging"]["enabled"] = not bool(cfg["logging"].get("enabled"))
        _save_config(cfg)
        state = "ON" if cfg["logging"]["enabled"] else "OFF"
        await interaction.response.send_message(f"🧾 Logging is now **{state}**.", ephemeral=True)

    @discord.ui.button(label="📍 Set Log Channel", style=discord.ButtonStyle.secondary)
    async def set_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a log channel:", view=_SetLogChannelView(), ephemeral=True)

    @discord.ui.button(label="🧹 Clear Log Channel", style=discord.ButtonStyle.danger)
    async def clear_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = _load_config()
        cfg["logging"]["channel_id"] = None
        _save_config(cfg)
        await interaction.response.send_message("✅ Log channel cleared.", ephemeral=True)


# =========================================================
# Admin: assign/remove roles to users (ALL roles w/ guardrails)
# =========================================================

class UserRoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ Assign Role to User", style=discord.ButtonStyle.success)
    async def assign(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a user:", view=_PickUserForAssignView(), ephemeral=True)

    @discord.ui.button(label="➖ Remove Role from User", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a user:", view=_PickUserForRemoveView(), ephemeral=True)


class _PickUserForAssignView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.user_select = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        self.user_select.callback = self._on_pick  # type: ignore
        self.add_item(self.user_select)

    async def _on_pick(self, interaction: discord.Interaction):
        user = self.user_select.values[0]
        await interaction.response.send_message(
            f"Now select a role to **assign** to {user.mention}:",
            view=_PickRoleToAssignView(user_id=user.id),
            ephemeral=True,
        )


class _PickRoleToAssignView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.role_select = discord.ui.RoleSelect(placeholder="Pick a role", min_values=1, max_values=1)
        self.role_select.callback = self._on_pick  # type: ignore
        self.add_item(self.role_select)

    async def _on_pick(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        me = _get_guild_me(interaction.guild)
        if not me:
            await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)
            return

        member = interaction.guild.get_member(self.user_id)
        if not member:
            await interaction.response.send_message("❌ User not found in this guild.", ephemeral=True)
            return

        role: discord.Role = self.role_select.values[0]
        if not _is_role_assignable(role, me):
            await interaction.response.send_message("❌ That role is blocked or not manageable by the bot.", ephemeral=True)
            return

        if role in member.roles:
            await interaction.response.send_message("ℹ️ They already have that role.", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason=f"Admin role assign by {interaction.user}")
        except Exception:
            await interaction.response.send_message("❌ Failed to assign that role (permissions).", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Assigned {role.mention} to {member.mention}", ephemeral=True)

        # Log if enabled
        cfg = _load_config()
        log_cfg = cfg.get("logging", {}) or {}
        if log_cfg.get("enabled") and log_cfg.get("channel_id"):
            chan = interaction.guild.get_channel(int(log_cfg["channel_id"]))
            if isinstance(chan, discord.TextChannel):
                emb = discord.Embed(title="🛂 Role Assigned", colour=discord.Colour.green())
                emb.add_field(name="Admin", value=interaction.user.mention, inline=False)
                emb.add_field(name="User", value=member.mention, inline=False)
                emb.add_field(name="Role", value=role.mention, inline=False)
                try:
                    await chan.send(embed=emb)
                except Exception:
                    pass


class _PickUserForRemoveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.user_select = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        self.user_select.callback = self._on_pick  # type: ignore
        self.add_item(self.user_select)

    async def _on_pick(self, interaction: discord.Interaction):
        user = self.user_select.values[0]
        await interaction.response.send_message(
            f"Now select a role to **remove** from {user.mention}:",
            view=_PickRoleToRemoveView(user_id=user.id),
            ephemeral=True,
        )


class _PickRoleToRemoveView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

        # RoleSelect can’t be limited to “only roles this user has”, so we build a normal Select.
        self.role_select = discord.ui.Select(placeholder="Pick a role to remove", min_values=1, max_values=1, options=[])
        self.role_select.callback = self._on_pick  # type: ignore
        self.add_item(self.role_select)

    async def _populate(self, guild: discord.Guild) -> None:
        member = guild.get_member(self.user_id)
        if not member:
            self.role_select.options = [discord.SelectOption(label="(User not found)", value="__none__", default=True)]
            return

        me = _get_guild_me(guild)
        if not me:
            self.role_select.options = [discord.SelectOption(label="(Bot missing)", value="__none__", default=True)]
            return

        options: List[discord.SelectOption] = []
        # only roles we are allowed to touch
        manageable = [r for r in member.roles if _is_role_assignable(r, me)]
        manageable.sort(key=lambda r: r.position, reverse=True)

        for r in manageable[:25]:
            options.append(discord.SelectOption(label=r.name[:100], value=str(r.id)))
        if not options:
            options = [discord.SelectOption(label="(No removable roles)", value="__none__", default=True)]
        self.role_select.options = options

    async def on_timeout(self) -> None:
        return

    async def _on_pick(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        me = _get_guild_me(interaction.guild)
        if not me:
            await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)
            return

        member = interaction.guild.get_member(self.user_id)
        if not member:
            await interaction.response.send_message("❌ User not found.", ephemeral=True)
            return

        val = self.role_select.values[0]
        if val == "__none__":
            await interaction.response.send_message("ℹ️ Nothing to remove.", ephemeral=True)
            return

        role = interaction.guild.get_role(int(val))
        if not role or not _is_role_assignable(role, me):
            await interaction.response.send_message("❌ That role is blocked or not manageable.", ephemeral=True)
            return

        if role not in member.roles:
            await interaction.response.send_message("ℹ️ They don’t have that role.", ephemeral=True)
            return

        try:
            await member.remove_roles(role, reason=f"Admin role remove by {interaction.user}")
        except Exception:
            await interaction.response.send_message("❌ Failed to remove that role (permissions).", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Removed {role.mention} from {member.mention}", ephemeral=True)

        cfg = _load_config()
        log_cfg = cfg.get("logging", {}) or {}
        if log_cfg.get("enabled") and log_cfg.get("channel_id"):
            chan = interaction.guild.get_channel(int(log_cfg["channel_id"]))
            if isinstance(chan, discord.TextChannel):
                emb = discord.Embed(title="🛂 Role Removed", colour=discord.Colour.red())
                emb.add_field(name="Admin", value=interaction.user.mention, inline=False)
                emb.add_field(name="User", value=member.mention, inline=False)
                emb.add_field(name="Role", value=role.mention, inline=False)
                try:
                    await chan.send(embed=emb)
                except Exception:
                    pass


# =========================================================
# Main rolesettings dashboard
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def selfroles_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select the self-roles channel:", view=_SetSelfRolesChannelView(), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Public Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        ok, msg = await _deploy_or_update_selfroles_menu(interaction.guild)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=True)

    @discord.ui.button(label="📂 Categories", style=discord.ButtonStyle.secondary)
    async def categories(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Category manager:", view=CategoryManagerView(), ephemeral=True)

    @discord.ui.button(label="🎭 Roles in Categories", style=discord.ButtonStyle.secondary)
    async def roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Role manager:", view=RoleManagerView(), ephemeral=True)

    @discord.ui.button(label="👥 Auto Roles", style=discord.ButtonStyle.secondary)
    async def autoroles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Auto-roles:", view=AutoRolesView(), ephemeral=True)

    @discord.ui.button(label="🧾 Logging", style=discord.ButtonStyle.secondary)
    async def logging(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = _load_config()
        state = "ON" if cfg.get("logging", {}).get("enabled") else "OFF"
        chan = cfg.get("logging", {}).get("channel_id")
        extra = f"\nCurrent: **{state}** | Channel: {f'<#{chan}>' if chan else 'Not set'}"
        await interaction.response.send_message("Logging settings:" + extra, view=LoggingView(), ephemeral=True)

    @discord.ui.button(label="🛂 Admin Assign Roles", style=discord.ButtonStyle.primary)
    async def admin_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("User role management:", view=UserRoleManagerView(), ephemeral=True)


@app_commands.command(name="rolesettings", description="Admin panel for roles & self-roles")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not _has_admin_access(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to use this.", ephemeral=True)
        return

    cfg = _load_config()
    ch = cfg.get("selfroles_channel_id")
    msg_id = cfg.get("selfroles_message_id")
    log = cfg.get("logging", {}) or {}

    desc = []
    desc.append(f"📍 **Self-roles channel:** {f'<#{ch}>' if ch else 'Not set'}")
    desc.append(f"📌 **Menu message:** {'Set' if msg_id else 'Not posted yet'}")
    desc.append(f"🧾 **Logging:** {'ON' if log.get('enabled') else 'OFF'}")
    if log.get("channel_id"):
        desc.append(f"🧾 **Log channel:** <#{log['channel_id']}>")

    embed = discord.Embed(
        title="⚙️ Role Settings",
        description="\n".join(desc),
        colour=discord.Colour.blurple(),
    )

    await interaction.response.send_message(embed=embed, view=RoleSettingsDashboard(), ephemeral=True)


# =========================================================
# Setup
# =========================================================

def setup(tree: app_commands.CommandTree, client: discord.Client, allowed_role_ids: List[int]):
    global _ALLOWED_ROLE_IDS
    _ALLOWED_ROLE_IDS = list(allowed_role_ids)

    tree.add_command(rolesettings)

    # Register persistent public view so it survives restarts (reads current JSON)
    try:
        client.add_view(SelfRoleView())
    except Exception:
        pass


# =========================================================
# Helper to refresh remove-role view options after sending
# (discord.py doesn’t call a hook automatically for that custom view)
# =========================================================

async def _prepare_remove_role_view(view: _PickRoleToRemoveView, guild: discord.Guild):
    await view._populate(guild)