from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands

from permissions import has_app_access  # ✅ Pilot permissions source of truth

CONFIG_FILE = "selfroles.json"


# =========================================================
# JSON helpers
# =========================================================

def _load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        raise RuntimeError("selfroles.json missing")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        raw = f.read().strip()
        return json.loads(raw) if raw else {}


def _save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _ensure_shape(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg.setdefault("selfroles_channel_id", None)
    cfg.setdefault("selfroles_message_id", None)
    cfg.setdefault("logging", {"enabled": False, "channel_id": None})
    cfg.setdefault("auto_roles", {"humans": [], "bots": []})
    cfg.setdefault("categories", {})
    cfg["logging"].setdefault("enabled", False)
    cfg["logging"].setdefault("channel_id", None)
    cfg["auto_roles"].setdefault("humans", [])
    cfg["auto_roles"].setdefault("bots", [])
    return cfg


# =========================================================
# Misc helpers
# =========================================================

def _get_me(guild: discord.Guild) -> Optional[discord.Member]:
    # guild.me is deprecated-ish but still present; fallback to member lookup
    try:
        if guild.me:
            return guild.me
    except Exception:
        pass
    try:
        if guild.client and guild.client.user:
            return guild.get_member(guild.client.user.id)
    except Exception:
        pass
    return None


def _parse_emoji(raw: Optional[str]) -> Optional[discord.PartialEmoji]:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return discord.PartialEmoji.from_str(s)
    except Exception:
        return None


def _strip_custom_emoji(text: str) -> str:
    # placeholders can be flaky on mobile with custom emoji. remove them there only.
    return re.sub(r"<a?:\w+:\d+>", "", text or "").strip()


def _role_auto_emoji(role: discord.Role) -> Optional[discord.PartialEmoji]:
    # Discord "role emoji" feature is unicode_emoji (string)
    uni = getattr(role, "unicode_emoji", None)
    if uni:
        return _parse_emoji(uni)
    return None


def _is_role_assignable(role: discord.Role, me: discord.Member) -> bool:
    # blocks we agreed
    if role.is_default():  # @everyone
        return False
    if role.managed:  # integration/bot roles
        return False
    if role.permissions.administrator:  # admin roles blocked
        return False
    if role >= me.top_role:
        return False
    return True


def _admin_ok(member: discord.Member) -> bool:
    # ✅ Use Pilot "roles" scope
    return has_app_access(member, "roles")


async def _log(guild: discord.Guild, *, title: str, fields: List[Tuple[str, str]], color: discord.Color):
    try:
        cfg = _ensure_shape(_load_config())
    except Exception:
        return

    log_cfg = cfg.get("logging", {}) or {}
    if not log_cfg.get("enabled"):
        return
    cid = log_cfg.get("channel_id")
    if not cid:
        return

    chan = guild.get_channel(int(cid))
    if not isinstance(chan, discord.TextChannel):
        return

    emb = discord.Embed(title=title, colour=color)
    for n, v in fields:
        emb.add_field(name=n, value=v, inline=False)
    try:
        await chan.send(embed=emb)
    except Exception:
        pass


# =========================================================
# Auto roles (humans vs bots)
# =========================================================

async def apply_auto_roles(member: discord.Member) -> None:
    try:
        cfg = _ensure_shape(_load_config())
    except Exception:
        return

    me = _get_me(member.guild)
    if not me:
        return

    target = "bots" if member.bot else "humans"
    role_ids = cfg.get("auto_roles", {}).get(target, []) or []

    for rid in role_ids:
        try:
            role = member.guild.get_role(int(rid))
        except Exception:
            role = None
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
# PUBLIC self-role flow (NO redeploy needed for changes)
# One persistent menu: pick category -> ephemeral role picker
# =========================================================

class PublicCategoryPicker(discord.ui.Select):
    def __init__(self):
        cfg = _ensure_shape(_load_config())
        cats: Dict[str, Any] = cfg.get("categories", {}) or {}

        options: List[discord.SelectOption] = []
        for key, cat in list(cats.items())[:25]:
            title = str(cat.get("title") or key)
            options.append(discord.SelectOption(
                label=_strip_custom_emoji(title)[:100],
                value=key,
            ))

        if not options:
            options = [discord.SelectOption(label="(No categories yet)", value="__none__")]

        super().__init__(
            placeholder="Choose a category…",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("⚠️ Guild missing.", ephemeral=True)

        key = self.values[0]
        if key == "__none__":
            return await interaction.response.send_message("ℹ️ No self-roles available yet.", ephemeral=True)

        cfg = _ensure_shape(_load_config())
        cat = (cfg.get("categories", {}) or {}).get(key)
        if not cat:
            return await interaction.response.send_message("⚠️ That category no longer exists.", ephemeral=True)

        await interaction.response.send_message(
            f"**{cat.get('title', key)}**\nSelect your roles:",
            view=PublicRolePickerView(category_key=key),
            ephemeral=True
        )


class PublicRolePicker(discord.ui.Select):
    def __init__(self, category_key: str):
        self.category_key = category_key

        cfg = _ensure_shape(_load_config())
        cat = (cfg.get("categories", {}) or {}).get(category_key) or {}
        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}

        options: List[discord.SelectOption] = []
        for rid_str, meta in list(roles_cfg.items())[:25]:
            label = str(meta.get("label") or "Role")[:100]
            emoji = _parse_emoji(meta.get("emoji"))
            options.append(discord.SelectOption(label=label, value=str(rid_str), emoji=emoji))

        multi = bool(cat.get("multi_select", True))
        super().__init__(
            placeholder="Pick roles…",
            min_values=0,
            max_values=len(options) if (multi and options) else 1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("⚠️ Guild missing.", ephemeral=True)

        member = guild.get_member(interaction.user.id)
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("⚠️ Member missing.", ephemeral=True)

        me = _get_me(guild)
        if not me:
            return await interaction.response.send_message("⚠️ Bot member missing.", ephemeral=True)

        cfg = _ensure_shape(_load_config())
        cat = (cfg.get("categories", {}) or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("⚠️ Category missing.", ephemeral=True)

        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}
        role_ids = {int(r) for r in roles_cfg.keys() if str(r).isdigit()}
        selected = {int(v) for v in self.values if str(v).isdigit()}

        added: List[discord.Role] = []
        removed: List[discord.Role] = []

        for rid in role_ids:
            role = guild.get_role(rid)
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

        # Ephemeral confirmation (your requirement)
        lines: List[str] = ["✨ **Your roles have been updated.**"]
        if added:
            lines.append("✅ **Added:** " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("❌ **Removed:** " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("ℹ️ No changes made.")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        # Optional logging
        if (added or removed):
            await _log(
                guild,
                title="🧩 Self-Role Update",
                color=discord.Color.blurple(),
                fields=[
                    ("User", interaction.user.mention),
                    ("Category", str(cat.get("title") or self.category_key)),
                    ("Added", ", ".join(r.mention for r in added) if added else "—"),
                    ("Removed", ", ".join(r.mention for r in removed) if removed else "—"),
                ],
            )


class PublicRolePickerView(discord.ui.View):
    def __init__(self, category_key: str):
        super().__init__(timeout=180)
        self.add_item(PublicRolePicker(category_key))


class PublicSelfRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PublicCategoryPicker())


async def _deploy_or_update_public_menu(guild: discord.Guild) -> Tuple[bool, str]:
    cfg = _ensure_shape(_load_config())
    channel_id = cfg.get("selfroles_channel_id")
    if not channel_id:
        return False, "Self-roles channel not set."

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False, "Configured self-roles channel is missing or not a text channel."

    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Pick a category, then pick your roles.\nYou can change these any time ✈️",
        colour=discord.Colour.blurple(),
    )

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
        _save_config(cfg)
        return True, "✅ Posted a new self-role menu."
    except Exception as e:
        return False, f"Failed to post menu: {e}"

# =========================================================
# ADMIN UI helpers
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
        channel = self.children[0].values[0]  # type: ignore
        cfg = _ensure_shape(_load_config())
        cfg["selfroles_channel_id"] = channel.id
        _save_config(cfg)
        await interaction.response.send_message(f"📍 Self-roles channel set to {channel.mention}", ephemeral=True)


class _SetLogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.ChannelSelect(
            placeholder="Select the log channel for role updates",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        sel.callback = self._on_select  # type: ignore
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        channel = self.children[0].values[0]  # type: ignore
        cfg = _ensure_shape(_load_config())
        cfg["logging"]["channel_id"] = channel.id
        _save_config(cfg)
        await interaction.response.send_message(f"🧾 Log channel set to {channel.mention}", ephemeral=True)


# =========================================================
# ADMIN: Category editor
# =========================================================

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
            label="Title (shows to users) e.g. 🎨 Colour Roles",
            required=True,
            max_length=150,
            default=(existing.get("title") if existing else "") or "",
        )
        self.desc = discord.ui.TextInput(
            label="Description (optional, admin notes)",
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
        cfg = _ensure_shape(_load_config())
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
    def __init__(self, placeholder: str, include_empty: bool = True):
        cfg = _ensure_shape(_load_config())
        cats: Dict[str, Any] = cfg.get("categories", {}) or {}

        options: List[discord.SelectOption] = []
        if include_empty and not cats:
            options.append(discord.SelectOption(label="(No categories yet)", value="__none__", default=True))

        for key, cat in list(cats.items())[:25]:
            title = str(cat.get("title") or key)
            options.append(discord.SelectOption(
                label=_strip_custom_emoji(title)[:100],
                value=key,
                description=(str(cat.get("description"))[:100] if cat.get("description") else None),
            ))

        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options[:25])


class CategoryManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.selected_key: Optional[str] = None

        self.cat_select = CategoryPicker("Select a category to edit/delete", include_empty=True)
        self.cat_select.callback = self._on_select  # type: ignore
        self.add_item(self.cat_select)

    async def _on_select(self, interaction: discord.Interaction):
        key = self.cat_select.values[0]
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
        cfg = _ensure_shape(_load_config())
        cat = cfg.get("categories", {}).get(self.selected_key)
        if not cat:
            return await interaction.response.send_message("❌ Category not found.", ephemeral=True)
        await interaction.response.send_modal(CategoryModal(mode="edit", existing_key=self.selected_key, existing=cat))

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def delete_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = _ensure_shape(_load_config())
        cats = cfg.get("categories", {}) or {}
        if self.selected_key not in cats:
            return await interaction.response.send_message("❌ Category not found.", ephemeral=True)
        del cats[self.selected_key]
        cfg["categories"] = cats
        _save_config(cfg)
        self.selected_key = None
        await interaction.response.send_message("✅ Category deleted.", ephemeral=True)


# =========================================================
# ADMIN: Role editor (multi-add + emoji auto-pull + emoji override)
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

        self.add_item(self.label_in)
        self.add_item(self.emoji_in)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = _ensure_shape(_load_config())
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category not found.", ephemeral=True)

        roles = cat.get("roles", {}) or {}
        rk = str(self.role_id)
        if rk not in roles:
            return await interaction.response.send_message("❌ Role not found in that category.", ephemeral=True)

        emoji_str = self.emoji_in.value.strip()
        if emoji_str and not _parse_emoji(emoji_str):
            return await interaction.response.send_message("❌ That emoji format looks invalid.", ephemeral=True)

        roles[rk]["label"] = self.label_in.value.strip()

        # optional override
        if emoji_str:
            roles[rk]["emoji"] = emoji_str
        else:
            roles[rk]["emoji"] = roles[rk].get("emoji")

        cat["roles"] = roles
        _save_config(cfg)
        await interaction.response.send_message("✅ Role display updated.", ephemeral=True)


class RoleManagerView(discord.ui.View):
    """
    Reduced friction: pick category once (stored on view), then actions.
    """
    def __init__(self):
        super().__init__(timeout=300)
        self.category_key: Optional[str] = None

        self.cat_select = CategoryPicker("Select a category to manage roles", include_empty=True)
        self.cat_select.callback = self._on_cat  # type: ignore
        self.add_item(self.cat_select)

    async def _on_cat(self, interaction: discord.Interaction):
        key = self.cat_select.values[0]
        if key == "__none__":
            self.category_key = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.category_key = key
        await interaction.response.send_message(f"✅ Selected category: `{key}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Roles (multi)", style=discord.ButtonStyle.success)
    async def add_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        me = _get_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        role_select = discord.ui.RoleSelect(
            placeholder="Pick roles to add (up to 25)",
            min_values=1,
            max_values=25,
        )

        async def on_pick(i: discord.Interaction):
            assert i.guild is not None
            me2 = _get_me(i.guild)
            if not me2:
                return await i.response.send_message("❌ Bot member missing.", ephemeral=True)

            cfg = _ensure_shape(_load_config())
            cat = cfg.get("categories", {}).get(self.category_key)
            if not cat:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)

            roles_cfg = cat.get("roles", {}) or {}
            added: List[discord.Role] = []

            for role in role_select.values:
                if not _is_role_assignable(role, me2):
                    continue

                rid = str(role.id)
                if rid in roles_cfg:
                    continue

                # ✅ auto pull emoji from role.unicode_emoji if exists
                auto_emoji = _role_auto_emoji(role)
                roles_cfg[rid] = {
                    "label": role.name,
                    "emoji": (str(auto_emoji) if auto_emoji else None),
                }
                added.append(role)

            cat["roles"] = roles_cfg
            _save_config(cfg)

            if added:
                await i.response.send_message(
                    "✅ Added: " + ", ".join(r.mention for r in added),
                    ephemeral=True
                )
            else:
                await i.response.send_message("ℹ️ Nothing added (blocked / duplicates).", ephemeral=True)

        role_select.callback = on_pick  # type: ignore
        view.add_item(role_select)
        await interaction.response.send_message("Select roles to add:", view=view, ephemeral=True)

    @discord.ui.button(label="➖ Remove Role", style=discord.ButtonStyle.danger)
    async def remove_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = _ensure_shape(_load_config())
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}
        if not roles_cfg:
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

        options: List[discord.SelectOption] = []
        for rid_str, meta in list(roles_cfg.items())[:25]:
            options.append(discord.SelectOption(
                label=str(meta.get("label") or rid_str)[:100],
                value=rid_str,
                emoji=_parse_emoji(meta.get("emoji") or None),
            ))

        select = discord.ui.Select(placeholder="Pick a role to remove", min_values=1, max_values=1, options=options)

        async def on_remove(i: discord.Interaction):
            rid_str = select.values[0]
            cfg2 = _ensure_shape(_load_config())
            cat2 = cfg2.get("categories", {}).get(self.category_key)
            if not cat2:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)

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

    @discord.ui.button(label="😀 Edit Label/Emoji", style=discord.ButtonStyle.primary)
    async def edit_display(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = _ensure_shape(_load_config())
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}
        if not roles_cfg:
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

        options: List[discord.SelectOption] = []
        for rid_str, meta in list(roles_cfg.items())[:25]:
            options.append(discord.SelectOption(
                label=str(meta.get("label") or rid_str)[:100],
                value=rid_str,
                emoji=_parse_emoji(meta.get("emoji") or None),
            ))

        select = discord.ui.Select(placeholder="Pick a role to edit", min_values=1, max_values=1, options=options)

        async def on_pick(i: discord.Interaction):
            rid_str = select.values[0]
            cfg2 = _ensure_shape(_load_config())
            cat2 = cfg2.get("categories", {}).get(self.category_key)
            if not cat2:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)
            meta = (cat2.get("roles", {}) or {}).get(rid_str)
            if not meta:
                return await i.response.send_message("❌ Role missing.", ephemeral=True)
            await i.response.send_modal(RoleDisplayModal(self.category_key, int(rid_str), meta))

        select.callback = on_pick  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(select)
        await interaction.response.send_message("Select a role to edit:", view=v, ephemeral=True)


