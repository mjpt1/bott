# src/security.py

import bcrypt

def hash_password(password: str) -> str:
    """
    یک رمز عبور رشته‌ای را دریافت کرده و نسخه هش‌شده آن را با استفاده از bcrypt برمی‌گرداند.
    """
    # تبدیل رشته رمز به بایت
    password_bytes = password.encode('utf-8')
    # تولید نمک (salt) و هش کردن رمز
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password_bytes, salt)
    # بازگرداندن نسخه هش‌شده به صورت رشته برای ذخیره‌سازی
    return hashed_password.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    بررسی می‌کند که آیا یک رمز عبور رشته‌ای با نسخه هش‌شده آن مطابقت دارد یا خیر.
    """
    # تبدیل رمزهای رشته‌ای به بایت
    plain_password_bytes = plain_password.encode('utf-8')
    hashed_password_bytes = hashed_password.encode('utf-8')
    # بررسی مطابقت رمز با استفاده از bcrypt
    return bcrypt.checkpw(plain_password_bytes, hashed_password_bytes)
