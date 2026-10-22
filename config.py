import os

API_ID = int(os.environ.get("API_ID", 34100810))
API_HASH = os.environ.get("API_HASH", "e5059d234c0d8500c048595354e179b8")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8834859784:AAHrYQH8ju3VVJjcQ0w3XNteab9oa9iASa0")

ADMIN_ID = 5998202318
LOG_CHAT_ID = -1003974652457

SESSIONS_DIR = "sessions"
DATA_FILE = "saas_secure_db.json"
os.makedirs(SESSIONS_DIR, exist_ok=True)
