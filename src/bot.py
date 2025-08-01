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
from src.category_management import category_management_handler
from src.content_management import content_management_handler
from src.user_flow import user_flow_handler
from src.broadcast import broadcast_handler
from src.support_management import user_support_handler, admin_support_handler
from src.statistics import statistics_handler
from src.logging_utils import setup_logging

# Call the setup function to configure logging
setup_logging()

# Also set up basic config for console logging
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
    application.add_handler(category_management_handler)
    application.add_handler(content_management_handler)
    application.add_handler(user_flow_handler)
    application.add_handler(broadcast_handler)
    application.add_handler(user_support_handler)
    application.add_handler(admin_support_handler)
    application.add_handler(statistics_handler)

    # نمایش لاگ برای شروع به کار ربات
    logger.info("ربات با موفقیت شروع به کار کرد.")

    # اجرای ربات تا زمانی که کاربر آن را متوقف کند
    application.run_polling()

if __name__ == "__main__":
    main()
