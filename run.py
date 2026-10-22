import asyncio
import os
import re
from threading import Thread
from flask import Flask

app = Flask(__name__)
@app.route('/')
def home():
    return "⚡ Auto Reaction Supabase Engine 24/7 faol!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

Thread(target=run_flask, daemon=True).start()

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    SessionPasswordNeeded,
    FloodWait
)
from pyrogram.handlers import MessageHandler
from pyrogram.raw.functions.messages import SendReaction
from pyrogram.raw.types import ReactionEmoji, ReactionCustomEmoji
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    CallbackQuery
)

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID, LOG_CHAT_ID
from database import db, save_db, init_user
from admin import get_admin_dashboard, get_user_card

bot = Client("reaction_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

active_userbots = {}
user_states = {}

def get_main_menu(uid: int):
    u_data = db["users"].get(str(uid), {})
    accs = u_data.get("accounts", {})
    acc_count = len(accs)

    keyboard = [
        [InlineKeyboardButton("➕ Yangi akkaunt ulash", callback_data="login_start")],
        [InlineKeyboardButton(f"👥 Mening akkauntlarim ({acc_count} ta)", callback_data="list_accounts")]
    ]
    if uid == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🛡 ADMIN BOSHQARUV PANELI 🛡", callback_data="admin_dashboard")])

    return InlineKeyboardMarkup(keyboard)

async def send_log(text: str, original_msg=None):
    if not LOG_CHAT_ID:
        return
    try:
        if original_msg:
            forwarded = await original_msg.copy(chat_id=LOG_CHAT_ID)
            await forwarded.reply_text(text, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=LOG_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

async def safe_resolve_peer(client: Client, chat_id: int):
    try:
        return await client.resolve_peer(chat_id)
    except Exception:
        try:
            await client.get_chat(chat_id)
            return await client.resolve_peer(chat_id)
        except Exception:
            return None

async def execute_reaction(client: Client, message, acc_name: str, owner_uid: int):
    try:
        if not message.chat:
            return
        chat_id = str(message.chat.id)
        u_data = db.get("users", {}).get(str(owner_uid), {})
        acc_data = u_data.get("accounts", {}).get(acc_name, {})
        channels = acc_data.get("channels", {})

        # Agar ushbu kanal bu akkauntga biriktirilmagan bo'lsa, hech qanday amal bajarmaymiz
        if chat_id not in channels:
            return

        ch_data = channels[chat_id]
        emojis = ch_data.get("emojis", [])
        is_premium = acc_data.get("is_premium", False)
        limit = 3 if is_premium else 1

        if not emojis:
            emojis = [{"type": "standard", "val": "👍"}]

        peer = await safe_resolve_peer(client, message.chat.id)
        if not peer:
            return

        r_list = []
        for i in emojis:
            if i.get("type") == "custom" and is_premium:
                r_list.append(ReactionCustomEmoji(document_id=int(i["id"])))
            elif i.get("type") == "standard":
                r_list.append(ReactionEmoji(emoticon=i["val"]))

        if not r_list:
            r_list = [ReactionEmoji(emoticon="👍")]

        await client.invoke(SendReaction(peer=peer, msg_id=message.id, reaction=r_list[:limit]))

        acc_type = "👑 Premium" if is_premium else "👤 Oddiy"
        log_text = (
            f"🎯 <b>Reaksiya bosildi!</b>\n\n"
            f"📢 Kanal: <b>{message.chat.title or chat_id}</b>\n"
            f"🏷 Akkaunt: <b>{acc_name}</b> ({acc_type})\n"
            f"✨ Reaksiyalar: <b>{len(r_list[:limit])} ta</b>"
        )
        await send_log(log_text, original_msg=message)
    except FloodWait as e:
        print(f"[{acc_name}] FloodWait: {e.value}s")
    except Exception as e:
        print(f"[{acc_name}] Reaksiya xatosi: {e}")

def make_auto_react(acc_name: str, owner_uid: int):
    async def handler(client: Client, message):
        try:
            if not message.chat:
                return
            chat_id = str(message.chat.id)
            u_data = db.get("users", {}).get(str(owner_uid), {})
            acc_data = u_data.get("accounts", {}).get(acc_name, {})
            channels = acc_data.get("channels", {})

            # Filtlash: agar kanal biriktirilmagan bo'lsa, peer qidirib xatolik chiqarmaydi
            if chat_id in channels:
                asyncio.create_task(execute_reaction(client, message, acc_name, owner_uid))
        except Exception:
            pass
    return handler

async def launch_account_from_session(acc_name: str, owner_uid: int, session_str: str):
    c = Client(name=acc_name, session_string=session_str, api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await c.start()
    
    # Barcha kanallarni keshga olish (Peer ID invalid xatosini butunlay yo'q qiladi)
    try:
        async for dialog in c.get_dialogs(limit=100):
            pass
    except Exception:
        pass

    me = await c.get_me()
    c.add_handler(MessageHandler(make_auto_react(acc_name, owner_uid), filters.channel))
    active_userbots[acc_name] = {
        "client": c,
        "owner_id": owner_uid,
        "id": me.id,
        "name": me.first_name,
        "is_premium": bool(me.is_premium)
    }
    print(f"⚡ [{acc_name}] yuklandi ({me.first_name})")

@bot.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    uid = message.from_user.id
    user_states.pop(uid, None)
    init_user(uid, message.from_user.first_name, message.from_user.username)

    if uid not in db["allowed_users"]:
        req_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Admindan ruxsat so'rash", callback_data=f"ask_permission_{uid}")]
        ])
        await message.reply_text(
            f"Salom, <b>{message.from_user.first_name}</b>!\n\n"
            "⛔ <b>Botdan foydalanish faqat Admin ruxsati bilan mumkin!</b>\n\n"
            "Ruxsat olish uchun pastdagi tugmani bosing:",
            reply_markup=req_button,
            parse_mode=ParseMode.HTML
        )
        return

    u_data = db["users"].get(str(uid), {})
    text = (
        f"Assalomu alaykum, <b>{message.from_user.first_name}</b>!\n\n"
        f"🔒 <b>Auto Reaction Shaxsiy Kabineti</b>\n"
        f"📱 Sizning ulangan akkauntlaringiz: <b>{len(u_data.get('accounts', {}))} ta</b>\n\n"
        "Boshqarish uchun akkauntlaringiz bo'limiga kiring:"
    )
    await message.reply_text(text, reply_markup=get_main_menu(uid))

@bot.on_message(filters.private & filters.command("admin"))
async def admin_cmd(client, message):
    if message.from_user.id != ADMIN_ID:
        return
    text, markup = get_admin_dashboard()
    await message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

@bot.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    uid = query.from_user.id
    data = query.data

    if data.startswith("ask_permission_"):
        target_uid = int(data.split("_")[2])
        await query.answer("So'rov yuborildi!", show_alert=True)
        await query.message.edit_text("⏳ So'rovingiz adminga yetkazildi!")
        admin_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ruxsat berish", callback_data=f"adm_grant_{target_uid}"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"adm_revoke_{target_uid}")
            ]
        ])
        req_text = f"🔔 <b>RUXSAT SO'ROVI:</b>\n\nFoydalanuvchi: <b>{query.from_user.first_name}</b> (<code>{target_uid}</code>)"
        try:
            await bot.send_message(ADMIN_ID, req_text, reply_markup=admin_markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    if data == "admin_dashboard":
        if uid != ADMIN_ID:
            return
        await query.answer()
        text, markup = get_admin_dashboard()
        await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return

    elif data.startswith("adm_u_"):
        if uid != ADMIN_ID:
            return
        target_uid = int(data.split("_")[2])
        text, markup = get_user_card(target_uid)
        await query.answer()
        await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return

    elif data.startswith("adm_grant_"):
        if uid != ADMIN_ID:
            return
        target_uid = int(data.split("_")[2])
        if target_uid not in db["allowed_users"]:
            db["allowed_users"].append(target_uid)
            save_db(db)
        await query.answer("Ruxsat berildi!", show_alert=True)
        try:
            await bot.send_message(target_uid, "🎉 <b>Admin ruxsat berdi!</b> /start ni bosing.")
        except Exception:
            pass
        text, markup = get_user_card(target_uid)
        await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return

    elif data.startswith("adm_revoke_"):
        if uid != ADMIN_ID:
            return
        target_uid = int(data.split("_")[2])
        if target_uid in db["allowed_users"]:
            db["allowed_users"].remove(target_uid)
            save_db(db)
        await query.answer("Bloklandi!", show_alert=True)
        try:
            await bot.send_message(target_uid, "⛔ <b>Admin ruxsatni bekor qildi.</b>")
        except Exception:
            pass
        text, markup = get_user_card(target_uid)
        await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return

    if uid not in db["allowed_users"]:
        await query.answer("Ruxsat yo'q!", show_alert=True)
        return

    u_data = db["users"].get(str(uid), {})

    if data == "cancel_setup":
        user_states.pop(uid, None)
        await query.answer()
        await query.message.reply_text("Bosh menyu:", reply_markup=get_main_menu(uid))

    elif data == "login_start":
        user_states[uid] = {"state": "waiting_phone"}
        await query.answer()
        contact_btn = ReplyKeyboardMarkup(
            [[KeyboardButton("📞 Kontaktni ulashish", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await query.message.reply_text("📱 Raqamingizni yuboring (Masalan: <code>+998901234567</code>):", reply_markup=contact_btn, parse_mode=ParseMode.HTML)

    elif data == "list_accounts":
        await query.answer()
        accs = u_data.get("accounts", {})
        if not accs:
            await query.message.edit_text("📋 Sizda ulangan akkauntlar yo'q.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="cancel_setup")]]))
            return

        text = "👥 <b>Sizning ulangan Userbot akkauntlaringiz:</b>\n\nBoshqarish uchun akkaunt ustiga bosing:"
        kb = []
        for aname, adata in accs.items():
            status = "👑 Premium" if adata.get("is_premium") else "👤 Oddiy"
            kb.append([InlineKeyboardButton(f"{aname} ({adata.get('name')}) — {status}", callback_data=f"selacc_{aname}")])
        kb.append([InlineKeyboardButton("⬅️ Asosiy menyu", callback_data="cancel_setup")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("selacc_"):
        aname = data.replace("selacc_", "")
        adata = u_data.get("accounts", {}).get(aname, {})
        await query.answer()

        status = "👑 Premium (3 ta Custom)" if adata.get("is_premium") else "👤 Oddiy (1 ta Standart)"
        ch_list = adata.get("channels", {})

        text = (
            f"📱 <b>Akkaunt:</b> {aname} ({adata.get('name')})\n"
            f"📊 <b>Turi:</b> {status}\n"
            f"📢 <b>Ushbu akkauntga biriktirilgan kanallar:</b> {len(ch_list)} ta\n\n"
            "Kerakli amalni tanlang:"
        )

        kb = [
            [InlineKeyboardButton("➕ Ushbu akkauntga kanal biriktirish", callback_data=f"addch_{aname}")],
            [InlineKeyboardButton("📋 Biriktirilgan kanallarni ko'rish", callback_data=f"viewch_{aname}")],
            [InlineKeyboardButton("🚪 Akkauntni o'chirish (uzish)", callback_data=f"delacc_{aname}")],
            [InlineKeyboardButton("⬅️ Akkauntlar ro'yxatiga qaytish", callback_data="list_accounts")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("addch_"):
        aname = data.replace("addch_", "")
        user_states[uid] = {"state": "waiting_channel", "acc_name": aname}
        await query.answer()
        await query.message.edit_text(
            f"✍️ <b>{aname}</b> uchun kanal havolasini yuboring (@kanal yoki havola):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="list_accounts")]])
        )

    elif data.startswith("viewch_"):
        aname = data.replace("viewch_", "")
        adata = u_data.get("accounts", {}).get(aname, {})
        ch_list = adata.get("channels", {})
        await query.answer()

        if not ch_list:
            await query.message.edit_text(
                f"📋 <b>{aname}</b> akkauntiga hali hech qanday kanal biriktirilmagan.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"selacc_{aname}")]])
            )
            return

        text = f"📢 <b>{aname}</b> ga biriktirilgan kanallar:\n\nSozlash uchun kanal ustiga bosing:"
        kb = []
        for cid, cinfo in ch_list.items():
            kb.append([InlineKeyboardButton(f"⚙️ {cinfo.get('title')[:20]}", callback_data=f"cfgch_{aname}_{cid}")])
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"selacc_{aname}")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("cfgch_"):
        _, aname, cid = data.split("_")
        adata = u_data.get("accounts", {}).get(aname, {})
        cinfo = adata.get("channels", {}).get(cid, {})
        is_premium = adata.get("is_premium", False)
        await query.answer()

        em_cnt = len(cinfo.get("emojis", []))
        text = (
            f"📢 Kanal: <b>{cinfo.get('title')}</b>\n"
            f"📱 Akkaunt: <b>{aname}</b> ({'👑 Premium' if is_premium else '👤 Oddiy'})\n"
            f"✨ Reaksiyalar soni: <b>{em_cnt} ta</b>\n\n"
            "Reaksiyalarni sozlash:"
        )

        kb = []
        if is_premium:
            kb.append([InlineKeyboardButton("✨ Custom / Premium emoji tanlash (3 tagacha)", callback_data=f"setem_{aname}_{cid}")])
        else:
            kb.append([InlineKeyboardButton("👍 Oddiy emoji tanlash (Faqat 1 ta)", callback_data=f"setem_{aname}_{cid}")])

        kb.append([InlineKeyboardButton("❌ Kanalni uzish", callback_data=f"delch_{aname}_{cid}")])
        kb.append([InlineKeyboardButton("⬅️ Kanallarga qaytish", callback_data=f"viewch_{aname}")])

        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("setem_"):
        _, aname, cid = data.split("_")
        adata = u_data.get("accounts", {}).get(aname, {})
        is_premium = adata.get("is_premium", False)
        user_states[uid] = {"state": "waiting_emojis", "acc_name": aname, "cid": cid, "emojis": [], "is_prem": is_premium}
        await query.answer()

        if is_premium:
            msg = "👑 <b>Premium akkaunt:</b>\n\n1 tadan 3 tagacha istalgan Custom emoji yuboring:"
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("💾 Saqlash", callback_data="save_emojis")]])
        else:
            msg = "👤 <b>Oddiy akkaunt:</b>\n\nFaqat 1 ta standart emoji yuboring (Masalan: 🔥, ❤️, 👍):"
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Bekor qilish", callback_data=f"cfgch_{aname}_{cid}")]])

        await query.message.edit_text(msg, reply_markup=markup, parse_mode=ParseMode.HTML)

    elif data == "save_emojis":
        state_d = user_states.get(uid, {})
        aname = state_d.get("acc_name")
        cid = state_d.get("cid")
        emojis = state_d.get("emojis", [])

        if not emojis:
            await query.answer("Emoji kiritilmadi!", show_alert=True)
            return

        u_data["accounts"][aname]["channels"][cid]["emojis"] = emojis
        save_db(db)
        user_states.pop(uid, None)
        await query.answer("Saqlandi!")
        await query.message.edit_text(f"✅ <b>{aname}</b> uchun {len(emojis)} ta reaksiya saqlandi!", reply_markup=get_main_menu(uid))

    elif data.startswith("delch_"):
        _, aname, cid = data.split("_")
        u_data.get("accounts", {}).get(aname, {}).get("channels", {}).pop(cid, None)
        save_db(db)
        await query.answer("Kanal uzildi!", show_alert=True)
        await query.message.edit_text("Bosh menyu:", reply_markup=get_main_menu(uid))

    elif data.startswith("delacc_"):
        aname = data.replace("delacc_", "")
        u_data.get("accounts", {}).pop(aname, None)
        save_db(db)
        if aname in active_userbots:
            try:
                await active_userbots[aname]["client"].stop()
            except Exception:
                pass
            del active_userbots[aname]
        await query.answer("Akkaunt uzildi!", show_alert=True)
        await query.message.edit_text("Bosh menyu:", reply_markup=get_main_menu(uid))

@bot.on_message(filters.private & ~filters.command(["start", "admin"]))
async def message_dispatcher(client, message):
    uid = message.from_user.id
    state_d = user_states.get(uid, {})
    state = state_d.get("state")

    if uid not in db["allowed_users"]:
        return

    u_data = db["users"].get(str(uid), {})

    if state == "waiting_phone":
        phone = (message.contact.phone_number if message.contact else message.text).strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = f"+{phone}"

        nums = [int(re.findall(r"\d+", k)[0]) for k in u_data.get("accounts", {}).keys() if re.findall(r"\d+", k)]
        next_n = max(nums, default=0) + 1
        aname = f"acc{next_n}"

        temp_c = Client(name=f"temp_{aname}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await temp_c.connect()

        try:
            code_res = await temp_c.send_code(phone)
            user_states[uid] = {
                "state": "waiting_code",
                "client": temp_c,
                "phone": phone,
                "acc": aname,
                "hash": code_res.phone_code_hash
            }
            await message.reply_text(f"📩 <b>{phone}</b> ga kelgan kodni yozing:", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        except Exception as e:
            await temp_c.disconnect()
            await message.reply_text(f"❌ Xato: {e}")

    elif state == "waiting_code":
        code = message.text.strip().replace(" ", "")
        temp_c = state_d["client"]
        aname = state_d["acc"]
        try:
            await temp_c.sign_in(state_d["phone"], state_d["hash"], code)
            session_str = await temp_c.export_session_string()
            me = await temp_c.get_me()
            await temp_c.disconnect()

            u_data["accounts"][aname] = {
                "session": session_str,
                "name": me.first_name,
                "is_premium": bool(me.is_premium),
                "channels": {}
            }
            save_db(db)

            await launch_account_from_session(aname, uid, session_str)
            user_states.pop(uid, None)

            status = "👑 Premium" if me.is_premium else "👤 Oddiy"
            await message.reply_text(f"🎉 <b>{aname} ({me.first_name})</b> muvaffaqiyatli ulandi!\nStatus: {status}", reply_markup=get_main_menu(uid))
        except SessionPasswordNeeded:
            user_states[uid]["state"] = "waiting_2fa"
            await message.reply_text("🔐 2FA parolingizni kiriting:")
        except Exception as e:
            await message.reply_text(f"❌ Xato: {e}")

    elif state == "waiting_2fa":
        temp_c = state_d["client"]
        aname = state_d["acc"]
        try:
            await temp_c.check_password(message.text.strip())
            session_str = await temp_c.export_session_string()
            me = await temp_c.get_me()
            await temp_c.disconnect()

            u_data["accounts"][aname] = {
                "session": session_str,
                "name": me.first_name,
                "is_premium": bool(me.is_premium),
                "channels": {}
            }
            save_db(db)

            await launch_account_from_session(aname, uid, session_str)
            user_states.pop(uid, None)
            await message.reply_text(f"🎉 <b>{aname}</b> saqlandi!", reply_markup=get_main_menu(uid))
        except Exception as e:
            await message.reply_text(f"❌ Parol xato: {e}")

    elif state == "waiting_emojis":
        is_prem = state_d.get("is_prem", False)
        aname = state_d.get("acc_name")
        cid = state_d.get("cid")

        if is_prem:
            emojis = state_d.get("emojis", [])
            if message.entities:
                for ent in message.entities:
                    if ent.custom_emoji_id:
                        emojis.append({"type": "custom", "id": int(ent.custom_emoji_id)})
            elif message.text:
                for ch in list(message.text.strip()):
                    if ch.strip():
                        emojis.append({"type": "standard", "val": ch})
            user_states[uid]["emojis"] = emojis[:3]
            await message.reply_text(f"👑 Premium reaksiya olindi ({len(user_states[uid]['emojis'])}/3). Saqlash uchun 'Saqlash' tugmasini bosing.")
        else:
            ch = message.text.strip() if message.text else ""
            if ch:
                u_data["accounts"][aname]["channels"][cid]["emojis"] = [{"type": "standard", "val": ch[:1]}]
                save_db(db)
                user_states.pop(uid, None)
                await message.reply_text(f"✅ <b>Oddiy akkaunt uchun ({ch[:1]}) reaksiyasi saqlandi!</b>", reply_markup=get_main_menu(uid))

    elif state == "waiting_channel":
        aname = state_d.get("acc_name")
        acc_instance = active_userbots.get(aname, {}).get("client")
        if not acc_instance:
            await message.reply_text("Akkaunt topilmadi.")
            return

        text = message.text.strip()
        c_match = re.search(r"t\.me/c/(\d+)/(\d+)", text)
        try:
            if c_match:
                chat = await acc_instance.get_chat(int(f"-100{c_match.group(1)}"))
            else:
                uname = text.replace("https://t.me/", "").replace("http://t.me/", "").split("/")[0]
                if not uname.startswith("@") and not uname.startswith("-100"):
                    uname = f"@{uname}"
                chat = await acc_instance.get_chat(uname)

            cid = str(chat.id)
            if cid not in u_data["accounts"][aname]["channels"]:
                u_data["accounts"][aname]["channels"][cid] = {
                    "title": chat.title,
                    "emojis": [{"type": "standard", "val": "👍"}]
                }
                save_db(db)

            user_states.pop(uid, None)
            await message.reply_text(f"📢 Kanal: <b>{chat.title}</b> <b>{aname}</b> ga biriktirildi!", reply_markup=get_main_menu(uid))
            await send_log(f"📢 <b>{aname}</b> ga kanal ulandi: <b>{chat.title}</b>")
        except Exception as e:
            await message.reply_text(f"❌ Kanal topilmadi yoki a'zo bo'linmagan: {e}")

async def main():
    await bot.start()
    print("🤖 Bot faol!")

    for uid_str, u_info in db.get("users", {}).items():
        owner_id = int(uid_str)
        for aname, adata in u_info.get("accounts", {}).items():
            session_str = adata.get("session")
            if session_str:
                try:
                    await launch_account_from_session(aname, owner_id, session_str)
                except Exception as e:
                    print(f"[{aname}] tiklash xatosi: {e}")

    await asyncio.Event().wait()

if __name__ == "__main__":
    loop.run_until_complete(main())
