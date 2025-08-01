# src/category_management.py

import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

from src.decorators import admin_only
from src.database import AsyncSessionLocal, Category
from sqlalchemy.future import select

logger = logging.getLogger(__name__)

# --- Conversation States ---
MAIN_MENU, ADD_CATEGORY_NAME, ADD_CATEGORY_PARENT = range(3)


# --- Keyboards ---
category_management_keyboard = [
    ["➕ افزودن دسته‌بندی", "👁 مشاهده دسته‌بندی‌ها"],
    ["⬅️ بازگشت به پنل ادمین"],
]
category_management_markup = ReplyKeyboardMarkup(category_management_keyboard, resize_keyboard=True)


# --- Entry Point ---
@admin_only
async def category_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نمایش منوی اصلی مدیریت دسته‌بندی‌ها.
    """
    await update.message.reply_text(
        "به بخش مدیریت دسته‌بندی‌ها خوش آمدید.",
        reply_markup=category_management_markup
    )
    return MAIN_MENU

# --- "Add Category" Flow ---
async def add_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع فرآیند افزودن دسته‌بندی جدید. درخواست نام.
    """
    await update.message.reply_text(
        "لطفاً نام دسته‌بندی جدید را وارد کنید:",
        reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
    )
    return ADD_CATEGORY_NAME

async def add_category_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت نام و درخواست انتخاب دسته‌بندی والد.
    """
    context.user_data['new_category_name'] = update.message.text

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Category).order_by(Category.name))
        categories = result.scalars().all()

    if not categories:
        # اگر هیچ دسته‌بندی دیگری وجود ندارد، این یکی اصلی خواهد بود
        await add_category_save(update, context, parent_id=None)
        return MAIN_MENU # End the sub-conversation here

    keyboard = [[InlineKeyboardButton("هیچکدام (دسته‌بندی اصلی)", callback_data="add_cat_parent_None")]]
    for cat in categories:
        keyboard.append([InlineKeyboardButton(cat.name, callback_data=f"add_cat_parent_{cat.id}")])

    await update.message.reply_text(
        "این دسته‌بندی زیرمجموعه‌ی کدام دسته‌بندی باشد؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADD_CATEGORY_PARENT

async def add_category_get_parent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت دسته‌بندی والد و ذخیره در پایگاه داده.
    """
    query = update.callback_query
    await query.answer()

    parent_id_str = query.data.replace("add_cat_parent_", "")
    parent_id = int(parent_id_str) if parent_id_str != "None" else None

    await add_category_save(query, context, parent_id)
    return MAIN_MENU

async def add_category_save(update_or_query, context: ContextTypes.DEFAULT_TYPE, parent_id: int | None):
    """
    منطق ذخیره‌سازی دسته‌بندی جدید.
    """
    category_name = context.user_data.get('new_category_name')

    new_category = Category(name=category_name, parent_id=parent_id)

    async with AsyncSessionLocal() as session:
        session.add(new_category)
        try:
            await session.commit()
            message = f"✅ دسته‌بندی '{category_name}' با موفقیت ایجاد شد."
            logger.info(f"Category '{category_name}' created by admin.")
        except Exception as e:
            await session.rollback()
            message = f"❌ خطایی در ایجاد دسته‌بندی رخ داد. احتمالاً نام آن تکراری است.\n{e}"
            logger.error(f"Error creating category '{category_name}': {e}")

    # بازگشت به منوی اصلی مدیریت دسته‌بندی
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(message, reply_markup=category_management_markup)
    else: # It's a CallbackQuery
        await update_or_query.message.edit_text(message, reply_markup=None) # Clear inline keyboard
        await update_or_query.message.reply_text("بازگشت به منوی مدیریت دسته‌بندی.", reply_markup=category_management_markup)

    context.user_data.pop('new_category_name', None)


