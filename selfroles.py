from __future__ import annotations

import os
import json
import base64
import requests
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands

from permissions import has_app_access

# =========================================================
# GitHub-backed config (same pattern as Pilot)
# =========================================================

GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
SELFROLES_FILE_PATH = os.getenv("SELFROLES_FILE_PATH", "selfroles.json")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}


def _gh_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SELFROLES_FILE_PATH}"


DEFAULT_CFG: Dict[str, Any] = {
    "selfroles_channel_id": None,
    "selfroles_message_id": None,
    "logging": {"enabled": False, "channel_id": None},
    "auto_roles": {"humans": [], "bots": []},
    # categories:
    #   key: { title, emoji(optional), multi_select(bool), roles: { role_id: {label, emoji(optional)} } }
    "categories": {},
}


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
    if not isinstance(cfg["categories"], dict):
        cfg["categories"] = {}
    # ensure each cat has required structure
    for k, cat in list(cfg["categories"].items()):
        if not isinstance(cat, dict):
            cfg["categories"].pop(k, None)
            continue
        cat.setdefault("title", k)
        cat.setdefault("emoji", None)  # optional (unicode or <:name:id>)
        cat.setdefault("multi_select", True)
        cat.setdefault("roles", {})
        if not isinstance(cat["roles"], dict):
            cat["roles"] = {}
    return cfg


def load_config() -> Dict[str, Any]:
    try:
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            content = r.json()
            raw = base64.b64decode(content["content"]).decode()
            data = json.loads(raw) if raw.strip() else DEFAULT_CFG.copy()
            return _ensure_shape(data)
        # create default if missing
        save_config(DEFAULT_CFG.copy())
        return _ensure_shape(DEFAULT_CFG.copy())
    except Exception:
        return _ensure_shape(DEFAULT_CFG.copy())


def save_config(cfg: Dict[str, Any]) -> None:
    cfg = _ensure_shape(cfg)
    try:
        sha = None
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": "Update selfroles config",
            "content": base64.b64encode(json.dumps(cfg, indent=2, ensure_ascii=False).encode()).decode(),
        }
        if sha:
            payload["sha"] = sha

        requests.put(_gh_url(), headers=HEADERS, json=payload, timeout=10)
    except Exception:
        pass


# =========================================================
# Helpers
# =========================================================

def _cid(v) -> int:
    return v.id if hasattr(v, "id") else int(v)


def _get_bot_member(guild: discord.Guild) -> Optional[discord.Member]:
    return guild.me or guild.get_member(guild.client.user.id) if guild.client.user else None


def _parse_emoji(raw: Optional[str]) -> Optional[discord.PartialEmoji]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except Exception:
        return None


def _role_default_emoji(role: discord.Role) -> Optional[str]:
    """
    Discord supports a unicode emoji on roles (role.unicode_emoji).
    This is the only "emoji-like" thing that can appear as a select option emoji.
    (Role icons/images cannot be used as select emojis.)
    """
    try:
        ue = getattr(role, "unicode_emoji", None)
        if ue:
            return str(ue)
    except Exception:
        pass
    return None


def _is_role_assignable(role: discord.Role, bot_member: discord.Member) -> bool:
    if role.is_default():           # @everyone
        return False
    if role.managed:               # bot/integration roles
        return False
    if role.permissions.administrator:  # block admin roles
        return False
    if role >= bot_member.top_role:     # must be below bot
        return False
    return True


def _admin_ok(interaction: discord.Interaction) -> bool:
    return has_app_access(interaction.user, "roles")


async def _no_perm(interaction: discord.Interaction):
    try:
        await interaction.response.send_message("❌ You do not have permission for Role Settings.", ephemeral=True)
    except Exception:
        pass


# =========================================================
# Public self-role view (category buttons -> ephemeral role picker)
# =========================================================

