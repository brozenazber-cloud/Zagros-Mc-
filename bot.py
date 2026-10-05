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
    max_uses = State()


class PurchaseCouponStates(StatesGroup):
    code = State()


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

    price_text = f"💰 قیمت: <b>{money(product['price'])} تومان</b>"
    if percent:
        price_text += (
            f"\n🎟️ تخفیف: <b>{percent}٪</b>"
            f"\n💵 مبلغ نهایی: <b>{money(final_price)} تومان</b>"
        )

    text = (
        f"🛒 <b>{product['title']}</b>\n\n"
        f"{product['description']}\n\n"
        f"{price_text}\n\n"
        f"💳 شماره کارت:\n<code>{card_number}</code>\n\n"
        f"👤 به نام: <b>{card_name}</b>\n\n"
        "بعد از پرداخت، عکس رسید را همینجا ارسال کنید.\n\n"
        f"🆘 پشتیبانی: @{support.lstrip('@')}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟️ وارد کردن کد تخفیف", callback_data=f"enter_coupon:{product['product_key']}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"category_{product['category']}")],
    ])
    await callback_or_message.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


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
    # Rebuild the purchase message without requiring a callback.
    class MessageWrapper:
        def __init__(self, msg):
            self.message = msg
            self.from_user = msg.from_user
    await show_purchase(MessageWrapper(message), product)
    await message.answer(f"✅ کد {code} با تخفیف {coupon['percent']}٪ اعمال شد.")


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
            f"💰 مبلغ: <b>{money(final_amount)} تومان</b>\n"
            + (f"🎟️ کد تخفیف: <b>{coupon_code}</b> ({discount_percent}٪)\n" if coupon_code else "")
            + f"🆔 سفارش: <b>#{order_id}</b>\n"
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
                    description,
                ),
            )
            db.commit()

        await state.clear()
        await message.answer(
            "✅ محصول با موفقیت اضافه شد.",
            reply_markup=admin_menu(),
        )

    except sqlite3.IntegrityError:
        await state.clear()
        await message.answer(
            "❌ این کلید محصول قبلاً استفاده شده است.",
            reply_markup=admin_menu(),
        )
    except Exception as e:
        await state.clear()
        print(f"Add product error: {e}")
        await message.answer(
            "❌ هنگام اضافه کردن محصول خطایی رخ داد.",
            reply_markup=admin_menu(),
        )


@admin_dp.callback_query(F.data.startswith("edit:"))
async def edit_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":", 1)[1])

    with get_db() as db:
        product = db.execute(
            "SELECT * FROM products WHERE id=?",
            (product_id,),
        ).fetchone()

    if not product:
        await callback.answer("محصول پیدا نشد.", show_alert=True)
        return

    status = "🟢 فعال" if product["enabled"] else "🔴 غیرفعال"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 تغییر نام", callback_data=f"edit_title:{product_id}")],
            [InlineKeyboardButton(text="💰 تغییر قیمت", callback_data=f"edit_price:{product_id}")],
            [InlineKeyboardButton(text="📄 تغییر توضیحات", callback_data=f"edit_desc:{product_id}")],
            [InlineKeyboardButton(text="🔄 فعال/غیرفعال", callback_data=f"toggle:{product_id}")],
            [InlineKeyboardButton(text="🗑️ حذف محصول", callback_data=f"delete:{product_id}")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"back_products:{product['category']}")],
        ]
    )

    await callback.message.edit_text(
        f"📦 <b>{product['title']}</b>\n\n"
        f"🔑 Key: <code>{product['product_key']}</code>\n"
        f"💰 قیمت: {money(product['price'])} تومان\n"
        f"📊 وضعیت: {status}\n\n"
        f"{product['description']}",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@admin_dp.callback_query(F.data.startswith("edit_title:"))
async def edit_title_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":", 1)[1])
    await state.update_data(product_id=product_id)
    await state.set_state(EditProductStates.title)
    await callback.message.answer("📝 نام جدید محصول را بفرست.")
    await callback.answer()


@admin_dp.message(EditProductStates.title)
async def edit_title_finish(message: Message, state: FSMContext):
    data = await state.get_data()

    with get_db() as db:
        db.execute(
            "UPDATE products SET title=? WHERE id=?",
            ((message.text or "").strip(), data["product_id"]),
        )
        db.commit()

    await state.clear()
    await message.answer("✅ نام محصول تغییر کرد.", reply_markup=admin_menu())