# =========================================================
# ADMIN: Auto roles panel
# =========================================================

class AutoRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def _pick_auto_role(self, interaction: discord.Interaction, target: str):
        assert interaction.guild is not None
        me = _get_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        role_select = discord.ui.RoleSelect(placeholder="Pick an auto-role", min_values=1, max_values=1)

        async def on_pick(i: discord.Interaction):
            role: discord.Role = role_select.values[0]
            if not _is_role_assignable(role, me):
                return await i.response.send_message("❌ That role can’t be managed (or is blocked).", ephemeral=True)

            cfg = _ensure_shape(_load_config())
            cfg.setdefault("auto_roles", {"humans": [], "bots": []})
            arr = cfg["auto_roles"].setdefault(target, [])
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
        cfg = _ensure_shape(_load_config())
        arr = cfg.get("auto_roles", {}).get(target, []) or []
        if not arr:
            return await interaction.response.send_message("ℹ️ None set.", ephemeral=True)

        options: List[discord.SelectOption] = []
        for rid_str in arr[:25]:
            role = interaction.guild.get_role(int(rid_str)) if interaction.guild else None
            options.append(discord.SelectOption(label=(role.name if role else rid_str), value=rid_str))

        select = discord.ui.Select(placeholder="Pick one to remove", min_values=1, max_values=1, options=options)

        async def on_remove(i: discord.Interaction):
            rid_str = select.values[0]
            cfg2 = _ensure_shape(_load_config())
            arr2 = cfg2.get("auto_roles", {}).get(target, []) or []
            if rid_str in arr2:
                arr2.remove(rid_str)
            cfg2["auto_roles"][target] = arr2
            _save_config(cfg2)
            await i.response.send_message("✅ Removed.", ephemeral=True)

        select.callback = on_remove  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(select)
        await interaction.response.send_message("Select one to remove:", view=v, ephemeral=True)

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


