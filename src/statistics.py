# src/statistics.py

import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from sqlalchemy import func, select

from src.decorators import admin_only
from src.database import AsyncSessionLocal, User, Category, Content, SupportTicket

logger = logging.getLogger(__name__)


@admin_only
async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Queries the database and displays key statistics to the admin.
    """
    async with AsyncSessionLocal() as session:
        total_users = (await session.execute(select(func.count(User.id)))).scalar()
        approved_users = (await session.execute(select(func.count(User.id)).where(User.is_approved == True))).scalar()
        blocked_users = (await session.execute(select(func.count(User.id)).where(User.is_blocked == True))).scalar()

        total_categories = (await session.execute(select(func.count(Category.id)))).scalar()
        total_contents = (await session.execute(select(func.count(Content.id)))).scalar()

        open_tickets = (await session.execute(select(func.count(SupportTicket.id)).where(SupportTicket.is_open == True))).scalar()

    stats_message = (
        "📊 **آمار کلی ربات** 📊\n\n"
        "--- کاربران ---\n"
        f"👤 کل کاربران ثبت‌نام کرده: {total_users}\n"
        f"✅ کاربران تایید شده: {approved_users}\n"
        f"🚫 کاربران مسدود شده: {blocked_users}\n\n"
        "--- محتوا ---\n"
        f"📁 تعداد دسته‌بندی‌ها: {total_categories}\n"
        f"📄 تعداد کل محتواها: {total_contents}\n\n"
        "--- پشتیبانی ---\n"
        f"🎫 تیکت‌های پشتیبانی باز: {open_tickets}\n"
    )

    await update.message.reply_text(stats_message, parse_mode='Markdown')


# --- Handler ---
statistics_handler = MessageHandler(filters.Regex("^آمار ربات$") & filters.ChatType.PRIVATE, show_statistics)
