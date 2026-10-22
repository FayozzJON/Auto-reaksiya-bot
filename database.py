import json
import os
import glob
import re
from config import DATA_FILE, SESSIONS_DIR, ADMIN_ID

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "allowed_users": [ADMIN_ID],
        "users": {}
    }

def save_db(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

db = load_db()

def init_user(uid: int, first_name="Foydalanuvchi", username=""):
    uid_str = str(uid)
    if uid_str not in db["users"]:
        db["users"][uid_str] = {
            "first_name": first_name,
            "username": username or "",
            "accounts": [],
            "channels": {}
        }
    else:
        db["users"][uid_str]["first_name"] = first_name
        if username:
            db["users"][uid_str]["username"] = username
    save_db(db)

def get_next_acc_name():
    existing = glob.glob(os.path.join(SESSIONS_DIR, "acc*.session"))
    nums = []
    for p in existing:
        fname = os.path.basename(p)
        m = re.match(r"acc(\d+)\.session", fname)
        if m:
            nums.append(int(m.group(1)))
    next_num = max(nums, default=0) + 1
    return f"acc{next_num}"