# =========================================================
# ADMIN: Logging panel
# =========================================================

class LoggingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔁 Toggle Logging", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = _ensure_shape(_load_config())
        cfg["logging"]["enabled"] = not bool(cfg["logging"].get("enabled"))
        _save_config(cfg)
        state = "ON" if cfg["logging"]["enabled"] else "OFF"
        await interaction.response.send_message(f"🧾 Logging is now **{state}**.", ephemeral=True)

    @discord.ui.button(label="📍 Set Log Channel", style=discord.ButtonStyle.secondary)
    async def set_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a log channel:", view=_SetLogChannelView(), ephemeral=True)

    @discord.ui.button(label="🧹 Clear Log Channel", style=discord.ButtonStyle.danger)
    async def clear_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = _ensure_shape(_load_config())
        cfg["logging"]["channel_id"] = None
        _save_config(cfg)
        await interaction.response.send_message("✅ Log channel cleared.", ephemeral=True)


# =========================================================
# ADMIN: Assign/remove roles to a user (ALL roles w/ guardrails)
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
        sel = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        sel.callback = self._on_pick  # type: ignore
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction):
        user = self.children[0].values[0]  # type: ignore
        await interaction.response.send_message(
            f"Now select a role to **assign** to {user.mention}:",
            view=_PickRoleToAssignView(user_id=user.id),
            ephemeral=True,
        )


