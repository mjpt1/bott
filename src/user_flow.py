# src/user_flow.py

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

from src.database import AsyncSessionLocal, User, Category, Content
from src.security import verify_password
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload, selectinload

logger = logging.getLogger(__name__)

# --- States ---
CHOOSE_CATEGORY, AWAIT_PASSWORD = range(2)

# --- Entry Point ---
async def browse_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Starts the user flow for browsing content. Shows accessible categories.
    """
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as session:
        # Find the user and their accessible categories
        result = await session.execute(
            select(User).options(joinedload(User.categories)).where(User.user_id == user_id)
        )
        user = result.scalars().first()

    if not user or not user.is_approved:
        await update.message.reply_text("شما دسترسی لازم برای مشاهده محتوا را ندارید. لطفاً منتظر تایید ادمین بمانید.")
        return ConversationHandler.END

    if not user.categories:
        await update.message.reply_text("در حال حاضر به هیچ دسته‌بندی‌ای دسترسی ندارید.")
        return ConversationHandler.END

    keyboard = []
    for cat in user.categories:
        # We only show top-level categories here. Sub-categories are accessed through their parents.
        if cat.parent_id is None:
            lock_icon = "🔒" if cat.password else ""
            keyboard.append([InlineKeyboardButton(f"{lock_icon} {cat.name}", callback_data=f"user_cat_{cat.id}")])

    if not keyboard:
        await update.message.reply_text("در حال حاضر به هیچ دسته‌بندی اصلی دسترسی ندارید.")
        return ConversationHandler.END

    await update.message.reply_text(
        "لطفاً یک دسته‌بندی را برای مشاهده محتوا انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSE_CATEGORY

# --- Helper Functions ---
async def display_category_contents(query, context: ContextTypes.DEFAULT_TYPE, category_id: int, page: int = 0):
    """
    Displays the contents (subcategories and content items) of a given category.
    """
    async with AsyncSessionLocal() as session:
        # Eagerly load subcategories and contents
        result = await session.execute(
            select(Category).options(
                selectinload(Category.subcategories),
                selectinload(Category.contents)
            ).where(Category.id == category_id)
        )
        category = result.scalars().first()

    if not category:
        await query.edit_message_text("خطا: دسته‌بندی یافت نشد.")
        return

    keyboard = []
    text = f"شما در دسته‌بندی *{category.name}* هستید.\n\n"

    # List subcategories first
    if category.subcategories:
        text += "زیرمجموعه‌ها:\n"
        for sub_cat in category.subcategories:
            lock_icon = "🔒" if sub_cat.password else ""
            keyboard.append([InlineKeyboardButton(f"📁 {lock_icon} {sub_cat.name}", callback_data=f"user_cat_{sub_cat.id}")])

    # List content items
    if category.contents:
        text += "\nمحتوا:\n"
        # Simple pagination (can be improved later)
        for item in category.contents[page * USERS_PER_PAGE : (page + 1) * USERS_PER_PAGE]:
             keyboard.append([InlineKeyboardButton(f"📄 {item.caption}", callback_data=f"user_content_{item.id}")])

    # Navigation
    if category.parent_id:
        keyboard.append([InlineKeyboardButton("⬆️ بازگشت به دسته‌بندی والد", callback_data=f"user_cat_{category.parent_id}")])
    else:
        keyboard.append([InlineKeyboardButton("⬆️ بازگشت به لیست اصلی", callback_data="user_cat_root")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


# --- Main Handlers ---
async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles a user selecting a category. Checks for password if needed.
    """
    query = update.callback_query
    await query.answer()

    if query.data == "user_cat_root":
        # This is a bit of a hack, we need to restart the conversation
        await query.message.delete()
        await browse_start(query.message, context)
        return CHOOSE_CATEGORY

    category_id = int(query.data.split("_")[2])

    async with AsyncSessionLocal() as session:
        category = await session.get(Category, category_id)

    if not category:
        await query.edit_message_text("خطا: دسته‌بندی یافت نشد.")
        return CHOOSE_CATEGORY

    if category.password:
        context.user_data['target_category_id'] = category_id
        await query.message.reply_text(f"دسته‌بندی '{category.name}' با رمز عبور محافظت می‌شود. لطفاً رمز را وارد کنید:")
        return AWAIT_PASSWORD
    else:
        # Category is not password protected, show contents
        await display_category_contents(query, context, category_id)
        return CHOOSE_CATEGORY

async def password_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Verifies the password entered by the user.
    """
    password = update.message.text
    category_id = context.user_data.get('target_category_id')

    async with AsyncSessionLocal() as session:
        category = await session.get(Category, category_id)

    if category and verify_password(password, category.password):
        await update.message.reply_text("✅ رمز صحیح است.")
        # We need a mock query object to pass to the display function
        class MockQuery:
            def __init__(self, message):
                self.message = message
            async def edit_message_text(self, *args, **kwargs):
                await self.message.reply(*args, **kwargs)

        await display_category_contents(MockQuery(update.message), context, category_id)
        context.user_data.pop('target_category_id', None)
        return CHOOSE_CATEGORY
    else:
        await update.message.reply_text("❌ رمز عبور اشتباه است. لطفاً دوباره تلاش کنید یا /cancel را بزنید.")
        return AWAIT_PASSWORD

async def content_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Sends the selected content to the user.
    """
    query = update.callback_query
    await query.answer()
    content_id = int(query.data.split("_")[2])

    async with AsyncSessionLocal() as session:
        content = await session.get(Content, content_id)

    if content:
        try:
            if content.file_type == 'text':
                await query.message.reply_text(content.text_content, protect_content=True)
            elif content.file_type == 'photo':
                await query.message.reply_photo(content.telegram_file_id, caption=content.caption, protect_content=True)
            elif content.file_type == 'video':
                await query.message.reply_video(content.telegram_file_id, caption=content.caption, protect_content=True)
            elif content.file_type == 'document':
                await query.message.reply_document(content.telegram_file_id, caption=content.caption, protect_content=True)
        except Exception as e:
            await query.message.reply_text(f"❌ خطایی در ارسال محتوا رخ داد: {e}")
    else:
        await query.message.reply_text("❌ محتوا یافت نشد.")

    return CHOOSE_CATEGORY


async def end_browsing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Ends the browsing session.
    """
    await update.message.reply_text("جلسه مشاهده محتوا پایان یافت.")
    return ConversationHandler.END

# --- Conversation Handler ---
user_flow_handler = ConversationHandler(
    entry_points=[CommandHandler("browse", browse_start)],
    states={
        CHOOSE_CATEGORY: [
            CallbackQueryHandler(category_selected, pattern="^user_cat_"),
            CallbackQueryHandler(content_selected, pattern="^user_content_"),
        ],
        AWAIT_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, password_entered)
        ],
    },
    fallbacks=[CommandHandler("cancel", end_browsing)],
    name="user_flow_conv",
    per_message=True,
)
