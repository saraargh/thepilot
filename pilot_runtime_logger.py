import os
from datetime import datetime, timedelta
import pytz
import discord

# ======================
# CONFIG (ENV VARS)
# ======================
PILOT_LOG_ENABLED = os.getenv("PILOT_LOG_ENABLED", "false").lower() == "true"
PILOT_LOG_CHANNEL_ID = int(os.getenv("PILOT_LOG_CHANNEL_ID", "0"))

# Error rate limit (seconds)
ERROR_COOLDOWN_SECONDS = int(os.getenv("PILOT_ERROR_COOLDOWN", "300"))

UK_TZ = pytz.timezone("Europe/London")

# ======================
# INTERNAL STATE
# ======================
_last_error_time: datetime | None = None


# ======================
# HELPERS
# ======================
def _get_commit_hash() -> str:
    """
    Returns short git commit hash if available.
    """
    commit = (
        os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("GIT_COMMIT")
        or ""
    )
    return commit[:7] if commit else "unknown"


def _get_trigger_type(commit_hash: str) -> str:
    """
    Infers deploy trigger.
    """
    if commit_hash != "unknown":
        return "Auto deploy (GitHub commit)"
    return "Manual restart / crash recovery"


async def _get_log_channel(client: discord.Client):
    if not PILOT_LOG_ENABLED or not PILOT_LOG_CHANNEL_ID:
        return None

    channel = client.get_channel(PILOT_LOG_CHANNEL_ID)
    if channel:
        return channel

    try:
        return await client.fetch_channel(PILOT_LOG_CHANNEL_ID)
    except Exception:
        return None


# ======================
# PUBLIC API
# ======================
async def log_startup(client: discord.Client):
    """
    Call once when The Pilot starts (setup_hook).
    """
    channel = await _get_log_channel(client)
    if not channel:
        return

    commit = _get_commit_hash()
    trigger = _get_trigger_type(commit)
    now = datetime.now(UK_TZ).strftime("%d %b %Y · %H:%M:%S")

    await channel.send(
        "🚀 **The Pilot started**\n"
        f"🧾 Commit: `{commit}`\n"
        f"🔁 Trigger: {trigger}\n"
        f"🕒 {now} (UK time)"
    )


async def log_error(client: discord.Client, event_method: str):
    """
    Call from on_error. Rate-limited.
    """
    global _last_error_time

    channel = await _get_log_channel(client)
    if not channel:
        return

    now = datetime.now(UK_TZ)

    if _last_error_time:
        delta = (now - _last_error_time).total_seconds()
        if delta < ERROR_COOLDOWN_SECONDS:
            return

    _last_error_time = now

    await channel.send(
        "💥 **The Pilot encountered an error**\n"
        f"📍 Event: `{event_method}`\n"
        f"🔕 Error cooldown: {ERROR_COOLDOWN_SECONDS}s\n"
        f"🕒 {now.strftime('%d %b %Y · %H:%M:%S')} (UK time)\n"
        "📄 Check Render logs for full traceback."
    )