class _PickRoleToAssignView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        sel = discord.ui.RoleSelect(placeholder="Pick a role", min_values=1, max_values=1)
        sel.callback = self._on_pick  # type: ignore
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        me = _get_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("❌ User not found in this guild.", ephemeral=True)

        role: discord.Role = self.children[0].values[0]  # type: ignore
        if not _is_role_assignable(role, me):
            return await interaction.response.send_message("❌ That role is blocked or not manageable by the bot.", ephemeral=True)

        if role in member.roles:
            return await interaction.response.send_message("ℹ️ They already have that role.", ephemeral=True)

        try:
            await member.add_roles(role, reason=f"Admin role assign by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed to assign that role (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Assigned {role.mention} to {member.mention}", ephemeral=True)

        await _log(
            interaction.guild,
            title="🛂 Role Assigned",
            color=discord.Color.green(),
            fields=[
                ("Admin", interaction.user.mention),
                ("User", member.mention),
                ("Role", role.mention),
            ],
        )


class _PickUserForRemoveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        sel.callback = self._on_pick  # type: ignore
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction):
        user = self.children[0].values[0]  # type: ignore
        view = _PickRoleToRemoveView(user_id=user.id)
        await view._populate(interaction.guild)
        await interaction.response.send_message(
            f"Now select a removable role to **remove** from {user.mention}:",
            view=view,
            ephemeral=True,
        )


