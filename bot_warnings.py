import discord
from discord import app_commands
import requests
import base64
import os
import json

# ------------------- GitHub Config -------------------
GITHUB_REPO = "saraargh/the-pilot"
GITHUB_FILE_PATH = "warnings.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"}

# ------------------- Default Data -------------------
DEFAULT_DATA = {}  # empty initially

# ------------------- GitHub Helpers -------------------
def load_data():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        content = r.json()
        data = base64.b64decode(content["content"]).decode()
        return json.loads(data), content["sha"]
    # file does not exist yet, create it
    sha = save_data(DEFAULT_DATA.copy())
    return DEFAULT_DATA.copy(), sha

def save_data(data, sha=None):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    encoded_content = base64.b64encode(json.dumps(data, indent=4).encode()).decode()
    payload = {"message": "Update warnings", "content": encoded_content}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=HEADERS, data=json.dumps(payload))
    if r.status_code not in [200, 201]:
        print(f"GitHub save error: {r.status_code} {r.text}")
        return sha
    return r.json().get("content", {}).get("sha")


# ------------------- Role IDs -------------------
ALLOWED_ROLES_IDS = [1420817462290681936, 1413545658006110401, 1404105470204969000, 1404098545006546954]  # Admin, William, Moderator, Helper
PASSENGERS_ROLE_ID = 1404100554807971971
WILLIAM_ROLE_ID = 1413545658006110401
SAZZLES_ROLE_ID = 1404104881098195015

# ------------------- Utilities -------------------
def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"


def add_warning(user_id, reason=None):
    data, sha = load_data()
    if str(user_id) not in data:
        data[str(user_id)] = []
    data[str(user_id)].append(reason if reason else "No reason provided")
    save_data(data, sha)
    return len(data[str(user_id)])


def get_warnings(user_id):
    data, _ = load_data()
    return data.get(str(user_id), [])


def clear_warnings(user_id):
    data, sha = load_data()
    if str(user_id) in data:
        del data[str(user_id)]
        save_data(data, sha)
        return True
    return False


def get_all_warnings():
    data, _ = load_data()
    return data


# ------------------- Command Setup -------------------
def setup_warnings_commands(tree: app_commands.CommandTree, allowed_role_ids=None):
    ALLOWED_ROLES_IDS_SET = set(allowed_role_ids or ALLOWED_ROLES_IDS)

    def can_warn(interaction: discord.Interaction, target_member: discord.Member):
        if SAZZLES_ROLE_ID in [r.id for r in target_member.roles]:
            return False
        author_roles = [r.id for r in interaction.user.roles]
        target_roles = [r.id for r in target_member.roles]
        if any(r in ALLOWED_ROLES_IDS_SET for r in author_roles):
            return True
        if PASSENGERS_ROLE_ID in author_roles and WILLIAM_ROLE_ID in target_roles:
            return True
        return False

    @tree.command(name="warn", description="Warn a user")
    @app_commands.describe(member="Member to warn", reason="Reason for warning (optional)")
    async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = None):
        if SAZZLES_ROLE_ID in [r.id for r in member.roles]:
            await interaction.response.send_message(
                "⚠️ You cannot warn this user as she is the best and made this so you could all warn William 🖤",
                ephemeral=False
            )
            return

        if not can_warn(interaction, member):
            await interaction.response.send_message(
                f"❌ You do not have permission to warn {member.mention}.", ephemeral=True
            )
            return

        count = add_warning(member.id, reason)
        msg = f"⚠️ {member.mention} was warned"
        if reason:
            msg += f" for {reason}"
        msg += f", this is their {ordinal(count)} warning."
        await interaction.response.send_message(msg, ephemeral=False)

    @tree.command(name="warnings_list", description="List warnings for a user")
    @app_commands.describe(member="Member to see warnings for")
    async def warnings_list(interaction: discord.Interaction, member: discord.Member):
        warns = get_warnings(member.id)
        if not warns:
            await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=False)
        else:
            msg = "\n".join([f"{i+1}. {w}" for i, w in enumerate(warns)])
            await interaction.response.send_message(f"{member.mention} warnings:\n{msg}", ephemeral=False)

    @tree.command(name="server_warnings", description="List all warnings on the server")
    async def server_warnings(interaction: discord.Interaction):
        data = get_all_warnings()
        if not data:
            await interaction.response.send_message("No warnings on this server.", ephemeral=False)
            return
        msg_list = []
        for user_id, warns in data.items():
            user = interaction.guild.get_member(int(user_id))
            if user:
                msg_list.append(f"{user.display_name}: {len(warns)} warning(s)")
        await interaction.response.send_message("\n".join(msg_list) if msg_list else "No warnings found.", ephemeral=False)

    @tree.command(name="clear_warns", description="Clear all warnings for a user")
    @app_commands.describe(member="Member to clear warnings for")
    async def clear_warns(interaction: discord.Interaction, member: discord.Member):
        success = clear_warnings(member.id)
        if success:
            await interaction.response.send_message(f"✅ All warnings cleared for {member.mention}.", ephemeral=False)
        else:
            await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=False)