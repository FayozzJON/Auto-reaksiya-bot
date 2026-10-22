from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode
from config import ADMIN_ID
from database import db, save_db

def get_admin_dashboard():
    total_users = len(db["users"])
    total_allowed = len(db["allowed_users"])
    total_accs = sum(len(u.get("accounts", [])) for u in db["users"].values())
    total_channels = sum(len(u.get("channels", {})) for u in db["users"].values())

    text = (
        f"👑 <b>ASOSIY ADMIN BOSHQARUV PANELI</b>\n\n"
        f"👥 Baza foydalanuvchilari: <b>{total_users} ta</b>\n"
        f"🟢 Ruxsat berilganlar: <b>{total_allowed} ta</b>\n"
        f"📱 Ulangan jami akkauntlar: <b>{total_accs} ta</b>\n"
        f"📢 Ulangan kanallar: <b>{total_channels} ta</b>\n\n"
        "Foydalanuvchini tanlang:"
    )

    keyboard = []
    for uid_str, u_info in db["users"].items():
        uid = int(uid_str)
        if uid == ADMIN_ID:
            continue
        status = "🟢" if uid in db["allowed_users"] else "🔴"
        name = u_info.get("first_name", "User")[:15]
        keyboard.append([InlineKeyboardButton(f"{status} {name} (ID: {uid})", callback_data=f"adm_u_{uid}")])

    keyboard.append([InlineKeyboardButton("⬅️ Bosh menyuga qaytish", callback_data="cancel_setup")])
    return text, InlineKeyboardMarkup(keyboard)

def get_user_card(target_uid: int):
    u_info = db["users"].get(str(target_uid), {})
    is_allowed = target_uid in db["allowed_users"]
    status_text = "VIP / Ruxsat berilgan 🟢" if is_allowed else "Bloklangan / Ruxsatsiz 🔴"

    ch_list = u_info.get("channels", {})
    ch_text = ""
    for cid, cdata in ch_list.items():
        mode = cdata.get("mode", "fixed")
        em_cnt = len(cdata.get("emojis", []))
        ch_text += f"\n  • <b>{cdata.get('title')}</b> (<code>{cid}</code>) | {mode} ({em_cnt} ta)"

    if not ch_text:
        ch_text = "\n  <i>(Hali kanal ulanmagan)</i>"

    text = (
        f"👤 <b>Foydalanuvchi:</b> {u_info.get('first_name')}\n"
        f"🆔 <b>ID:</b> <code>{target_uid}</code>\n"
        f"🔗 <b>Username:</b> @{u_info.get('username') or 'Mavjud emas'}\n"
        f"👑 <b>Maqomi:</b> <code>{status_text}</code>\n"
        f"📱 <b>Ulangan akkauntlari:</b> {len(u_info.get('accounts', []))} ta\n"
        f"📁 <b>Biriktirilgan kanallari:</b>{ch_text}\n"
    )

    action_btn = (
        InlineKeyboardButton("🚫 Ruxsatni bekor qilish (Bloklash)", callback_data=f"adm_revoke_{target_uid}")
        if is_allowed
        else InlineKeyboardButton("✅ Ruxsat berish (Faollashtirish)", callback_data=f"adm_grant_{target_uid}")
    )

    markup = InlineKeyboardMarkup([
        [action_btn],
        [InlineKeyboardButton("✉️ Xabar yozish", callback_data=f"adm_msg_{target_uid}")],
        [InlineKeyboardButton("⬅️ Foydalanuvchilar ro'yxatiga qaytish", callback_data="admin_dashboard")]
    ])
    return text, markup
