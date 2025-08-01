# src/category_management.py

import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from typing import Optional
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

from src.decorators import admin_only
from src.database import AsyncSessionLocal, Category, User
from src.security import hash_password
from sqlalchemy.future import select
from sqlalchemy import func

logger = logging.getLogger(__name__)

# --- Conversation States ---
MAIN_MENU, ADD_CATEGORY_NAME, ADD_CATEGORY_PARENT, EDIT_CATEGORY_NAME, SET_PASSWORD, MANAGE_ACCESS = range(6)


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

async def add_category_save(update_or_query, context: ContextTypes.DEFAULT_TYPE, parent_id: Optional[int]):
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
        [InlineKeyboardButton("🗂️ مدیریت محتوا", callback_data=f"content_mgmt_{category.id}")],
        [InlineKeyboardButton("⬆️ بازگشت به لیست اصلی", callback_data="view_cat_root")],
    ])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return MAIN_MENU

async def delete_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    درخواست تایید برای حذف یک دسته‌بندی.
    """
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split("_")[2])

    keyboard = [
        [
            InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"delete_confirm_{category_id}"),
            InlineKeyboardButton(" خیر", callback_data=f"view_cat_{category_id}") # Go back to the category view
        ]
    ]
    await query.edit_message_text(
        "آیا از حذف این دسته‌بندی مطمئن هستید؟\n\n"
        "⚠️ **توجه:** اگر این دسته‌بندی شامل زیرمجموعه‌هایی باشد، حذف نخواهد شد.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def delete_category_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    حذف نهایی دسته‌بندی پس از تایید.
    """
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split("_")[2])

    async with AsyncSessionLocal() as session:
        # بررسی وجود زیرمجموعه‌ها
        result = await session.execute(select(Category).where(Category.parent_id == category_id))
        if result.scalars().first():
            await query.edit_message_text("❌ این دسته‌بندی شامل زیرمجموعه است و قابل حذف نیست. لطفاً ابتدا زیرمجموعه‌های آن را حذف کنید.")
            # Show the root categories again
            await view_categories(update, context)
            return

        # حذف دسته‌بندی
        category_to_delete = await session.get(Category, category_id)
        if category_to_delete:
            category_name = category_to_delete.name
            await session.delete(category_to_delete)
            await session.commit()
            logger.info(f"Category '{category_name}' (ID: {category_id}) was deleted by an admin.")
            await query.edit_message_text(f"✅ دسته‌بندی '{category_name}' با موفقیت حذف شد.")
        else:
            await query.edit_message_text("❌ خطایی در حذف رخ داد: دسته‌بندی یافت نشد.")

    # نمایش مجدد لیست دسته‌بندی‌های اصلی
    class MockUpdate:
        def __init__(self, message):
            self.message = message
    await view_categories(MockUpdate(query.message), context)


# --- "Edit Category" Flow ---
async def edit_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع فرآیند ویرایش نام دسته‌بندی.
    """
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split("_")[2])
    context.user_data['category_to_edit'] = category_id

    await query.message.reply_text(
        "لطفاً نام جدید را برای این دسته‌بندی وارد کنید. برای لغو /cancel را بزنید."
    )
    return EDIT_CATEGORY_NAME

async def edit_category_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت نام جدید و به‌روزرسانی پایگاه داده.
    """
    new_name = update.message.text
    category_id = context.user_data.get('category_to_edit')

    async with AsyncSessionLocal() as session:
        category = await session.get(Category, category_id)
        if category:
            original_name = category.name
            category.name = new_name
            try:
                await session.commit()
                message = f"✅ نام دسته‌بندی از '{original_name}' به '{new_name}' با موفقیت تغییر کرد."
                logger.info(f"Category {category_id} renamed from '{original_name}' to '{new_name}'.")
            except Exception as e:
                await session.rollback()
                message = f"❌ خطایی در تغییر نام رخ داد. احتمالاً نام جدید تکراری است.\n{e}"
                logger.error(f"Error renaming category {category_id}: {e}")
        else:
            message = "❌ دسته‌بندی مورد نظر برای ویرایش یافت نشد."

    await update.message.reply_text(message)
    context.user_data.pop('category_to_edit', None)

    # Show the main category menu again
    await category_management_menu(update, context)
    return MAIN_MENU


# --- Password Management Flow ---
async def password_menu_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نمایش منوی مدیریت رمز عبور برای یک دسته‌بندی.
    """
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split("_")[2])
    context.user_data['category_for_pass'] = category_id

    async with AsyncSessionLocal() as session:
        category = await session.get(Category, category_id)

    if not category:
        await query.edit_message_text("خطا: دسته‌بندی یافت نشد.")
        return MAIN_MENU

    text = f"مدیریت رمز برای دسته‌بندی: *{category.name}*"
    keyboard = []
    if category.password:
        keyboard.append([InlineKeyboardButton("🔄 تغییر رمز", callback_data="set_pass_change")])
        keyboard.append([InlineKeyboardButton("🗑 حذف رمز", callback_data="set_pass_remove")])
    else:
        keyboard.append([InlineKeyboardButton("➕ افزودن رمز", callback_data="set_pass_change")])

    keyboard.append([InlineKeyboardButton("⬅️ بازگشت", callback_data=f"view_cat_{category_id}")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return MAIN_MENU

async def ask_for_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    درخواست از کاربر برای ارسال رمز جدید.
    """
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفاً رمز عبور جدید را وارد کنید. برای لغو /cancel را بزنید.")
    return SET_PASSWORD

