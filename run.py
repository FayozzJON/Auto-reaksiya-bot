import asyncio
import os
import re
from threading import Thread
from flask import Flask

# Keep-Alive
app = Flask(__name__)
@app.route('/')
def home():
    return "⚡ Auto Reaction Multi-User Secure Bot faol!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

Thread(target=run_flask, daemon=True).start()

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid,
    FloodWait
)
from pyrogram.handlers import MessageHandler
from pyrogram.raw.functions.channels import GetFullChannel
from pyrogram.raw.functions.messages import SendReaction
from pyrogram.raw.types import (
    ReactionEmoji,
    ReactionCustomEmoji,
    ChatReactionsSome,
    ChatReactionsAll
)
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    CallbackQuery
)

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID, LOG_CHAT_ID, SESSIONS_DIR
from database import db, save_db, init_user, get_next_acc_name
from admin import get_admin_dashboard, get_user_card

bot = Client("reaction_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

active_userbots = {}
user_states = {}
channel_reactions_cache = {}

DEFAULT_PREMIUM = [{"type": "standard", "val": "🔥"}, {"type": "standard", "val": "❤️"}, {"type": "standard", "val": "👍"}]
DEFAULT_STANDARD = [{"type": "standard", "val": "👍"}]

def get_main_menu(uid: int):
    u_data = db["users"].get(str(uid), {})
    acc_count = len(u_data.get("accounts", []))
    ch_count = len(u_data.get("channels", {}))

    keyboard = [
        [InlineKeyboardButton("📱 Shaxsiy akkaunt ulash", callback_data="login_start")],
        [InlineKeyboardButton("📢 Kanal biriktirish", callback_data="add_channel")],
        [InlineKeyboardButton(f"📋 Mening kanallarim ({ch_count})", callback_data="list_channels")],
        [InlineKeyboardButton(f"👥 Mening akkauntlarim ({acc_count} ta)", callback_data="list_accounts")]
    ]
    if uid == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🛡 ADMIN BOSHQARUV PANELI 🛡", callback_data="admin_dashboard")])

    return InlineKeyboardMarkup(keyboard)

def get_channel_action_markup(cid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Premium akkauntlar uchun (3 ta Custom)", callback_data=f"set_prem_{cid}")],
        [InlineKeyboardButton("👤 Oddiy akkauntlar uchun (1 ta Oddiy)", callback_data=f"set_norm_{cid}")],
        [InlineKeyboardButton("⚡ Kanalning dastlabki reaksiyalarini qo'yish", callback_data=f"edit_first3_{cid}")],
        [InlineKeyboardButton("🔄 Yangi postlarga moslashish (Dinamik)", callback_data=f"edit_dyn_{cid}")],
        [InlineKeyboardButton("❌ Kanalni o'chirish", callback_data=f"del_{cid}")],
        [InlineKeyboardButton("⬅️ Ortga qaytish", callback_data="list_channels")]
    ])

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

async def fetch_channel_reactions(u_client: Client, chat_id: int):
    if chat_id in channel_reactions_cache:
        return channel_reactions_cache[chat_id]

    available = []
    try:
        peer = await safe_resolve_peer(u_client, chat_id)
        if peer:
            full = await u_client.invoke(GetFullChannel(channel=peer))
            ar = full.full_chat.available_reactions
            if ar:
                if isinstance(ar, ChatReactionsSome):
                    for r in ar.reactions:
                        if isinstance(r, ReactionEmoji):
                            available.append({"type": "standard", "val": r.emoticon})
                        elif isinstance(r, ReactionCustomEmoji):
                            available.append({"type": "custom", "id": int(r.document_id)})
                elif isinstance(ar, ChatReactionsAll):
                    available.extend(DEFAULT_PREMIUM)
    except Exception:
        pass

    res = available if available else DEFAULT_PREMIUM
    channel_reactions_cache[chat_id] = res
    return res

