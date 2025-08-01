# src/user_management.py

import logging
from sqlalchemy.future import select
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src import constants
from src.database import AsyncSessionLocal, User

# تنظیمات لاگینگ
logger = logging.getLogger(__name__)

# تعریف مراحل مکالمه برای ثبت نام
ASK_FULL_NAME, ASK_NFT_CODE, ASK_WALLET_ADDRESS = range(3)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع فرآیند ثبت نام یا نمایش پیام برای کاربران ثبت‌شده.
    """
    user_id = update.message.from_user.id
    async with AsyncSessionLocal() as session:
        # بررسی اینکه آیا کاربر قبلاً ثبت نام کرده است یا خیر
        result = await session.execute(select(User).where(User.user_id == user_id))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            if existing_user.is_approved:
                await update.message.reply_text("شما قبلاً ثبت نام کرده و تایید شده‌اید.")
            else:
                await update.message.reply_text("شما قبلاً ثبت نام کرده‌اید. لطفاً منتظر تایید ادمین بمانید.")
            return ConversationHandler.END

    # اگر کاربر جدید است، فرآیند ثبت نام را شروع کن
    await update.message.reply_text(
        f"{constants.WELCOME_MESSAGE}\n{constants.REGISTRATION_START_MESSAGE}"
    )
    await update.message.reply_text(
        constants.ASK_FOR_FULL_NAME,
        reply_markup=ReplyKeyboardMarkup([[constants.CANCEL_BUTTON]], one_time_keyboard=True, resize_keyboard=True),
    )
    return ASK_FULL_NAME


async def ask_nft_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت نام کامل کاربر و درخواست کد NFT.
    """
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text(constants.ASK_FOR_NFT_CODE)
    return ASK_NFT_CODE


async def ask_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت کد NFT و درخواست آدرس کیف پول.
    """
    context.user_data['nft_code'] = update.message.text
    await update.message.reply_text(constants.ASK_FOR_WALLET_ADDRESS)
    return ASK_WALLET_ADDRESS


async def save_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    ذخیره اطلاعات کاربر در پایگاه داده و پایان مکالمه.
    """
    user_id = update.message.from_user.id
    context.user_data['wallet_address'] = update.message.text

    # ایجاد یک کاربر جدید با اطلاعات جمع‌آوری شده
    new_user = User(
        user_id=user_id,
        full_name=context.user_data['full_name'],
        nft_code=context.user_data['nft_code'],
        wallet_address=context.user_data['wallet_address'],
    )

    try:
        async with AsyncSessionLocal() as session:
            session.add(new_user)
            await session.commit()

        await update.message.reply_text(
            constants.REGISTRATION_COMPLETE_MESSAGE,
            reply_markup=ReplyKeyboardRemove(),
        )
        logger.info(f"کاربر جدید با شناسه {user_id} ثبت نام کرد.")

    except Exception as e:
        logger.error(f"خطا در ذخیره کاربر {user_id}: {e}")
        await update.message.reply_text(
            constants.GENERAL_ERROR_MESSAGE,
            reply_markup=ReplyKeyboardRemove(),
        )

    # پاک کردن اطلاعات موقت کاربر
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    لغو فرآیند ثبت نام و پایان مکالمه.
    """
    await update.message.reply_text(
        constants.COMMAND_CANCELLED_MESSAGE, reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END

# ساخت ConversationHandler برای مدیریت فرآیند ثبت نام
registration_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start_handler)],
    states={
        ASK_FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_nft_code)],
        ASK_NFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_wallet_address)],
        ASK_WALLET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_registration)],
    },
    fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(f"^{constants.CANCEL_BUTTON}$"), cancel)],
)
