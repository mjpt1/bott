# src/content_management.py

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
from src.database import AsyncSessionLocal, Content, Category
from sqlalchemy.future import select

logger = logging.getLogger(__name__)

# --- States ---
MAIN_CONTENT_MENU, AWAIT_CONTENT, AWAIT_CAPTION = range(3)

# --- Keyboards ---
content_management_keyboard = [
    ["➕ افزودن محتوا", "👁 مشاهده محتوا"],
    ["⬅️ بازگشت به دسته‌بندی"],
]
content_management_markup = ReplyKeyboardMarkup(content_management_keyboard, resize_keyboard=True)

# --- Entry Point ---
async def content_management_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point for the content management conversation.
    """
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split("_")[2])
    context.user_data['category_for_content'] = category_id

    async with AsyncSessionLocal() as session:
        category = await session.get(Category, category_id)

    await query.edit_message_text(
        f"مدیریت محتوا برای دسته‌بندی: *{category.name}*",
        reply_markup=content_management_markup,
        parse_mode='Markdown'
    )
    return MAIN_CONTENT_MENU

# --- "Add Content" Flow ---
async def add_content_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Asks the admin to send the content to be added.
    """
    await update.message.reply_text(
        "لطفاً محتوای مورد نظر خود را ارسال کنید (متن، عکس, ویدیو, فایل)...\n\n"
        "برای لغو، /cancel را بزنید."
    )
    return AWAIT_CONTENT

async def add_content_get_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Receives the content, stores its info, and asks for a caption.
    """
    message = update.message
    content_info = {}

    if message.text:
        content_info['type'] = 'text'
        content_info['text'] = message.text
        content_info['file_id'] = None
    elif message.photo:
        content_info['type'] = 'photo'
        content_info['file_id'] = message.photo[-1].file_id
        content_info['text'] = message.caption
    elif message.video:
        content_info['type'] = 'video'
        content_info['file_id'] = message.video.file_id
        content_info['text'] = message.caption
    elif message.document:
        content_info['type'] = 'document'
        content_info['file_id'] = message.document.file_id
        content_info['text'] = message.caption
    else:
        await message.reply_text("❌ نوع فایل پشتیبانی نمی‌شود. لطفاً متن، عکس، ویدیو یا فایل ارسال کنید.")
        return AWAIT_CONTENT

    context.user_data['new_content'] = content_info
    await message.reply_text("لطفاً یک عنوان یا توضیح برای این محتوا بنویسید. این عنوان در لیست محتوا به کاربر نمایش داده می‌شود.")
    return AWAIT_CAPTION

async def add_content_get_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Receives the caption and saves the new content to the database.
    """
    caption = update.message.text
    content_info = context.user_data.get('new_content')
    category_id = context.user_data.get('category_for_content')

    new_content = Content(
        category_id=category_id,
        file_type=content_info['type'],
        telegram_file_id=content_info['file_id'],
        text_content=content_info['text'] if content_info['type'] == 'text' else None,
        caption=caption,
    )

    async with AsyncSessionLocal() as session:
        session.add(new_content)
        await session.commit()

    await update.message.reply_text(
        f"✅ محتوای جدید با عنوان '{caption}' با موفقیت به این دسته‌بندی اضافه شد.",
        reply_markup=content_management_markup
    )

    context.user_data.pop('new_content', None)
    return MAIN_CONTENT_MENU


