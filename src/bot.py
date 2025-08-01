# src/bot.py

import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# وارد کردن ماژول‌های پروژه
from src import config
from src import constants
from src.user_management import registration_handler
from src.admin_panel import (
    admin_panel_handler,
    show_unapproved_users_handler,
    user_approval_callback_handler,
    next_unapproved_handler,
    list_all_users_handler,
    list_users_callback_handler,
    block_unblock_callback_handler,
    user_info_callback_handler,
)

# تنظیمات اولیه لاگینگ
# لاگ‌ها در این مرحله فقط در کنسول نمایش داده می‌شوند
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main() -> None:
    """شروع به کار ربات و اجرای آن."""
    # بررسی وجود توکن ربات
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("توکن ربات تلگرام (TELEGRAM_BOT_TOKEN) در فایل .env تعریف نشده است.")
        return

    # ساخت اپلیکیشن ربات
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # افزودن هندلرهای اصلی
    application.add_handler(registration_handler)
    application.add_handler(admin_panel_handler)
    application.add_handler(show_unapproved_users_handler)
    application.add_handler(user_approval_callback_handler)
    application.add_handler(next_unapproved_handler)
    application.add_handler(list_all_users_handler)
    application.add_handler(list_users_callback_handler)
    application.add_handler(block_unblock_callback_handler)
    application.add_handler(user_info_callback_handler)

    # نمایش لاگ برای شروع به کار ربات
    logger.info("ربات با موفقیت شروع به کار کرد.")

    # اجرای ربات تا زمانی که کاربر آن را متوقف کند
    application.run_polling()

if __name__ == "__main__":
    main()
