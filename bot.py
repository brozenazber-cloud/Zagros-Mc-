import os
import asyncio
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


# =========================
# SETTINGS
# =========================

MAIN_BOT_TOKEN = os.getenv("MAIN_BOT_TOKEN", "").strip()
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "shop.db")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

DEFAULT_CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
DEFAULT_CARD_NAME = os.getenv("CARD_NAME", "").strip()
DEFAULT_SUPPORT = os.getenv("SUPPORT_USERNAME", "IBrOzen").strip()

if not MAIN_BOT_TOKEN:
    raise RuntimeError("MAIN_BOT_TOKEN is missing")

if not ADMIN_BOT_TOKEN:
    raise RuntimeError("ADMIN_BOT_TOKEN is missing")


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_key TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                price INTEGER NOT NULL,
                description TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                product_key TEXT,
                product_name TEXT,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                code TEXT PRIMARY KEY,
                percent INTEGER NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS user_pending (
                user_id INTEGER PRIMARY KEY,
                product_key TEXT
            )
        """)

        defaults = {
            "card_number": DEFAULT_CARD_NUMBER,
            "card_name": DEFAULT_CARD_NAME,
            "support": DEFAULT_SUPPORT,
        }

        for key, value in defaults.items():
            db.execute(
                """
                INSERT OR IGNORE INTO settings(key, value)
                VALUES (?, ?)
                """,
                (key, value),
            )

        products = [
            (
                "vip",
                "rank",
                "VIP",
                100000,
                "💎 رنک VIP\n• کیت دایم دیاموند\n• تجهیزات دیاموند",
            ),
            (
                "legend",
                "rank",
                "LEGEND",
                150000,
                "👑 رنک LEGEND\n• کیت ندرایت\n• دسترسی به /anvil\n• دسترسی به /craft\n• دسترسی به /enchantingtable",
            ),
            (
                "fly",
                "op",
                "/fly",
                50000,
                "⚡ قابلیت پرواز /fly",
            ),
            (
                "nick",
                "op",
                "/nick",
                30000,
                "✨ قابلیت تغییر نیک /nick",
            ),
            (
                "enderchest",
                "op",
                "/enderchest",
                20000,
                "📦 دسترسی به /enderchest",
            ),
        ]

        for product in products:
            db.execute(
                """
                INSERT OR IGNORE INTO products
                (product_key, category, title, price, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                product,
            )

        db.commit()


