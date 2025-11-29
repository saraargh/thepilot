# bot_warnings.py
import os
import json
import base64
import requests
import discord
from discord import app_commands

# ------------------- GitHub Config -------------------
GITHUB_REPO = "saraargh/the-pilot"
GITHUB_FILE_PATH = "warnings.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Defaults & Roles -------------------
DEFAULT_DATA = {}  # top-level is a dict of user_id(str) -> list of reasons

# Default allowed roles (can be overridden by passing allowed_role_ids to setup function)
DEFAULT_ALLOWED_ROLES = [
    1420817462290681936,
    1413545658006110401,
    1404105470204969000,
    1404098545006546954
]

PASSENGERS_ROLE_ID = 1404100554807971971
WILLIAM_ROLE_ID = 1413545658006110401
SAZZLES_ROLE_ID = 1404104881098195015

# ------------------- Utilities -------------------
def ordinal(n: int) -> str:
    """Return ordinal string for a number: 1 -> 1st, 2 -> 2nd, 11 -> 11th, etc."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

# ------------------- GitHub helpers -------------------
def _gh_url():
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

def load_data():
    """
    Load the JSON data from GitHub. Returns (data_dict, sha) or (DEFAULT_DATA.copy(), None)
    """
    if not GITHUB_TOKEN:
        print("❗ GITHUB_TOKEN not set in environment. GitHub persistence will fail.")
        return DEFAULT_DATA.copy(), None

    try:
        url = _gh_url()
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            content = r.json()
            raw = base64.b64decode(content["content"]).decode()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print("⚠️ GitHub content JSON decode error, reinitializing to DEFAULT_DATA.")
                data = DEFAULT_DATA.copy()
            sha = content.get("sha")
            return data, sha

        # If file not found (404), create it
        if r.status_code == 404:
            print("ℹ️ warnings.json not found in repo — creating a new one.")
            sha = save_data(DEFAULT_DATA.copy(), sha=None)
            return DEFAULT_DATA.copy(), sha

        # Other responses
        print(f"❌ load_data: unexpected status {r.status_code} - {r.text}")
        return DEFAULT_DATA.copy(), None

    except Exception as e:
        print("❌ Exception in load_data():", e)
        return DEFAULT_DATA.copy(), None

def save_data(data, sha=None):
    """
    Save a Python dict to the GitHub file. Returns new sha on success, None on failure.
    """
    if not GITHUB_TOKEN:
        print("❗ GITHUB_TOKEN not set — cannot save to GitHub.")
        return None

    try:
        url = _gh_url()
        content_b64 = base64.b64encode(json.dumps(data, indent=4).encode()).decode()
        payload = {"message": "Update warnings.json", "content": content_b64}
        if sha:
            payload["sha"] = sha

        r = requests.put(url, headers=HEADERS, data=json.dumps(payload), timeout=10)
        if r.status_code in (200, 201):
            resp = r.json()
            new_sha = resp.get("content", {}).get("sha")
            print("✅ save_data: saved warnings.json, new sha:", new_sha)
            return new_sha
        else:
            print("❌ save_data FAILED:", r.status_code, r.text)
            # If GitHub returns 422 it may be because sha is wrong — attempt to re-load and retry once
            if r.status_code == 422:
                print("ℹ️ Attempting save retry after reloading remote SHA...")
                remote_data, remote_sha = load_data()
                payload["sha"] = remote_sha
                r2 = requests.put(url, headers=HEADERS, data=json.dumps(payload), timeout=10)
                if r2.status_code in (200, 201):
                    new_sha = r2.json().get("content", {}).get("sha")
                    print("✅ save_data (retry) succeeded, new sha:", new_sha)
                    return new_sha
                else:
                    print("❌ save_data (retry) failed:", r2.status_code, r2.text)
            return None

    except Exception as e:
        print("❌ Exception in save_data():", e)
        return None

# ------------------- Data functions -------------------
def add_warning(user_id: int, reason: str | None = None) -> int:
    """
    Add a warning. Returns the new count for that user.
    """
    data, sha = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = []
    data[uid].append(reason if reason else "No reason provided")
    new_sha = save_data(data, sha)
    if new_sha is None:
        print("⚠️ Warning added locally but failed to persist to GitHub.")
    return len(data.get(uid, []))

def get_warnings(user_id: int):
    data, _sha = load_data()
    return data.get(str(user_id), [])

def clear_warnings(user_id: int) -> bool:
    data, sha = load_data()
    uid = str(user_id)
    if uid in data:
        del data[uid]
        save_data(data, sha)
        return True
    return False

def get_all_warnings():
    data, _sha = load_data()
    return data

# ------------------- Command setup -------------------
def setup_warnings_commands(tree: app_commands.CommandTree, allowed_role_ids=None):
    """
    Call this from your main bot to register the warnings commands.
    Example:
        setup_warnings_commands(client.tree, allowed_role_ids=ALLOWED_ROLE_IDS)
    """
    allowed_set = set(allowed_role_ids or DEFAULT_ALLOWED_ROLES)

    def can_warn(interaction: discord.Interaction, target_member: discord.Member) -> bool:
        # Sazzles cannot be warned by anyone — check target roles first
        if SAZZLES_ROLE_ID in [r.id for r in target_member.roles]:
            return False

        author_role_ids = {r.id for r in interaction.user.roles}
        target_role_ids = {r.id for r in target_member.roles}

        # Allowed role can warn anyone
        if author_role_ids & allowed_set:
            return True

        # Passengers can only warn William
        if PASSENGERS_ROLE_ID in author_role_ids and WILLIAM_ROLE_ID in target_role_ids:
            return True

        return False

    # ---------------- /warn ----------------
    @tree.command(name="warn", description="Warn a user (joke warnings).")
    @app_commands.describe(member="Member to warn", reason="Reason (optional)")
    async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = None):
        # Sazzles special message (public)
        if SAZZLES_ROLE_ID in [r.id for r in member.roles]:
            await interaction.response.send_message(
                "⚠️ You cannot warn this user as she is the best and made this so you could all warn William 🖤",
                ephemeral=False
            )
            return

        if not can_warn(interaction, member):
            await interaction.response.send_message(
                f"❌ You do not have permission to warn {member.mention}.",
                ephemeral=True
            )
            return

        count = add_warning(member.id, reason)
        msg = f"⚠️ {member.mention} was warned"
        if reason:
            msg += f" for {reason}"
        msg += f", this is their {ordinal(count)} warning."
        await interaction.response.send_message(msg, ephemeral=False)

    # --------------- /warnings_list (per user) ---------------
    @tree.command(name="warnings_list", description="List warnings for a user (public).")
    @app_commands.describe(member="Member to see warnings for")
    async def warnings_list(interaction: discord.Interaction, member: discord.Member):
        warns = get_warnings(member.id)
        if not warns:
            await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=False)
            return

        # Show all reasons, visible to everyone
        msg_lines = [f"{i+1}. {w}" for i, w in enumerate(warns)]
        await interaction.response.send_message(
            f"{member.mention} warnings:\n" + "\n".join(msg_lines),
            ephemeral=False
        )

    # --------------- /server_warnings ---------------
    @tree.command(name="server_warnings", description="Show all warnings on this server (counts only).")
    async def server_warnings(interaction: discord.Interaction):
        data = get_all_warnings()
        if not data:
            await interaction.response.send_message("No warnings on this server.", ephemeral=False)
            return

        lines = []
        for uid, warns in data.items():
            try:
                user = interaction.guild.get_member(int(uid))
            except Exception:
                user = None
            if user:
                lines.append(f"{user.display_name}: {len(warns)} warning(s)")

        await interaction.response.send_message("\n".join(lines) if lines else "No warnings found for this server.", ephemeral=False)

    # --------------- /remove_warn ---------------
    @tree.command(name="remove_warn", description="Remove a warning from a user (remove last by default).")
    @app_commands.describe(member="Member to remove warning from", index="Index of warning to remove (1-based, optional)")
    async def remove_warn(interaction: discord.Interaction, member: discord.Member, index: int = None):
        # permission check: same as warn (so only allowed roles etc can remove)
        if not can_warn(interaction, member):
            await interaction.response.send_message("❌ You do not have permission to remove warnings for this person.", ephemeral=True)
            return

        # operate on underlying data
        data, sha = load_data()
        uid = str(member.id)
        user_warnings = data.get(uid, [])
        if not user_warnings:
            await interaction.response.send_message(f"❌ {member.mention} has no warnings.", ephemeral=False)
            return

        if index is None:
            # pop last
            user_warnings.pop()
        else:
            if 1 <= index <= len(user_warnings):
                user_warnings.pop(index - 1)
            else:
                await interaction.response.send_message("❌ Invalid index.", ephemeral=True)
                return

        if user_warnings:
            data[uid] = user_warnings
        else:
            data.pop(uid, None)

        save_data(data, sha)
        await interaction.response.send_message(f"✅ Warning removed from {member.mention}.", ephemeral=False)

    # --------------- /clear_warns ---------------
    @tree.command(name="clear_warns", description="Clear all warnings for a user.")
    @app_commands.describe(member="Member to clear warnings for")
    async def clear_warns(interaction: discord.Interaction, member: discord.Member):
        if not can_warn(interaction, member):
            await interaction.response.send_message("❌ You do not have permission to clear warnings for this person.", ephemeral=True)
            return

        success = clear_warnings(member.id)
        if success:
            await interaction.response.send_message(f"✅ All warnings cleared for {member.mention}.", ephemeral=False)
        else:
            await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=False)