import os
import asyncio
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ==================== Config from ENV ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # BotFather token
BOT_USERNAME = os.getenv("BOT_USERNAME")  # without @
ADMINS = list(map(int, os.getenv("ADMINS", "").split(","))) if os.getenv("ADMINS") else []
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("PG_URL") or os.getenv("POSTGRES_URL")

# ==================== Texts ====================
WELCOME_TEXT = "سلام! من «منشی نارین» هستم. برای ثبت سفارش یا پرسیدن سوال درباره‌ی خدمات مجازی، روی گزینه‌ی زیر بزن:"

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

DEFAULT_VSERVICES = (
    "🔹 فروش سرویس‌های مجازی (تلگرام/سوشال، بدون ورود به اکانت)\n"
    "🔹 ممبر و ویو و ری‌اکشن\n"
    "🔹 ربات‌های امنیتی و موزیک\n"
    "🔹 ساخت و استارت انواع ربات‌ها\n"
    "🔹 سایر خدمات اپلیکیشن‌ها — اگر خدمتی مدنظرت هست همین‌جا بپرس 🌸"
)

# ==================== Globals ====================
POOL: asyncpg.Pool | None = None

# ==================== DB Helpers ====================
async def init_db():
    global POOL
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL تنظیم نشده است.")
    POOL = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with POOL.acquire() as con:
        # users
        await con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """
        )
        # rules
        await con.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_rules (
                section TEXT NOT NULL,
                sub TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (section, sub)
            );
            """
        )
        # state
        await con.execute(
            """
            CREATE TABLE IF NOT EXISTS user_state (
                user_id BIGINT PRIMARY KEY,
                state TEXT NOT NULL
            );
            """
        )
        # seed default vserv text if empty
        exists = await con.fetchval("SELECT 1 FROM kv_rules WHERE section=$1 AND sub=$2 LIMIT 1;", "vserv", "general")
        if not exists:
            await con.execute(
                "INSERT INTO kv_rules(section, sub, text) VALUES($1,$2,$3);",
                "vserv", "general", DEFAULT_VSERVICES
            )

async def ensure_user(m: Message):
    async with POOL.acquire() as con:
        await con.execute(
            """
            INSERT INTO users(user_id, first_name, last_name, username)
            VALUES($1,$2,$3,$4)
            ON CONFLICT (user_id) DO UPDATE SET
                first_name=EXCLUDED.first_name,
                last_name=EXCLUDED.last_name,
                username=EXCLUDED.username;
            """,
            m.from_user.id,
            getattr(m.from_user, "first_name", None),
            getattr(m.from_user, "last_name", None),
            getattr(m.from_user, "username", None),
        )

async def set_rules(section: str, sub: str, text: str):
    async with POOL.acquire() as con:
        await con.execute(
            """
            INSERT INTO kv_rules(section, sub, text)
            VALUES($1,$2,$3)
            ON CONFLICT (section, sub) DO UPDATE SET text=EXCLUDED.text;
            """,
            section, sub, text
        )

async def get_rules(section: str, sub: str) -> str:
    async with POOL.acquire() as con:
        val = await con.fetchval("SELECT text FROM kv_rules WHERE section=$1 AND sub=$2;", section, sub)
        return val or ""

async def set_state(user_id: int, state: str):
    async with POOL.acquire() as con:
        await con.execute(
            """
            INSERT INTO user_state(user_id, state)
            VALUES($1,$2)
            ON CONFLICT (user_id) DO UPDATE SET state=EXCLUDED.state;
            """,
            user_id, state
        )

async def clear_state(user_id: int):
    async with POOL.acquire() as con:
        await con.execute("DELETE FROM user_state WHERE user_id=$1;", user_id)

async def get_state(user_id: int) -> str | None:
    async with POOL.acquire() as con:
        return await con.fetchval("SELECT state FROM user_state WHERE user_id=$1;", user_id)

async def get_all_user_ids() -> list[int]:
    async with POOL.acquire() as con:
        rows = await con.fetch("SELECT user_id FROM users;")
    return [r["user_id"] for r in rows]

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# ==================== Bot init ====================
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده است.")
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== Keyboards ====================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_SECTION_VSERV, callback_data="sec|vserv")],
    ])

def quick_send_kb(section: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ارسال پیام", callback_data=f"send|{section}")]
    ])

# ==================== Handlers ====================
@dp.message(Command("start"))
async def start_cmd(m: Message):
    await ensure_user(m)
    await m.answer(WELCOME_TEXT, reply_markup=main_menu_kb())

@dp.message(Command("help"))
async def help_cmd(m: Message):
    text = HELP_USER_TEXT + (HELP_ADMIN_EXTRA if is_admin(m.from_user.id) else "")
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
        await call.answer()

# ----- setvserv (Admin only)
@dp.message(Command("setvserv"))
async def set_vserv_cmd(m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply("این دستور فقط برای ادمین‌هاست.")
    await m.reply("متن جدید خدمات مجازی را ارسال کن:")
    await set_state(m.from_user.id, "await_vserv_text")

@dp.message(F.text)
async def text_router(m: Message):
    state = await get_state(m.from_user.id)
    if state == "await_vserv_text":
        if not is_admin(m.from_user.id):
            return
        await set_rules("vserv", "general", m.html_text)
        await clear_state(m.from_user.id)
        return await m.reply("✅ متن خدمات مجازی ذخیره شد.")

# ----- broadcast (Admin only)
@dp.message(Command("broadcast"))
async def broadcast_cmd(m: Message):
    if not is_admin(m.from_user.id):
        return
    await m.reply("پیام همگانی را ارسال کن (متن/عکس/ویدیو/آلبوم...)")
    await set_state(m.from_user.id, "await_broadcast")

@dp.message(F.media_group_id | F.photo | F.video | F.animation | F.document | F.audio | F.voice | F.sticker | F.text)
async def broadcast_or_passthrough(m: Message):
    state = await get_state(m.from_user.id)
    if state != "await_broadcast":
        return  # not in broadcast mode
    if not is_admin(m.from_user.id):
        return
    await clear_state(m.from_user.id)

    user_ids = await get_all_user_ids()
    sent = 0
    for uid in user_ids:
        try:
            await bot.copy_message(uid, m.chat.id, m.message_id)
            sent += 1
        except Exception:
            pass
    await m.reply(f"✅ پیام همگانی برای {sent} کاربر ارسال شد.")

# ----- Group listener
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

# ==================== Main ====================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
