import asyncio
import json
import os
import re
import glob
from threading import Thread
from flask import Flask

# 1. Render Keep-Alive Port
app = Flask(__name__)

@app.route('/')
def home():
    return "⚡ Auto Reaction Multi-User Bot 24/7 faol!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_flask, daemon=True).start()

# 2. Telegram Pyrogram Bot & Userbots
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid
)
from pyrogram.handlers import MessageHandler
from pyrogram.raw.functions.channels import GetFullChannel
from pyrogram.raw.functions.messages import SendReaction, GetMessages
from pyrogram.raw.types import (
    ReactionEmoji,
    ReactionCustomEmoji,
    ChatReactionsSome,
    ChatReactionsAll,
    InputMessageID
)
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    CallbackQuery
)

API_ID = int(os.environ.get("API_ID", 34100810))
API_HASH = os.environ.get("API_HASH", "e5059d234c0d8500c048595354e179b8")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8834859784:AAHrYQH8ju3VVJjcQ0w3XNteab9oa9iASa0")

SESSIONS_DIR = "sessions"
DATA_FILE = "channel_reactions.json"
os.makedirs(SESSIONS_DIR, exist_ok=True)

bot = Client("reaction_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

active_userbots = {}
user_states = {}

DEFAULT_FALLBACK = [
    {"type": "standard", "val": "🔥"},
    {"type": "standard", "val": "❤️"},
    {"type": "standard", "val": "👍"}
]

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                d = json.load(f)
                if "channels" not in d:
                    return {"channels": d, "accounts": []}
                return d
        except Exception:
            return {"channels": {}, "accounts": []}
    return {"channels": {}, "accounts": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

db = load_data()

def get_next_acc_name():
    existing = db.get("accounts", [])
    nums = []
    for name in existing:
        m = re.match(r"acc(\d+)", name)
        if m:
            nums.append(int(m.group(1)))
    next_num = max(nums, default=0) + 1
    return f"acc{next_num}"

def get_main_menu():
    acc_count = len(active_userbots)
    ch_count = len(db.get("channels", {}))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Yangi akkaunt ulash", callback_data="login_start")],
        [InlineKeyboardButton("📢 Kanal biriktirish", callback_data="add_channel")],
        [InlineKeyboardButton(f"📋 Ulangan kanallar ({ch_count})", callback_data="list_channels")],
        [InlineKeyboardButton(f"👥 Faol akkauntlar ({acc_count} ta)", callback_data="list_accounts")]
    ])

def get_channel_action_markup(cid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Custom / Yangi reaksiyalar kiritish", callback_data=f"edit_custom_{cid}")],
        [InlineKeyboardButton("⚡ Kanalning dastlabki 3 ta reaksiyasini qo'yish", callback_data=f"edit_first3_{cid}")],
        [InlineKeyboardButton("🔄 Yangi postlarga moslashish (Dinamik)", callback_data=f"edit_dyn_{cid}")],
        [InlineKeyboardButton("❌ Kanalni o'chirish", callback_data=f"del_{cid}")],
        [InlineKeyboardButton("⬅️ Ortga qaytish", callback_data="list_channels")]
    ])

async def fetch_channel_reactions(u_client: Client, chat_id: int, msg_id: int = None):
    available = []
    try:
        peer = await u_client.resolve_peer(chat_id)
        full = await u_client.invoke(GetFullChannel(channel=peer))
        full_chat = full.full_chat

        if hasattr(full_chat, "available_reactions") and full_chat.available_reactions:
            ar = full_chat.available_reactions
            if isinstance(ar, ChatReactionsSome):
                for r in ar.reactions:
                    if isinstance(r, ReactionEmoji):
                        available.append({"type": "standard", "val": r.emoticon})
                    elif isinstance(r, ReactionCustomEmoji):
                        available.append({"type": "custom", "id": int(r.document_id)})
            elif isinstance(ar, ChatReactionsAll):
                available.extend(DEFAULT_FALLBACK)
    except Exception as e:
        print(f"Kanal tahlilida xatolik: {e}")

    if msg_id:
        try:
            peer = await u_client.resolve_peer(chat_id)
            res = await u_client.invoke(GetMessages(id=[InputMessageID(id=msg_id)]))
            if res.messages:
                m = res.messages[0]
                if hasattr(m, "reactions") and m.reactions and m.reactions.results:
                    for count_react in m.reactions.results:
                        r = count_react.reaction
                        if isinstance(r, ReactionEmoji):
                            if not any(x.get("val") == r.emoticon for x in available):
                                available.append({"type": "standard", "val": r.emoticon})
                        elif isinstance(r, ReactionCustomEmoji):
                            doc_id = int(r.document_id)
                            if not any(x.get("id") == doc_id for x in available):
                                available.append({"type": "custom", "id": doc_id})
        except Exception as e:
            print(f"Post tahlilida xatolik: {e}")

    return available if available else DEFAULT_FALLBACK