class _PickRoleToRemoveView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.role_select = discord.ui.Select(placeholder="Pick a role to remove", min_values=1, max_values=1, options=[])
        self.role_select.callback = self._on_pick  # type: ignore
        self.add_item(self.role_select)

    async def _populate(self, guild: discord.Guild):
        member = guild.get_member(self.user_id)
        me = _get_me(guild)
        if not member or not me:
            self.role_select.options = [discord.SelectOption(label="(None)", value="__none__", default=True)]
            return

        manageable = [r for r in member.roles if _is_role_assignable(r, me)]
        manageable.sort(key=lambda r: r.position, reverse=True)

        opts = [discord.SelectOption(label=r.name[:100], value=str(r.id)) for r in manageable[:25]]
        if not opts:
            opts = [discord.SelectOption(label="(No removable roles)", value="__none__", default=True)]
        self.role_select.options = opts

    async def _on_pick(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        me = _get_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("❌ User not found.", ephemeral=True)

        val = self.role_select.values[0]
        if val == "__none__":
            return await interaction.response.send_message("ℹ️ Nothing to remove.", ephemeral=True)

        role = interaction.guild.get_role(int(val))
        if not role or not _is_role_assignable(role, me):
            return await interaction.response.send_message("❌ That role is blocked or not manageable.", ephemeral=True)

        if role not in member.roles:
            return await interaction.response.send_message("ℹ️ They don’t have that role.", ephemeral=True)

        try:
            await member.remove_roles(role, reason=f"Admin role remove by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed to remove that role (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Removed {role.mention} from {member.mention}", ephemeral=True)

        await _log(
            interaction.guild,
            title="🛂 Role Removed",
            color=discord.Color.red(),
            fields=[
                ("Admin", interaction.user.mention),
                ("User", member.mention),
                ("Role", role.mention),
            ],
        )


# =========================================================
# ADMIN: Main dashboard
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def selfroles_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select the self-roles channel:", view=_SetSelfRolesChannelView(), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Public Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        ok, msg = await _deploy_or_update_public_menu(interaction.guild)
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
        cfg = _ensure_shape(_load_config())
        state = "ON" if cfg.get("logging", {}).get("enabled") else "OFF"
        chan = cfg.get("logging", {}).get("channel_id")
        extra = f"\nCurrent: **{state}** | Channel: {f'<#{chan}>' if chan else 'Not set'}"
        await interaction.response.send_message("Logging settings:" + extra, view=LoggingView(), ephemeral=True)

    @discord.ui.button(label="🛂 Admin Assign Roles", style=discord.ButtonStyle.primary)
    async def admin_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("User role management:", view=UserRoleManagerView(), ephemeral=True)


# =========================================================
# Slash command: /rolesettings
# =========================================================

@app_commands.command(name="rolesettings", description="Admin panel for roles & self-roles")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not _admin_ok(interaction.user):
        return await interaction.response.send_message("❌ You do not have permission to use this.", ephemeral=True)

    cfg = _ensure_shape(_load_config())
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

    embed = discord.Embed(
        title="⚙️ Role Settings",
        description="\n".join(desc),
        colour=discord.Colour.blurple(),
    )

    await interaction.response.send_message(embed=embed, view=RoleSettingsDashboard(), ephemeral=True)


# =========================================================
# Setup
# =========================================================

def setup(tree: app_commands.CommandTree, client: discord.Client):
    tree.add_command(rolesettings)

    # Persistent public view (category picker only; reads JSON live)
    try:
        client.add_view(PublicSelfRolesView())
    except Exception:
        pass