async def view_content_start(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> int:
    """
    Displays a paginated list of content within the current category.
    """
    category_id = context.user_data['category_for_content']

    async with AsyncSessionLocal() as session:
        # Get content for the current page
        content_result = await session.execute(
            select(Content)
            .where(Content.category_id == category_id)
            .order_by(Content.id)
            .offset(page * USERS_PER_PAGE)
            .limit(USERS_PER_PAGE)
        )
        contents = content_result.scalars().all()

        # Get total count for pagination
        total_content_count = (await session.execute(
            select(func.count(Content.id)).where(Content.category_id == category_id)
        )).scalar()

        category = await session.get(Category, category_id)

    if not contents:
        await update.message.reply_text("هیچ محتوایی در این دسته‌بندی یافت نشد.")
        return MAIN_CONTENT_MENU

    text = f"محتوای دسته‌بندی: *{category.name}* (صفحه {page + 1})\n"
    keyboard = []
    for item in contents:
        keyboard.append([
            InlineKeyboardButton(item.caption, callback_data=f"view_content_{item.id}"),
            InlineKeyboardButton("🗑", callback_data=f"delete_content_{item.id}_{page}"),
        ])

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"content_page_{page - 1}"))
    if (page + 1) * USERS_PER_PAGE < total_content_count:
        nav_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"content_page_{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # Send as new message if called from ReplyKeyboard, edit if from pagination
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    return MAIN_CONTENT_MENU


# --- View/Delete Callback Handlers ---
async def content_view_or_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles callbacks for viewing, deleting, or paginating content.
    """
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("content_page_"):
        page = int(data.split("_")[2])
        await view_content_start(update, context, page=page)

    elif data.startswith("view_content_"):
        content_id = int(data.split("_")[2])
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

    elif data.startswith("delete_content_"):
        _, content_id_str, page_str = data.split("_")
        keyboard = [
            [
                InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"delete_content_confirm_{content_id_str}_{page_str}"),
                InlineKeyboardButton(" خیر", callback_data=f"content_page_{page_str}") # Go back to the list
            ]
        ]
        await query.edit_message_text(
            "آیا از حذف این محتوا مطمئن هستید؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("delete_content_confirm_"):
        _, content_id_str, page_str = data.split("_")
        content_id = int(content_id_str)
        page = int(page_str)
        async with AsyncSessionLocal() as session:
            content_to_delete = await session.get(Content, content_id)
            if content_to_delete:
                await session.delete(content_to_delete)
                await session.commit()
                await query.answer("محتوا با موفقیت حذف شد.", show_alert=True)
            else:
                await query.answer("خطا: محتوا یافت نشد.", show_alert=True)
        # Refresh the list
        await view_content_start(update, context, page=page)

    return MAIN_CONTENT_MENU


async def back_to_category_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Ends the content management conversation and shows the category view again.
    """
    from src.category_management import view_category_callback # Avoid circular import

    category_id = context.user_data.get('category_for_content')

    # We need a mock query object to pass back to the category view handler
    class MockQuery:
        def __init__(self, message, data):
            self.message = message
            self.data = data
        async def answer(self):
            pass
    class MockUpdate:
        def __init__(self, query):
            self.callback_query = query

    # Create a new message to call the category view on, to avoid conflicts
    message = await update.message.reply_text("بازگشت به منوی دسته‌بندی...")
    mock_query = MockQuery(message, f"view_cat_{category_id}")
    await view_category_callback(MockUpdate(mock_query), context)
    await message.delete() # Delete the temporary message

    context.user_data.pop('category_for_content', None)
    return ConversationHandler.END

# --- Conversation Handler ---
content_management_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(content_management_start, pattern="^content_mgmt_")],
    states={
        MAIN_CONTENT_MENU: [
            MessageHandler(filters.Regex("^➕ افزودن محتوا$"), add_content_start),
            MessageHandler(filters.Regex("^👁 مشاهده محتوا$"), view_content_start),
            CallbackQueryHandler(content_view_or_delete_callback, pattern="^(view_content_|delete_content|content_page_)"),
        ],
        AWAIT_CONTENT: [
            MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, add_content_get_content)
        ],
        AWAIT_CAPTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, add_content_get_caption)
        ],
    },
    fallbacks=[
        MessageHandler(filters.Regex("^⬅️ بازگشت به دسته‌بندی$"), back_to_category_view),
        CommandHandler("cancel", back_to_category_view)
    ],
    # This conversation is entered from another handler, so it should not be persistent
    # across application restarts. We also don't map to parent, we just end it.
    per_message=True,
    name="content_management_conv",
)