async def set_password_get_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت رمز جدید، هش کردن و ذخیره در پایگاه داده.
    """
    password = update.message.text
    category_id = context.user_data.get('category_for_pass')

    hashed = hash_password(password)

    async with AsyncSessionLocal() as session:
        category = await session.get(Category, category_id)
        if category:
            category.password = hashed
            await session.commit()
            message = "✅ رمز عبور با موفقیت برای دسته‌بندی تنظیم شد."
            logger.info(f"Password set for category {category_id}.")
        else:
            message = "❌ خطایی در تنظیم رمز رخ داد: دسته‌بندی یافت نشد."

    await update.message.reply_text(message)
    context.user_data.pop('category_for_pass', None)

    await category_management_menu(update, context)
    return MAIN_MENU

async def remove_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    حذف رمز عبور از یک دسته‌بندی.
    """
    query = update.callback_query
    await query.answer()
    category_id = context.user_data.get('category_for_pass')

    async with AsyncSessionLocal() as session:
        category = await session.get(Category, category_id)
        if category:
            category.password = None
            await session.commit()
            message = "✅ رمز عبور با موفقیت حذف شد."
            logger.info(f"Password removed for category {category_id}.")
        else:
            message = "❌ خطایی در حذف رمز رخ داد: دسته‌بندی یافت نشد."

    await query.edit_message_text(message)
    context.user_data.pop('category_for_pass', None)

    await category_management_menu(update, context)
    return MAIN_MENU


# --- Access Management Flow ---
USERS_PER_PAGE = 5

async def manage_access_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point for the access management sub-conversation.
    """
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split("_")[2])
    context.user_data['category_for_access'] = category_id

    await list_users_for_access(query, context, page=0)
    return MANAGE_ACCESS

async def list_users_for_access(query, context: ContextTypes.DEFAULT_TYPE, page: int):
    """
    Displays a paginated list of users with their access status for a category.
    """
    category_id = context.user_data['category_for_access']

    async with AsyncSessionLocal() as session:
        # Get the category name
        category = await session.get(Category, category_id)
        if not category:
            await query.edit_message_text("خطا: دسته‌بندی یافت نشد.")
            return

        # Get the paginated list of approved users
        users_result = await session.execute(
            select(User).where(User.is_approved == True).order_by(User.id).offset(page * USERS_PER_PAGE).limit(USERS_PER_PAGE)
        )
        users_on_page = users_result.scalars().all()

        # Get total count of approved users for pagination
        total_users_count = (await session.execute(select(func.count(User.id)).where(User.is_approved == True))).scalar()

        # Get IDs of users who already have access
        access_result = await session.execute(
            select(User.id).join(User.categories).where(Category.id == category_id)
        )
        users_with_access_ids = {row[0] for row in access_result}

    text = f"مدیریت دسترسی برای: *{category.name}* (صفحه {page + 1})\n"
    keyboard = []
    for user in users_on_page:
        access_status_icon = "✅" if user.id in users_with_access_ids else "❌"
        button_text = f"{access_status_icon} {user.full_name}"
        callback_data = f"toggle_access_{user.id}_{page}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"access_page_{page - 1}"))
    if (page + 1) * USERS_PER_PAGE < total_users_count:
        nav_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"access_page_{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ بازگشت به دسته‌بندی", callback_data=f"view_cat_{category_id}")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def manage_access_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles all callbacks within the MANAGE_ACCESS state (pagination and toggling).
    """
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("access_page_"):
        page = int(data.split("_")[2])
        await list_users_for_access(query, context, page=page)

    elif data.startswith("toggle_access_"):
        _, user_id_str, page_str = data.split("_")
        user_id = int(user_id_str)
        page = int(page_str)
        category_id = context.user_data['category_for_access']

        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            category = await session.get(Category, category_id)

            if user and category:
                if category in user.categories:
                    user.categories.remove(category)
                    logger.info(f"Access removed for user {user_id} from category {category_id}.")
                else:
                    user.categories.append(category)
                    logger.info(f"Access granted for user {user_id} to category {category_id}.")
                await session.commit()

        # Refresh the list
        await list_users_for_access(query, context, page=page)

    return MANAGE_ACCESS


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
            CallbackQueryHandler(delete_category_start, pattern="^delete_cat_"),
            CallbackQueryHandler(delete_category_confirm, pattern="^delete_confirm_"),
            CallbackQueryHandler(edit_category_start, pattern="^edit_cat_"),
            CallbackQueryHandler(password_menu_start, pattern="^pass_cat_"),
            CallbackQueryHandler(ask_for_password, pattern="^set_pass_change$"),
            CallbackQueryHandler(remove_password, pattern="^set_pass_remove$"),
            CallbackQueryHandler(manage_access_start, pattern="^access_cat_"),
        ],
        ADD_CATEGORY_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^لغو$"), add_category_get_name)
        ],
        ADD_CATEGORY_PARENT: [
            CallbackQueryHandler(add_category_get_parent, pattern="^add_cat_parent_")
        ],
        EDIT_CATEGORY_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, edit_category_get_name)
        ],
        SET_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, set_password_get_pass)
        ],
        MANAGE_ACCESS: [
            CallbackQueryHandler(manage_access_callback_handler, pattern="^(toggle_access|access_page)_"),
            CallbackQueryHandler(view_category_callback, pattern="^view_cat_") # To handle the "Back" button
        ],
    },
    fallbacks=[
        MessageHandler(filters.Regex("^⬅️ بازگشت به پنل ادمین$"), back_to_admin_panel),
        MessageHandler(filters.Regex("^لغو$"), category_management_menu), # Go back to the cat mgmt menu
        CommandHandler("cancel", back_to_admin_panel) # Allow cancelling with /cancel
    ],
    # Since we are not nesting this inside another ConversationHandler, we don't need map_to_parent
)
