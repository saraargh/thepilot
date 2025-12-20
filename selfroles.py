from __future__ import annotations

import json
import os
import asyncio
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands

from permissions import has_global_access, has_app_access

CONFIG_FILE = "selfroles.json"

# Fixed number of public select menus so the view shape NEVER changes.
# This is how we avoid redeploy/restart when admins add/remove categories.
MAX_PUBLIC_MENUS = 5  # increase if you want more categories shown at once (max 5 recommended for UI)


# =========================================================
# JSON helpers
# =========================================================

def _load() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        # create a safe default file
        cfg = {
            "selfroles_channel_id": None,
            "selfroles_message_id": None,
            "logging": {"enabled": False, "channel_id": None},
            "auto_roles": {"humans": [], "bots": []},
            "categories": {}
        }
        _save(cfg)
        return cfg

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        raw = f.read().strip()
        if not raw:
            cfg = {
                "selfroles_channel_id": None,
                "selfroles_message_id": None,
                "logging": {"enabled": False, "channel_id": None},
                "auto_roles": {"humans": [], "bots": []},
                "categories": {}
            }
            _save(cfg)
            return cfg
        return json.loads(raw)


def _save(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _ensure_shape(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg.setdefault("selfroles_channel_id", None)
    cfg.setdefault("selfroles_message_id", None)
    cfg.setdefault("logging", {})
    cfg["logging"].setdefault("enabled", False)
    cfg["logging"].setdefault("channel_id", None)
    cfg.setdefault("auto_roles", {})
    cfg["auto_roles"].setdefault("humans", [])
    cfg["auto_roles"].setdefault("bots", [])
    cfg.setdefault("categories", {})
    # ensure each category has expected keys
    cats = cfg.get("categories", {}) or {}
    for key, cat in cats.items():
        if not isinstance(cat, dict):
            cats[key] = {"title": key, "description": "", "multi_select": True, "roles": {}}
            continue
        cat.setdefault("title", key)
        cat.setdefault("description", "")
        cat.setdefault("multi_select", True)
        cat.setdefault("roles", {})
    cfg["categories"] = cats
    return cfg


# =========================================================
# Permissions (Pilot source of truth)
# =========================================================

def _can_manage(member: discord.Member) -> bool:
    # Global admins always allowed, OR an app scope called "roles"
    # If you later add "roles" to pilotsettings scopes, it'll work without changing this file.
    return has_global_access(member) or has_app_access(member, "roles")


async def _no_perm(interaction: discord.Interaction):
    try:
        if interaction.response.is_done():
            await interaction.followup.send("❌ You do not have permission.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
    except Exception:
        pass


# =========================================================
# Discord helpers
# =========================================================

def _parse_emoji(raw: Optional[str]) -> Optional[discord.PartialEmoji]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except Exception:
        return None


def _me(guild: discord.Guild) -> Optional[discord.Member]:
    try:
        return guild.me or guild.get_member(guild.client.user.id)  # type: ignore
    except Exception:
        return None


def _is_assignable(role: discord.Role, bot_member: discord.Member) -> bool:
    # Guardrails we agreed:
    if role.is_default():  # @everyone
        return False
    if role.managed:  # integration / bot roles
        return False
    if role.permissions.administrator:  # block admin roles
        return False
    if role >= bot_member.top_role:  # must be strictly below bot's top role
        return False
    return True


def _sorted_categories(cfg: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    cats = cfg.get("categories", {}) or {}
    # stable display ordering: by title then key
    items = list(cats.items())
    items.sort(key=lambda kv: (str((kv[1] or {}).get("title") or kv[0]).lower(), kv[0]))
    return [(k, v) for k, v in items if isinstance(v, dict)]


# =========================================================
# Auto roles (humans vs bots)
# =========================================================

async def apply_auto_roles(member: discord.Member) -> None:
    try:
        cfg = _ensure_shape(_load())
    except Exception:
        return

    me = _me(member.guild)
    if not me:
        return

    target = "bots" if member.bot else "humans"
    role_ids = cfg.get("auto_roles", {}).get(target, []) or []

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
        if not _is_assignable(role, me):
            continue
        try:
            await member.add_roles(role, reason="Auto role assignment (selfroles)")
        except Exception:
            pass


# =========================================================
# Public self-roles view (fixed menus, live JSON)
# =========================================================

def _public_embed() -> discord.Embed:
    return discord.Embed(
        title="✨ Choose Your Roles",
        description="Use the menus below to update your roles.\nYou can change these any time ✈️",
        colour=discord.Colour.blurple(),
    )


class PublicCategorySelect(discord.ui.Select):
    """
    One of MAX_PUBLIC_MENUS slots. It reads current JSON on every interaction.
    Slot index selects the Nth category in sorted order.
    """
    def __init__(self, slot_index: int):
        self.slot_index = slot_index
        super().__init__(placeholder="Loading…", min_values=0, max_values=1, options=[discord.SelectOption(label="Loading…", value="__loading__")])

        # Build initial options (best effort). If JSON changes, callback rebuilds live anyway.
        self._rebuild_from_json()

    def _rebuild_from_json(self):
        try:
            cfg = _ensure_shape(_load())
        except Exception:
            self.placeholder = "Self roles unavailable"
            self.options = [discord.SelectOption(label="Config missing", value="__none__", default=True)]
            self.disabled = True
            return

        cats = _sorted_categories(cfg)
        if self.slot_index >= len(cats):
            self.placeholder = "—"
            self.options = [discord.SelectOption(label="No category", value="__none__", default=True)]
            self.disabled = True
            self.min_values = 0
            self.max_values = 1
            return

        key, cat = cats[self.slot_index]
        roles = cat.get("roles", {}) or {}
        opts: List[discord.SelectOption] = []

        for rid_str, meta in list(roles.items())[:25]:
            label = str((meta or {}).get("label") or "Role")
            emoji = _parse_emoji((meta or {}).get("emoji"))
            desc = (meta or {}).get("description")
            opts.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(rid_str),
                    emoji=emoji,
                    description=(str(desc)[:100] if desc else None),
                )
            )

        multi = bool(cat.get("multi_select", True))
        self.placeholder = str(cat.get("title") or key)[:150]
        self.options = opts if opts else [discord.SelectOption(label="(No roles)", value="__none__", default=True)]
        self.disabled = False if opts else True
        self.min_values = 0
        self.max_values = len(opts) if multi else 1
        if self.max_values < 1:
            self.max_values = 1

        # store current category key so callback knows which category this slot represents
        self.custom_id = f"selfroles:slot:{self.slot_index}:{key}"

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return await interaction.response.send_message("⚠️ Member not found.", ephemeral=True)

        # Always rebuild live (JSON can change without restart)
        self._rebuild_from_json()

        # Determine category key from custom_id
        parts = (self.custom_id or "").split(":")
        cat_key = parts[-1] if len(parts) >= 4 else None
        if not cat_key or cat_key == "__none__":
            return await interaction.response.send_message("⚠️ No category in this slot.", ephemeral=True)

        cfg = _ensure_shape(_load())
        cat = (cfg.get("categories", {}) or {}).get(cat_key)
        if not cat:
            return await interaction.response.send_message("⚠️ Category no longer exists.", ephemeral=True)

        me = _me(interaction.guild)
        if not me:
            return await interaction.response.send_message("⚠️ Bot member missing.", ephemeral=True)

        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}
        role_ids = {int(rid) for rid in roles_cfg.keys() if str(rid).isdigit()}
        selected = {int(v) for v in self.values if str(v).isdigit() and v != "__none__"}

        added: List[discord.Role] = []
        removed: List[discord.Role] = []

        # apply only within this category
        for rid in role_ids:
            role = interaction.guild.get_role(rid)
            if not role:
                continue
            if not _is_assignable(role, me):
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

        # ephemeral confirmation for user
        lines = ["✨ **Your roles have been updated.**"]
        if added:
            lines.append("✅ **Added:** " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("❌ **Removed:** " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("ℹ️ No changes made.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        # logging
        log_cfg = cfg.get("logging", {}) or {}
        if log_cfg.get("enabled") and log_cfg.get("channel_id") and (added or removed):
            chan = interaction.guild.get_channel(int(log_cfg["channel_id"]))
            if isinstance(chan, discord.TextChannel):
                emb = discord.Embed(title="🧩 Self-Role Update", colour=discord.Colour.blurple())
                emb.add_field(name="User", value=interaction.user.mention, inline=False)
                emb.add_field(name="Category", value=str(cat.get("title") or cat_key), inline=False)
                if added:
                    emb.add_field(name="Added", value=", ".join(r.mention for r in added), inline=False)
                if removed:
                    emb.add_field(name="Removed", value=", ".join(r.mention for r in removed), inline=False)
                try:
                    await chan.send(embed=emb)
                except Exception:
                    pass


class PublicSelfRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for i in range(MAX_PUBLIC_MENUS):
            self.add_item(PublicCategorySelect(i))


async def _deploy_or_update_menu(guild: discord.Guild) -> Tuple[bool, str]:
    cfg = _ensure_shape(_load())
    channel_id = cfg.get("selfroles_channel_id")
    if not channel_id:
        return False, "Self-roles channel not set."

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False, "Configured self-roles channel is missing or not a text channel."

    embed = _public_embed()
    view = PublicSelfRolesView()

    msg_id = cfg.get("selfroles_message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            return True, "✅ Updated existing self-role menu."
        except Exception:
            pass

    try:
        sent = await channel.send(embed=embed, view=view)
        cfg["selfroles_message_id"] = sent.id
        _save(cfg)
        return True, "✅ Posted a new self-role menu."
    except Exception as e:
        return False, f"Failed to post menu: {e}"


async def _try_autoupdate_menu(guild: Optional[discord.Guild]):
    # Called after admin changes so the public menu stays current without redeploy
    if not guild:
        return
    try:
        cfg = _ensure_shape(_load())
        if cfg.get("selfroles_channel_id") and cfg.get("selfroles_message_id"):
            await _deploy_or_update_menu(guild)
    except Exception:
        pass


# =========================================================
# Admin UI pieces
# =========================================================

class ChannelPickerView(discord.ui.View):
    def __init__(self, *, label: str, on_pick):
        super().__init__(timeout=180)
        self._on_pick = on_pick
        sel = discord.ui.ChannelSelect(
            placeholder=label,
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1
        )
        sel.callback = self._picked  # type: ignore
        self.add_item(sel)

    async def _picked(self, interaction: discord.Interaction):
        channel = interaction.data["values"][0]  # type: ignore
        await self._on_pick(interaction, int(channel))


class CategoryModal(discord.ui.Modal):
    def __init__(self, mode: str, existing_key: Optional[str] = None, existing: Optional[Dict[str, Any]] = None):
        super().__init__(title="Category Settings")
        self.mode = mode
        self.existing_key = existing_key

        self.key = discord.ui.TextInput(
            label="Category key (unique, no spaces) e.g. colours",
            required=True,
            max_length=50,
            default=existing_key or "",
        )
        self.title_in = discord.ui.TextInput(
            label="Title (shows on the menu) e.g. 🎨 Colour Roles",
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
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)

        cfg = _ensure_shape(_load())
        cats = cfg.get("categories", {}) or {}

        key = self.key.value.strip().lower().replace(" ", "_")
        if not key:
            return await interaction.response.send_message("❌ Category key is required.", ephemeral=True)

        multi_raw = self.multi.value.strip().lower()
        multi_select = multi_raw in ("yes", "y", "true", "1", "on")

        if self.mode == "add":
            if key in cats:
                return await interaction.response.send_message("❌ That category key already exists.", ephemeral=True)
            cats[key] = {
                "title": self.title_in.value.strip(),
                "description": self.desc.value.strip(),
                "multi_select": multi_select,
                "roles": {},
            }
        else:
            if not self.existing_key or self.existing_key not in cats:
                return await interaction.response.send_message("❌ Category no longer exists.", ephemeral=True)

            if key != self.existing_key:
                if key in cats:
                    return await interaction.response.send_message("❌ New key already exists.", ephemeral=True)
                cats[key] = cats.pop(self.existing_key)

            cats[key]["title"] = self.title_in.value.strip()
            cats[key]["description"] = self.desc.value.strip()
            cats[key]["multi_select"] = multi_select
            cats[key].setdefault("roles", {})

        cfg["categories"] = cats
        _save(cfg)

        await interaction.response.send_message("✅ Category saved.", ephemeral=True)
        await _try_autoupdate_menu(interaction.guild)
        
class CategoryPicker(discord.ui.Select):
    def __init__(self, placeholder: str, custom_id: str):
        cfg = _ensure_shape(_load())
        cats = cfg.get("categories", {}) or {}

        options: List[discord.SelectOption] = []
        if not cats:
            options = [discord.SelectOption(label="(No categories)", value="__none__", default=True)]
        else:
            for key, cat in _sorted_categories(cfg)[:25]:
                options.append(
                    discord.SelectOption(
                        label=str(cat.get("title") or key)[:100],
                        value=key,
                        description=(str(cat.get("description"))[:100] if cat.get("description") else None),
                    )
                )

        super().__init__(placeholder=placeholder, options=options[:25], min_values=1, max_values=1, custom_id=custom_id)


class CategoryManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.selected: Optional[str] = None

        self.sel = CategoryPicker("Select a category", "rolesettings:catpick")
        self.sel.callback = self._picked  # type: ignore
        self.add_item(self.sel)

    async def _picked(self, interaction: discord.Interaction):
        val = self.sel.values[0]
        if val == "__none__":
            self.selected = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.selected = val
        await interaction.response.send_message(f"✅ Selected `{val}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Category", style=discord.ButtonStyle.success)
    async def add_cat(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await interaction.response.send_modal(CategoryModal("add"))

    @discord.ui.button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary)
    async def edit_cat(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = _ensure_shape(_load())
        cat = (cfg.get("categories", {}) or {}).get(self.selected)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)
        await interaction.response.send_modal(CategoryModal("edit", self.selected, cat))

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def delete_cat(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = _ensure_shape(_load())
        cats = cfg.get("categories", {}) or {}
        if self.selected not in cats:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        del cats[self.selected]
        cfg["categories"] = cats
        _save(cfg)
        self.selected = None

        await interaction.response.send_message("✅ Category deleted.", ephemeral=True)
        await _try_autoupdate_menu(interaction.guild)


class RoleAddToCategoryView(discord.ui.View):
    def __init__(self, cat_key: str):
        super().__init__(timeout=180)
        self.cat_key = cat_key
        sel = discord.ui.RoleSelect(placeholder="Pick a role to add", min_values=1, max_values=1)
        sel.callback = self._picked  # type: ignore
        self.add_item(sel)
        self._sel = sel

    async def _picked(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        assert interaction.guild is not None

        role: discord.Role = self._sel.values[0]  # type: ignore
        me = _me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot missing.", ephemeral=True)
        if not _is_assignable(role, me):
            return await interaction.response.send_message("❌ That role is blocked / not manageable.", ephemeral=True)

        cfg = _ensure_shape(_load())
        cat = (cfg.get("categories", {}) or {}).get(self.cat_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles = cat.get("roles", {}) or {}
        rid = str(role.id)
        if rid in roles:
            return await interaction.response.send_message("ℹ️ Already in that category.", ephemeral=True)

        roles[rid] = {"label": role.name, "emoji": None, "description": None}
        cat["roles"] = roles
        _save(cfg)

        await interaction.response.send_message(f"✅ Added {role.mention} to `{self.cat_key}`.", ephemeral=True)
        await _try_autoupdate_menu(interaction.guild)


class RoleRemoveFromCategoryView(discord.ui.View):
    def __init__(self, cat_key: str):
        super().__init__(timeout=180)
        self.cat_key = cat_key

        cfg = _ensure_shape(_load())
        cat = (cfg.get("categories", {}) or {}).get(cat_key) or {}
        roles = cat.get("roles", {}) or {}

        opts: List[discord.SelectOption] = []
        for rid, meta in list(roles.items())[:25]:
            opts.append(
                discord.SelectOption(
                    label=str((meta or {}).get("label") or rid)[:100],
                    value=str(rid),
                    emoji=_parse_emoji((meta or {}).get("emoji")),
                )
            )
        if not opts:
            opts = [discord.SelectOption(label="(No roles)", value="__none__", default=True)]

        sel = discord.ui.Select(placeholder="Pick a role to remove", min_values=1, max_values=1, options=opts)
        sel.callback = self._picked  # type: ignore
        self.add_item(sel)
        self._sel = sel

    async def _picked(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)

        rid = self._sel.values[0]  # type: ignore
        if rid == "__none__":
            return await interaction.response.send_message("ℹ️ Nothing to remove.", ephemeral=True)

        cfg = _ensure_shape(_load())
        cat = (cfg.get("categories", {}) or {}).get(self.cat_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles = cat.get("roles", {}) or {}
        if rid in roles:
            del roles[rid]
        cat["roles"] = roles
        _save(cfg)

        await interaction.response.send_message("✅ Role removed from category.", ephemeral=True)
        await _try_autoupdate_menu(interaction.guild)


class RoleMetaModal(discord.ui.Modal):
    def __init__(self, cat_key: str, role_id: str, existing: Dict[str, Any]):
        super().__init__(title="Role Display Settings")
        self.cat_key = cat_key
        self.role_id = role_id

        self.label_in = discord.ui.TextInput(
            label="Label",
            required=True,
            max_length=100,
            default=str(existing.get("label") or "Role"),
        )
        self.emoji_in = discord.ui.TextInput(
            label="Emoji (optional) unicode or <:name:id>",
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
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)

        emoji_str = self.emoji_in.value.strip()
        if emoji_str and not _parse_emoji(emoji_str):
            return await interaction.response.send_message("❌ Emoji format invalid.", ephemeral=True)

        cfg = _ensure_shape(_load())
        cat = (cfg.get("categories", {}) or {}).get(self.cat_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)
        roles = cat.get("roles", {}) or {}
        if self.role_id not in roles:
            return await interaction.response.send_message("❌ Role missing in category.", ephemeral=True)

        roles[self.role_id]["label"] = self.label_in.value.strip()
        roles[self.role_id]["emoji"] = emoji_str or None
        roles[self.role_id]["description"] = self.desc_in.value.strip() or None
        cat["roles"] = roles
        _save(cfg)

        await interaction.response.send_message("✅ Role display updated.", ephemeral=True)
        await _try_autoupdate_menu(interaction.guild)


class RoleMetaPickerView(discord.ui.View):
    def __init__(self, cat_key: str):
        super().__init__(timeout=180)
        self.cat_key = cat_key

        cfg = _ensure_shape(_load())
        cat = (cfg.get("categories", {}) or {}).get(cat_key) or {}
        roles = cat.get("roles", {}) or {}

        opts: List[discord.SelectOption] = []
        for rid, meta in list(roles.items())[:25]:
            opts.append(
                discord.SelectOption(
                    label=str((meta or {}).get("label") or rid)[:100],
                    value=str(rid),
                    emoji=_parse_emoji((meta or {}).get("emoji")),
                )
            )
        if not opts:
            opts = [discord.SelectOption(label="(No roles)", value="__none__", default=True)]

        sel = discord.ui.Select(placeholder="Pick a role to edit", min_values=1, max_values=1, options=opts)
        sel.callback = self._picked  # type: ignore
        self.add_item(sel)
        self._sel = sel

    async def _picked(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)

        rid = self._sel.values[0]  # type: ignore
        if rid == "__none__":
            return await interaction.response.send_message("ℹ️ Nothing to edit.", ephemeral=True)

        cfg = _ensure_shape(_load())
        cat = (cfg.get("categories", {}) or {}).get(self.cat_key) or {}
        meta = (cat.get("roles", {}) or {}).get(rid) or {}
        await interaction.response.send_modal(RoleMetaModal(self.cat_key, rid, meta))


class RoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.selected: Optional[str] = None

        sel = CategoryPicker("Select category to manage roles", "rolesettings:rolecat")
        sel.callback = self._picked  # type: ignore
        self.add_item(sel)
        self._sel = sel

    async def _picked(self, interaction: discord.Interaction):
        val = self._sel.values[0]
        if val == "__none__":
            self.selected = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.selected = val
        await interaction.response.send_message(f"✅ Selected `{val}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Role", style=discord.ButtonStyle.success)
    async def add_role(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        await interaction.response.send_message("Pick a role:", view=RoleAddToCategoryView(self.selected), ephemeral=True)

    @discord.ui.button(label="➖ Remove Role", style=discord.ButtonStyle.danger)
    async def remove_role(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        await interaction.response.send_message("Pick a role to remove:", view=RoleRemoveFromCategoryView(self.selected), ephemeral=True)

    @discord.ui.button(label="😀 Edit Emoji/Label/Desc", style=discord.ButtonStyle.primary)
    async def edit_meta(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        await interaction.response.send_message("Pick a role to edit:", view=RoleMetaPickerView(self.selected), ephemeral=True)


class AutoRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def _pick(self, interaction: discord.Interaction, target: str):
        assert interaction.guild is not None
        me = _me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot missing.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        sel = discord.ui.RoleSelect(placeholder="Pick a role", min_values=1, max_values=1)

        async def cb(i: discord.Interaction):
            if not isinstance(i.user, discord.Member) or not _can_manage(i.user):
                return await _no_perm(i)

            role: discord.Role = sel.values[0]  # type: ignore
            if not _is_assignable(role, me):
                return await i.response.send_message("❌ That role is blocked / not manageable.", ephemeral=True)

            cfg = _ensure_shape(_load())
            arr = cfg.get("auto_roles", {}).get(target, []) or []
            rid = str(role.id)
            if rid not in arr:
                arr.append(rid)
            cfg["auto_roles"][target] = arr
            _save(cfg)
            await i.response.send_message(f"✅ Added {role.mention} to auto-roles ({target}).", ephemeral=True)

        sel.callback = cb  # type: ignore
        view.add_item(sel)
        await interaction.response.send_message("Pick a role:", view=view, ephemeral=True)

    async def _remove(self, interaction: discord.Interaction, target: str):
        cfg = _ensure_shape(_load())
        arr = cfg.get("auto_roles", {}).get(target, []) or []
        if not arr:
            return await interaction.response.send_message("ℹ️ None set.", ephemeral=True)

        opts: List[discord.SelectOption] = []
        for rid in arr[:25]:
            role = interaction.guild.get_role(int(rid)) if interaction.guild else None
            opts.append(discord.SelectOption(label=(role.name if role else rid), value=str(rid)))

        sel = discord.ui.Select(placeholder="Pick one to remove", min_values=1, max_values=1, options=opts)

        async def cb(i: discord.Interaction):
            if not isinstance(i.user, discord.Member) or not _can_manage(i.user):
                return await _no_perm(i)
            rid = sel.values[0]
            cfg2 = _ensure_shape(_load())
            arr2 = cfg2.get("auto_roles", {}).get(target, []) or []
            if rid in arr2:
                arr2.remove(rid)
            cfg2["auto_roles"][target] = arr2
            _save(cfg2)
            await i.response.send_message("✅ Removed.", ephemeral=True)

        sel.callback = cb  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(sel)
        await interaction.response.send_message("Pick one:", view=v, ephemeral=True)

    @discord.ui.button(label="➕ Add Human Auto-Role", style=discord.ButtonStyle.success)
    async def add_h(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await self._pick(interaction, "humans")

    @discord.ui.button(label="➕ Add Bot Auto-Role", style=discord.ButtonStyle.success)
    async def add_b(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await self._pick(interaction, "bots")

    @discord.ui.button(label="➖ Remove Human Auto-Role", style=discord.ButtonStyle.danger)
    async def rem_h(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await self._remove(interaction, "humans")

    @discord.ui.button(label="➖ Remove Bot Auto-Role", style=discord.ButtonStyle.danger)
    async def rem_b(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await self._remove(interaction, "bots")


class LoggingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔁 Toggle Logging", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        cfg = _ensure_shape(_load())
        cfg["logging"]["enabled"] = not bool(cfg.get("logging", {}).get("enabled"))
        _save(cfg)
        state = "ON" if cfg["logging"]["enabled"] else "OFF"
        await interaction.response.send_message(f"🧾 Logging is now **{state}**.", ephemeral=True)

    @discord.ui.button(label="📍 Set Log Channel", style=discord.ButtonStyle.secondary)
    async def set_chan(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)

        async def on_pick(i: discord.Interaction, cid: int):
            cfg = _ensure_shape(_load())
            cfg["logging"]["channel_id"] = cid
            _save(cfg)
            await i.response.send_message(f"✅ Log channel set to <#{cid}>", ephemeral=True)

        await interaction.response.send_message("Pick a log channel:", view=ChannelPickerView(label="Select log channel…", on_pick=on_pick), ephemeral=True)

    @discord.ui.button(label="🧹 Clear Log Channel", style=discord.ButtonStyle.danger)
    async def clear_chan(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        cfg = _ensure_shape(_load())
        cfg["logging"]["channel_id"] = None
        _save(cfg)
        await interaction.response.send_message("✅ Log channel cleared.", ephemeral=True)


# ---------------- Admin assign/remove roles (ALL roles, guardrails) ----------------

class PickUserView(discord.ui.View):
    def __init__(self, mode: str):
        super().__init__(timeout=180)
        self.mode = mode
        sel = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        sel.callback = self._picked  # type: ignore
        self.add_item(sel)
        self._sel = sel

    async def _picked(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        user = self._sel.values[0]  # type: ignore
        if self.mode == "assign":
            await interaction.response.send_message(f"Pick a role to **assign** to {user.mention}:", view=PickRoleAssignView(user.id), ephemeral=True)
        else:
            v = PickRoleRemoveView(user.id)
            await v._populate(interaction.guild)
            await interaction.response.send_message(f"Pick a role to **remove** from {user.mention}:", view=v, ephemeral=True)


class PickRoleAssignView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        sel = discord.ui.RoleSelect(placeholder="Pick a role", min_values=1, max_values=1)
        sel.callback = self._picked  # type: ignore
        self.add_item(sel)
        self._sel = sel

    async def _picked(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        assert interaction.guild is not None

        me = _me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot missing.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("❌ User not found.", ephemeral=True)

        role: discord.Role = self._sel.values[0]  # type: ignore
        if not _is_assignable(role, me):
            return await interaction.response.send_message("❌ That role is blocked / not manageable.", ephemeral=True)

        if role in member.roles:
            return await interaction.response.send_message("ℹ️ They already have that role.", ephemeral=True)

        try:
            await member.add_roles(role, reason=f"Admin assign via rolesettings by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed to assign (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Assigned {role.mention} to {member.mention}", ephemeral=True)

        cfg = _ensure_shape(_load())
        log = cfg.get("logging", {}) or {}
        if log.get("enabled") and log.get("channel_id"):
            ch = interaction.guild.get_channel(int(log["channel_id"]))
            if isinstance(ch, discord.TextChannel):
                emb = discord.Embed(title="🛂 Role Assigned", colour=discord.Colour.green())
                emb.add_field(name="Admin", value=interaction.user.mention, inline=False)
                emb.add_field(name="User", value=member.mention, inline=False)
                emb.add_field(name="Role", value=role.mention, inline=False)
                try:
                    await ch.send(embed=emb)
                except Exception:
                    pass


class PickRoleRemoveView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.sel = discord.ui.Select(placeholder="Loading…", min_values=1, max_values=1, options=[discord.SelectOption(label="Loading…", value="__loading__")])
        self.sel.callback = self._picked  # type: ignore
        self.add_item(self.sel)

    async def _populate(self, guild: Optional[discord.Guild]):
        if not guild:
            self.sel.options = [discord.SelectOption(label="(Guild missing)", value="__none__", default=True)]
            self.sel.disabled = True
            return

        member = guild.get_member(self.user_id)
        me = _me(guild)
        if not member or not me:
            self.sel.options = [discord.SelectOption(label="(Missing)", value="__none__", default=True)]
            self.sel.disabled = True
            return

        manageable = [r for r in member.roles if _is_assignable(r, me)]
        manageable.sort(key=lambda r: r.position, reverse=True)

        opts: List[discord.SelectOption] = []
        for r in manageable[:25]:
            opts.append(discord.SelectOption(label=r.name[:100], value=str(r.id)))
        if not opts:
            opts = [discord.SelectOption(label="(No removable roles)", value="__none__", default=True)]
            self.sel.disabled = True
        else:
            self.sel.disabled = False
        self.sel.options = opts

    async def _picked(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        assert interaction.guild is not None

        val = self.sel.values[0]
        if val == "__none__":
            return await interaction.response.send_message("ℹ️ Nothing to remove.", ephemeral=True)

        me = _me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot missing.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("❌ User not found.", ephemeral=True)

        role = interaction.guild.get_role(int(val))
        if not role or not _is_assignable(role, me):
            return await interaction.response.send_message("❌ Role blocked / not manageable.", ephemeral=True)

        if role not in member.roles:
            return await interaction.response.send_message("ℹ️ They don’t have that role.", ephemeral=True)

        try:
            await member.remove_roles(role, reason=f"Admin remove via rolesettings by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed to remove (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Removed {role.mention} from {member.mention}", ephemeral=True)

        cfg = _ensure_shape(_load())
        log = cfg.get("logging", {}) or {}
        if log.get("enabled") and log.get("channel_id"):
            ch = interaction.guild.get_channel(int(log["channel_id"]))
            if isinstance(ch, discord.TextChannel):
                emb = discord.Embed(title="🛂 Role Removed", colour=discord.Colour.red())
                emb.add_field(name="Admin", value=interaction.user.mention, inline=False)
                emb.add_field(name="User", value=member.mention, inline=False)
                emb.add_field(name="Role", value=role.mention, inline=False)
                try:
                    await ch.send(embed=emb)
                except Exception:
                    pass


class AdminAssignRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ Assign Role to User", style=discord.ButtonStyle.success)
    async def assign(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await interaction.response.send_message("Pick a user:", view=PickUserView("assign"), ephemeral=True)

    @discord.ui.button(label="➖ Remove Role from User", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await interaction.response.send_message("Pick a user:", view=PickUserView("remove"), ephemeral=True)


# =========================================================
# Main /rolesettings dashboard
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def set_selfroles_channel(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)

        async def on_pick(i: discord.Interaction, cid: int):
            cfg = _ensure_shape(_load())
            cfg["selfroles_channel_id"] = cid
            _save(cfg)
            await i.response.send_message(f"✅ Self-roles channel set to <#{cid}>", ephemeral=True)

        await interaction.response.send_message("Pick the self-roles channel:", view=ChannelPickerView(label="Select self-roles channel…", on_pick=on_pick), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Public Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        ok, msg = await _deploy_or_update_menu(interaction.guild)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=True)

    @discord.ui.button(label="📂 Categories", style=discord.ButtonStyle.secondary)
    async def categories(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await interaction.response.send_message("Category manager:", view=CategoryManagerView(), ephemeral=True)

    @discord.ui.button(label="🎭 Roles in Categories", style=discord.ButtonStyle.secondary)
    async def roles(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await interaction.response.send_message("Role manager:", view=RoleManagerView(), ephemeral=True)

    @discord.ui.button(label="👥 Auto Roles", style=discord.ButtonStyle.secondary)
    async def autoroles(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await interaction.response.send_message("Auto-roles:", view=AutoRolesView(), ephemeral=True)

    @discord.ui.button(label="🧾 Logging", style=discord.ButtonStyle.secondary)
    async def logging(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        cfg = _ensure_shape(_load())
        state = "ON" if cfg.get("logging", {}).get("enabled") else "OFF"
        chan = cfg.get("logging", {}).get("channel_id")
        extra = f"\nCurrent: **{state}** | Channel: {f'<#{chan}>' if chan else 'Not set'}"
        await interaction.response.send_message("Logging settings:" + extra, view=LoggingView(), ephemeral=True)

    @discord.ui.button(label="🛂 Admin Assign Roles", style=discord.ButtonStyle.primary)
    async def admin_assign(self, interaction: discord.Interaction, _):
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            return await _no_perm(interaction)
        await interaction.response.send_message("User role management:", view=AdminAssignRolesView(), ephemeral=True)


@app_commands.command(name="rolesettings", description="Admin panel for self roles")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
        return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

    cfg = _ensure_shape(_load())
    ch = cfg.get("selfroles_channel_id")
    msg_id = cfg.get("selfroles_message_id")
    log = cfg.get("logging", {}) or {}

    desc = [
        f"📍 **Self-roles channel:** {f'<#{ch}>' if ch else 'Not set'}",
        f"📌 **Menu message:** {'Set' if msg_id else 'Not posted yet'}",
        f"🧾 **Logging:** {'ON' if log.get('enabled') else 'OFF'}",
    ]
    if log.get("channel_id"):
        desc.append(f"🧾 **Log channel:** <#{log['channel_id']}>")

    embed = discord.Embed(title="⚙️ Role Settings", description="\n".join(desc), colour=discord.Colour.blurple())
    await interaction.response.send_message(embed=embed, view=RoleSettingsDashboard(), ephemeral=True)


# =========================================================
# Setup
# =========================================================

def setup(tree: app_commands.CommandTree, client: discord.Client):
    tree.add_command(rolesettings)

    # Register persistent public view so it survives restarts
    try:
        client.add_view(PublicSelfRolesView())
    except Exception:
        pass