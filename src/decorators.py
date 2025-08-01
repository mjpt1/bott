# src/decorators.py

from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

from src import config
from src import constants

def admin_only(func):
    """
    یک دکوراتور برای محدود کردن دسترسی به دستورات فقط برای ادمین‌ها.
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in config.ADMIN_USER_IDS:
            await update.message.reply_text(constants.ACCESS_DENIED_MESSAGE)
            return
        return await func(update, context, *args, **kwargs)
    return wrapped
