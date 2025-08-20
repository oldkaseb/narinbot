import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

# -------------------- Config --------------------
BOT_TOKEN = "PUT-YOUR-BOT-TOKEN-HERE"  # توکن ربات
BOT_USERNAME = "YourBotUsername"        # نام کاربری ربات بدون @
ADMINS = [123456789]                   # لیست آی‌دی عددی ادمین‌ها

# -------------------- Texts --------------------
WELCOME_TEXT = "سلام! 👋\nمن «منشی نارین» هستم. برای ثبت سفارش یا پرسیدن سوال درباره‌ی خدمات مجازی، روی گزینه‌ی زیر بزن:"

HELP_USER_TEXT = (
    "📖 راهنمای دستورات:\n\n"
    "— /start : شروع گفتگو با منشی نارین.\n"
    "— /help : نمایش همین راهنما.\n"
    "— منو: «🛍️ خدمات مجازی» را انتخاب کن تا لیست و راهنمای سفارش را ببینی.\n"
    "— در گروه اگر اسم «نارین» گفته شود، منشی لینک پیام خصوصی را می‌فرستد.\n"
)

HELP_ADMIN_EXTRA = (
    "\n👮‍♀️ دستورات ویژه ادمین‌ها:\n"
    "— /setvserv : تغییر متن «خدمات مجازی» (بعد از این دستور متن جدید را بفرست).\n"
    "— /broadcast : ارسال پیام همگانی به همه کاربران ثبت‌شده.\n"
)

BTN_SECTION_VSERV = "🛍️ خدمات مجازی"

VIRTUAL_SERVICES_LIST = (
    "🔹 فروش سرویس‌های مجازی (تلگرام/سوشال، بدون ورود به اکانت)\n"
    "🔹 ممبر و ویو و ری‌اکشن\n"
    "🔹 ربات‌های امنیتی و موزیک\n"
    "🔹 ساخت و استارت انواع ربات‌ها\n"
    "🔹 سایر خدمات اپلیکیشن‌ها — اگر خدمتی مدنظرت هست همین‌جا بپرس 🌸"
)

# -------------------- State store (in-memory) --------------------
STATE = {}
RULES = {"vserv": VIRTUAL_SERVICES_LIST}
USERS = set()

# -------------------- Utils --------------------
async def is_user_admin(user_id: int) -> bool:
    return user_id in ADMINS

async def set_state(user_id: int, state: str):
    STATE[user_id] = state

async def clear_state(user_id: int):
    STATE.pop(user_id, None)

async def get_state(user_id: int):
    return STATE.get(user_id)

async def set_rules(section: str, sub: str, text: str):
    RULES[section] = text

async def get_rules(section: str, sub: str):
    return RULES.get(section, "")

# -------------------- Bot init --------------------
bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# -------------------- Keyboards --------------------
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SECTION_VSERV, callback_data="sec|vserv")],
    ])

def quick_send_kb(section: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ارسال پیام", callback_data=f"send|{section}")]
    ])

# -------------------- Handlers --------------------
@dp.message(Command("start"))
async def start_cmd(m: Message):
    USERS.add(m.from_user.id)
    await m.answer(WELCOME_TEXT, reply_markup=main_menu_kb())

@dp.message(Command("help"))
async def help_cmd(m: Message):
    text = HELP_USER_TEXT
    if await is_user_admin(m.from_user.id):
        text += HELP_ADMIN_EXTRA
    await m.reply(text)

@dp.callback_query(F.data.startswith("sec|"))
async def section_cb(call: CallbackQuery):
    section = call.data.split("|")[1]
    if section == "vserv":
        rules = await get_rules("vserv", "general")
        text = (
            "🛍️ لیست خدمات مجازی نارین:\n"
            f"{rules}\n\n"
            "برای ثبت سفارش، روی «ارسال پیام» بزن و توضیحات را ارسال کن 🌸"
        )
        await call.message.answer(text, reply_markup=quick_send_kb("vserv"))

# -------------------- Set vserv (Admin only) --------------------
@dp.message(Command("setvserv"))
async def set_vserv_cmd(m: Message):
    if not await is_user_admin(m.from_user.id):
        return await m.reply("این دستور فقط برای ادمین‌هاست.")
    await m.reply("متن جدید خدمات مجازی را ارسال کن:")
    await set_state(m.from_user.id, "await_vserv_text")

@dp.message(F.text, lambda m: get_state(m.from_user.id) == "await_vserv_text")
async def save_vserv_text(m: Message):
    if not await is_user_admin(m.from_user.id):
        return
    await set_rules("vserv", "general", m.html_text)
    await clear_state(m.from_user.id)
    await m.reply("✅ متن خدمات مجازی ذخیره شد.")

# -------------------- Broadcast (Admin only) --------------------
@dp.message(Command("broadcast"))
async def broadcast_cmd(m: Message):
    if not await is_user_admin(m.from_user.id):
        return
    await m.reply("پیام همگانی را ارسال کن (متن/عکس/ویدیو/آلبوم...)")
    await set_state(m.from_user.id, "await_broadcast")

@dp.message(lambda m: get_state(m.from_user.id) == "await_broadcast")
async def do_broadcast(m: Message):
    if not await is_user_admin(m.from_user.id):
        return
    await clear_state(m.from_user.id)
    for uid in USERS:
        try:
            await bot.copy_message(uid, m.chat.id, m.message_id)
        except Exception:
            pass
    await m.reply("✅ پیام همگانی ارسال شد.")

# -------------------- Group listener --------------------
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def group_listener(m: Message):
    text = m.text or m.caption or ""
    if "نارین" in text:
        btns = None
        if BOT_USERNAME:
            btns = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="ارسال پیام به منشی نارین",
                    url=f"https://t.me/{BOT_USERNAME}?start=start"
                )]
            ])
        sent = await m.reply(
            "سلام، من منشی نارین هستم. برای هماهنگی خدمات، در پی‌وی پیام بده 🌸",
            reply_markup=btns
        )
        asyncio.create_task(_auto_delete(sent.chat.id, sent.message_id, 30))

async def _auto_delete(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

# -------------------- Main --------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
