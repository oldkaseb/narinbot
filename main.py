import os, asyncio, asyncpg, logging, traceback
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("narinbot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
ADMINS = list(map(int, os.getenv("ADMINS", "").split(","))) if os.getenv("ADMINS") else []
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("PG_URL") or os.getenv("POSTGRES_URL")

BTN_SECTION_VSERV = "🛍️ خدمات مجازی"
DEFAULT_VSERVICES = (
    "🔹 فروش سرویس‌های مجازی (تلگرام/سوشال، بدون ورود به اکانت)\n"
    "🔹 ممبر و ویو و ری‌اکشن\n"
    "🔹 ربات‌های امنیتی و موزیک\n"
    "🔹 ساخت و استارت انواع ربات‌ها\n"
    "🔹 سایر خدمات اپلیکیشن‌ها — اگر خدمتی مدنظرت هست همین‌جا بپرس 🌸"
)

async def init_db():
    log.info("init_db: DATABASE_URL present=%s", bool(DATABASE_URL))
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with pool.acquire() as con:
        await con.execute("""CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, first_name TEXT, last_name TEXT, username TEXT, created_at TIMESTAMP DEFAULT NOW());""")
        await con.execute("""CREATE TABLE IF NOT EXISTS kv_rules (section TEXT NOT NULL, sub TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (section, sub));""")
        await con.execute("""CREATE TABLE IF NOT EXISTS user_state (user_id BIGINT PRIMARY KEY, state TEXT NOT NULL);""")
        exists = await con.fetchval("SELECT 1 FROM kv_rules WHERE section=$1 AND sub=$2 LIMIT 1;", "vserv", "general")
        if not exists:
            await con.execute("INSERT INTO kv_rules(section, sub, text) VALUES($1,$2,$3);", "vserv", "general", DEFAULT_VSERVICES)
    log.info("init_db: done")
    return pool

def is_admin(uid: int) -> bool:
    return uid in ADMINS

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=BTN_SECTION_VSERV, callback_data="sec|vserv")]])

@dp.message(Command("start"))
async def start_cmd(m: Message):
    await m.answer("✅ Bot is up. Use the menu.", reply_markup=main_menu_kb())

@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.reply("help ok")

@dp.callback_query(F.data.startswith("sec|"))
async def sec_cb(c: CallbackQuery):
    await c.message.answer("vserv ok")
    await c.answer()

@dp.message(F.chat.type.in_({"group","supergroup"}))
async def grp(m: Message):
    if "نارین" in (m.text or m.caption or ""):
        await m.reply("سلام، من منشی نارین هستم.")

async def main():
    try:
        log.info("boot: starting. python ok, envs: BOT=%s, USERNAME=%s, ADMINS=%s", bool(BOT_TOKEN), BOT_USERNAME, ADMINS)
        if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN not set")
        pool = await init_db()
        log.info("boot: db pool ready: %s", pool is not None)
        log.info("boot: starting polling...")
        await dp.start_polling(bot)
    except Exception as e:
        log.error("FATAL: %s\n%s", e, traceback.format_exc())
        raise

if __name__ == "__main__":
    asyncio.run(main())
