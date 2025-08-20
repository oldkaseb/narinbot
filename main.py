# -*- coding: utf-8 -*-
"""
Telegram Bot – aiogram v3.7 + asyncpg (single file)

ENV (Railway):
  BOT_TOKEN="..."
  DATABASE_URL="postgresql://user:pass@host:port/dbname"
  ADMIN_ID="123456, 987654"  # یک یا چند آیدی با کاما/فاصله
"""

import asyncio
import logging
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
    InputMediaPhoto,
    InputMediaVideo,
)
from aiogram.client.default import DefaultBotProperties

# -------------------- Config & Logging --------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID_RAW = os.getenv("ADMIN_ID", os.getenv("ADMIN_SEED_IDS", "")).strip()
ADMIN_IDS_SEED = {int(n) for n in ADMIN_ID_RAW.replace(",", " ").split() if n.strip().isdigit()}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is required")

DB_POOL: Optional[asyncpg.Pool] = None
BOT_USERNAME: str = ""

# -------------------- Texts --------------------
WELCOME_TEXT = """سلام.
من «منشی نارین» هستم. برای دریافت خدمات مجازی از منوی زیر استفاده کنید."""
MAIN_MENU_TEXT = "یکی از گزینه‌ها را انتخاب کنید:"

# Buttons
BTN_SECTION_BOTS   = "🤖 گفت‌وگو درباره ربات‌ها"
BTN_SECTION_SOULS  = "💬 گروه Souls"
BTN_SECTION_VSERV  = "🛍️ خدمات مجازی"
BTN_SECTION_FREE   = "🗣️ گفت‌وگوی آزاد"

BTN_GROUP_ADMIN_CHAT = "درخواست ادمین چت"
BTN_GROUP_ADMIN_CALL = "درخواست ادمین کال"

BTN_SEND_REQUEST = "✅ می‌پذیرم و ارسال درخواست"   # فقط برای Souls
BTN_CANCEL       = "❌ انصراف"
BTN_SEND_AGAIN   = "✉️ ارسال پیام مجدد"          # بعد از ارسال موفق کاربر
BTN_QUICK_SEND   = "✉️ ارسال پیام"               # برای bots/vserv/free

BTN_REPLY        = "✉️ پاسخ"
BTN_REPLY_AGAIN  = "✉️ پاسخِ مجدد"                # بعد از ارسال موفق ادمین

# Callback data prefixes
CB_MAIN    = "main"
CB_SEC     = "sec"      # sec|bots / sec|souls / sec|vserv / sec|free
CB_SOULS   = "souls"    # souls|chat / souls|call
CB_ACTION  = "act"      # act|send|<kind> or act|cancel|<kind>
CB_AGAIN   = "again"    # again|start
CB_REPLY   = "reply"    # reply|<user_id>

# -------------------- FSM --------------------
class SendToAdmin(StatesGroup):
    waiting_for_text = State()

class Broadcast(StatesGroup):       # به کاربران
    waiting_for_message = State()

class GroupBroadcast(StatesGroup):  # به گروه‌ها
    waiting_for_message = State()

class AdminReply(StatesGroup):
    waiting_for_any = State()

class SetRules(StatesGroup):
    waiting_for_text = State()

# -------------------- DB --------------------
@dp.message(Command("setvserv"))
async def cmd_setvserv(m: Message, state: FSMContext):
    if m.chat.type != "private" or not await require_admin_msg(m):
        return
    await state.set_state(SetRules.waiting_for_text)
    await state.update_data(section="vserv", kind="general")
    await m.answer("متن قوانین/شرایط «خدمات مجازی» را بفرستید. لغو: /cancel")

@dp.message(SetRules.waiting_for_text)
async def on_set_rules_text(m: Message, state: FSMContext):
    if m.text and m.text.startswith("/") and m.text != "/cancel":
        return
    if m.chat.type != "private" or not await require_admin_msg(m):
        return
    data = await state.get_data()
    await set_rules(data["section"], data["kind"], m.html_text)
    await state.clear()
    await m.answer("✅ قوانین ذخیره شد.")

@dp.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    if m.chat.type != "private":
        return
    await state.clear()
    await m.answer("لغو شد.")

# -------------------- User flows (callbacks) --------------------
@dp.callback_query(F.data.startswith(f"{CB_MAIN}|"))
async def on_back_to_menu(call: CallbackQuery, state: FSMContext):
    if call.message.chat.type != "private":
        return
    await disable_markup(call)
    await state.clear()
    await call.message.answer(MAIN_MENU_TEXT, reply_markup=main_menu_kb())
    await call.answer()

