import asyncio
import os
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CopyTextButton,
)
from dotenv import load_dotenv

# ================= LOAD ENV =================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
VPN_KEY = os.getenv("VPN_KEY")
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "")
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/supp_vpntock1a")
INSTRUCTION_URL = os.getenv("INSTRUCTION_URL", "https://t.me/blackvpn_connect")
KEY_LIFETIME_SECONDS = int(os.getenv("KEY_LIFETIME_SECONDS", "45"))
KEY_COOLDOWN_SECONDS = int(os.getenv("KEY_COOLDOWN_SECONDS", "60"))
BRAND_NAME = os.getenv("BRAND_NAME", "Black VPN")
SUBSCRIPTION_PRICE = os.getenv("SUBSCRIPTION_PRICE", "699")
SUBSCRIPTION_PERIOD = os.getenv("SUBSCRIPTION_PERIOD", "12 месяцев")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID не найден в .env")
if not VPN_KEY:
    raise ValueError("VPN_KEY не найден в .env")
if not PAYMENT_CARD:
    raise ValueError("PAYMENT_CARD не найден в .env")

# ================= INIT =================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ================= TEXTS =================

def start_text(first_name: str | None) -> str:
    return (
        f"⚫️ <b>{BRAND_NAME}</b>\n\n"
        "Добро пожаловать.\n\n"
        "Премиальный VPN-доступ для тех, кто ценит:\n"
        "• стабильное соединение\n"
        "• высокую скорость\n"
        "• приватность без лишнего шума\n\n"
        "Выберите нужный раздел ниже 👇"
    )

BUY_TEXT = (
    "💎 <b>Премиум-доступ</b>\n\n"
    f"Стоимость: <b>{SUBSCRIPTION_PRICE} ₽</b>\n"
    f"Срок доступа: <b>{SUBSCRIPTION_PERIOD}</b>\n\n"
    "Для оплаты переведите по номеру карты:\n"
    "<code>{payment_card}</code>\n\n"
    "Нажмите кнопку ниже, чтобы скопировать номер карты.\n"
    "После перевода нажмите <b>«Я оплатил»</b> и отправьте чек."
)

WAITING_CHECK_TEXT = (
    "📸 <b>Отправьте чек одним сообщением</b>\n"
    "Как только чек поступит, мы передадим его на проверку."
)

CHECK_ACCEPTED_TEXT = (
    "✅ <b>Чек принят</b>\n"
    "Проверка оплаты уже запущена. Ожидайте подтверждения."
)

HOME_TEXT = (
    "🏠 <b>Главное меню</b>\n\n"
    "Управление доступом доступно ниже 👇"
)

NO_SUB_TEXT = (
    "❌ <b>Доступ не активирован</b>\n\n"
    "Чтобы получить VPN-ключ, сначала купите подписку."
)

EXPIRED_SUB_TEXT = (
    "❌ <b>Срок доступа истёк</b>\n\n"
    "Продлите подписку, чтобы снова получить VPN-ключ."
)

# ================= DATABASE =================

