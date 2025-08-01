# src/broadcast.py

import logging
import asyncio
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
from src.database import AsyncSessionLocal, User, Category
from sqlalchemy.future import select

logger = logging.getLogger(__name__)

# --- States ---
GET_MESSAGE, GET_AUDIENCE, GET_CATEGORY_FOR_BROADCAST, CONFIRM_BROADCAST = range(4)


# --- Entry Point ---
@admin_only
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Starts the broadcast conversation.
    """
    await update.message.reply_text(
        "شما وارد بخش ارسال پیام همگانی شده‌اید.\n\n"
        "لطفاً پیامی که می‌خواهید ارسال شود را بفرستید (متن، عکس، ویدیو، فایل).\n\n"
        "برای لغو /cancel را بزنید.",
        reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
    )
    return GET_MESSAGE

# --- Main Handlers ---
async def get_message_and_ask_audience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Saves the message to be broadcast and asks for the target audience.
    """
    # Storing the entire message object is easier for re-sending later
    context.user_data['broadcast_message'] = update.message

    keyboard = [
        [InlineKeyboardButton("همه کاربران تایید شده", callback_data="broadcast_audience_all")],
        [InlineKeyboardButton("کاربران یک دسته‌بندی", callback_data="broadcast_audience_category")],
        [InlineKeyboardButton("لغو", callback_data="broadcast_audience_cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "پیام شما برای ارسال ذخیره شد.\n\n"
        "لطفاً مخاطبین خود را برای ارسال انتخاب کنید:",
        reply_markup=reply_markup
    )
    return GET_AUDIENCE


async def get_audience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles the audience selection from the inline keyboard.
    """
    query = update.callback_query
    await query.answer()
    selection = query.data

    if selection == "broadcast_audience_all":
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User.id).where(User.is_approved == True))
            user_ids = [row[0] for row in result]

        context.user_data['broadcast_user_ids'] = user_ids

        confirmation_keyboard = [
            [InlineKeyboardButton("✅ ارسال", callback_data="broadcast_send_confirm")],
            [InlineKeyboardButton("❌ لغو", callback_data="broadcast_send_cancel")],
        ]

        await query.edit_message_text(
            f"مخاطب: همه کاربران تایید شده ({len(user_ids)} نفر).\n\n"
            "آیا برای ارسال پیام تایید می‌کنید؟",
            reply_markup=InlineKeyboardMarkup(confirmation_keyboard)
        )
        return CONFIRM_BROADCAST

    elif selection == "broadcast_audience_category":
        async with AsyncSessionLocal() as session:
            categories = await session.execute(select(Category).order_by(Category.name))
            keyboard = [
                [InlineKeyboardButton(cat.name, callback_data=f"broadcast_cat_{cat.id}")]
                for cat in categories.scalars().all()
            ]
        await query.edit_message_text("لطفاً دسته‌بندی مورد نظر را انتخاب کنید:",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return GET_CATEGORY_FOR_BROADCAST

    elif selection == "broadcast_audience_cancel":
        await query.edit_message_text("ارسال همگانی لغو شد.")
        await cancel_broadcast(update, context) # Use the existing cancel function
        return ConversationHandler.END


async def get_category_for_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gets the users of the selected category.
    """
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split("_")[2])

    async with AsyncSessionLocal() as session:
        # Get users associated with this category
        result = await session.execute(
            select(User.id).join(User.categories).where(Category.id == category_id, User.is_approved == True)
        )
        user_ids = [row[0] for row in result]

    context.user_data['broadcast_user_ids'] = user_ids
    category = await session.get(Category, category_id)

    confirmation_keyboard = [
        [InlineKeyboardButton("✅ ارسال", callback_data="broadcast_send_confirm")],
        [InlineKeyboardButton("❌ لغو", callback_data="broadcast_send_cancel")],
    ]

    await query.edit_message_text(
        f"مخاطب: کاربران دسته‌بندی '{category.name}' ({len(user_ids)} نفر).\n\n"
        "آیا برای ارسال پیام تایید می‌کنید؟",
        reply_markup=InlineKeyboardMarkup(confirmation_keyboard)
    )
    return CONFIRM_BROADCAST


async def confirm_broadcast_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Confirms the broadcast and starts the sending process.
    """
    query = update.callback_query
    await query.answer()
    selection = query.data

    if selection == "broadcast_send_cancel":
        await query.edit_message_text("ارسال همگانی لغو شد.")
        await cancel_broadcast(update, context)
        return ConversationHandler.END

    await query.edit_message_text("در حال شروع ارسال پیام...")

    user_ids = context.user_data.get('broadcast_user_ids', [])
    message_to_send = context.user_data.get('broadcast_message')
    total_users = len(user_ids)
    success_count = 0
    fail_count = 0

    for user_id in user_ids:
        try:
            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=message_to_send.chat_id,
                message_id=message_to_send.message_id,
                protect_content=True
            )
            success_count += 1
            logger.info(f"Broadcast message sent to user {user_id}")
        except Exception as e:
            fail_count += 1
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")

        await asyncio.sleep(0.1) # To avoid hitting rate limits

    report_message = (
        f"--- گزارش ارسال همگانی ---\n\n"
        f"ارسال موفق: {success_count} نفر\n"
        f"ارسال ناموفق: {fail_count} نفر\n"
        f"کل مخاطبین: {total_users} نفر"
    )
    await query.message.reply_text(report_message)

    # Clean up user_data
    context.user_data.pop('broadcast_message', None)
    context.user_data.pop('broadcast_user_ids', None)

    await cancel_broadcast(update, context) # Return to main admin menu
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cancels the broadcast conversation and returns to the main admin panel.
    """
    from src.admin_panel import admin_panel # Avoid circular import
    await admin_panel(update, context)
    return ConversationHandler.END


# --- Conversation Handler ---
broadcast_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^ارسال همگانی$"), broadcast_start)],
    states={
        GET_MESSAGE: [
            MessageHandler(filters.ALL & ~filters.COMMAND, get_message_and_ask_audience)
        ],
        GET_AUDIENCE: [
            CallbackQueryHandler(get_audience, pattern="^broadcast_audience_")
        ],
        GET_CATEGORY_FOR_BROADCAST: [
            CallbackQueryHandler(get_category_for_broadcast, pattern="^broadcast_cat_")
        ],
        CONFIRM_BROADCAST: [
            CallbackQueryHandler(confirm_broadcast_and_send, pattern="^broadcast_send_")
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_broadcast),
        MessageHandler(filters.Regex("^لغو$"), cancel_broadcast)
    ],
    name="broadcast_conv",
    per_message=True,
)
