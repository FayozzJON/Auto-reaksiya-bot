import json
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, ADMIN_ID

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

DEFAULT_DATA = {
    "allowed_users": [ADMIN_ID],
    "users": {}  # "uid": {"first_name": "", "username": "", "accounts": {"acc1": {"session": "...", "name": "", "is_premium": False, "channels": {}}}}
}

def load_db():
    try:
        res = supabase.table("bot_storage").select("data").eq("key", "main_state").execute()
        if res.data:
            return res.data[0]["data"]
        else:
            supabase.table("bot_storage").insert({"key": "main_state", "data": DEFAULT_DATA}).execute()
            return DEFAULT_DATA
    except Exception as e:
        print(f"Supabase yuklash xatosi: {e}")
        return DEFAULT_DATA

db = load_db()

def save_db(data):
    try:
        supabase.table("bot_storage").upsert({"key": "main_state", "data": data}).execute()
    except Exception as e:
        print(f"Supabase saqlash xatosi: {e}")

def init_user(uid: int, first_name="Foydalanuvchi", username=""):
    uid_str = str(uid)
    if uid_str not in db["users"]:
        db["users"][uid_str] = {
            "first_name": first_name,
            "username": username or "",
            "accounts": {}
        }
    else:
        db["users"][uid_str]["first_name"] = first_name
        if username:
            db["users"][uid_str]["username"] = username
    save_db(db)
