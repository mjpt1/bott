# src/admin_panel.py
import logging
from sqlalchemy.future import select
from sqlalchemy import func
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from src.decorators import admin_only
from src.database import AsyncSessionLocal, User
from src import constants

logger = logging.getLogger(__name__)

# --- Keyboard Markups ---
admin_keyboard = [
    ["تایید کاربران منتظر", "لیست تمام کاربران"],
    ["مدیریت دسته‌بندی‌ها", "ارسال همگانی"],
    ["پشتیبانی", "آمار ربات"],
    ["بازگشت به منوی اصلی"],
]
admin_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)

# --- Admin Panel Entry ---
@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نمایش پنل مدیریت برای ادمین‌ها.
    """
    await update.message.reply_text(
        "به پنل مدیریت خوش آمدید. لطفاً یک گزینه را انتخاب کنید:",
        reply_markup=admin_markup
    )

# --- User Approval Flow ---
@admin_only
async def show_unapproved_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نمایش اولین کاربر تایید نشده برای تایید یا رد.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.is_approved == False, User.is_blocked == False).order_by(User.created_at)
        )
        user_to_approve = result.scalars().first()

    if not user_to_approve:
        await update.message.reply_text("در حال حاضر کاربری در صف انتظار تایید وجود ندارد.")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"approve_{user_to_approve.user_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{user_to_approve.user_id}"),
        ],
        [InlineKeyboardButton("▶️ بعدی", callback_data="next_unapproved")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    user_info = (
        f"کاربر جدید در انتظار تایید:\n\n"
        f"نام: {user_to_approve.full_name}\n"
        f"شناسه تلگرام: `{user_to_approve.user_id}`\n"
        f"کد NFT: `{user_to_approve.nft_code}`\n"
        f"آدرس کیف پول: `{user_to_approve.wallet_address}`"
    )
    await update.message.reply_text(user_info, reply_markup=reply_markup, parse_mode='Markdown')


@admin_only
async def handle_user_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    پردازش کلیک دکمه‌های تایید یا رد کاربر.
    """
    query = update.callback_query
    await query.answer()

    action, user_id_str = query.data.split("_")
    user_id = int(user_id_str)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            await query.edit_message_text("کاربر مورد نظر یافت نشد.")
            return

        if action == "approve":
            user.is_approved = True
            await session.commit()
            await query.edit_message_text(f"✅ کاربر {user.full_name} با موفقیت تایید شد.")
            try:
                await context.bot.send_message(chat_id=user.user_id, text="حساب شما توسط ادمین تایید شد. اکنون به محتوا دسترسی دارید.")
            except Exception as e:
                logger.error(f"Failed to send approval notification to {user.user_id}: {e}")

        elif action == "reject":
            await session.delete(user)
            await session.commit()
            await query.edit_message_text(f"❌ کاربر {user.full_name} رد و از سیستم حذف شد.")
            try:
                await context.bot.send_message(chat_id=user.user_id, text="متاسفانه درخواست عضویت شما رد شد.")
            except Exception as e:
                logger.error(f"Failed to send rejection notification to {user.user_id}: {e}")

    # پس از انجام عملیات، کاربر بعدی را نمایش بده
    await show_unapproved_users(query.message, context)


# --- User Listing and Management ---
USERS_PER_PAGE = 5

@admin_only
async def list_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    """
    نمایش لیست صفحه‌بندی شده تمام کاربران.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).order_by(User.id).offset(page * USERS_PER_PAGE).limit(USERS_PER_PAGE))
        users = result.scalars().all()

        count_q = select(func.count()).select_from(User)
        total_users = (await session.execute(count_q)).scalar()

    if not users:
        await update.message.reply_text("هیچ کاربری در سیستم ثبت نام نکرده است.")
        return

    message_text = f"لیست کاربران (صفحه {page + 1}):"
    keyboard = []

    for user in users:
        status = "✅" if user.is_approved else "⏳"
        blocked_status = "🚫" if user.is_blocked else ""
        user_text = f"{status}{blocked_status} {user.full_name} (`{user.user_id}`)"

        block_text = "آزاد کردن" if user.is_blocked else "مسدود کردن"
        block_action = "unblock" if user.is_blocked else "block"

        keyboard.append([
            InlineKeyboardButton(user_text, callback_data=f"user_info_{user.user_id}"),
            InlineKeyboardButton(block_text, callback_data=f"{block_action}_{user.user_id}_{page}")
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"list_users_{page - 1}"))
    if (page + 1) * USERS_PER_PAGE < total_users:
        nav_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"list_users_{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # If called from a button press (MessageHandler), send a new message.
    # If called from a callback (pagination), edit the existing message.
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def list_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازش دکمه‌های صفحه‌بندی لیست کاربران."""
    query = update.callback_query
    await query.answer()

    page = int(query.data.split("_")[2])
    await list_all_users(update, context, page=page)


@admin_only
async def handle_block_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    پردازش کلیک دکمه‌های مسدود/آزاد کردن کاربر.
    """
    query = update.callback_query
    await query.answer()

    action, user_id_str, page_str = query.data.split("_")
    user_id = int(user_id_str)
    page = int(page_str)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            await query.answer("کاربر یافت نشد.", show_alert=True)
            return

        user.is_blocked = True if action == "block" else False
        await session.commit()

        await query.answer(f"کاربر {('مسدود' if user.is_blocked else 'آزاد')} شد.", show_alert=True)

    # Refresh the list to show the change
    await list_all_users(update, context, page=page)


@admin_only
async def handle_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the user info button click. For now, just an acknowledgement."""
    query = update.callback_query
    await query.answer("این دکمه در آینده جزئیات بیشتری از کاربر نمایش خواهد داد.")

# --- Handlers ---
admin_panel_handler = CommandHandler("admin", admin_panel)
show_unapproved_users_handler = MessageHandler(filters.Regex("^تایید کاربران منتظر$") & filters.ChatType.PRIVATE, show_unapproved_users)
user_approval_callback_handler = CallbackQueryHandler(handle_user_approval, pattern="^(approve|reject)_")
next_unapproved_handler = CallbackQueryHandler(show_unapproved_users, pattern="^next_unapproved$")
list_all_users_handler = MessageHandler(filters.Regex("^لیست تمام کاربران$") & filters.ChatType.PRIVATE, list_all_users)
list_users_callback_handler = CallbackQueryHandler(list_users_callback, pattern="^list_users_")
block_unblock_callback_handler = CallbackQueryHandler(handle_block_unblock, pattern="^(block|unblock)_")
user_info_callback_handler = CallbackQueryHandler(handle_user_info, pattern="^user_info_")
