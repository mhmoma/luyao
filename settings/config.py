import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HTTP_PROXY = os.getenv("HTTP_PROXY", None)
HTTPS_PROXY = os.getenv("HTTPS_PROXY", None)

# OpenAI-Compatible API Settings
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")

# Welcome message channel IDs
WELCOME_CHANNEL_IDS = os.getenv("WELCOME_CHANNEL_IDS")

# Allowed channel IDs for the bot to speak in
ALLOWED_CHANNEL_IDS = os.getenv("ALLOWED_CHANNEL_IDS")

# Admin user ID
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

# Tomkk user ID — Luyao's closest person; special tone only for him
TOMKK_USER_ID = os.getenv("TOMKK_USER_ID")

# Xiaoha bot user ID — Luyao's pet dog bot
XIAOHA_USER_ID = os.getenv("XIAOHA_USER_ID")

# Channel IDs for automatic cleanup
CLEANUP_CHANNEL_IDS = os.getenv("CLEANUP_CHANNEL_IDS")

# ComfyUI Server Address
COMFYUI_SERVER_ADDRESS = os.getenv("COMFYUI_SERVER_ADDRESS", "127.0.0.1:8188")

# Proactive chat reply probability (0.0–1.0), default 0.3
try:
    PROACTIVE_CHAT_PROBABILITY = max(0.0, min(1.0, float(os.getenv("PROACTIVE_CHAT_PROBABILITY", "0.3"))))
except ValueError:
    print("警告: PROACTIVE_CHAT_PROBABILITY 无效，使用默认值 0.3")
    PROACTIVE_CHAT_PROBABILITY = 0.3

# Minimum seconds between proactive replies in the same channel
try:
    PROACTIVE_COOLDOWN_SECONDS = max(0, int(os.getenv("PROACTIVE_COOLDOWN_SECONDS", "90")))
except ValueError:
    print("警告: PROACTIVE_COOLDOWN_SECONDS 无效，使用默认值 90")
    PROACTIVE_COOLDOWN_SECONDS = 90

# IDLECLOUD API Settings
API_BASE_URL = "https://api.idlecloud.cc/api"
IDLECLOUD_API_KEY = os.getenv("IDLECLOUD_API_KEY")