async def execute_reaction(client: Client, message, acc_name: str, owner_uid: int):
    try:
        if not message.chat:
            return

        chat_id = str(message.chat.id)
        u_channels = db.get("users", {}).get(str(owner_uid), {}).get("channels", {})

        if chat_id not in u_channels:
            return

        ch_data = u_channels[chat_id]
        mode = ch_data.get("mode", "fixed")
        acc_info = active_userbots.get(acc_name, {})
        is_premium = acc_info.get("is_premium", False)

        # Reaksiyalarni tanlash
        if is_premium:
            emojis = ch_data.get("premium_emojis", [])
            limit = 3
        else:
            emojis = ch_data.get("normal_emojis", [])
            limit = 1

        if mode == "dynamic" or not emojis:
            options = await fetch_channel_reactions(client, message.chat.id)
            if not is_premium:
                # Oddiy akkaunt uchun faqat standart emoji olamiz
                std_options = [x for x in options if x.get("type") == "standard"]
                emojis = std_options[:1] if std_options else DEFAULT_STANDARD
            else:
                emojis = options[:limit]

        if not emojis:
            emojis = DEFAULT_PREMIUM[:limit] if is_premium else DEFAULT_STANDARD

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

        acc_type = "👑 Premium (3 ta)" if is_premium else "👤 Oddiy (1 ta)"
        log_text = (
            f"🎯 <b>Reaksiya bosildi!</b>\n\n"
            f"📢 Kanal: <b>{message.chat.title or chat_id}</b>\n"
            f"🏷 Akkaunt: <b>{acc_name}</b> ({acc_type})\n"
            f"✨ Reaksiyalar: <b>{len(r_list[:limit])} ta</b>"
        )
        await send_log(log_text, original_msg=message)

    except FloodWait as e:
        print(f"[{acc_name}] FloodWait: {e.value} soniya kutilmoqda")
    except Exception as e:
        print(f"[{acc_name}] Reaksiya xatosi: {e}")

def make_auto_react(acc_name: str, owner_uid: int):
    async def handler(client: Client, message):
        asyncio.create_task(execute_reaction(client, message, acc_name, owner_uid))
    return handler

async def launch_account(acc_name: str, owner_uid: int):
    s_path = os.path.join(SESSIONS_DIR, acc_name)
    c = Client(s_path, api_id=API_ID, api_hash=API_HASH)
    await c.start()
    me = await c.get_me()
    c.add_handler(MessageHandler(make_auto_react(acc_name, owner_uid), filters.channel))
    active_userbots[acc_name] = {
        "client": c,
        "owner_id": owner_uid,
        "id": me.id,
        "name": me.first_name,
        "is_premium": bool(me.is_premium)
    }
    init_user(owner_uid)
    if acc_name not in db["users"][str(owner_uid)]["accounts"]:
        db["users"][str(owner_uid)]["accounts"].append(acc_name)
        save_db(db)
    print(f"⚡ [{acc_name}] foydalanuvchi [{owner_uid}] uchun yuklandi.")