@admin_dp.callback_query(F.data.startswith("edit_price:"))
async def edit_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":", 1)[1])
    await state.update_data(product_id=product_id)
    await state.set_state(EditProductStates.price)
    await callback.message.answer("💰 قیمت جدید را فقط به صورت عدد بفرست.")
    await callback.answer()


@admin_dp.message(EditProductStates.price)
async def edit_price_finish(message: Message, state: FSMContext):
    text = (message.text or "").strip().replace(",", "").replace("٬", "")

    if not text.isdigit():
        await message.answer("❌ قیمت باید فقط عدد باشد.")
        return

    data = await state.get_data()

    with get_db() as db:
        db.execute(
            "UPDATE products SET price=? WHERE id=?",
            (int(text), data["product_id"]),
        )
        db.commit()

    await state.clear()
    await message.answer("✅ قیمت تغییر کرد.", reply_markup=admin_menu())


@admin_dp.callback_query(F.data.startswith("edit_desc:"))
async def edit_description_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":", 1)[1])
    await state.update_data(product_id=product_id)
    await state.set_state(EditProductStates.description)
    await callback.message.answer("📄 توضیحات جدید محصول را بفرست.")
    await callback.answer()


@admin_dp.message(EditProductStates.description)
async def edit_description_finish(message: Message, state: FSMContext):
    data = await state.get_data()

    with get_db() as db:
        db.execute(
            "UPDATE products SET description=? WHERE id=?",
            ((message.text or "").strip(), data["product_id"]),
        )
        db.commit()

    await state.clear()
    await message.answer("✅ توضیحات تغییر کرد.", reply_markup=admin_menu())


@admin_dp.callback_query(F.data.startswith("toggle:"))
async def toggle_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":", 1)[1])

    with get_db() as db:
        product = db.execute(
            "SELECT enabled FROM products WHERE id=?",
            (product_id,),
        ).fetchone()

        if not product:
            await callback.answer("محصول پیدا نشد.", show_alert=True)
            return

        new_status = 0 if product["enabled"] else 1
        db.execute(
            "UPDATE products SET enabled=? WHERE id=?",
            (new_status, product_id),
        )
        db.commit()

    # Refresh the same product screen.
    fake_data = f"edit:{product_id}"
    callback.data = fake_data
    await edit_product(callback)


@admin_dp.callback_query(F.data.startswith("delete:"))
async def delete_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":", 1)[1])

    with get_db() as db:
        product = db.execute(
            "SELECT category FROM products WHERE id=?",
            (product_id,),
        ).fetchone()

        if not product:
            await callback.answer("محصول پیدا نشد.", show_alert=True)
            return

        category = product["category"]
        db.execute("DELETE FROM products WHERE id=?", (product_id,))
        db.commit()

    await callback.message.edit_text(
        "✅ محصول حذف شد.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"back_products:{category}")]
            ]
        ),
    )
    await callback.answer()


