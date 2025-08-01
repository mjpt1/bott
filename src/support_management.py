# src/support_management.py

import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.decorators import admin_only
from src.database import AsyncSessionLocal, User, SupportTicket, SupportMessage
from src import config
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from src.admin_panel import USERS_PER_PAGE # Re-use constant

logger = logging.getLogger(__name__)

# --- States ---
AWAIT_FIRST_MESSAGE, IN_TICKET = range(2)


# --- Entry Point & User Handlers ---
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point for the /support command.
    Checks for existing open tickets or starts a new one.
    """
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as session:
        # Find user's open ticket
        result = await session.execute(
            select(SupportTicket).where(SupportTicket.user.has(user_id=user_id), SupportTicket.is_open == True)
        )
        open_ticket = result.scalars().first()

    if open_ticket:
        await update.message.reply_text(
            "شما یک تیکت پشتیبانی باز دارید. لطفاً پیام خود را ارسال کنید.\n"
            "برای خروج از این حالت، /end_support را بزنید.",
            reply_markup=ReplyKeyboardMarkup([["/end_support"]], resize_keyboard=True)
        )
        context.user_data['support_ticket_id'] = open_ticket.id
        return IN_TICKET
    else:
        await update.message.reply_text(
            "به بخش پشتیبانی خوش آمدید. لطفاً اولین پیام خود را برای ایجاد یک تیکت جدید ارسال کنید.\n"
            "برای لغو، /cancel را بزنید."
        )
        return AWAIT_FIRST_MESSAGE

# --- Helper Functions ---
async def notify_admins(context: ContextTypes.DEFAULT_TYPE, message_text: str):
    """
    Sends a notification message to all admins.
    """
    for admin_id in config.ADMIN_USER_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=message_text)
        except Exception as e:
            logger.error(f"Failed to send notification to admin {admin_id}: {e}")

async def save_message_and_notify(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_id: int):
    """
    Saves a user's message to the database and notifies admins.
    """
    message = update.message
    async with AsyncSessionLocal() as session:
        new_message = SupportMessage(
            ticket_id=ticket_id,
            telegram_message_id=message.message_id,
            chat_id=message.chat_id,
            text=message.text,
            sender_is_admin=False,
        )
        session.add(new_message)
        await session.commit()

    await notify_admins(
        context,
        f"پیام جدیدی در تیکت پشتیبانی شماره {ticket_id} از طرف کاربر {update.effective_user.full_name} دریافت شد."
    )
    await message.reply_text("پیام شما برای ادمین‌ها ارسال شد.")


# --- Main Handlers ---
async def handle_first_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles the first message from a user to create a new ticket.
    """
    user_id = update.effective_user.id
    message_text = update.message.text

    async with AsyncSessionLocal() as session:
        # Get the user's database ID
        user_db_id_result = await session.execute(select(User.id).where(User.user_id == user_id))
        user_db_id = user_db_id_result.scalar_one_or_none()

        if not user_db_id:
            await update.message.reply_text("خطا: کاربر شما در سیستم یافت نشد.")
            return ConversationHandler.END

        # Create new ticket
        new_ticket = SupportTicket(user_id=user_db_id)
        session.add(new_ticket)
        await session.flush() # To get the new_ticket.id

        context.user_data['support_ticket_id'] = new_ticket.id
        await save_message_and_notify(update, context, new_ticket.id)

    await update.message.reply_text(
        "تیکت پشتیبانی شما ایجاد شد. ادمین‌ها به زودی پاسخ خواهند داد.\n"
        "شما می‌توانید به ارسال پیام در این گفتگو ادامه دهید.\n"
        "برای خروج از این حالت، /end_support را بزنید.",
        reply_markup=ReplyKeyboardMarkup([["/end_support"]], resize_keyboard=True)
    )
    return IN_TICKET

async def handle_ticket_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles subsequent messages in an open ticket.
    """
    ticket_id = context.user_data.get('support_ticket_id')
    if not ticket_id:
        # This shouldn't happen if the conversation is managed correctly
        await update.message.reply_text("خطا: تیکت بازی یافت نشد. لطفاً با /support دوباره شروع کنید.")
        return ConversationHandler.END

    await save_message_and_notify(update, context, ticket_id)
    return IN_TICKET

async def end_support_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    User exits the support conversation state. Does not close the ticket.
    """
    context.user_data.pop('support_ticket_id', None)
    await update.message.reply_text(
        "شما از حالت گفتگوی پشتیبانی خارج شدید.\n"
        "برای ارسال پیام مجدد، از دستور /support استفاده کنید.",
        reply_markup=ReplyKeyboardMarkup.from_row(["/browse"]), # A more useful default keyboard
    )
    return ConversationHandler.END

