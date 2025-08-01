# src/config.py

import os
from dotenv import load_dotenv

# بارگیری متغیرهای محیطی از فایل .env
# این کار باید قبل از دسترسی به متغیرها انجام شود
load_dotenv()

# توکن ربات تلگرام
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# مسیر اتصال به پایگاه داده
DATABASE_URL = os.getenv("DATABASE_URL")

# شناسه عددی ادمین‌های ربات
# خواندن رشته از .env و تبدیل آن به لیست اعداد صحیح
admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
ADMIN_USER_IDS = [int(admin_id.strip()) for admin_id in admin_ids_str.split(',') if admin_id.strip().isdigit()]

# مسیر فایل لاگ
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH")

# مسیر ذخیره‌سازی محتوا
CONTENT_STORAGE_PATH = os.getenv("CONTENT_STORAGE_PATH")

# بررسی اینکه آیا توکن ربات تنظیم شده است یا خیر
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("توکن ربات تلگرام (TELEGRAM_BOT_TOKEN) در فایل .env تعریف نشده است.")

# ایجاد دایرکتوری‌های مورد نیاز در صورت عدم وجود
# این کار تضمین می‌کند که مسیرهای لاگ، محتوا و پایگاه داده همیشه در دسترس هستند
if LOG_FILE_PATH:
    os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
if CONTENT_STORAGE_PATH:
    os.makedirs(CONTENT_STORAGE_PATH, exist_ok=True)
if DATABASE_URL and DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.split("///")[1]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