class RolePickerSelect(discord.ui.Select):
    def __init__(self, category_key: str):
        self.category_key = category_key
        cfg = load_config()
        cat = (cfg.get("categories", {}) or {}).get(category_key) or {}
        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}

        options: List[discord.SelectOption] = []
        for rid_str, meta in list(roles_cfg.items())[:25]:
            label = str(meta.get("label") or "Role")
            emoji_str = meta.get("emoji") or None
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(rid_str),
                    emoji=_parse_emoji(emoji_str) if emoji_str else None,
                )
            )

        multi = bool(cat.get("multi_select", True))
        max_values = len(options) if multi else 1
        if max_values < 1:
            max_values = 1

        super().__init__(
            placeholder="Select your roles…",
            options=options,
            min_values=0,
            max_values=max_values,
            custom_id=f"selfroles:picker:{category_key}",
        )

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        member = interaction.guild.get_member(interaction.user.id)
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("⚠️ Could not resolve your member object.", ephemeral=True)

        cfg = load_config()
        cat = (cfg.get("categories", {}) or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category no longer exists.", ephemeral=True)

        roles_cfg: Dict[str, Any] = cat.get("roles", {}) or {}
        role_ids = {int(rid) for rid in roles_cfg.keys() if str(rid).isdigit()}
        selected = {int(v) for v in self.values if str(v).isdigit()}

        me = _get_bot_member(interaction.guild)
        if not me:
            return await interaction.response.send_message("⚠️ Bot member not found.", ephemeral=True)

        added: List[discord.Role] = []
        removed: List[discord.Role] = []

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
                emb = discord.Embed(title="🧩 Self-Role Update", colour=discord.Colour.blurple())
                emb.add_field(name="User", value=interaction.user.mention, inline=False)
                emb.add_field(name="Category", value=str(cat.get("title") or self.category_key), inline=False)
                if added:
                    emb.add_field(name="Added", value=", ".join(r.mention for r in added), inline=False)
                if removed:
                    emb.add_field(name="Removed", value=", ".join(r.mention for r in removed), inline=False)
                try:
                    await chan.send(embed=emb)
                except Exception:
                    pass


class RolePickerView(discord.ui.View):
    def __init__(self, category_key: str):
        super().__init__(timeout=180)
        self.add_item(RolePickerSelect(category_key))


class CategoryButton(discord.ui.Button):
    def __init__(self, category_key: str, title: str, emoji: Optional[str]):
        super().__init__(
            label=title[:80],
            emoji=_parse_emoji(emoji) if emoji else None,
            style=discord.ButtonStyle.secondary,
            custom_id=f"selfroles:catbtn:{category_key}",
        )
        self.category_key = category_key

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        cat = (cfg.get("categories", {}) or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ That category no longer exists.", ephemeral=True)

        if not (cat.get("roles") or {}):
            return await interaction.response.send_message("ℹ️ No roles in this category yet.", ephemeral=True)

        # IMPORTANT: opens the picker instantly, ephemeral (no extra junk posted under the main menu)
        await interaction.response.send_message(
            f"**{cat.get('title', self.category_key)}**\nSelect your roles:",
            view=RolePickerView(self.category_key),
            ephemeral=True,
        )


class PublicSelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        cfg = load_config()
        cats: Dict[str, Any] = cfg.get("categories", {}) or {}

        # one embed with multiple category buttons (Discord rows handled automatically)
        for key, cat in list(cats.items()):
            roles = cat.get("roles", {}) or {}
            if not roles:
                continue
            self.add_item(CategoryButton(key, str(cat.get("title") or key), cat.get("emoji")))


async def build_public_embed_and_view() -> Tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(
        title="✨ Choose Your Roles",
        description="Tap a category button, then pick your roles.\nYou can change these any time ✈️",
        colour=discord.Colour.blurple(),
    )
    return embed, PublicSelfRoleView()


async def deploy_or_update_public_menu(guild: discord.Guild) -> Tuple[bool, str]:
    cfg = load_config()
    channel_id = cfg.get("selfroles_channel_id")
    if not channel_id:
        return False, "Self-roles channel not set."

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False, "Configured self-roles channel is missing or not a text channel."

    embed, view = await build_public_embed_and_view()
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
        save_config(cfg)
        return True, "✅ Posted a new self-role menu."
    except Exception as e:
        return False, f"Failed to post menu: {e}"


# =========================================================
# Auto roles (humans vs bots)
# =========================================================

async def apply_auto_roles(member: discord.Member) -> None:
    cfg = load_config()
    auto = cfg.get("auto_roles", {}) or {}
    role_ids = auto.get("bots" if member.bot else "humans", []) or []

    me = _get_bot_member(member.guild)
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
        except Exception:
            pass


# =========================================================
# Admin UI views
# =========================================================

class _SetSelfRolesChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        cid = _cid(interaction.data["values"][0])
        cfg = load_config()
        cfg["selfroles_channel_id"] = cid
        save_config(cfg)
        await interaction.response.send_message(f"📍 Self-roles channel set to <#{cid}>", ephemeral=True)


class _SetLogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        sel.callback = self.pick
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        cid = _cid(interaction.data["values"][0])
        cfg = load_config()
        cfg.setdefault("logging", {"enabled": False, "channel_id": None})
        cfg["logging"]["channel_id"] = cid
        save_config(cfg)
        await interaction.response.send_message(f"🧾 Log channel set to <#{cid}>", ephemeral=True)


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
            label="Title (can include emojis / custom <:name:id>)",
            required=True,
            max_length=150,
            default=(existing.get("title") if existing else "") or "",
        )
        self.emoji_in = discord.ui.TextInput(
            label="Button emoji (optional) unicode or <:name:id>",
            required=False,
            max_length=80,
            default=str((existing.get("emoji") if existing else "") or ""),
        )
        self.multi = discord.ui.TextInput(
            label="Multi-select? (yes/no)",
            required=True,
            max_length=5,
            default=("yes" if (existing.get("multi_select", True) if existing else True) else "no"),
        )

        self.add_item(self.key)
        self.add_item(self.title_in)
        self.add_item(self.emoji_in)
        self.add_item(self.multi)

    async def on_submit(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)

        cfg = load_config()
        categories = cfg.get("categories", {}) or {}

        key = self.key.value.strip().lower().replace(" ", "_")
        if not key:
            return await interaction.response.send_message("❌ Category key is required.", ephemeral=True)

        multi_raw = self.multi.value.strip().lower()
        multi_select = multi_raw in ("yes", "y", "true", "1", "on")

        emoji_str = self.emoji_in.value.strip()
        if emoji_str and not _parse_emoji(emoji_str):
            return await interaction.response.send_message("❌ That button emoji format looks invalid.", ephemeral=True)

        if self.mode == "add":
            if key in categories:
                return await interaction.response.send_message("❌ That category key already exists.", ephemeral=True)
            categories[key] = {
                "title": self.title_in.value.strip(),
                "emoji": emoji_str or None,
                "multi_select": multi_select,
                "roles": {},
            }
        else:
            if self.existing_key is None or self.existing_key not in categories:
                return await interaction.response.send_message("❌ Category no longer exists.", ephemeral=True)

            if key != self.existing_key:
                if key in categories:
                    return await interaction.response.send_message("❌ New key already exists.", ephemeral=True)
                categories[key] = categories.pop(self.existing_key)

            categories[key]["title"] = self.title_in.value.strip()
            categories[key]["emoji"] = emoji_str or None
            categories[key]["multi_select"] = multi_select
            categories[key].setdefault("roles", {})

        cfg["categories"] = categories
        save_config(cfg)
        await interaction.response.send_message("✅ Category saved.", ephemeral=True)


class EmojiLabelModal(discord.ui.Modal):
    def __init__(self, category_key: str, role_id: int, existing: Dict[str, Any]):
        super().__init__(title="Role Display Settings")
        self.category_key = category_key
        self.role_id = role_id

        self.label_in = discord.ui.TextInput(
            label="Label (what users see) — can include emojis",
            required=True,
            max_length=100,
            default=str(existing.get("label") or "Role"),
        )
        self.emoji_in = discord.ui.TextInput(
            label="Emoji override (optional) unicode or <:name:id>",
            required=False,
            max_length=80,
            default=str(existing.get("emoji") or ""),
        )

        self.add_item(self.label_in)
        self.add_item(self.emoji_in)

    async def on_submit(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)

        cfg = load_config()
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
        cat["roles"] = roles
        save_config(cfg)

        await interaction.response.send_message("✅ Role display updated.", ephemeral=True)


class CategoryPicker(discord.ui.Select):
    def __init__(self, placeholder: str, custom_id: str):
        cfg = load_config()
        cats: Dict[str, Any] = cfg.get("categories", {}) or {}

        options: List[discord.SelectOption] = []
        if not cats:
            options.append(discord.SelectOption(label="(No categories yet)", value="__none__", default=True))
        else:
            for key, cat in list(cats.items())[:25]:
                options.append(discord.SelectOption(label=str(cat.get("title") or key)[:100], value=key))

        super().__init__(placeholder=placeholder, options=options[:25], min_values=1, max_values=1, custom_id=custom_id)


class CategoryManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.selected_key: Optional[str] = None

        sel = CategoryPicker("Select a category to edit/delete", "rolesettings:cat_select")
        sel.callback = self._on_select  # type: ignore
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        key = interaction.data["values"][0]
        if key == "__none__":
            self.selected_key = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.selected_key = key
        await interaction.response.send_message(f"✅ Selected category: `{key}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Category", style=discord.ButtonStyle.success)
    async def add_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_modal(CategoryModal(mode="add"))

    @discord.ui.button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary)
    async def edit_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        if not self.selected_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = load_config()
        cat = (cfg.get("categories", {}) or {}).get(self.selected_key)
        if not cat:
            return await interaction.response.send_message("❌ Category not found.", ephemeral=True)
        await interaction.response.send_modal(CategoryModal(mode="edit", existing_key=self.selected_key, existing=cat))

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def delete_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        if not self.selected_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = load_config()
        cats = cfg.get("categories", {}) or {}
        if self.selected_key not in cats:
            return await interaction.response.send_message("❌ Category not found.", ephemeral=True)
        del cats[self.selected_key]
        cfg["categories"] = cats
        save_config(cfg)
        self.selected_key = None
        await interaction.response.send_message("✅ Category deleted.", ephemeral=True)


class RoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.category_key: Optional[str] = None

        sel = CategoryPicker("Select a category to manage roles", "rolesettings:role_cat_select")
        sel.callback = self._on_cat  # type: ignore
        self.add_item(sel)

    async def _on_cat(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        key = interaction.data["values"][0]
        if key == "__none__":
            self.category_key = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.category_key = key
        await interaction.response.send_message(f"✅ Selected category: `{key}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Roles (up to 25)", style=discord.ButtonStyle.success)
    async def add_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        role_select = discord.ui.RoleSelect(placeholder="Pick up to 25 roles", min_values=1, max_values=25)

        async def on_pick(i: discord.Interaction):
            if not _admin_ok(i):
                return await _no_perm(i)
            assert i.guild is not None
            me = _get_bot_member(i.guild)
            if not me:
                return await i.response.send_message("❌ Bot member missing.", ephemeral=True)

            cfg = load_config()
            cat = (cfg.get("categories", {}) or {}).get(self.category_key)
            if not cat:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)

            roles = cat.get("roles", {}) or {}
            added = 0

            for role in role_select.values:
                if not _is_role_assignable(role, me):
                    continue
                rid = str(role.id)
                if rid in roles:
                    continue

                # Auto-pull role unicode emoji if it exists, otherwise None (manual override later)
                roles[rid] = {
                    "label": role.name,
                    "emoji": _role_default_emoji(role),
                }
                added += 1

            cat["roles"] = roles
            save_config(cfg)
            await i.response.send_message(f"✅ Added **{added}** roles to `{self.category_key}`.", ephemeral=True)

        role_select.callback = on_pick  # type: ignore
        view.add_item(role_select)
        await interaction.response.send_message("Select roles to add:", view=view, ephemeral=True)

    @discord.ui.button(label="➖ Remove Role", style=discord.ButtonStyle.danger)
    async def remove_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = load_config()
        cat = (cfg.get("categories", {}) or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles: Dict[str, Any] = cat.get("roles", {}) or {}
        if not roles:
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

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
            if not _admin_ok(i):
                return await _no_perm(i)
            cfg2 = load_config()
            cat2 = (cfg2.get("categories", {}) or {}).get(self.category_key)
            if not cat2:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)
            roles2 = cat2.get("roles", {}) or {}
            rid_str = select.values[0]
            roles2.pop(rid_str, None)
            cat2["roles"] = roles2
            save_config(cfg2)
            await i.response.send_message("✅ Role removed from category.", ephemeral=True)

        select.callback = on_remove  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(select)
        await interaction.response.send_message("Select a role to remove:", view=v, ephemeral=True)

    @discord.ui.button(label="😀 Edit Label / Emoji", style=discord.ButtonStyle.primary)
    async def edit_display(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = load_config()
        cat = (cfg.get("categories", {}) or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles: Dict[str, Any] = cat.get("roles", {}) or {}
        if not roles:
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

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
            if not _admin_ok(i):
                return await _no_perm(i)
            rid_str = select.values[0]
            cfg2 = load_config()
            cat2 = (cfg2.get("categories", {}) or {}).get(self.category_key)
            if not cat2:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)
            role_meta = (cat2.get("roles", {}) or {}).get(rid_str)
            if not role_meta:
                return await i.response.send_message("❌ Role missing.", ephemeral=True)
            await i.response.send_modal(EmojiLabelModal(self.category_key, int(rid_str), role_meta))

        select.callback = on_pick  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(select)
        await interaction.response.send_message("Select a role to edit:", view=v, ephemeral=True)


class AutoRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def _pick_auto_role(self, interaction: discord.Interaction, target: str):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        assert interaction.guild is not None
        me = _get_bot_member(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        role_select = discord.ui.RoleSelect(placeholder="Pick an auto-role", min_values=1, max_values=1)

        async def on_pick(i: discord.Interaction):
            if not _admin_ok(i):
                return await _no_perm(i)
            role: discord.Role = role_select.values[0]
            if not _is_role_assignable(role, me):
                return await i.response.send_message("❌ That role can’t be managed by the bot (or is blocked).", ephemeral=True)

            cfg = load_config()
            cfg.setdefault("auto_roles", {"humans": [], "bots": []})
            arr = cfg["auto_roles"].get(target, []) or []
            rid = str(role.id)
            if rid not in arr:
                arr.append(rid)
            cfg["auto_roles"][target] = arr
            save_config(cfg)
            await i.response.send_message(f"✅ Added {role.mention} to auto-roles ({target}).", ephemeral=True)

        role_select.callback = on_pick  # type: ignore
        view.add_item(role_select)
        await interaction.response.send_message("Select a role:", view=view, ephemeral=True)

    async def _remove_auto_role(self, interaction: discord.Interaction, target: str):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        cfg = load_config()
        arr = (cfg.get("auto_roles", {}) or {}).get(target, []) or []
        if not arr:
            return await interaction.response.send_message("ℹ️ None set.", ephemeral=True)

        options: List[discord.SelectOption] = []
        for rid_str in arr[:25]:
            role = interaction.guild.get_role(int(rid_str)) if interaction.guild else None
            options.append(discord.SelectOption(label=(role.name if role else rid_str), value=rid_str))

        select = discord.ui.Select(placeholder="Pick one to remove", min_values=1, max_values=1, options=options)

        async def on_remove(i: discord.Interaction):
            if not _admin_ok(i):
                return await _no_perm(i)
            rid_str = select.values[0]
            cfg2 = load_config()
            arr2 = (cfg2.get("auto_roles", {}) or {}).get(target, []) or []
            if rid_str in arr2:
                arr2.remove(rid_str)
            cfg2["auto_roles"][target] = arr2
            save_config(cfg2)
            await i.response.send_message("✅ Removed.", ephemeral=True)

        select.callback = on_remove  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(select)
        await interaction.response.send_message("Select one to remove:", view=v, ephemeral=True)

    @discord.ui.button(label="➕ Add Human Auto-Role", style=discord.ButtonStyle.success)
    async def add_human(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._pick_auto_role(interaction, "humans")

    @discord.ui.button(label="➕ Add Bot Auto-Role", style=discord.ButtonStyle.success)
    async def add_bot(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._pick_auto_role(interaction, "bots")

    @discord.ui.button(label="➖ Remove Human Auto-Role", style=discord.ButtonStyle.danger)
    async def rem_human(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._remove_auto_role(interaction, "humans")

    @discord.ui.button(label="➖ Remove Bot Auto-Role", style=discord.ButtonStyle.danger)
    async def rem_bot(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._remove_auto_role(interaction, "bots")


class LoggingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔁 Toggle Logging", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        cfg = load_config()
        cfg.setdefault("logging", {"enabled": False, "channel_id": None})
        cfg["logging"]["enabled"] = not bool(cfg["logging"].get("enabled"))
        save_config(cfg)
        state = "ON" if cfg["logging"]["enabled"] else "OFF"
        await interaction.response.send_message(f"🧾 Logging is now **{state}**.", ephemeral=True)

    @discord.ui.button(label="📍 Set Log Channel", style=discord.ButtonStyle.secondary)
    async def set_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_message("Select a log channel:", view=_SetLogChannelView(), ephemeral=True)

    @discord.ui.button(label="🧹 Clear Log Channel", style=discord.ButtonStyle.danger)
    async def clear_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        cfg = load_config()
        cfg.setdefault("logging", {"enabled": False, "channel_id": None})
        cfg["logging"]["channel_id"] = None
        save_config(cfg)
        await interaction.response.send_message("✅ Log channel cleared.", ephemeral=True)


# =========================================================
# Admin assign/remove roles to users (guardrails)
# =========================================================

class UserRoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ Assign Role to User", style=discord.ButtonStyle.success)
    async def assign(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_message("Select a user:", view=_PickUserForAssignView(), ephemeral=True)

    @discord.ui.button(label="➖ Remove Role from User", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_message("Select a user:", view=_PickUserForRemoveView(), ephemeral=True)


class _PickUserForAssignView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        sel.callback = self._on_pick  # type: ignore
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        user = interaction.data["values"][0]
        uid = int(user)
        await interaction.response.send_message(
            "Now pick a role to **assign**:",
            view=_PickRoleToAssignView(uid),
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
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        assert interaction.guild is not None
        me = _get_bot_member(interaction.guild)
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
            return await interaction.response.send_message("❌ Failed to assign that role.", ephemeral=True)

        await interaction.response.send_message(f"✅ Assigned {role.mention} to {member.mention}", ephemeral=True)


class _PickUserForRemoveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        sel.callback = self._on_pick  # type: ignore
        self.add_item(sel)

    async def _on_pick(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        uid = int(interaction.data["values"][0])
        view = _PickRoleToRemoveView(uid)
        await view._populate(interaction.guild)
        await interaction.response.send_message("Now pick a role to **remove**:", view=view, ephemeral=True)


class _PickRoleToRemoveView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.select = discord.ui.Select(placeholder="Pick a role to remove", min_values=1, max_values=1, options=[])
        self.select.callback = self._on_pick  # type: ignore
        self.add_item(self.select)

    async def _populate(self, guild: Optional[discord.Guild]) -> None:
        if not guild:
            self.select.options = [discord.SelectOption(label="(Guild missing)", value="__none__", default=True)]
            return
        member = guild.get_member(self.user_id)
        me = _get_bot_member(guild)
        if not member or not me:
            self.select.options = [discord.SelectOption(label="(User/Bot missing)", value="__none__", default=True)]
            return
        manageable = [r for r in member.roles if _is_role_assignable(r, me)]
        manageable.sort(key=lambda r: r.position, reverse=True)
        opts = [discord.SelectOption(label=r.name[:100], value=str(r.id)) for r in manageable[:25]]
        if not opts:
            opts = [discord.SelectOption(label="(No removable roles)", value="__none__", default=True)]
        self.select.options = opts

    async def _on_pick(self, interaction: discord.Interaction):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        assert interaction.guild is not None
        me = _get_bot_member(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("❌ User not found.", ephemeral=True)

        val = self.select.values[0]
        if val == "__none__":
            return await interaction.response.send_message("ℹ️ Nothing to remove.", ephemeral=True)

        role = interaction.guild.get_role(int(val))
        if not role or not _is_role_assignable(role, me):
            return await interaction.response.send_message("❌ Role blocked or not manageable.", ephemeral=True)

        try:
            await member.remove_roles(role, reason=f"Admin role remove by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed to remove role.", ephemeral=True)

        await interaction.response.send_message(f"✅ Removed {role.mention} from {member.mention}", ephemeral=True)


# =========================================================
# Admin dashboard
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def selfroles_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_message("Select the self-roles channel:", view=_SetSelfRolesChannelView(), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Public Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        ok, msg = await deploy_or_update_public_menu(interaction.guild)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=True)

    @discord.ui.button(label="📂 Categories", style=discord.ButtonStyle.secondary)
    async def categories(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_message("Category manager:", view=CategoryManagerView(), ephemeral=True)

    @discord.ui.button(label="🎭 Roles in Categories", style=discord.ButtonStyle.secondary)
    async def roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_message("Role manager:", view=RoleManagerView(), ephemeral=True)

    @discord.ui.button(label="👥 Auto Roles", style=discord.ButtonStyle.secondary)
    async def autoroles(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_message("Auto-roles:", view=AutoRolesView(), ephemeral=True)

    @discord.ui.button(label="🧾 Logging", style=discord.ButtonStyle.secondary)
    async def logging(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        cfg = load_config()
        log = cfg.get("logging", {}) or {}
        state = "ON" if log.get("enabled") else "OFF"
        chan = log.get("channel_id")
        extra = f"\nCurrent: **{state}** | Channel: {f'<#{chan}>' if chan else 'Not set'}"
        await interaction.response.send_message("Logging settings:" + extra, view=LoggingView(), ephemeral=True)

    @discord.ui.button(label="🛂 Admin Assign Roles", style=discord.ButtonStyle.primary)
    async def admin_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _admin_ok(interaction):
            return await _no_perm(interaction)
        await interaction.response.send_message("User role management:", view=UserRoleManagerView(), ephemeral=True)


@app_commands.command(name="rolesettings", description="Admin panel for roles & self-roles")
async def rolesettings(interaction: discord.Interaction):
    if not _admin_ok(interaction):
        return await _no_perm(interaction)

    cfg = load_config()
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

def setup(tree: app_commands.CommandTree, client: discord.Client):
    """
    Call from bot_slash.py as:
        from selfroles import setup as selfroles_setup
        selfroles_setup(self.tree, self)
    """
    tree.add_command(rolesettings)

    # Register persistent public view so it survives restarts
    try:
        client.add_view(PublicSelfRoleView())
    except Exception:
        pass