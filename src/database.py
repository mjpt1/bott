# src/database.py

import asyncio
from datetime import datetime
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    BigInteger,
    ForeignKey,
    Table,
    Text,
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship

from src.config import DATABASE_URL

# ایجاد موتور پایگاه داده آسنکرون
# از `create_async_engine` برای کار با `aiosqlite` استفاده می‌شود
async_engine = create_async_engine(DATABASE_URL)

# ایجاد یک sessionmaker آسنکرون برای مدیریت نشست‌های پایگاه داده
# expire_on_commit=False از جدا شدن اشیاء از نشست پس از کامیت جلوگیری می‌کند
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
)

# تعریف کلاس پایه برای مدل‌های SQLAlchemy
# تمام مدل‌های ما از این کلاس ارث‌بری خواهند کرد
Base = declarative_base()

# جدول واسط برای ارتباط چند به چند بین کاربران و دسته‌بندی‌ها
user_category_association = Table(
    'user_category_association', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('category_id', Integer, ForeignKey('categories.id'))
)

# تعریف مدل کاربر (User)
class User(Base):
    """
    مدل جدول کاربران در پایگاه داده.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    nft_code = Column(String, nullable=False, unique=True)
    wallet_address = Column(String, nullable=False, unique=True)
    is_approved = Column(Boolean, default=False)
    is_blocked = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # تعریف ارتباط با دسته‌بندی‌ها
    categories = relationship(
        "Category",
        secondary=user_category_association,
        back_populates="users"
    )

    # ارتباط با تیکت‌های پشتیبانی
    support_tickets = relationship("SupportTicket", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, user_id={self.user_id}, full_name='{self.full_name}')>"

# تعریف مدل دسته‌بندی (Category)
class Category(Base):
    """
    مدل جدول دسته‌بندی‌ها.
    """
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    password = Column(String, nullable=True)  # برای دسته‌بندی‌های محافظت‌شده

    # برای ساختن ساختار درختی (پدر و فرزندی)
    parent_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    parent = relationship('Category', remote_side=[id], back_populates='subcategories')
    subcategories = relationship('Category', back_populates='parent')

    # تعریف ارتباط با کاربران
    users = relationship(
        "User",
        secondary=user_category_association,
        back_populates="categories"
    )

    # ارتباط با محتوا
    contents = relationship("Content", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Category(id={self.id}, name='{self.name}')>"

# تعریف مدل محتوا (Content)
class Content(Base):
    """
    مدل جدول محتوا. هر ردیف یک محتوای قابل ارائه در یک دسته‌بندی است.
    """
    __tablename__ = "contents"

    id = Column(Integer, primary_key=True, index=True)
    file_type = Column(String, nullable=False) # e.g., 'text', 'photo', 'video', 'document'
    telegram_file_id = Column(String, nullable=True, unique=True) # For files
    text_content = Column(Text, nullable=True) # For text messages
    caption = Column(Text, nullable=True)

    # ارتباط با دسته‌بندی
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)
    category = relationship("Category", back_populates="contents")

    def __repr__(self):
        return f"<Content(id={self.id}, type='{self.file_type}', category_id={self.category_id})>"


# تعریف مدل تیکت پشتیبانی (SupportTicket)
class SupportTicket(Base):
    __tablename__ = 'support_tickets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    is_open = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="support_tickets")
    messages = relationship("SupportMessage", back_populates="ticket", cascade="all, delete-orphan")

# تعریف مدل پیام پشتیبانی (SupportMessage)
class SupportMessage(Base):
    __tablename__ = 'support_messages'
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('support_tickets.id'), nullable=False)
    telegram_message_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    text = Column(Text, nullable=True)
    sender_is_admin = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("SupportTicket", back_populates="messages")


async def init_db():
    """
    تابع آسنکرون برای مقداردهی اولیه پایگاه داده.
    این تابع تمام جداول تعریف‌شده در مدل‌ها را ایجاد می‌کند.
    """
    async with async_engine.begin() as conn:
        # `run_sync` متدهای همزمان SQLAlchemy را در یک محیط آسنکرون اجرا می‌کند
        await conn.run_sync(Base.metadata.create_all)

# اجرای تابع init_db برای ایجاد جداول در اولین اجرای برنامه
# این کار را می‌توان به یک اسکریپت جداگانه نیز منتقل کرد
if __name__ == "__main__":
    asyncio.run(init_db())
    print("پایگاه داده و جداول با موفقیت ایجاد شدند.")