@admin_dp.callback_query(F.data.startswith("back_products:"))
async def back_products(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    category = callback.data.split(":", 1)[1]
    await show_products_message(callback.message, category)
    await callback.answer()


@admin_dp.callback_query(F.data == "admin_home")
async def admin_home(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    await callback.message.edit_text(
        "🛠️ <b>پنل مدیریت Zagros MC</b>",
        reply_markup=admin_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================
# ORDERS
# =========================

@admin_dp.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    with get_db() as db:
        orders = db.execute(
            """
            SELECT *
            FROM orders
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()

    if not orders:
        text = "📦 هیچ سفارشی ثبت نشده است."
    else:
        text = "📦 <b>آخرین سفارش‌ها</b>\n\n"
        for order in orders:
            text += (
                f"#{order['id']} | {order['product_name']}\n"
                f"💰 {money(order['amount'])} تومان\n"
                f"👤 {order['username'] or 'ندارد'}\n"
                f"📌 وضعیت: {order['status']}\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 پنل", callback_data="admin_home")]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


async def set_order_status(order_id, status):
    with get_db() as db:
        order = db.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()

        if not order:
            return None

        db.execute(
            "UPDATE orders SET status=? WHERE id=?",
            (status, order_id),
        )
        db.commit()

    return order


@admin_dp.callback_query(F.data.startswith("approve:"))
async def approve_order(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    order_id = int(callback.data.split(":", 1)[1])
    order = await set_order_status(order_id, "approved")

    if not order:
        await callback.answer("سفارش پیدا نشد.", show_alert=True)
        return

    try:
        await main_bot.send_message(
            order["user_id"],
            "✅ <b>سفارش شما تایید شد!</b>\n\n"
            f"📦 محصول: {order['product_name']}\n"
            f"🧾 شماره سفارش: #{order_id}\n\n"
            "پرداخت شما توسط مدیریت تایید شد.",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"Could not notify user: {e}")

    try:
        await callback.message.edit_caption(
            caption=(
                f"🧾 <b>سفارش #{order_id}</b>\n\n"
                f"📦 محصول: <b>{order['product_name']}</b>\n"
                f"💰 مبلغ: <b>{money(order['amount'])} تومان</b>\n"
                "✅ <b>تایید شد</b>"
            ),
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass

    await callback.answer("سفارش تایید شد.")


@admin_dp.callback_query(F.data.startswith("reject:"))
async def reject_order(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    order_id = int(callback.data.split(":", 1)[1])
    order = await set_order_status(order_id, "rejected")

    if not order:
        await callback.answer("سفارش پیدا نشد.", show_alert=True)
        return

    try:
        await main_bot.send_message(
            order["user_id"],
            "❌ <b>سفارش شما رد شد.</b>\n\n"
            f"📦 محصول: {order['product_name']}\n"
            f"🧾 شماره سفارش: #{order_id}\n\n"
            "در صورت نیاز با پشتیبانی تماس بگیرید.",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"Could not notify user: {e}")

    try:
        await callback.message.edit_caption(
            caption=(
                f"🧾 <b>سفارش #{order_id}</b>\n\n"
                f"📦 محصول: <b>{order['product_name']}</b>\n"
                f"💰 مبلغ: <b>{money(order['amount'])} تومان</b>\n"
                "❌ <b>رد شد</b>"
            ),
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass

    await callback.answer("سفارش رد شد.")


# =========================
# COUPONS
# =========================

@admin_dp.callback_query(F.data == "admin_coupons")
async def admin_coupons(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    with get_db() as db:
        coupons = db.execute(
            "SELECT * FROM coupons ORDER BY code"
        ).fetchall()

    text = "🎟️ <b>کوپن‌ها</b>\n\n"

    if not coupons:
        text += "هیچ کوپنی وجود ندارد."
    else:
        for coupon in coupons:
            text += (
                f"🎟️ <code>{coupon['code']}</code> → {coupon['percent']}٪\n"
                f"📊 استفاده: {coupon['used_count']}/{'∞' if coupon['max_uses'] == 0 else coupon['max_uses']}\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                *[[InlineKeyboardButton(text=f"🗑️ حذف {coupon['code']}", callback_data=f"delete_coupon:{coupon['code']}")] for coupon in coupons],
                [InlineKeyboardButton(text="➕ افزودن کوپن", callback_data="add_coupon")],
                [InlineKeyboardButton(text="🔙 پنل", callback_data="admin_home")],
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@admin_dp.callback_query(F.data == "add_coupon")
async def add_coupon_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(CouponStates.code)
    await callback.message.answer("🎟️ کد کوپن را بفرست.")
    await callback.answer()


@admin_dp.message(CouponStates.code)
async def coupon_code(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()

    if not code:
        await message.answer("❌ کد کوپن نمی‌تواند خالی باشد.")
        return

    await state.update_data(code=code)
    await state.set_state(CouponStates.percent)
    await message.answer("📊 درصد تخفیف را بفرست.\nمثال: 20")


@admin_dp.message(CouponStates.percent)
async def coupon_percent(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    if not text.isdigit():
        await message.answer("❌ درصد باید عدد باشد.")
        return

    percent = int(text)

    if not 1 <= percent <= 100:
        await message.answer("❌ درصد باید بین 1 تا 100 باشد.")
        return

    data = await state.get_data()
    await state.update_data(percent=percent)
    await state.set_state(CouponStates.max_uses)
    await message.answer("🔢 حداکثر تعداد استفاده را بفرست.\nمثال: 10\nبرای استفاده نامحدود: 0")


@admin_dp.message(CouponStates.max_uses)
async def coupon_max_uses(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ تعداد استفاده باید عدد باشد.")
        return

    max_uses = int(text)
    data = await state.get_data()
    with get_db() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO coupons(code, percent, max_uses, used_count)
            VALUES (?, ?, ?, COALESCE((SELECT used_count FROM coupons WHERE code=?), 0))
            """,
            (data["code"], data["percent"], max_uses, data["code"]),
        )
        db.commit()

    await state.clear()
    limit_text = "نامحدود" if max_uses == 0 else str(max_uses)
    await message.answer(f"✅ کوپن ذخیره شد.\n🎟️ کد: {data['code']}\n📊 تخفیف: {data['percent']}٪\n🔢 سقف استفاده: {limit_text}", reply_markup=admin_menu())


@admin_dp.callback_query(F.data.startswith("delete_coupon:"))
async def delete_coupon(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    code = callback.data.split(":", 1)[1].upper()
    with get_db() as db:
        cur = db.execute("DELETE FROM coupons WHERE code=?", (code,))
        db.commit()

    if cur.rowcount == 0:
        await callback.answer("کوپن پیدا نشد.", show_alert=True)
        return

    await callback.answer(f"کوپن {code} حذف شد.")
    await admin_coupons(callback)


# =========================
# PAYMENT SETTINGS
# =========================

@admin_dp.callback_query(F.data == "admin_payment")
async def admin_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    card_number = get_setting("card_number", DEFAULT_CARD_NUMBER)
    card_name = get_setting("card_name", DEFAULT_CARD_NAME)

    await callback.message.edit_text(
        "💳 <b>تنظیمات پرداخت</b>\n\n"
        f"شماره کارت:\n<code>{card_number}</code>\n\n"
        f"نام صاحب کارت: <b>{card_name}</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 تغییر شماره کارت", callback_data="change_card_number")],
                [InlineKeyboardButton(text="👤 تغییر نام صاحب کارت", callback_data="change_card_name")],
                [InlineKeyboardButton(text="🔙 پنل", callback_data="admin_home")],
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@admin_dp.callback_query(F.data == "change_card_number")
async def change_card_number(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(PaymentStates.card_number)
    await callback.message.answer("💳 شماره کارت جدید را بفرست.")
    await callback.answer()


@admin_dp.message(PaymentStates.card_number)
async def save_card_number(message: Message, state: FSMContext):
    set_setting("card_number", (message.text or "").strip())
    await state.clear()
    await message.answer("✅ شماره کارت تغییر کرد.", reply_markup=admin_menu())


@admin_dp.callback_query(F.data == "change_card_name")
async def change_card_name(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(PaymentStates.card_name)
    await callback.message.answer("👤 نام صاحب کارت جدید را بفرست.")
    await callback.answer()


@admin_dp.message(PaymentStates.card_name)
async def save_card_name(message: Message, state: FSMContext):
    set_setting("card_name", (message.text or "").strip())
    await state.clear()
    await message.answer("✅ نام صاحب کارت تغییر کرد.", reply_markup=admin_menu())


# =========================
# SUPPORT SETTINGS
# =========================

@admin_dp.callback_query(F.data == "admin_support")
async def admin_support(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    username = get_setting("support", DEFAULT_SUPPORT)

    await callback.message.edit_text(
        "🆘 <b>تنظیمات پشتیبانی</b>\n\n"
        f"پشتیبانی فعلی: @{username.lstrip('@')}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✏️ تغییر پشتیبانی", callback_data="change_support")],
                [InlineKeyboardButton(text="🔙 پنل", callback_data="admin_home")],
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@admin_dp.callback_query(F.data == "change_support")
async def change_support(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(SupportStates.username)
    await callback.message.answer(
        "🆘 یوزرنیم پشتیبانی را بفرست.\nمثال: IBrOzen"
    )
    await callback.answer()


@admin_dp.message(SupportStates.username)
async def save_support(message: Message, state: FSMContext):
    username = (message.text or "").strip().lstrip("@")

    if not username:
        await message.answer("❌ یوزرنیم نمی‌تواند خالی باشد.")
        return

    set_setting("support", username)
    await state.clear()
    await message.answer(
        f"✅ پشتیبانی به @{username} تغییر کرد.",
        reply_markup=admin_menu(),
    )


# =========================
# START
# =========================

async def start_bots():
    init_db()
    print("Starting Zagros MC bots...")

    await asyncio.gather(
        main_dp.start_polling(main_bot, handle_signals=False),
        admin_dp.start_polling(admin_bot, handle_signals=False),
    )


def run_bot():
    asyncio.run(start_bots())


if __name__ == "__main__":
    run_bot()