async def init_db():
    async with aiosqlite.connect("vpn.db") as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            subscription_until TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS payment_waiting (
            user_id INTEGER PRIMARY KEY,
            created_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS key_access (
            user_id INTEGER PRIMARY KEY,
            last_sent_at TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS temp_messages (
            user_id INTEGER PRIMARY KEY,
            message_id INTEGER
        )
        """)

        await db.commit()


def now() -> datetime:
    return datetime.now(timezone.utc)

# ================= SUBSCRIPTIONS =================

async def set_subscription(user_id: int, days: int = 365):
    async with aiosqlite.connect("vpn.db") as db:
        async with db.execute(
            "SELECT subscription_until FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

        base_date = now()

        if row and row[0]:
            try:
                current_until = datetime.fromisoformat(row[0])
                if current_until > base_date:
                    base_date = current_until
            except ValueError:
                pass

        new_expire = base_date + timedelta(days=days)

        await db.execute("""
        INSERT INTO users (user_id, subscription_until)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET subscription_until = excluded.subscription_until
        """, (user_id, new_expire.isoformat()))
        await db.commit()


async def get_subscription(user_id: int):
    async with aiosqlite.connect("vpn.db") as db:
        async with db.execute(
            "SELECT subscription_until FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

# ================= PAYMENT WAITING =================

async def set_waiting(user_id: int):
    async with aiosqlite.connect("vpn.db") as db:
        await db.execute("""
        INSERT INTO payment_waiting (user_id, created_at)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET created_at = excluded.created_at
        """, (user_id, now().isoformat()))
        await db.commit()


async def is_waiting(user_id: int) -> bool:
    async with aiosqlite.connect("vpn.db") as db:
        async with db.execute(
            "SELECT 1 FROM payment_waiting WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def clear_waiting(user_id: int):
    async with aiosqlite.connect("vpn.db") as db:
        await db.execute(
            "DELETE FROM payment_waiting WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()

# ================= TEMP MESSAGE =================

async def save_temp_message(user_id: int, message_id: int):
    async with aiosqlite.connect("vpn.db") as db:
        await db.execute("""
        INSERT INTO temp_messages (user_id, message_id)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET message_id = excluded.message_id
        """, (user_id, message_id))
        await db.commit()


async def get_temp_message(user_id: int):
    async with aiosqlite.connect("vpn.db") as db:
        async with db.execute(
            "SELECT message_id FROM temp_messages WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def clear_temp_message(user_id: int):
    async with aiosqlite.connect("vpn.db") as db:
        await db.execute(
            "DELETE FROM temp_messages WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()

# ================= KEY COOLDOWN =================

async def get_remaining_cooldown(user_id: int) -> int:
    async with aiosqlite.connect("vpn.db") as db:
        async with db.execute(
            "SELECT last_sent_at FROM key_access WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row or not row[0]:
        return 0

    try:
        last_sent_at = datetime.fromisoformat(row[0])
    except ValueError:
        return 0

    seconds_passed = int((now() - last_sent_at).total_seconds())
    remaining = KEY_COOLDOWN_SECONDS - seconds_passed
    return max(0, remaining)


async def update_key_sent_time(user_id: int):
    async with aiosqlite.connect("vpn.db") as db:
        await db.execute("""
        INSERT INTO key_access (user_id, last_sent_at)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET last_sent_at = excluded.last_sent_at
        """, (user_id, now().isoformat()))
        await db.commit()

# ================= KEYBOARDS =================

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="🔑 Получить ключ", callback_data="key")],
        [InlineKeyboardButton(text="📅 Моя подписка", callback_data="sub")],
        [InlineKeyboardButton(text="📖 Как подключиться", url=INSTRUCTION_URL)],
        [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],
    ])


def pay_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📋 Скопировать номер карты",
                copy_text=CopyTextButton(text=PAYMENT_CARD)
            )
        ],
        [InlineKeyboardButton(text="💸 Я оплатил", callback_data="paid")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
    ])


def confirm_kb(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Подтвердить оплату",
            callback_data=f"confirm_{user_id}"
        )]
    ])

# ================= HELPERS =================

async def send_temporary_key(chat_id: int, user_id: int):
    await update_key_sent_time(user_id)

    msg = await bot.send_message(
        chat_id,
        "✅ <b>Доступ активирован</b>\n\n"
        "🔑 <b>Ваш VPN-ключ:</b>\n"
        f"<code>{VPN_KEY}</code>\n\n"
        f"👤 Доступ выдан для ID: <code>{user_id}</code>\n"
        f"🕒 Сообщение будет удалено через <b>{KEY_LIFETIME_SECONDS}</b> сек.\n\n"
        "⚠️ Не передавайте ключ третьим лицам."
    )

    await asyncio.sleep(KEY_LIFETIME_SECONDS)

    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception:
        pass


async def safe_delete_message(chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def format_subscription_text(expire: datetime) -> str:
    days_left = (expire - now()).days
    if days_left < 0:
        days_left = 0

    return (
        "📅 <b>Моя подписка</b>\n\n"
        f"Статус: <b>активна</b>\n"
        f"Действует до: <b>{expire.strftime('%d.%m.%Y')}</b>\n"
        f"Осталось дней: <b>{days_left}</b>"
    )

# ================= START =================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        start_text(message.from_user.first_name),
        reply_markup=main_menu()
    )

# ================= BUY =================

@dp.callback_query(F.data == "buy")
async def buy(callback: CallbackQuery):
    formatted_card = " ".join([PAYMENT_CARD[i:i + 4] for i in range(0, len(PAYMENT_CARD), 4)])

    await callback.message.edit_text(
        BUY_TEXT.format(payment_card=formatted_card),
        reply_markup=pay_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "paid")
async def paid(callback: CallbackQuery):
    user_id = callback.from_user.id
    await set_waiting(user_id)

    old_temp_msg_id = await get_temp_message(user_id)
    if old_temp_msg_id:
        await safe_delete_message(user_id, old_temp_msg_id)
        await clear_temp_message(user_id)

    msg = await callback.message.answer(WAITING_CHECK_TEXT)
    await save_temp_message(user_id, msg.message_id)

    await callback.answer()

# ================= RECEIPT =================

@dp.message(F.photo)
async def receipt(message: Message):
    user_id = message.from_user.id

    if user_id == ADMIN_ID:
        return

    if not await is_waiting(user_id):
        await message.answer("❌ <b>Сначала нажмите кнопку «Я оплатил»</b>")
        return

    temp_msg_id = await get_temp_message(user_id)
    if temp_msg_id:
        await safe_delete_message(user_id, temp_msg_id)
        await clear_temp_message(user_id)

    try:
        await message.delete()
    except Exception:
        pass

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "без username"
    )

    try:
        await bot.send_photo(
            ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=(
                "💸 <b>Новый чек на подтверждение</b>\n\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"👤 Username: {username}"
            ),
            reply_markup=confirm_kb(user_id)
        )

        await message.answer(CHECK_ACCEPTED_TEXT)

    except TelegramBadRequest:
        await message.answer(
            "❌ <b>Не удалось передать чек администратору</b>\n"
            "Проверьте <code>ADMIN_ID</code> и убедитесь, что администратор написал боту <code>/start</code>."
        )

# ================= CONFIRM =================

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int(callback.data.split("_")[1])

    await set_subscription(user_id, days=365)
    await clear_waiting(user_id)

    asyncio.create_task(send_temporary_key(user_id, user_id))

    try:
        await callback.message.edit_caption("✅ <b>Оплата подтверждена</b>")
    except TelegramBadRequest:
        await callback.message.edit_text("✅ <b>Оплата подтверждена</b>")

    await callback.answer("Готово")

# ================= KEY =================

@dp.callback_query(F.data == "key")
async def key(callback: CallbackQuery):
    user_id = callback.from_user.id

    sub_value = await get_subscription(user_id)
    if not sub_value:
        await callback.answer("Нет подписки", show_alert=True)
        await callback.message.answer(NO_SUB_TEXT, reply_markup=main_menu())
        return

    try:
        expire = datetime.fromisoformat(sub_value)
    except ValueError:
        await callback.answer("Ошибка данных", show_alert=True)
        return

    if expire <= now():
        await callback.answer("Подписка истекла", show_alert=True)
        await callback.message.answer(EXPIRED_SUB_TEXT, reply_markup=main_menu())
        return

    remaining = await get_remaining_cooldown(user_id)
    if remaining > 0:
        await callback.answer(
            f"⏳ Повторная выдача через {remaining} сек.",
            show_alert=True
        )
        return

    await callback.answer("Ключ отправлен")
    asyncio.create_task(send_temporary_key(user_id, user_id))

# ================= SUB =================

@dp.callback_query(F.data == "sub")
async def sub(callback: CallbackQuery):
    sub_value = await get_subscription(callback.from_user.id)

    if not sub_value:
        text = NO_SUB_TEXT
    else:
        try:
            expire = datetime.fromisoformat(sub_value)
            if expire > now():
                text = format_subscription_text(expire)
            else:
                text = EXPIRED_SUB_TEXT
        except ValueError:
            text = "❌ <b>Не удалось прочитать данные подписки</b>"

    await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer()

# ================= HOME =================

@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):
    await callback.message.edit_text(
        HOME_TEXT,
        reply_markup=main_menu()
    )
    await callback.answer()

# ================= RUN =================

async def main():
    await init_db()
    print("✅ Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())