def make_auto_react(acc_name: str):
    async def handler(client: Client, message):
        chat_id = str(message.chat.id)
        channels = db.get("channels", {})
        if chat_id in channels:
            ch_data = channels[chat_id]
            mode = ch_data.get("mode", "fixed")
            emojis = ch_data.get("emojis", [])
            acc_info = active_userbots.get(acc_name, {})
            max_limit = 3 if acc_info.get("is_premium") else 1

            if mode == "dynamic" or not emojis:
                options = await fetch_channel_reactions(client, message.chat.id)
                emojis = options[:max_limit]

            if not emojis:
                emojis = DEFAULT_FALLBACK[:max_limit]

            try:
                peer = await client.resolve_peer(message.chat.id)
                reaction_list = []
                for item in emojis:
                    if item.get("type") == "custom":
                        reaction_list.append(ReactionCustomEmoji(document_id=int(item["id"])))
                    else:
                        reaction_list.append(ReactionEmoji(emoticon=item["val"]))

                await client.invoke(
                    SendReaction(
                        peer=peer,
                        msg_id=message.id,
                        reaction=reaction_list
                    )
                )
                print(f"✅ [{acc_name}] -> [{message.chat.title or chat_id}] ga reaksiya bosildi!")
            except Exception as e:
                print(f"❌ [{acc_name}] Reaksiya xatosi ({message.chat.title or chat_id}): {e}")

    return handler

async def launch_account_session(acc_name: str):
    session_file_base = os.path.join(SESSIONS_DIR, acc_name)
    c = Client(session_file_base, api_id=API_ID, api_hash=API_HASH)
    await c.start()
    me = await c.get_me()
    c.add_handler(MessageHandler(make_auto_react(acc_name), filters.channel))
    active_userbots[acc_name] = {
        "client": c,
        "id": me.id,
        "name": me.first_name,
        "is_premium": bool(me.is_premium)
    }
    if acc_name not in db["accounts"]:
        db["accounts"].append(acc_name)
        save_data(db)
    print(f"⚡ [{acc_name}] yuklandi ({me.first_name} | Premium: {me.is_premium})")

@bot.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    uid = message.from_user.id
    user_states.pop(uid, None)
    acc_count = len(active_userbots)
    ch_count = len(db.get("channels", {}))

    text = (
        f"Assalomu alaykum, <b>{message.from_user.first_name}</b>!\n\n"
        f"⚡ <b>Auto Reaction Multi-User Bot</b> faol.\n"
        f"👥 Ulangan akkauntlar: <b>{acc_count} ta</b>\n"
        f"📢 Biriktirilgan kanallar: <b>{ch_count} ta</b>\n\n"
        "Yangi akkaunt qo'shish yoki kanallarni sozlash uchun tanlang:"
    )
    await message.reply_text(text, reply_markup=get_main_menu())