# /start
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

    u_data = db["users"][str(uid)]
    text = (
        f"Assalomu alaykum, <b>{message.from_user.first_name}</b>!\n\n"
        f"🔒 <b>Auto Reaction Shaxsiy Kabineti</b>\n"
        f"📱 Akkauntlaringiz: <b>{len(u_data.get('accounts', []))} ta</b>\n"
        f"📢 Kanallaringiz: <b>{len(u_data.get('channels', {}))} ta</b>\n\n"
        "Kerakli bo'limni tanlang:"
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
        await query.message.edit_text(
            "⏳ <b>So'rovingiz adminga yetkazildi!</b>\n\nAdmin ruxsat bergach, bot sizga xabar beradi.",
            parse_mode=ParseMode.HTML
        )

        admin_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ruxsat berish", callback_data=f"adm_grant_{target_uid}"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"adm_revoke_{target_uid}")
            ]
        ])
        req_text = (
            f"🔔 <b>YANGI RUXSAT SO'ROVI!</b>\n\n"
            f"👤 Foydalanuvchi: <b>{query.from_user.first_name}</b>\n"
            f"🔗 Username: @{query.from_user.username or 'yoq'}\n"
            f"🆔 ID: <code>{target_uid}</code>"
        )
        try:
            await bot.send_message(ADMIN_ID, req_text, reply_markup=admin_markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await send_log(req_text)
        return

    # Admin
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
            await bot.send_message(target_uid, "🎉 <b>Admin sizga ruxsat berdi!</b>\n\n/start buyrug'ini bosing.", parse_mode=ParseMode.HTML)
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
        await query.answer("Ruxsat bekor qilindi!", show_alert=True)
        try:
            await bot.send_message(target_uid, "⛔ <b>Admin ruxsatingizni bekor qildi.</b>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        text, markup = get_user_card(target_uid)
        await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return

    if uid not in db["allowed_users"]:
        await query.answer("Sizga ruxsat berilmagan!", show_alert=True)
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
        await query.message.reply_text(
            "📱 Raqamingizni yuboring (Masalan: <code>+998901234567</code>):",
            reply_markup=contact_btn,
            parse_mode=ParseMode.HTML
        )

    elif data == "list_accounts":
        await query.answer()
        accs = u_data.get("accounts", [])
        if not accs:
            await query.message.edit_text("📋 Sizda ulangan akkauntlar yo'q.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="cancel_setup")]]))
            return
        text = "👥 <b>Sizning ulangan Userbot akkauntlaringiz:</b>\n\n"
        kb = []
        for name in accs:
            info = active_userbots.get(name, {})
            status = "👑 Premium" if info.get("is_premium") else "👤 Oddiy"
            text += f"• <b>{name}</b> ({info.get('name')}) — {status}\n"
            kb.append([InlineKeyboardButton(f"🚪 {name} ni uzish", callback_data=f"delacc_{name}")])
        kb.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="cancel_setup")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("delacc_"):
        acc_name = data.replace("delacc_", "")
        if acc_name in u_data.get("accounts", []):
            u_data["accounts"].remove(acc_name)
            save_db(db)
        if acc_name in active_userbots:
            try:
                await active_userbots[acc_name]["client"].stop()
            except Exception:
                pass
            del active_userbots[acc_name]
        s_file = os.path.join(SESSIONS_DIR, f"{acc_name}.session")
        if os.path.exists(s_file):
            try:
                os.remove(s_file)
            except Exception:
                pass
        await query.answer("Akkaunt uzildi!", show_alert=True)
        await query.message.edit_text("Bosh menyu:", reply_markup=get_main_menu(uid))

    elif data == "add_channel":
        if not u_data.get("accounts"):
            await query.answer("Avval akkauntingizni ulang!", show_alert=True)
            return
        user_states[uid] = {"state": "waiting_channel"}
        await query.answer()
        await query.message.edit_text("✍️ Kanal havolasini yuboring (@kanal yoki post linki):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="cancel_setup")]]))

    elif data == "list_channels":
        await query.answer()
        channels = u_data.get("channels", {})
        if not channels:
            await query.message.edit_text("📋 Sizda biriktirilgan kanallar yo'q.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="cancel_setup")]]))
            return
        text = "📋 <b>Sizning kanallaringiz:</b>\n\n"
        kb = [[InlineKeyboardButton(f"⚙️ {info.get('title')[:20]}", callback_data=f"manage_{cid}")] for cid, info in channels.items()]
        kb.append([InlineKeyboardButton("⬅️ Asosiy menyu", callback_data="cancel_setup")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("manage_"):
        cid = data.split("_")[1]
        info = u_data.get("channels", {}).get(cid, {})
        await query.answer()
        p_cnt = len(info.get("premium_emojis", []))
        n_cnt = len(info.get("normal_emojis", []))
        desc = f"👑 Premium: {p_cnt} ta | 👤 Oddiy: {n_cnt} ta"

        await query.message.edit_text(
            f"📢 Kanal: <b>{info.get('title')}</b>\n"
            f"🆔 ID: <code>{cid}</code>\n"
            f"📊 Holat: <b>{desc}</b>\n\n"
            "Reaksiyalarni qaysi akkauntlar uchun sozlamoqchisiz?",
            reply_markup=get_channel_action_markup(cid),
            parse_mode=ParseMode.HTML
        )

    # 1. Premium akkauntlar uchun reaksiya kiritish (1-3 ta Custom/oddiy)
    elif data.startswith("set_prem_"):
        cid = data.split("_")[2]
        user_states[uid] = {"state": "waiting_prem_emojis", "cid": cid, "emojis": []}
        await query.answer()
        await query.message.edit_text(
            "👑 <b>Premium akkauntlar uchun:</b>\n\n"
            "Klaviaturangizdan <b>1 tadan 3 tagacha</b> bo'lgan istalgan Custom emoji yoki stikerni yuboring:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💾 Saqlash", callback_data="save_prem_emojis")]])
        )

    elif data == "save_prem_emojis":
        cid = user_states[uid].get("cid")
        emojis = user_states[uid].get("emojis", [])
        if not emojis:
            await query.answer("Reaksiya yuborilmadi!", show_alert=True)
            return
        u_data["channels"][cid]["premium_emojis"] = emojis
        u_data["channels"][cid]["mode"] = "fixed"
        save_db(db)
        user_states.pop(uid, None)
        await query.answer("Saqlandi!")
        await query.message.edit_text("✅ <b>Premium akkauntlar uchun reaksiyalar saqlandi!</b>", reply_markup=get_main_menu(uid))

    # 2. Oddiy akkauntlar uchun reaksiya kiritish (faqat 1 ta standart)
    elif data.startswith("set_norm_"):
        cid = data.split("_")[2]
        user_states[uid] = {"state": "waiting_norm_emoji", "cid": cid}
        await query.answer()
        await query.message.edit_text(
            "👤 <b>Oddiy akkauntlar uchun:</b>\n\n"
            "Klaviaturangizdan faqat <b>1 ta standart emoji</b> yuboring (Masalan: 🔥 yoki ❤️ yoki 👍):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="cancel_setup")]])
        )

    elif data.startswith("edit_first3_"):
        cid = data.split("_")[2]
        first_acc = u_data["accounts"][0]
        options = await fetch_channel_reactions(active_userbots[first_acc]["client"], int(cid))
        u_data["channels"][cid]["premium_emojis"] = options[:3]
        std_opts = [x for x in options if x.get("type") == "standard"]
        u_data["channels"][cid]["normal_emojis"] = std_opts[:1] if std_opts else DEFAULT_STANDARD
        u_data["channels"][cid]["mode"] = "fixed"
        save_db(db)
        await query.answer("Kanal reaksiyalari biriktirildi!")
        await query.message.edit_text("✅ Kanalning dastlabki reaksiyalari saqlandi!", reply_markup=get_main_menu(uid))

    elif data.startswith("edit_dyn_"):
        cid = data.split("_")[2]
        u_data["channels"][cid]["mode"] = "dynamic"
        save_db(db)
        await query.answer("Dinamik rejim yoqildi!")
        await query.message.edit_text("✅ Dinamik rejim faollashtirildi!", reply_markup=get_main_menu(uid))

    elif data.startswith("del_"):
        cid = data.split("_")[1]
        u_data.get("channels", {}).pop(cid, None)
        save_db(db)
        await query.answer("Kanal o'chirildi!")
        await query.message.edit_text("Bosh menyu:", reply_markup=get_main_menu(uid))

@bot.on_message(filters.private & ~filters.command(["start", "admin"]))
async def message_dispatcher(client, message):
    uid = message.from_user.id
    state_data = user_states.get(uid, {})
    state = state_data.get("state")

    if uid not in db["allowed_users"]:
        return

    u_data = db["users"].get(str(uid), {})

    if state == "waiting_phone":
        phone = (message.contact.phone_number if message.contact else message.text).strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = f"+{phone}"

        acc_name = get_next_acc_name()
        s_base = os.path.join(SESSIONS_DIR, acc_name)
        temp_c = Client(s_base, api_id=API_ID, api_hash=API_HASH)
        await temp_c.connect()

        try:
            code_res = await temp_c.send_code(phone)
            user_states[uid] = {
                "state": "waiting_code",
                "client": temp_c,
                "phone": phone,
                "acc": acc_name,
                "hash": code_res.phone_code_hash
            }
            await message.reply_text(f"📩 <b>{phone}</b> ga kelgan kodni yozing:", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        except Exception as e:
            await temp_c.disconnect()
            await message.reply_text(f"❌ Xato: {e}")

    elif state == "waiting_code":
        code = message.text.strip().replace(" ", "")
        temp_c = state_data["client"]
        try:
            await temp_c.sign_in(state_data["phone"], state_data["hash"], code)
            await temp_c.disconnect()
            await launch_account(state_data["acc"], uid)
            user_states.pop(uid, None)
            await message.reply_text("🎉 Akkauntingiz muvaffaqiyatli saqlandi!", reply_markup=get_main_menu(uid))
        except SessionPasswordNeeded:
            user_states[uid]["state"] = "waiting_2fa"
            await message.reply_text("🔐 2FA parolingizni kiriting:")
        except Exception as e:
            await message.reply_text(f"❌ Kod xato: {e}")

    elif state == "waiting_2fa":
        temp_c = state_data["client"]
        try:
            await temp_c.check_password(message.text.strip())
            await temp_c.disconnect()
            await launch_account(state_data["acc"], uid)
            user_states.pop(uid, None)
            await message.reply_text("🎉 Akkaunt saqlandi!", reply_markup=get_main_menu(uid))
        except Exception as e:
            await message.reply_text(f"❌ Parol xato: {e}")

    # Premium emoji qabul qilish (1-3 ta)
    elif state == "waiting_prem_emojis":
        emojis = state_data.get("emojis", [])
        if message.entities:
            for ent in message.entities:
                if ent.custom_emoji_id:
                    emojis.append({"type": "custom", "id": int(ent.custom_emoji_id)})
        elif message.text:
            for ch in list(message.text.strip()):
                if ch.strip():
                    emojis.append({"type": "standard", "val": ch})
        user_states[uid]["emojis"] = emojis[:3]
        await message.reply_text(f"👑 Premium reaksiya qabul qilindi ({len(user_states[uid]['emojis'])}/3). Saqlash tugmasini bosing.")

    # Oddiy emoji qabul qilish (faqat 1 ta standart)
    elif state == "waiting_norm_emoji":
        ch = message.text.strip() if message.text else ""
        if ch:
            cid = state_data.get("cid")
            u_data["channels"][cid]["normal_emojis"] = [{"type": "standard", "val": ch[:1]}]
            u_data["channels"][cid]["mode"] = "fixed"
            save_db(db)
            user_states.pop(uid, None)
            await message.reply_text(f"✅ <b>Oddiy akkauntlar uchun ({ch[:1]}) reaksiyasi saqlandi!</b>", reply_markup=get_main_menu(uid))
        else:
            await message.reply_text("Iltimos, faqat bitta standart emoji yuboring.")

    elif state == "waiting_channel":
        accs = u_data.get("accounts", [])
        client_instance = active_userbots[accs[0]]["client"]
        text = message.text.strip()
        c_match = re.search(r"t\.me/c/(\d+)/(\d+)", text)
        try:
            if c_match:
                chat = await client_instance.get_chat(int(f"-100{c_match.group(1)}"))
            else:
                uname = text.replace("https://t.me/", "").replace("http://t.me/", "").split("/")[0]
                if not uname.startswith("@") and not uname.startswith("-100"):
                    uname = f"@{uname}"
                chat = await client_instance.get_chat(uname)

            cid = str(chat.id)
            if cid not in u_data["channels"]:
                u_data["channels"][cid] = {
                    "title": chat.title,
                    "premium_emojis": DEFAULT_PREMIUM,
                    "normal_emojis": DEFAULT_STANDARD,
                    "mode": "fixed"
                }
                save_db(db)
            user_states.pop(uid, None)
            await message.reply_text(f"📢 Kanal: <b>{chat.title}</b> ulandi!", reply_markup=get_channel_action_markup(chat.id), parse_mode=ParseMode.HTML)
            await send_log(f"📢 Foydalanuvchi [{uid}] kanal uladi: <b>{chat.title}</b> (<code>{cid}</code>)")
        except Exception as e:
            await message.reply_text(f"❌ Kanal topilmadi: {e}")

async def main():
    await bot.start()
    print("🤖 Bot ishga tushdi.")
    for uid_str, u_info in db.get("users", {}).items():
        owner_id = int(uid_str)
        for acc in list(u_info.get("accounts", [])):
            s_file = os.path.join(SESSIONS_DIR, f"{acc}.session")
            if os.path.exists(s_file):
                try:
                    await launch_account(acc, owner_id)
                except Exception:
                    pass
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop.run_until_complete(main())
