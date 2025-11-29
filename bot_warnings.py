# bot_warnings.py
import os
import json
import base64
import requests
import discord
from discord import app_commands

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "warnings.json"
GITHUB_TOKEN = os.getenv("GITHUB_TEST_TOKEN")  # Use your test token here
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Roles -------------------
DEFAULT_ALLOWED_ROLES = [
    1420817462290681936,
    1413545658006110401,
    1404105470204969000,
    1404098545006546954
]

PASSENGERS_ROLE_ID = 1404100554807971971
WILLIAM_ROLE_ID = 1413545658006110401
SAZZLES_ROLE_ID = 1404104881098195015

# ------------------- Helpers -------------------
def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def _gh_url():
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

# ------------------- GitHub Load/Save with Debug -------------------
def load_data():
    """Load full JSON from GitHub with debug prints."""
    try:
        print("🔍 Loading warnings.json from GitHub...")
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        print(f"GET status: {r.status_code}")
        if r.status_code == 200:
            content = r.json()
            raw = base64.b64decode(content["content"]).decode()
            data = json.loads(raw)
            sha = content.get("sha")
            print(f"✅ Loaded warnings.json, SHA={sha}")
            if "warnings" not in data:
                data["warnings"] = {}
            return data, sha
        elif r.status_code == 404:
            print("⚠️ warnings.json not found on GitHub, creating new file.")
            return {"warnings": {}}, None
        else:
            print(f"❌ load_data: unexpected status {r.status_code} - {r.text}")
            return {"warnings": {}}, None
    except Exception as e:
        print("❌ Exception in load_data:", e)
        return {"warnings": {}}, None

def save_data(data, sha=None):
    """Save full JSON to GitHub with debug prints."""
    try:
        payload = {
            "message": "Update warnings.json",
            "content": base64.b64encode(json.dumps(data, indent=4).encode()).decode()
        }
        if sha:
            payload["sha"] = sha
            print(f"Using SHA: {sha}")
        print("🔧 Saving warnings.json to GitHub...")
        r = requests.put(_gh_url(), headers=HEADERS, data=json.dumps(payload), timeout=10)
        print(f"PUT status: {r.status_code}")
        print(f"PUT response: {r.text}")
        if r.status_code in (200, 201):
            new_sha = r.json().get("content", {}).get("sha")
            print(f"✅ warnings.json saved successfully, new SHA={new_sha}")
            return new_sha
        else:
            print("❌ save_data FAILED")
            return sha
    except Exception as e:
        print("❌ Exception in save_data():", e)
        return sha

# ------------------- Warning Operations -------------------
def add_warning(user_id: int, reason: str | None = None):
    data, sha = load_data()
    uid = str(user_id)
    if uid not in data["warnings"]:
        data["warnings"][uid] = []
    data["warnings"][uid].append(reason if reason else "No reason provided")
    sha = save_data(data, sha)
    return len(data["warnings"][uid])

def get_warnings(user_id: int):
    data, _ = load_data()
    return data["warnings"].get(str(user_id), [])

def clear_warnings(user_id: int):
    data, sha = load_data()
    uid = str(user_id)
    if uid in data["warnings"]:
        del data["warnings"][uid]
        sha = save_data(data, sha)
        return True
    return False

def get_all_warnings():
    data, _ = load_data()
    return data["warnings"]

# ------------------- Command Setup -------------------
def setup_warnings_commands(tree: app_commands.CommandTree, allowed_role_ids=None):
    allowed_set = set(allowed_role_ids or DEFAULT_ALLOWED_ROLES)

    def can_warn(interaction: discord.Interaction, target_member: discord.Member) -> bool:
        if SAZZLES_ROLE_ID in [r.id for r in target_member.roles]:
            return False
        author_roles = {r.id for r in interaction.user.roles}
        target_roles = {r.id for r in target_member.roles}
        if author_roles & allowed_set:
            return True
        if PASSENGERS_ROLE_ID in author_roles and WILLIAM_ROLE_ID in target_roles:
            return True
        return False

    # ---------------- /warn ----------------
    @tree.command(name="warn", description="Warn a user (joke warnings).")
    @app_commands.describe(member="Member to warn", reason="Reason (optional)")
    async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = None):
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

    # ---------------- /warnings_list ----------------
    @tree.command(name="warnings_list", description="List warnings for a user (public).")
    @app_commands.describe(member="Member to see warnings for")
    async def warnings_list(interaction: discord.Interaction, member: discord.Member):
        warns = get_warnings(member.id)
        if not warns:
            await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=False)
            return
        lines = [f"{i+1}. {w}" for i, w in enumerate(warns)]
        await interaction.response.send_message(f"{member.mention} warnings:\n" + "\n".join(lines), ephemeral=False)

    # ---------------- /server_warnings ----------------
    @tree.command(name="server_warnings", description="Show all warnings on this server (counts only).")
    async def server_warnings(interaction: discord.Interaction):
        all_warns = get_all_warnings()
        lines = []
        for uid, warns in all_warns.items():
            user = interaction.guild.get_member(int(uid))
            if user:
                lines.append(f"{user.display_name}: {len(warns)} warning(s)")
        await interaction.response.send_message("\n".join(lines) if lines else "No warnings found for this server.", ephemeral=False)

    # ---------------- /clear_warnings ----------------
    @tree.command(name="clear_warnings", description="Clear warnings for a user.")
    @app_commands.describe(member="Member to clear warnings for")
    async def clear(interaction: discord.Interaction, member: discord.Member):
        if not can_warn(interaction, member):
            await interaction.response.send_message(
                f"❌ You do not have permission to clear warnings for {member.mention}.",
                ephemeral=True
            )
            return
        if clear_warnings(member.id):
            await interaction.response.send_message(f"✅ Cleared all warnings for {member.mention}.", ephemeral=False)
        else:
            await interaction.response.send_message(f"{member.mention} had no warnings.", ephemeral=False)