@dp.callback_query(F.data.startswith(f"{CB_SEC}|"))
async def on_section(call: CallbackQuery):
    if call.message.chat.type != "private":
        return
    await disable_markup(call)
    _, section = call.data.split("|", 1)

    if section == "souls":
        await call.message.answer("بخش گروه Souls – نوع درخواست را انتخاب کنید:", reply_markup=souls_submenu_kb())

    elif section == "bots":
        rules = await get_rules("bots", "general")
        text = f"{rules}\n\nبرای ارسال پیام درباره ربات‌ها، روی دکمه‌ی زیر بزنید و توضیحات خود را بفرستید."
        await call.message.answer(text, reply_markup=quick_send_kb("bots"))

    elif section == "vserv":
        rules = await get_rules("vserv", "general")
        text = (
            "🛍️ لیست خدمات مجازی نارین:\n"
            f"{VIRTUAL_SERVICES_LIST}\n\n"
            f"{rules}\n\n"
            "برای ثبت درخواست، روی «ارسال پیام» بزنید و سرویس/تعداد/لینک‌ها/زمان‌بندی را بنویسید."
        )
        await call.message.answer(text, reply_markup=quick_send_kb("vserv"))

    elif section == "free":
        text = (
            "🗣️ گفت‌وگوی آزاد\n"
            "سؤال یا موضوع آزادت رو بنویس؛ من به ادمین می‌رسونم و از همین‌جا جواب می‌گیری."
        )
        await call.message.answer(text, reply_markup=quick_send_kb("free"))

    await call.answer()

@dp.callback_query(F.data.startswith(f"{CB_SOULS}|"))
async def on_souls_kind(call: CallbackQuery):
    if call.message.chat.type != "private":
        return
    await disable_markup(call)
    _, kind = call.data.split("|", 1)  # chat or call
    rules = await get_rules("souls", kind)
    await call.message.answer(rules, reply_markup=after_rules_kb(kind))
    await call.answer()

@dp.callback_query(F.data.startswith(f"{CB_ACTION}|"))
async def on_action(call: CallbackQuery, state: FSMContext):
    if call.message.chat.type != "private":
        return
    await disable_markup(call)
    _, action, kind = call.data.split("|", 2)
    if action == "send":
        await state.set_state(SendToAdmin.waiting_for_text)
        await state.update_data(kind=kind)  # bots/vserv/free/chat/call
        await call.message.answer("لطفاً پیام/فایل/آلبوم خود را ارسال کنید. لغو: /cancel")
    else:
        await state.clear()
        await call.message.answer("لغو شد.")
    await call.answer()

@dp.callback_query(F.data.startswith(f"{CB_AGAIN}|"))
async def on_send_again(call: CallbackQuery, state: FSMContext):
    if call.message.chat.type != "private":
        return
    await disable_markup(call)
    await state.set_state(SendToAdmin.waiting_for_text)
    await call.message.answer("متن یا فایل جدید را بفرستید. لغو: /cancel")
    await call.answer()