def get_setting(key, default=""):
    with get_db() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,),
        ).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with get_db() as db:
        db.execute(
            """
            INSERT INTO settings(key, value)
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        db.commit()


# =========================
# HELPERS
# =========================

def money(value):
    return f"{int(value):,}".replace(",", "٬")


def is_admin(user_id):
    return user_id in ADMIN_IDS


def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 رنک‌ها", callback_data="category_rank")],
            [InlineKeyboardButton(text="⚡ قابلیت‌های اوپی", callback_data="category_op")],
            [InlineKeyboardButton(text="👤 پروفایل", callback_data="profile")],
            [InlineKeyboardButton(text="🆘 پشتیبانی", callback_data="support")],
        ]
    )


def admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 مدیریت رنک‌ها", callback_data="admin_rank")],
            [InlineKeyboardButton(text="⚡ مدیریت قابلیت‌ها", callback_data="admin_op")],
            [InlineKeyboardButton(text="📦 سفارش‌ها", callback_data="admin_orders")],
            [InlineKeyboardButton(text="🎟️ کوپن‌ها", callback_data="admin_coupons")],
            [InlineKeyboardButton(text="💳 تنظیمات پرداخت", callback_data="admin_payment")],
            [InlineKeyboardButton(text="🆘 تنظیمات پشتیبانی", callback_data="admin_support")],
        ]
    )


def admin_product_list_keyboard(rows, category):
    buttons = []

    for row in rows:
        status = "🟢" if row["enabled"] else "🔴"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {row['title']}",
                callback_data=f"edit:{row['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="➕ افزودن", callback_data=f"add:{category}")
    ])
    buttons.append([
        InlineKeyboardButton(text="🔙 پنل", callback_data="admin_home")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =========================
# STATES
# =========================

class ProductStates(StatesGroup):
    key = State()
    title = State()
    price = State()
    description = State()


class EditProductStates(StatesGroup):
    title = State()
    price = State()
    description = State()


class CouponStates(StatesGroup):
    code = State()
    percent = State()


class PaymentStates(StatesGroup):
    card_number = State()
    card_name = State()


class SupportStates(StatesGroup):
    username = State()


# =========================
# BOTS
# =========================

main_bot = Bot(MAIN_BOT_TOKEN)
admin_bot = Bot(ADMIN_BOT_TOKEN)

main_dp = Dispatcher()
admin_dp = Dispatcher()


# =========================
# MAIN BOT
# =========================

@main_dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "💎 <b>به ربات خرید رنک Zagros MC خوش آمدید!</b>\n\n"
        "از منوی زیر محصول موردنظر خود را انتخاب کنید.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@main_dp.callback_query(F.data.startswith("category_"))
async def category(callback: CallbackQuery):
    category_name = callback.data.replace("category_", "", 1)

    with get_db() as db:
        rows = db.execute(
            """
            SELECT *
            FROM products
            WHERE category=? AND enabled=1
            ORDER BY id
            """,
            (category_name,),
        ).fetchall()

    buttons = []

    for row in rows:
        if category_name == "rank":
            if row["product_key"] == "vip":
                icon = "💎"
            elif row["product_key"] == "legend":
                icon = "👑"
            else:
                icon = "💠"
        else:
            icon = "⚡"

        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {row['title']} — {money(row['price'])} تومان",
                callback_data=f"buy:{row['product_key']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="🔙 برگشت",
            callback_data="back_main",
        )
    ])

    if category_name == "rank":
        text = (
            "💎 <b>رنک‌های ZAGROS</b>\n\n"
            "رنک موردنظر را انتخاب کن:"
        )
    else:
        text = (
            "⚡ <b>قابلیت‌های اوپی ZAGROS</b>\n\n"
            "قابلیت موردنظر را انتخاب کن:"
        )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )
    await callback.answer()


@main_dp.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]

    with get_db() as db:
        product = db.execute(
            """
            SELECT *
            FROM products
            WHERE product_key=? AND enabled=1
            """,
            (key,),
        ).fetchone()

    if not product:
        await callback.answer("این محصول وجود ندارد.", show_alert=True)
        return

    with get_db() as db:
        db.execute(
            """
            INSERT INTO user_pending(user_id, product_key)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET product_key=excluded.product_key
            """,
            (callback.from_user.id, key),
        )
        db.commit()

    card_number = get_setting("card_number", DEFAULT_CARD_NUMBER)
    card_name = get_setting("card_name", DEFAULT_CARD_NAME)
    support = get_setting("support", DEFAULT_SUPPORT)

    text = (
        f"🛒 <b>{product['title']}</b>\n\n"
        f"{product['description']}\n\n"
        f"💰 قیمت: <b>{money(product['price'])} تومان</b>\n\n"
        f"💳 شماره کارت:\n<code>{card_number}</code>\n\n"
        f"👤 به نام: <b>{card_name}</b>\n\n"
        "بعد از پرداخت، عکس رسید را همینجا ارسال کنید.\n\n"
        f"🆘 پشتیبانی: @{support.lstrip('@')}"
    )

    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


@main_dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id

    with get_db() as db:
        orders = db.execute(
            """
            SELECT *
            FROM orders
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 10
            """,
            (user_id,),
        ).fetchall()

    text = (
        "👤 <b>پروفایل شما</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
    )

    if not orders:
        text += "📦 هنوز سفارشی ثبت نکرده‌اید."
    else:
        text += "📦 سفارش‌های اخیر:\n\n"
        for order in orders:
            text += (
                f"#{order['id']} - {order['product_name']} - "
                f"{money(order['amount'])} تومان\n"
                f"وضعیت: {order['status']}\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@main_dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    username = get_setting("support", DEFAULT_SUPPORT)

    await callback.message.edit_text(
        f"🆘 پشتیبانی:\n\n@{username.lstrip('@')}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")]
            ]
        ),
    )
    await callback.answer()


@main_dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "💎 <b>Zagros MC</b>\n\nمحصول موردنظر را انتخاب کنید.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================
# RECEIPTS
# =========================

@main_dp.message(F.photo)
async def receipt(message: Message):
    user_id = message.from_user.id

    with get_db() as db:
        pending = db.execute(
            """
            SELECT p.*
            FROM user_pending u
            JOIN products p ON p.product_key=u.product_key
            WHERE u.user_id=? AND p.enabled=1
            """,
            (user_id,),
        ).fetchone()

    if not pending:
        await message.answer("❌ ابتدا یک محصول را انتخاب کنید.")
        return

    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO orders
            (user_id, username, product_key, product_name, amount, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (
                user_id,
                message.from_user.username or "",
                pending["product_key"],
                pending["title"],
                pending["price"],
            ),
        )
        order_id = cursor.lastrowid

        db.execute(
            "DELETE FROM user_pending WHERE user_id=?",
            (user_id,),
        )
        db.commit()

    try:
        photo = message.photo[-1]
        file = await main_bot.get_file(photo.file_id)
        data = await main_bot.download_file(file.file_path)

        if hasattr(data, "getvalue"):
            image_bytes = data.getvalue()
        elif hasattr(data, "read"):
            image_bytes = data.read()
        else:
            raise RuntimeError("Could not read downloaded photo")

        caption = (
            "🧾 <b>سفارش جدید</b>\n\n"
            f"📦 محصول: <b>{pending['title']}</b>\n"
            f"💰 مبلغ: <b>{money(pending['price'])} تومان</b>\n"
            f"🆔 سفارش: <b>#{order_id}</b>\n"
            f"👤 کاربر: @{message.from_user.username or 'ندارد'}\n"
            f"🆔 User ID: <code>{user_id}</code>"
        )

        sent = False

        for admin_id in ADMIN_IDS:
            try:
                await admin_bot.send_photo(
                    chat_id=admin_id,
                    photo=BufferedInputFile(
                        image_bytes,
                        filename=f"receipt_{order_id}.jpg",
                    ),
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="✅ تایید",
                                    callback_data=f"approve:{order_id}",
                                ),
                                InlineKeyboardButton(
                                    text="❌ رد",
                                    callback_data=f"reject:{order_id}",
                                ),
                            ]
                        ]
                    ),
                )
                sent = True
            except Exception as e:
                print(
                    f"Could not send order #{order_id} "
                    f"to admin {admin_id}: {e}"
                )

        if sent:
            await message.answer(
                f"✅ رسید شما ثبت شد.\n\n"
                f"شماره سفارش: #{order_id}\n"
                "پس از بررسی توسط مدیریت، نتیجه برای شما ارسال می‌شود."
            )
        else:
            await message.answer(
                "⚠️ سفارش ثبت شد، اما ارسال آن برای مدیریت با مشکل مواجه شد."
            )

    except Exception as e:
        print(f"Receipt processing error: {e}")
        await message.answer(
            f"⚠️ سفارش #{order_id} ثبت شد، اما پردازش رسید با مشکل مواجه شد."
        )


# =========================
# ADMIN START
# =========================

@admin_dp.message(CommandStart())
@admin_dp.message(Command("admin"))
async def admin_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی ندارید.")
        return

    await message.answer(
        "🛠️ <b>پنل مدیریت Zagros MC</b>",
        reply_markup=admin_menu(),
        parse_mode="HTML",
    )


# =========================
# ADMIN PRODUCTS
# =========================

async def show_products_message(message: Message, category: str):
    with get_db() as db:
        rows = db.execute(
            """
            SELECT *
            FROM products
            WHERE category=?
            ORDER BY id
            """,
            (category,),
        ).fetchall()

    await message.edit_text(
        "مدیریت محصولات:",
        reply_markup=admin_product_list_keyboard(rows, category),
    )


@admin_dp.callback_query(F.data.in_(["admin_rank", "admin_op"]))
async def admin_products(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    category = "rank" if callback.data == "admin_rank" else "op"
    await show_products_message(callback.message, category)
    await callback.answer()


@admin_dp.callback_query(F.data.startswith("add:"))
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    category = callback.data.split(":", 1)[1]
    await state.update_data(category=category)
    await state.set_state(ProductStates.key)

    await callback.message.answer(
        "🔑 کلید محصول را بفرست.\nمثال: vip2"
    )
    await callback.answer()


@admin_dp.message(ProductStates.key)
async def add_product_key(message: Message, state: FSMContext):
    value = (message.text or "").strip().lower()

    if not value:
        await message.answer("❌ کلید نمی‌تواند خالی باشد.")
        return

    await state.update_data(key=value)
    await state.set_state(ProductStates.title)
    await message.answer("📝 نام محصول را بفرست.")


@admin_dp.message(ProductStates.title)
async def add_product_title(message: Message, state: FSMContext):
    value = (message.text or "").strip()

    if not value:
        await message.answer("❌ نام محصول نمی‌تواند خالی باشد.")
        return

    await state.update_data(title=value)
    await state.set_state(ProductStates.price)
    await message.answer("💰 قیمت را فقط به تومان و عدد بفرست.\nمثال: 100000")


@admin_dp.message(ProductStates.price)
async def add_product_price(message: Message, state: FSMContext):
    text = (message.text or "").strip().replace(",", "").replace("٬", "")

    if not text.isdigit():
        await message.answer("❌ قیمت باید عدد باشد.")
        return

    await state.update_data(price=int(text))
    await state.set_state(ProductStates.description)
    await message.answer("📄 توضیحات محصول را بفرست.")


@admin_dp.message(ProductStates.description)
async def add_product_description(message: Message, state: FSMContext):
    data = await state.get_data()
    description = (message.text or "").strip()

    try:
        with get_db() as db:
            db.execute(
                """
                INSERT INTO products
                (product_key, category, title, price, description, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    data["key"],
                    data["category"],
                    data["title"],
                    data["price"],
                    descrip
