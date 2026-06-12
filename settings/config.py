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

# Channel IDs for automatic cleanup
CLEANUP_CHANNEL_IDS = os.getenv("CLEANUP_CHANNEL_IDS")

# ComfyUI Server Address
COMFYUI_SERVER_ADDRESS = os.getenv("COMFYUI_SERVER_ADDRESS", "127.0.0.1:8188")

# IDLECLOUD API Settings
API_BASE_URL = "https://api.idlecloud.cc/api"
IDLECLOUD_API_KEY = os.getenv("IDLECLOUD_API_KEY")