# -------------------- User -> Admin message (only in state) --------------------
@dp.message(SendToAdmin.waiting_for_text)
async def on_user_message_to_admin(m: Message, state: FSMContext):
    if m.text and m.text.startswith("/") and m.text != "/cancel":
        return
    if m.chat.type != "private":
        return

    u = await get_user(m.from_user.id)
    if u and u.blocked:
        return await m.answer("شما مسدود شده‌اید.")

    data = await state.get_data()
    kind = data.get("kind", "general")  # bots / vserv / free / chat / call
    admin_ids = await get_admin_ids()
    if not admin_ids:
        return await m.answer("فعلاً ادمینی ثبت نشده.")

    full_name = " ".join(filter(None, [m.from_user.first_name, m.from_user.last_name])) or "-"
    uname = ("@" + m.from_user.username) if m.from_user.username else "-"
    info_text = (
        f"📬 پیام جدید از <a href=\"tg://user?id={m.from_user.id}\">{full_name}</a>\n"
        f"🆔 ID: <code>{m.from_user.id}</code>\n"
        f"👤 Username: {uname}\n"
        f"بخش: {kind}\n\n— برای پاسخ از دکمهٔ زیر استفاده کنید —"
    )

    # آلبوم عکس/ویدیو
    if m.media_group_id:
        key = (m.from_user.id, m.media_group_id)
        buf = _album_buffer_u2a.get(key, [])
        item = _collect_item_from_message(m)
        if item:
            buf.append(item); _album_buffer_u2a[key] = buf

        async def _flush():
            await asyncio.sleep(2)
            items = _album_buffer_u2a.pop(key, [])
            caption, ents = m.caption or '', m.caption_entities
            for aid in admin_ids:
                try:
                    kb = admin_reply_kb(m.from_user.id)
                    await bot.send_message(aid, info_text, reply_markup=kb)
                    await _send_media_group(bot, aid, items, caption, ents)
                except Exception:
                    pass
            await log_message(m.from_user.id, None, "user_to_admin", f"album({len(items)})")
            await state.clear()
            await m.answer("✅ درخواست شما برای ادمین‌ها ارسال شد.", reply_markup=send_again_kb())
        t = _album_tasks_u2a.get(key)
        if t and not t.done():
            t.cancel()
        _album_tasks_u2a[key] = asyncio.create_task(_flush())
        return

    # تک‌پیام (همه انواع)
    for aid in admin_ids:
        try:
            kb = admin_reply_kb(m.from_user.id)
            await bot.send_message(aid, info_text, reply_markup=kb)
            await bot.copy_message(chat_id=aid, from_chat_id=m.chat.id, message_id=m.message_id, reply_markup=kb)
        except Exception:
            pass

    await log_message(m.from_user.id, None, "user_to_admin", m.caption or m.text or m.content_type)
    await state.clear()
    await m.answer("✅ درخواست شما برای ادمین‌ها ارسال شد.", reply_markup=send_again_kb())

# -------------------- Group behavior & registration --------------------
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def group_gate(m: Message):
    await upsert_group(
        chat_id=m.chat.id,
        title=getattr(m.chat, "title", None),
        username=getattr(m.chat, "username", None),
        active=True
    )

    text = (m.text or m.caption or "")
    if contains_malek(text):
        btns = None
        if BOT_USERNAME:
            btns = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="ارسال پیام به منشی نارین",
                    url=f"https://t.me/{BOT_USERNAME}?start=start"
                )]
            ])

        # ⬇️ پیام ربات
        sent = await m.reply(
            "سلام، من منشی نارین هستم. می‌تونی پیوی من پیام بدی و من به مالک برسونمش.",
            reply_markup=btns
        )
        # ⬇️ حذف خودکار همون پیام بعد از ۳۰ ثانیه
        asyncio.create_task(_auto_delete(sent.chat.id, sent.message_id, delay=30))

# فقط پی‌وی: فالبک غیر دستوری (وقتی در حالت خاصی نیستیم)
@dp.message(F.chat.type == "private", F.text, ~F.text.regexp(r"^/"))
async def private_fallback(m: Message, state: FSMContext):
    if await state.get_state():
        return
    await m.answer("برای شروع از /menu استفاده کنید.")

# -------------------- Entrypoint --------------------
async def main():
    global BOT_USERNAME, DB_POOL
    await init_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    logging.info(f"Bot connected as @{BOT_USERNAME}")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        if DB_POOL:
            await DB_POOL.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")




@dp.message(Command("help"))
async def cmd_help(m: Message):
    if m.chat.type != "private":
        return
    await upsert_user(m)
    u = await get_user(m.from_user.id)
    is_admin = bool(u and u.is_admin)
    user_help = (
        "راهنما:\n"
        "— /start یا /menu : شروع و نمایش منو.\n"
        "— منو: فقط «🛍️ خدمات مجازی» فعال است.\n"
        "— در گروه‌ها با نوشتن «نارین»، لینک پیام‌دادن به منشی ارسال می‌شود.\n"
    )
    admin_help = (
        "\nدستورات ادمین:\n"
        "— /setvserv : تنظیم متن خدمات مجازی.\n"
        "— /broadcast : پیام همگانی به کاربران.\n"
        "— /groupsend : پیام همگانی به گروه‌های ثبت‌شده.\n"
        "— /listgroups : لیست گروه‌های ثبت‌شده.\n"
        "— /stats : آمار کاربران/گروه‌ها.\n"
        "— /addadmin <id> ، /deladmin <id> ، /block <id> ، /unblock <id>\n"
        "— /reply <id> : پاسخ مستقیم به کاربر.\n"
        "— /cancel : لغو حالت جاری.\n"
    )
    await m.answer(user_help + (admin_help if is_admin else ""))
