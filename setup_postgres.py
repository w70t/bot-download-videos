#!/usr/bin/env python3
"""
إنشاء جداول PostgreSQL للبوت
Create PostgreSQL tables for the bot
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def create_tables():
    """إنشاء جميع الجداول المطلوبة"""
    
    # الاتصال بقاعدة البيانات
    conn = psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'telegram_bot'),
        user=os.getenv('POSTGRES_USER', 'bot_user'),
        password=os.getenv('POSTGRES_PASSWORD')
    )
    
    cursor = conn.cursor()
    
    print("🔧 إنشاء الجداول...")
    
    # جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            is_subscribed INTEGER DEFAULT 0,
            subscription_end TIMESTAMP,
            payment_method VARCHAR(100),
            language VARCHAR(10) DEFAULT 'ar',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("✅ جدول users")
    
    # جدول الإعدادات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key VARCHAR(255) PRIMARY KEY,
            value TEXT
        )
    ''')
    print("✅ جدول settings")
    
    # جدول الدفوعات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            payment_id SERIAL PRIMARY KEY,
            user_id BIGINT,
            amount REAL,
            payment_method VARCHAR(100),
            proof_file_id VARCHAR(255),
            proof_message_id BIGINT,
            status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP,
            approved_by BIGINT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    print("✅ جدول payments")
    
    # جدول التحميلات اليومية
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_downloads (
            user_id BIGINT,
            download_date DATE DEFAULT CURRENT_DATE,
            download_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, download_date),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    print("✅ جدول daily_downloads")
    
    # إضافة الإعدادات الافتراضية (قيم عامة فقط)
    cursor.execute('''
        INSERT INTO settings (key, value) VALUES
        ('max_duration_minutes', '60'),
        ('daily_download_limit', '6'),
        ('subscription_price', '10'),
        ('subscription_duration_days', '30')
        ON CONFLICT (key) DO NOTHING
    ''')

    # القيم التجارية (معرّف Binance ومعرّف الدعم) تُقرأ من متغيرات البيئة بدل
    # كتابتها داخل الكود؛ تُضاف فقط إذا كانت مُعرّفة في .env
    business_defaults = {
        'binance_pay_id': os.getenv('BINANCE_PAY_ID', '').strip(),
        'telegram_support': os.getenv('SUPPORT_USERNAME', '').strip().lstrip('@'),
    }
    for key, value in business_defaults.items():
        if value:
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO NOTHING",
                (key, value)
            )
    print("✅ الإعدادات الافتراضية")
    
    # إنشاء indexes للأداء
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_language ON users(language)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_subscribed ON users(is_subscribed)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)')
    print("✅ Indexes")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print("\n✅ تم إنشاء جميع الجداول بنجاح!")

if __name__ == "__main__":
    create_tables()