@bot.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    uid = query.from_user.id
    data = query.data

    if data == "cancel_setup":
        if uid in user_states and "client" in user_states[uid]:
            try:
                await user_states[uid]["client"].disconnect()
            except Exception:
                pass
        user_states.pop(uid, None)
        await query.answer()
        await query.message.reply_text("Bosh menyu:", reply_markup=get_main_menu())

    elif data == "login_start":
        user_states[uid] = {"state": "waiting_phone_or_contact"}
        await query.answer()

        contact_keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("📞 Kontaktni ulashish (Raqamni yuborish)", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await query.message.reply_text(
            "📱 <b>Akkauntni ulash uchun:</b>\n\n"
            "Pastdagi <b>'📞 Kontaktni ulashish'</b> tugmasini bosing yoki telefon raqamingizni xalqaro formatda yozib yuboring:\n"
            "Masalan: <code>+998901234567</code>",
            reply_markup=contact_keyboard,
            parse_mode=ParseMode.HTML
        )

    elif data == "list_accounts":
        await query.answer()
        if not active_userbots:
            await query.message.edit_text(
                "📋 <b>Hozircha faol akkauntlar mavjud emas.</b>\n\n"
                "<b>'➕ Yangi akkaunt ulash'</b> tugmasi orqali akkaunt qo'shing.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="cancel_setup")]])
            )
            return

        text = "👥 <b>Ulangan Userbot akkauntlari:</b>\n\n"
        keyboard = []
        for name, info in active_userbots.items():
            status = "👑 Premium" if info["is_premium"] else "👤 Oddiy"
            text += f"• <b>{name}</b> ({info['name']}) — {status} (ID: <code>{info['id']}</code>)\n"
            keyboard.append([InlineKeyboardButton(f"🚪 {name} ni uzish", callback_data=f"remove_acc_{name}")])

        keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="cancel_setup")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    elif data.startswith("remove_acc_"):
        acc_name = data.replace("remove_acc_", "")
        if acc_name in active_userbots:
            try:
                await active_userbots[acc_name]["client"].stop()
            except Exception:
                pass
            del active_userbots[acc_name]

        if acc_name in db.get("accounts", []):
            db["accounts"].remove(acc_name)
            save_data(db)

        s_file = os.path.join(SESSIONS_DIR, f"{acc_name}.session")
        if os.path.exists(s_file):
            try:
                os.remove(s_file)
            except Exception:
                pass

        await query.answer(f"{acc_name} uzildi va o'chirildi!", show_alert=True)
        await query.message.edit_text("Bosh menyu:", reply_markup=get_main_menu())

    elif data == "add_channel":
        if not active_userbots:
            await query.answer("Avval kamida 1 ta akkauntni ulang!", show_alert=True)
            return

        user_states[uid] = {"state": "waiting_channel"}
        await query.answer()
        await query.message.edit_text(
            "✍️ <b>Kanal havolasini yuboring:</b>\n\n"
            "• Ochiq kanal: <code>@kanal</code> yoki <code>t.me/kanal</code>\n"
            "• Yopiq kanal: post havolasi (Masalan: <code>t.me/c/3934769192/247</code>)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="cancel_setup")]])
        )

    elif data == "list_channels":
        await query.answer()
        channels = db.get("channels", {})
        if not channels:
            await query.message.edit_text(
                "📋 <b>Hali hech qanday kanal biriktirilmagan.</b>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="cancel_setup")]])
            )
            return

        keyboard = []
        text = "📋 <b>Ulangan kanallar ro'yxati:</b>\n\n"
        for cid, info in channels.items():
            title = info.get("title", "Kanal")
            mode = info.get("mode", "fixed")
            desc = "Dinamik" if mode == "dynamic" else f"{len(info.get('emojis', []))} ta reaksiya"
            text += f"📢 <b>{title}</b> — {desc}\n"
            keyboard.append([InlineKeyboardButton(f"⚙️ {title[:20]}", callback_data=f"manage_{cid}")])

        keyboard.append([InlineKeyboardButton("⬅️ Asosiy menyu", callback_data="cancel_setup")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    elif data.startswith("manage_"):
        cid = data.split("_")[1]
        info = db.get("channels", {}).get(cid)
        if not info:
            await query.answer("Kanal topilmadi!", show_alert=True)
            return
        await query.answer()
        title = info.get("title", "Kanal")
        mode = info.get("mode", "fixed")
        desc = "Dinamik rejim" if mode == "dynamic" else f"{len(info.get('emojis', []))} ta reaksiya saqlangan"

        await query.message.edit_text(
            f"📢 Kanal: <b>{title}</b>\n"
            f"🆔 ID: <code>{cid}</code>\n"
            f"📊 Holat: <b>{desc}</b>\n\n"
            "Reaksiyalarni qanday sozlamoqchisiz?",
            reply_markup=get_channel_action_markup(cid),
            parse_mode=ParseMode.HTML
        )

    elif data.startswith("edit_custom_"):
        cid = data.split("_")[2]
        info = db.get("channels", {}).get(cid, {})
        user_states[uid] = {
            "state": "waiting_custom_emojis",
            "chat_id": int(cid),
            "chat_title": info.get("title", "Kanal"),
            "emojis": []
        }
        await query.answer()
        await query.message.edit_text(
            f"✨ <b>{info.get('title', 'Kanal')}</b> uchun reaksiyalar:\n\n"
            "Klaviaturangizdan <b>1 tadan 3 tagacha</b> bo'lgan istalgan Premium emoji yoki stikerni yuboring.\n\n"
            "Hozircha: <b>0/3 ta</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💾 Borini saqlash", callback_data="finish_custom_save")],
                [InlineKeyboardButton("⬅️ Bekor qilish", callback_data="cancel_setup")]
            ])
        )

    elif data == "finish_custom_save":
        cur_emojis = user_states[uid].get("emojis", [])
        if not cur_emojis:
            await query.answer("Reaksiyalar yuborilmadi!", show_alert=True)
            return
        cid = str(user_states[uid].get("chat_id"))
        title = user_states[uid].get("chat_title")
        db["channels"][cid] = {
            "title": title,
            "emojis": cur_emojis,
            "mode": "fixed"
        }
        save_data(db)
        await query.answer("Reaksiyalar saqlandi!", show_alert=True)
        user_states.pop(uid, None)
        await query.message.edit_text(
            f"✅ <b>{title}</b> kanali uchun <b>{len(cur_emojis)} ta</b> reaksiya saqlandi!\n\nBosh menyu:",
            reply_markup=get_main_menu()
        )

    elif data.startswith("edit_first3_"):
        cid = int(data.split("_")[2])
        title = db.get("channels", {}).get(str(cid), {}).get("title", "Kanal")
        first_client = next(iter(active_userbots.values()))["client"]
        options = await fetch_channel_reactions(first_client, cid)
        chosen = options[:3]
        db["channels"][str(cid)] = {
            "title": title,
            "emojis": chosen,
            "mode": "fixed"
        }
        save_data(db)
        await query.answer("Dastlabki 3 ta reaksiya biriktirildi!", show_alert=True)
        await query.message.edit_text(
            f"✅ <b>{title}</b> kanaliga dastlabki <b>{len(chosen)} ta</b> reaksiya biriktirildi!\n\nBosh menyu:",
            reply_markup=get_main_menu()
        )

    elif data.startswith("edit_dyn_"):
        cid = data.split("_")[2]
        title = db.get("channels", {}).get(cid, {}).get("title", "Kanal")
        db["channels"][cid] = {
            "title": title,
            "emojis": [],
            "mode": "dynamic"
        }
        save_data(db)
        await query.answer("Dinamik rejim yoqildi!", show_alert=True)
        await query.message.edit_text(
            f"✅ <b>{title}</b> dinamik rejimga o'tkazildi!\n\nBosh menyu:",
            reply_markup=get_main_menu()
        )

    elif data.startswith("del_"):
        cid = data.split("_")[1]
        channels = db.get("channels", {})
        if cid in channels:
            title = channels[cid].get("title", "Kanal")
            del channels[cid]
            save_data(db)
            await query.answer(f"{title} o'chirildi!", show_alert=True)
            await query.message.edit_text("Bosh menyu:", reply_markup=get_main_menu())