async def cancel_new_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cancels the creation of a new ticket.
    """
    await update.message.reply_text(
        "ایجاد تیکت جدید لغو شد.",
        reply_markup=ReplyKeyboardMarkup.from_row(["/browse"]),
    )
    return ConversationHandler.END


# --- Admin-Side Handlers ---
ADMIN_MAIN, ADMIN_TICKET_VIEW, ADMIN_AWAIT_REPLY = range(10, 13) # Use a different range to avoid clashes

support_admin_keyboard = [
    ["مشاهده تیکت‌های باز"],
    ["بازگشت به پنل اصلی"],
]
support_admin_markup = ReplyKeyboardMarkup(support_admin_keyboard, resize_keyboard=True)

@admin_only
async def support_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Shows the main support menu for admins.
    """
    await update.message.reply_text(
        "به پنل مدیریت پشتیبانی خوش آمدید.",
        reply_markup=support_admin_markup
    )
    return ADMIN_MAIN

@admin_only
async def view_open_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> int:
    """
    Displays a paginated list of open support tickets.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SupportTicket)
            .options(joinedload(SupportTicket.user))
            .where(SupportTicket.is_open == True)
            .order_by(SupportTicket.created_at.desc())
            .offset(page * USERS_PER_PAGE)
            .limit(USERS_PER_PAGE)
        )
        tickets = result.scalars().all()

        total_tickets_count = (await session.execute(
            select(func.count(SupportTicket.id)).where(SupportTicket.is_open == True)
        )).scalar()

    if not tickets:
        await update.message.reply_text("هیچ تیکت بازی یافت نشد.")
        return ADMIN_MAIN

    keyboard = []
    for ticket in tickets:
        keyboard.append([
            InlineKeyboardButton(
                f"تیکت #{ticket.id} - {ticket.user.full_name} ({ticket.created_at.strftime('%Y-%m-%d')})",
                callback_data=f"admin_view_ticket_{ticket.id}"
            )
        ])

    # Pagination logic here if needed... (omitted for brevity for now)

    await update.message.reply_text(
        "لیست تیکت‌های باز:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_MAIN


async def back_to_main_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from src.admin_panel import admin_panel
    await admin_panel(update, context)
    return ConversationHandler.END


# --- User-Side Conversation Handler ---
user_support_handler = ConversationHandler(
    entry_points=[CommandHandler("support", support_start)],
    states={
        AWAIT_FIRST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_first_message)],
        IN_TICKET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ticket_message)],
    },
    fallbacks=[
        CommandHandler("end_support", end_support_conversation),
        CommandHandler("cancel", cancel_new_ticket)
    ],
    name="user_support_conv",
    per_message=True,
)

# --- Admin-Side Conversation Handler ---
admin_support_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^پشتیبانی$"), support_admin_menu)],
    states={
        ADMIN_MAIN: [
            MessageHandler(filters.Regex("^مشاهده تیکت‌های باز$"), view_open_tickets),
            CallbackQueryHandler(view_ticket_conversation, pattern="^admin_view_ticket_")
        ],
        ADMIN_TICKET_VIEW: [
            CallbackQueryHandler(ask_for_reply, pattern="^admin_reply_"),
            CallbackQueryHandler(close_ticket, pattern="^admin_close_"),
            CallbackQueryHandler(view_open_tickets, pattern="^admin_back_to_tickets$"),
        ],
        ADMIN_AWAIT_REPLY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_reply)
        ],
    },
    fallbacks=[MessageHandler(filters.Regex("^بازگشت به پنل اصلی$"), back_to_main_admin_panel)],
    name="admin_support_conv",
    per_message=True,
)

async def view_ticket_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Displays the full conversation for a single ticket.
    """
    query = update.callback_query
    await query.answer()
    ticket_id = int(query.data.split("_")[-1])
    context.user_data['current_admin_ticket_id'] = ticket_id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SupportTicket)
            .options(joinedload(SupportTicket.messages), joinedload(SupportTicket.user))
            .where(SupportTicket.id == ticket_id)
        )
        ticket = result.scalars().first()

    if not ticket:
        await query.edit_message_text("خطا: تیکت یافت نشد.")
        return ADMIN_MAIN

    conversation_history = f"--- تاریخچه تیکت #{ticket.id} برای کاربر: {ticket.user.full_name} ---\n\n"
    for msg in sorted(ticket.messages, key=lambda m: m.timestamp):
        sender = "ادمین" if msg.sender_is_admin else "کاربر"
        conversation_history += f"**{sender}:** {msg.text}\n"

    keyboard = [
        [
            InlineKeyboardButton("پاسخ به تیکت", callback_data=f"admin_reply_{ticket.id}"),
            InlineKeyboardButton(" بستن تیکت", callback_data=f"admin_close_{ticket.id}"),
        ],
        [InlineKeyboardButton(" بازگشت به لیست تیکت‌ها", callback_data="admin_back_to_tickets")],
    ]

    await query.edit_message_text(conversation_history, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return ADMIN_TICKET_VIEW


async def ask_for_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Asks the admin to type their reply message.
    """
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفاً پاسخ خود را تایپ کنید. برای لغو /cancel را بزنید.")
    return ADMIN_AWAIT_REPLY


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Saves the admin's reply, sends it to the user, and shows the conversation again.
    """
    reply_text = update.message.text
    ticket_id = context.user_data.get('current_admin_ticket_id')

    async with AsyncSessionLocal() as session:
        ticket_result = await session.execute(
            select(SupportTicket).options(joinedload(SupportTicket.user)).where(SupportTicket.id == ticket_id)
        )
        ticket = ticket_result.scalars().first()

        if not ticket:
            await update.message.reply_text("خطا: تیکت یافت نشد.")
            return await back_to_main_admin_panel(update, context)

        # Save admin's message
        new_message = SupportMessage(
            ticket_id=ticket.id,
            telegram_message_id=update.message.message_id,
            chat_id=update.message.chat_id,
            text=reply_text,
            sender_is_admin=True,
        )
        session.add(new_message)

        # Send message to user
        try:
            await context.bot.send_message(
                chat_id=ticket.user.user_id,
                text=f"پاسخ ادمین به تیکت #{ticket.id}:\n\n{reply_text}"
            )
            await session.commit()
            await update.message.reply_text("✅ پاسخ شما برای کاربر ارسال شد.")
        except Exception as e:
            await session.rollback()
            await update.message.reply_text(f"❌ خطایی در ارسال پیام به کاربر رخ داد: {e}")

    # Mock an update object to go back to the ticket view.
    # NOTE: This is a workaround for navigating between different parts of a conversation.
    # A more elegant solution might involve a larger refactor of the conversation flow,
    # but this approach is functional and contained.
    class MockQuery:
        def __init__(self, message, data):
            self.message = message
            self.data = data
        async def answer(self): pass
        async def edit_message_text(self, *args, **kwargs): await self.message.reply_text(*args, **kwargs)
    class MockUpdate:
        def __init__(self, query): self.callback_query = query

    mock_query = MockQuery(update.message, f"admin_view_ticket_{ticket_id}")
    return await view_ticket_conversation(MockUpdate(mock_query), context)


async def close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Closes an open support ticket.
    """
    query = update.callback_query
    await query.answer()
    ticket_id = int(query.data.split("_")[-1])

    async with AsyncSessionLocal() as session:
        ticket = await session.get(SupportTicket, ticket_id, options=[joinedload(SupportTicket.user)])
        if ticket:
            ticket.is_open = False
            await session.commit()
            await query.edit_message_text(f"✅ تیکت #{ticket_id} با موفقیت بسته شد.")
            try:
                await context.bot.send_message(
                    chat_id=ticket.user.user_id,
                    text=f"تیکت پشتیبانی شما با شماره #{ticket.id} توسط ادمین بسته شد."
                )
            except Exception as e:
                logger.error(f"Could not notify user {ticket.user.user_id} about ticket closure: {e}")
        else:
            await query.answer("خطا: تیکت یافت نشد.", show_alert=True)

    return await support_admin_menu(update, context)