# --- "View Categories" Flow ---
async def view_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نمایش لیست دسته‌بندی‌ها به صورت درختی و قابل تعامل.
    """
    async with AsyncSessionLocal() as session:
        # فقط دسته‌بندی‌های اصلی (بدون والد) را برای شروع نمایش بده
        result = await session.execute(select(Category).where(Category.parent_id == None).order_by(Category.name))
        top_level_categories = result.scalars().all()

    if not top_level_categories:
        await update.message.reply_text("هیچ دسته‌بندی‌ای یافت نشد. لطفاً ابتدا یک دسته‌بندی اضافه کنید.")
        return MAIN_MENU

    keyboard = []
    for cat in top_level_categories:
        # دکمه‌ای برای هر دسته‌بندی که با کلیک، جزئیات آن نمایش داده می‌شود
        keyboard.append([InlineKeyboardButton(f"📁 {cat.name}", callback_data=f"view_cat_{cat.id}")])

    await update.message.reply_text(
        "لیست دسته‌بندی‌های اصلی:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MAIN_MENU # Stay in the main menu state to receive callbacks


async def view_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    پردازش کلیک روی یک دسته‌بندی برای نمایش جزئیات و زیرمجموعه‌ها یا بازگشت به ریشه.
    """
    query = update.callback_query
    await query.answer()

    if query.data == "view_cat_root":
        # Re-show the top-level categories
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Category).where(Category.parent_id == None).order_by(Category.name))
            top_level_categories = result.scalars().all()

        keyboard = []
        for cat in top_level_categories:
            keyboard.append([InlineKeyboardButton(f"📁 {cat.name}", callback_data=f"view_cat_{cat.id}")])

        await query.edit_message_text(
            "لیست دسته‌بندی‌های اصلی:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MAIN_MENU

    category_id = int(query.data.split("_")[2])

    async with AsyncSessionLocal() as session:
        from sqlalchemy.orm import joinedload
        result = await session.execute(
            select(Category)
            .options(joinedload(Category.subcategories), joinedload(Category.parent))
            .where(Category.id == category_id)
        )
        category = result.scalars().first()

    if not category:
        await query.edit_message_text("خطا: دسته‌بندی یافت نشد.")
        return MAIN_MENU

    text = f"ویرایش دسته‌بندی: *{category.name}*\n"
    if category.parent:
        text += f"زیرمجموعه‌ی: *{category.parent.name}*\n"

    keyboard = []
    if category.subcategories:
        text += "\nزیرمجموعه‌ها:\n"
        for sub_cat in category.subcategories:
             keyboard.append([InlineKeyboardButton(f"📁 {sub_cat.name}", callback_data=f"view_cat_{sub_cat.id}")])

    keyboard.extend([
        [
            InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"edit_cat_{category.id}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"delete_cat_{category.id}"),
        ],
        [
            InlineKeyboardButton("🔑 مدیریت رمز", callback_data=f"pass_cat_{category.id}"),
            InlineKeyboardButton("👤 مدیریت دسترسی", callback_data=f"access_cat_{category.id}"),
        ],
        [InlineKeyboardButton("⬆️ بازگشت به لیست اصلی", callback_data="view_cat_root")],
    ])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return MAIN_MENU

async def handle_coming_soon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles buttons for features that are not yet implemented."""
    query = update.callback_query
    await query.answer("این قابلیت به زودی پیاده‌سازی خواهد شد.", show_alert=True)

async def back_to_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    بازگشت به پنل اصلی ادمین و پایان مکالمه مدیریت دسته‌بندی.
    """
    from src.admin_panel import admin_panel, admin_markup # Avoid circular import
    await update.message.reply_text(
        "بازگشت به پنل اصلی مدیریت.",
        reply_markup=admin_markup
    )
    return ConversationHandler.END


# --- Conversation Handler ---
category_management_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^مدیریت دسته‌بندی‌ها$"), category_management_menu)],
    states={
        MAIN_MENU: [
            MessageHandler(filters.Regex("^➕ افزودن دسته‌بندی$"), add_category_start),
            MessageHandler(filters.Regex("^👁 مشاهده دسته‌بندی‌ها$"), view_categories),
            CallbackQueryHandler(view_category_callback, pattern="^view_cat_"),
            CallbackQueryHandler(handle_coming_soon, pattern="^(edit_cat|delete_cat|pass_cat|access_cat)_"),
        ],
        ADD_CATEGORY_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^لغو$"), add_category_get_name)
        ],
        ADD_CATEGORY_PARENT: [
            CallbackQueryHandler(add_category_get_parent, pattern="^add_cat_parent_")
        ],
    },
    fallbacks=[
        MessageHandler(filters.Regex("^⬅️ بازگشت به پنل ادمین$"), back_to_admin_panel),
        MessageHandler(filters.Regex("^لغو$"), category_management_menu), # Go back to the cat mgmt menu
        CommandHandler("cancel", back_to_admin_panel) # Allow cancelling with /cancel
    ],
    # Since we are not nesting this inside another ConversationHandler, we don't need map_to_parent
)
