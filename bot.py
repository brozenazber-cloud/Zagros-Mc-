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
DEFAULT_COIN_NAME = os.getenv("COIN_NAME", "کوین").strip() or "کوین"
DEFAULT_COIN_ICON = os.getenv("COIN_ICON", "🪙").strip() or "🪙"

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
                percent INTEGER NOT NULL,
                max_uses INTEGER NOT NULL DEFAULT 0,
                used_count INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Migrate older coupon tables. 0 = unlimited uses.
        coupon_columns = {row["name"] for row in db.execute("PRAGMA table_info(coupons)").fetchall()}
        if "max_uses" not in coupon_columns:
            db.execute("ALTER TABLE coupons ADD COLUMN max_uses INTEGER NOT NULL DEFAULT 0")
        if "used_count" not in coupon_columns:
            db.execute("ALTER TABLE coupons ADD COLUMN used_count INTEGER NOT NULL DEFAULT 0")

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS user_pending (
                user_id INTEGER PRIMARY KEY,
                product_key TEXT,
                coupon_code TEXT,
                discount_percent INTEGER DEFAULT 0
            )
        """)

        pending_columns = {row["name"] for row in db.execute("PRAGMA table_info(user_pending)").fetchall()}
        if "coupon_code" not in pending_columns:
            db.execute("ALTER TABLE user_pending ADD COLUMN coupon_code TEXT")
        if "discount_percent" not in pending_columns:
            db.execute("ALTER TABLE user_pending ADD COLUMN discount_percent INTEGER DEFAULT 0")

        defaults = {
            "card_number": DEFAULT_CARD_NUMBER,
            "card_name": DEFAULT_CARD_NAME,
            "support": DEFAULT_SUPPORT,
            "coin_name": DEFAULT_COIN_NAME,
            "coin_icon": DEFAULT_COIN_ICON,
        }

        for key, value in defaults.items():
            db.execute(
                """
                INSERT OR IGNORE INTO settings(key, value)
                VALUES (?, ?)
                """,
                (key, value),
            )

        # OP products are no longer part of Zagros MC.
        db.execute("DELETE FROM products WHERE category='op'")

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


def currency_label(value):
    return f"{money(value)} {get_setting('coin_name', DEFAULT_COIN_NAME)}"


def currency_icon():
    return get_setting("coin_icon", DEFAULT_COIN_ICON)


def is_admin(user_id):
    return user_id in ADMIN_IDS


def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 رنک‌ها", callback_data="category_rank")],
            [InlineKeyboardButton(text="🐾 پت‌ها", callback_data="category_pet")],
            [InlineKeyboardButton(text="👤 پروفایل", callback_data="profile")],
            [InlineKeyboardButton(text="🆘 پشتیبانی", callback_data="support")],
        ]
    )


def admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 مدیریت رنک‌ها", callback_data="admin_rank")],
            [InlineKeyboardButton(text="🐾 مدیریت پت‌ها", callback_data="admin_pet")],
            [InlineKeyboardButton(text="📦 سفارش‌ها", callback_data="admin_orders")],
            [InlineKeyboardButton(text="🎟️ کوپن‌ها", callback_data="admin_coupons")],
            [InlineKeyboardButton(text="🪙 تنظیمات واحد پول", callback_data="admin_currency")],
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
    max_uses = State()


class PurchaseCouponStates(StatesGroup):
    code = State()


class PaymentStates(StatesGroup):
    card_number = State()
    card_name = State()


class SupportStates(StatesGroup):
    username = State()


class CurrencyStates(StatesGroup):
    name = State()
    icon = State()


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
        "💎 <b>به فروشگاه Zagros MC خوش آمدید!</b>\n\n"
        f"واحد پول سرور: {currency_icon()} <b>{get_setting('coin_name', DEFAULT_COIN_NAME)}</b>\n"
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
            icon = "🐾"

        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {row['title']} — {currency_label(row['price'])}",
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
            "🐾 <b>پت‌های ZAGROS</b>\n\n"
            "پت موردنظر را انتخاب کن:"
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
            "SELECT * FROM products WHERE product_key=? AND enabled=1",
            (key,),
        ).fetchone()

        if not product:
            await callback.answer("این محصول وجود ندارد.", show_alert=True)
            return

        # Starting a new product clears any coupon from the previous purchase.
        db.execute(
            """
            INSERT INTO user_pending(user_id, product_key, coupon_code, discount_percent)
            VALUES (?, ?, NULL, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                product_key=excluded.product_key,
                coupon_code=NULL,
                discount_percent=0
            """,
            (callback.from_user.id, key),
        )
        db.commit()

    await show_purchase(callback, product)
    await callback.answer()


async def show_purchase(callback_or_message, product):
    user_id = callback_or_message.from_user.id
    with get_db() as db:
        pending = db.execute(
            "SELECT coupon_code, discount_percent FROM user_pending WHERE user_id=?",
            (user_id,),
        ).fetchone()

    percent = int(pending["discount_percent"] or 0) if pending else 0
    final_price = product["price"] - (product["price"] * percent // 100)
    card_number = get_setting("card_number", DEFAULT_CARD_NUMBER)
    card_name = get_setting("card_name", DEFAULT_CARD_NAME)
    support = get_setting("support", DEFAULT_SUPPORT)

    price_text = f"{currency_icon()} قیمت: <b>{currency_label(product['price'])}</b>"
    if percent:
        price_text += (
            f"\n🎟️ تخفیف: <b>{percent}٪</b>"
            f"\n💵 مبلغ نهایی: <b>{currency_label(final_price)}</b>"
        )

    text = (
        f"🛒 <b>{product['title']}</b>\n\n"
        f"{product['description']}\n\n"
        f"{price_text}\n\n"
        f"💳 شماره کارت:\n<code>{card_number}</code>\n\n"
        f"👤 به نام: <b>{card_name}</b>\n\n"
        "بعد از پرداخت، عکس رسید را همینجا ارسال کنید.\n"
        f"💡 مبلغ سفارش بر اساس واحد پول سرور ({get_setting('coin_name', DEFAULT_COIN_NAME)}) ثبت می‌شود.\n\n"
        f"🆘 پشتیبانی: @{support.lstrip('@')}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟️ وارد کردن کد تخفیف", callback_data=f"enter_coupon:{product['product_key']}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"category_{product['category']}")],
    ])
    # CallbackQuery messages can be edited, but a user's incoming Message cannot.
    # After a coupon is entered, send a new purchase message instead of trying
    # to edit the user's own message (which causes TelegramBadRequest).
    if isinstance(callback_or_message, CallbackQuery):
        await callback_or_message.message.edit_text(
            text, reply_markup=keyboard, parse_mode="HTML"
        )
    else:
        await callback_or_message.answer(
            text, reply_markup=keyboard, parse_mode="HTML"
        )


@main_dp.callback_query(F.data.startswith("enter_coupon:"))
async def enter_coupon_start(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    with get_db() as db:
        product = db.execute("SELECT * FROM products WHERE product_key=? AND enabled=1", (key,)).fetchone()
    if not product:
        await callback.answer("محصول پیدا نشد.", show_alert=True)
        return

    await state.update_data(product_key=key)
    await state.set_state(PurchaseCouponStates.code)
    await callback.message.answer("🎟️ کد تخفیف را ارسال کن.\nمثال: ZAGROS20")
    await callback.answer()


@main_dp.message(PurchaseCouponStates.code)
async def apply_coupon(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    data = await state.get_data()
    key = data.get("product_key")

    with get_db() as db:
        coupon = db.execute("SELECT * FROM coupons WHERE code=?", (code,)).fetchone()
        product = db.execute("SELECT * FROM products WHERE product_key=? AND enabled=1", (key,)).fetchone()

    if not product:
        await state.clear()
        await message.answer("❌ محصول پیدا نشد.")
        return
    if not coupon:
        await message.answer("❌ کد تخفیف معتبر نیست.")
        return
    if coupon["max_uses"] > 0 and coupon["used_count"] >= coupon["max_uses"]:
        await message.answer("❌ ظرفیت استفاده از این کد تخفیف تمام شده است.")
        return

    with get_db() as db:
        db.execute(
            "UPDATE user_pending SET coupon_code=?, discount_percent=? WHERE user_id=? AND product_key=?",
            (code, coupon["percent"], message.from_user.id, key),
        )
        db.commit()

    await state.clear()
    # Message objects cannot be edited because they belong to the user.
    # show_purchase() sends a fresh bot message for this case.
    await show_purchase(message, product)


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
                f"{currency_label(order['amount'])}\n"
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
            SELECT p.*, u.coupon_code, u.discount_percent
            FROM user_pending u
            JOIN products p ON p.product_key=u.product_key
            WHERE u.user_id=? AND p.enabled=1
            """,
            (user_id,),
        ).fetchone()

    if not pending:
        await message.answer("❌ ابتدا یک محصول را انتخاب کنید.")
        return

    discount_percent = int(pending["discount_percent"] or 0)
    final_amount = pending["price"] - (pending["price"] * discount_percent // 100)
    coupon_code = pending["coupon_code"]

    with get_db() as db:
        # Consume one use only when a receipt becomes an order.
        if coupon_code:
            coupon = db.execute("SELECT * FROM coupons WHERE code=?", (coupon_code,)).fetchone()
            if not coupon or (coupon["max_uses"] > 0 and coupon["used_count"] >= coupon["max_uses"]):
                await message.answer("❌ این کد تخفیف دیگر قابل استفاده نیست. دوباره محصول را انتخاب کنید.")
                return

        cursor = db.execute(
            """
            INSERT INTO orders
            (user_id, username, product_key, product_name, amount, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (user_id, message.from_user.username or "", pending["product_key"], pending["title"], final_amount),
        )
        order_id = cursor.lastrowid

        if coupon_code:
            db.execute("UPDATE coupons SET used_count=used_count+1 WHERE code=?", (coupon_code,))

        db.execute("DELETE FROM user_pending WHERE user_id=?", (user_id,))
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
            f"💰 مبلغ: <b>{currency_label(final_amount)}</b>\n"
    
