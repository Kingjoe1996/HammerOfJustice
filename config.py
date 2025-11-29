import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# Channel Names
DASHBOARD_CHANNEL_NAME = "👮‍♂️warnings-monitor"
MOD_LOG_CHANNEL_NAME = "🗒️admin-logs"

# Strike Configuration
STRIKE_RESET_HOURS = 72  # 3 days
DASHBOARD_UPDATE_INTERVAL = 5  # seconds

# Moderation Roles (case-sensitive)
MODERATOR_ROLES = ["Admin", "Hub President","Hub Moderator"]

# Punishment Escalation (strikes → timeout minutes)
PUNISHMENT_ESCALATION = {
    1: 5,    # 1st violation: 5 min
    2: 10,   # 2nd violation: 10 min
    3: 60,   # 3rd violation: 1 hour
    4: 120,  # 4th violation: 2 hours
    5: 180,  # 5th violation: 3 hours
    6: 1440  # 6th violation: 24 hours
}