async def process_phone_sign_in(client, message, phone_number: str):
    uid = message.from_user.id
    phone = phone_number.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = f"+{phone}"

    target_acc_name = get_next_acc_name()
    session_file_base = os.path.join(SESSIONS_DIR, target_acc_name)

    await message.reply_text(
        f"⏳ <b>{target_acc_name}</b> uchun kod so'ralmoqda...",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML
    )

    temp_client = Client(session_file_base, api_id=API_ID, api_hash=API_HASH)
    try:
        await temp_client.connect()
        sent_code = await temp_client.send_code(phone)
        user_states[uid] = {
            "state": "waiting_code",
            "client": temp_client,
            "acc_name": target_acc_name,
            "phone": phone,
            "phone_code_hash": sent_code.phone_code_hash
        }
        await message.reply_text(
            f"📩 <b>{phone}</b> raqamiga Telegram orqali tasdiqlash kodi yuborildi!\n\n"
            f"🏷 Sessiya: <code>{target_acc_name}</code>\n\n"
            "Kodni quyidagicha yuboring:\n"
            "Masalan: <code>1 2 3 4 5</code> yoki <code>12345</code>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        try:
            await temp_client.disconnect()
        except Exception:
            pass
        s_file = f"{session_file_base}.session"
        if os.path.exists(s_file):
            try:
                os.remove(s_file)
            except Exception:
                pass
        await message.reply_text(f"❌ Xatolik yuz berdi: {e}")

@bot.on_message(filters.private & filters.contact)
async def contact_message_handler(client, message):
    uid = message.from_user.id
    if user_states.get(uid, {}).get("state") == "waiting_phone_or_contact":
        await process_phone_sign_in(client, message, message.contact.phone_number)

@bot.on_message(filters.private & ~filters.command(["start"]))
async def message_handler(client, message):
    uid = message.from_user.id
    state_data = user_states.get(uid, {})
    state = state_data.get("state")

    if state == "waiting_phone_or_contact" and message.text:
        await process_phone_sign_in(client, message, message.text)
        return

    elif state == "waiting_code":
        code = message.text.strip().replace(" ", "").replace("-", "")
        temp_client = state_data.get("client")
        phone = state_data.get("phone")
        phone_code_hash = state_data.get("phone_code_hash")
        acc_name = state_data.get("acc_name")

        if not temp_client:
            await message.reply_text("❌ Sessiya topilmadi. Qaytadan urinib ko'ring.")
            user_states.pop(uid, None)
            return

        try:
            if not temp_client.is_connected:
                await temp_client.connect()

            await temp_client.sign_in(phone, phone_code_hash, code)
            me = await temp_client.get_me()
            is_premium = bool(me.is_premium)
            await temp_client.disconnect()

            await launch_account_session(acc_name)
            user_states.pop(uid, None)

            status_text = "👑 Premium" if is_premium else "👤 Oddiy"
            await message.reply_text(
                f"🎉 <b>Yangi akkaunt muvaffaqiyatli saqlandi!</b>\n\n"
                f"🏷 Sessiya: <b>{acc_name}</b>\n"
                f"👤 Ism: <b>{me.first_name}</b>\n"
                f"📊 Turi: <b>{status_text}</b>\n\n"
                "Endi bot o'chirilganda ham bu akkaunt saqlanib qoladi!",
                reply_markup=get_main_menu()
            )

        except SessionPasswordNeeded:
            user_states[uid]["state"] = "waiting_2fa"
            await message.reply_text(
                "🔐 Akkauntingizda <b>2FA parol</b> o'rnatilgan!\n\n"
                "Iltimos, parolingizni yozib yuboring:"
            )
        except (PhoneCodeInvalid, PhoneCodeExpired):
            await message.reply_text("❌ Kod noto'g'ri yoki muddati o'tgan! Qaytadan kiriting:")
        except Exception as e:
            await message.reply_text(f"❌ Xatolik: {e}")

    elif state == "waiting_2fa":
        password = message.text.strip()
        temp_client = state_data.get("client")
        acc_name = state_data.get("acc_name")

        if not temp_client:
            await message.reply_text("❌ Sessiya topilmadi. Qaytadan urinib ko'ring.")
            user_states.pop(uid, None)
            return

        try:
            if not temp_client.is_connected:
                await temp_client.connect()

            await temp_client.check_password(password)
            me = await temp_client.get_me()
            is_premium = bool(me.is_premium)
            await temp_client.disconnect()

            await launch_account_session(acc_name)
            user_states.pop(uid, None)

            status_text = "👑 Premium" if is_premium else "👤 Oddiy"
            await message.reply_text(
                f"🎉 <b>Yangi akkaunt muvaffaqiyatli saqlandi!</b>\n\n"
                f"🏷 Sessiya: <b>{acc_name}</b>\n"
                f"👤 Ism: <b>{me.first_name}</b>\n"
                f"📊 Turi: <b>{status_text}</b>\n\n"
                "Akkaunt faol!",
                reply_markup=get_main_menu()
            )
        except PasswordHashInvalid:
            await message.reply_text("❌ 2FA parol noto'g'ri! Qaytadan kiriting:")
        except Exception as e:
            await message.reply_text(f"❌ Xatolik: {e}")

    elif state == "waiting_custom_emojis":
        cur_list = state_data.get("emojis", [])

        if message.entities:
            for ent in message.entities:
                if ent.custom_emoji_id:
                    doc_id = int(ent.custom_emoji_id)
                    if not any(e.get("id") == doc_id for e in cur_list):
                        cur_list.append({"type": "custom", "id": doc_id})
                if len(cur_list) >= 3:
                    break
        elif message.sticker and getattr(message.sticker, "custom_emoji_id", None):
            doc_id = int(message.sticker.custom_emoji_id)
            if not any(e.get("id") == doc_id for e in cur_list):
                cur_list.append({"type": "custom", "id": doc_id})
        elif message.text:
            for ch in list(message.text.strip()):
                if ch.strip() and not any(e.get("val") == ch for e in cur_list):
                    cur_list.append({"type": "standard", "val": ch})
                if len(cur_list) >= 3:
                    break

        user_states[uid]["emojis"] = cur_list

        if len(cur_list) >= 3:
            cid = str(state_data["chat_id"])
            title = state_data["chat_title"]
            db["channels"][cid] = {
                "title": title,
                "emojis": cur_list,
                "mode": "fixed"
            }
            save_data(db)
            user_states.pop(uid, None)
            await message.reply_text(
                f"✅ <b>{title}</b> kanali uchun <b>{len(cur_list)} ta</b> reaksiya saqlandi!\n\n"
                "Endi barcha faol akkauntlar yangi postlarga ushbu reaksiyalarni bosadi.",
                reply_markup=get_main_menu()
            )
        else:
            await message.reply_text(
                f"👍 Reaksiya qabul qilindi! Hozircha: <b>{len(cur_list)}/3 ta</b>.\n\n"
                "Yana yuboring yoki <b>'💾 Borini saqlash'</b> tugmasini bosing:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💾 Borini saqlash", callback_data="finish_custom_save")],
                    [InlineKeyboardButton("⬅️ Bekor qilish", callback_data="cancel_setup")]
                ])
            )

    elif state == "waiting_channel":
        if not active_userbots:
            await message.reply_text("Faol akkauntlar topilmadi.")
            return

        first_client = next(iter(active_userbots.values()))["client"]
        chat_obj = None
        target_msg_id = None

        if message.forward_from_chat:
            chat_obj = message.forward_from_chat
        elif message.text:
            text = message.text.strip()
            c_match = re.search(r"t\.me/c/(\d+)/(\d+)", text)
            if c_match:
                raw_id = int(c_match.group(1))
                target_msg_id = int(c_match.group(2))
                full_id = int(f"-100{raw_id}")
                try:
                    chat_obj = await first_client.get_chat(full_id)
                except Exception:
                    chat_obj = type("ChatStub", (), {"id": full_id, "title": f"Yopiq kanal ({full_id})"})()
            else:
                clean_username = text.replace("https://t.me/", "").replace("http://t.me/", "").split("/")[0]
                if not clean_username.startswith("@") and not clean_username.startswith("-100"):
                    clean_username = f"@{clean_username}"
                try:
                    for acc in active_userbots.values():
                        try:
                            await acc["client"].join_chat(clean_username)
                        except Exception:
                            pass
                    chat_obj = await first_client.get_chat(clean_username)
                except Exception as e:
                    await message.reply_text(f"❌ Kanal topilmadi! Akkauntlar a'zo bo'lishi kerak.\nXato: {e}")
                    return

        if chat_obj:
            cid_str = str(chat_obj.id)
            if cid_str not in db.get("channels", {}):
                db["channels"][cid_str] = {
                    "title": getattr(chat_obj, "title", "Kanal"),
                    "emojis": [],
                    "mode": "dynamic"
                }
                save_data(db)

            user_states.pop(uid, None)
            await message.reply_text(
                f"📢 Kanal aniqlandi: <b>{getattr(chat_obj, 'title', 'Kanal')}</b>\n"
                f"🆔 ID: <code>{chat_obj.id}</code>\n\n"
                "Ushbu kanal uchun reaksiyalarni qanday sozlamoqchisiz?",
                reply_markup=get_channel_action_markup(chat_obj.id),
                parse_mode=ParseMode.HTML
            )

async def main():
    await bot.start()
    print("🤖 Asosiy boshqaruv boti ishga tushdi.")

    saved_accounts = list(db.get("accounts", []))
    for acc_name in saved_accounts:
        s_file = os.path.join(SESSIONS_DIR, f"{acc_name}.session")
        if os.path.exists(s_file):
            try:
                await launch_account_session(acc_name)
            except Exception as e:
                print(f"❌ [{acc_name}] sessiyasini yuklashda xatolik: {e}")
        else:
            if acc_name in db["accounts"]:
                db["accounts"].remove(acc_name)
                save_data(db)

    print(f"🔥 Jami {len(active_userbots)} ta Userbot akkaunti parallel ishlamoqda!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop.run_until_complete(main())
