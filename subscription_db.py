"""
نظام قاعدة البيانات للاشتراكات
==================================
إدارة المشتركين والدفوعات والإعدادات
PostgreSQL Database System
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# PostgreSQL Configuration
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
    'database': os.getenv('POSTGRES_DB', 'telegram_bot'),
    'user': os.getenv('POSTGRES_USER', 'bot_user'),
    'password': os.getenv('POSTGRES_PASSWORD')
}

def init_db():
    """إنشاء قاعدة البيانات والجداول - PostgreSQL version"""
    # الجداول موجودة بالفعل من setup_postgres.py
    # هذه الدالة للتوافق فقط
    logger.info("✅ تم إنشاء قاعدة البيانات بنجاح")

def get_connection():
    """الحصول على اتصال بقاعدة البيانات - PostgreSQL"""
    return psycopg2.connect(**POSTGRES_CONFIG)

# ═══════════════════════════════════════════════════════════════
# دوال المستخدمين والاشتراكات
# ═══════════════════════════════════════════════════════════════

def is_user_subscribed(user_id: int) -> bool:
    """التحقق من اشتراك المستخدم"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT is_subscribed, subscription_end 
        FROM users 
        WHERE user_id = %s
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return False
    
    is_subscribed, end_date = result
    
    if not is_subscribed:
        return False
    
    # التحقق من انتهاء الاشتراك
    if end_date:
        # PostgreSQL يُرجع datetime object مباشرة، بينما SQLite يُرجع string
        if isinstance(end_date, str):
            end_datetime = datetime.fromisoformat(end_date)
        else:
            end_datetime = end_date
        
        if datetime.now() > end_datetime:
            # انتهى الاشتراك
            deactivate_subscription(user_id)
            return False
    
    return True

def add_or_update_user(user_id: int, username: str = None, first_name: str = None):
    """إضافة أو تحديث معلومات المستخدم"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # استخدام INSERT ON CONFLICT للحفاظ على بيانات الاشتراك
    cursor.execute('''
        INSERT INTO users (user_id, username, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    ''', (user_id, username, first_name))
    
    conn.commit()
    conn.close()

def activate_subscription(user_id: int, duration_days: int = 30, payment_method: str = 'manual'):
    """تفعيل اشتراك المستخدم"""
    conn = get_connection()
    cursor = conn.cursor()
    
    end_date = datetime.now() + timedelta(days=duration_days)
    
    cursor.execute('''
        UPDATE users
        SET is_subscribed = 1, subscription_end = %s, payment_method = %s
        WHERE user_id = %s
    ''', (end_date.isoformat(), payment_method, user_id))
    
    conn.commit()
    conn.close()
    logger.info(f"✅ تم تفعيل اشتراك المستخدم {user_id} حتى {end_date}")

def deactivate_subscription(user_id: int):
    """إلغاء اشتراك المستخدم (إلغاء الترقية)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE users
        SET is_subscribed = 0, subscription_end = NULL, payment_method = NULL
        WHERE user_id = %s
    ''', (user_id,))
    
    conn.commit()
    conn.close()
    logger.info(f"❌ تم إلغاء اشتراك المستخدم {user_id}")

def get_recent_users(limit: int = 50):
    """الحصول على آخر المستخدمين"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, username, first_name, is_subscribed
        FROM users
        ORDER BY user_id DESC
        LIMIT %s
    ''', (limit,))
    
    users = cursor.fetchall()
    conn.close()
    
    return users

def get_all_subscribers():
    """الحصول على قائمة جميع المشتركين"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, username, first_name, subscription_end, payment_method
        FROM users
        WHERE is_subscribed = 1
        ORDER BY subscription_end DESC
    ''')
    
    results = cursor.fetchall()
    conn.close()
    
    return results

# ═══════════════════════════════════════════════════════════════
# دوال الإعدادات
# ═══════════════════════════════════════════════════════════════

def get_setting(key: str, default: str = None) -> str:
    """الحصول على قيمة إعداد"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT value FROM settings WHERE key = %s', (key,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else default

def set_setting(key: str, value: str):
    """تحديث قيمة إعداد"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO settings (key, value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    ''', (key, value))
    
    conn.commit()
    conn.close()
    logger.info(f"✅ تم تحديث الإعداد {key} = {value}")

def get_max_duration() -> int:
    """الحصول على الحد الأقصى لمدة الفيديو (بالدقائق)"""
    return int(get_setting('max_duration_minutes', '60'))

def set_max_duration(minutes: int):
    """تحديد الحد الأقصى لمدة الفيديو (بالدقائق)"""
    set_setting('max_duration_minutes', str(minutes))

# ═══════════════════════════════════════════════════════════════
# دوال الدفوعات
# ═══════════════════════════════════════════════════════════════

def add_payment(user_id: int, payment_method: str, proof_file_id: str = None, 
                proof_message_id: int = None, amount: float = None):
    """إضافة دفعة جديدة معلقة"""
    if amount is None:
        amount = float(get_setting('subscription_price', '10'))
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO payments (user_id, amount, payment_method, proof_file_id, proof_message_id)
        VALUES (%s, %s, %s, %s, %s)
    ''', (user_id, amount, payment_method, proof_file_id, proof_message_id))
    
    payment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    logger.info(f"💰 دفعة جديدة #{payment_id} من المستخدم {user_id} عبر {payment_method}")
    return payment_id

def approve_payment(payment_id: int, admin_id: int):
    """قبول الدفعة وتفعيل الاشتراك"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # الحصول على معلومات الدفعة
    cursor.execute('''
        SELECT user_id, payment_method, status
        FROM payments
        WHERE payment_id = %s
    ''', (payment_id,))
    
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return False, "الدفعة غير موجودة"
    
    user_id, payment_method, status = result
    
    if status == 'approved':
        conn.close()
        return False, "تم قبول هذه الدفعة مسبقاً"
    
    # تحديث حالة الدفعة
    cursor.execute('''
        UPDATE payments
        SET status = 'approved',
            approved_at = %s,
            approved_by = %s
        WHERE payment_id = %s
    ''', (datetime.now().isoformat(), admin_id, payment_id))
    
    conn.commit()
    conn.close()
    
    # تفعيل الاشتراك
    activate_subscription(user_id, payment_method)
    
    logger.info(f"✅ تم قبول الدفعة #{payment_id} للمستخدم {user_id}")
    return True, "تم تفعيل الاشتراك بنجاح"

def reject_payment(payment_id: int):
    """رفض الدفعة"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE payments
        SET status = 'rejected'
        WHERE payment_id = %s
    ''', (payment_id,))
    
    conn.commit()
    conn.close()
    
    logger.info(f"❌ تم رفض الدفعة #{payment_id}")

def get_pending_payments():
    """الحصول على قائمة الدفوعات المعلقة"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT p.payment_id, p.user_id, u.username, u.first_name,
               p.payment_method, p.amount, p.proof_file_id, p.created_at
        FROM payments p
        LEFT JOIN users u ON p.user_id = u.user_id
        WHERE p.status = 'pending'
        ORDER BY p.created_at DESC
    ''')
    
    results = cursor.fetchall()
    conn.close()
    
    return results

def get_payment_by_id(payment_id: int):
    """الحصول على معلومات دفعة محددة"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT p.payment_id, p.user_id, u.username, u.first_name,
               p.payment_method, p.amount, p.proof_file_id, p.status, p.created_at
        FROM payments p
        LEFT JOIN users u ON p.user_id = u.user_id
        WHERE p.payment_id = %s
    ''', (payment_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result

# ═══════════════════════════════════════════════════════════════
# دوال إضافية للإدارة
# ═══════════════════════════════════════════════════════════════

def get_user_stats():
    """الحصول على إحصائيات المستخدمين"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # إجمالي المستخدمين
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    # المشتركون
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_subscribed = 1')
    subscribed_users = cursor.fetchone()[0]
    
    # العاديون
    free_users = total_users - subscribed_users
    
    conn.close()
    
    return {
        'total': total_users,
        'subscribed': subscribed_users,
        'free': free_users
    }

def get_all_users():
    """الحصول على قائمة جميع المستخدمين"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, username, first_name, is_subscribed, subscription_end
        FROM users
        ORDER BY created_at DESC
    ''')
    
    results = cursor.fetchall()
    conn.close()
    
    return results

def find_user_by_id(user_id: int):
    """البحث عن مستخدم بواسطة ID"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, username, first_name, is_subscribed, subscription_end
        FROM users
        WHERE user_id = %s
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result

def find_user_by_username(username: str):
    """البحث عن مستخدم بواسطة Username"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # إزالة @ إذا كانت موجودة
    username = username.lstrip('@')
    
    cursor.execute('''
        SELECT user_id, username, first_name, is_subscribed, subscription_end
        FROM users
        WHERE username = %s
    ''', (username,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result

def get_days_remaining(user_id: int):
    """الحصول على الأيام المتبقية للاشتراك"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT subscription_end
        FROM users
        WHERE user_id = %s AND is_subscribed = 1
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result or not result[0]:
        return None
    
    # PostgreSQL يُرجع datetime object مباشرة، بينما SQLite يُرجع string
    end_date_value = result[0]
    if isinstance(end_date_value, str):
        end_date = datetime.fromisoformat(end_date_value)
    else:
        end_date = end_date_value
    
    days_left = (end_date - datetime.now()).days
    
    return max(0, days_left)

def get_time_remaining(user_id: int):
    """الحصول على الوقت المتبقي للاشتراك (أيام وساعات)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT subscription_end
        FROM users
        WHERE user_id = %s AND is_subscribed = 1
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result or not result[0]:
        return None
    
    # PostgreSQL يُرجع datetime object مباشرة، بينما SQLite يُرجع string
    end_date_value = result[0]
    if isinstance(end_date_value, str):
        end_date = datetime.fromisoformat(end_date_value)
    else:
        end_date = end_date_value
    
    time_delta = end_date - datetime.now()
    
    # حساب الأيام والساعات المتبقية
    days = time_delta.days
    hours = time_delta.seconds // 3600
    
    return {
        'end_date': end_date,
        'days': max(0, days),
        'hours': max(0, hours),
        'end_date_formatted': end_date.strftime('%Y-%m-%d %H:%M:%S')
    }


# ═══════════════════════════════════════════════════════════════
# دوال الحد اليومي للتحميلات
# ═══════════════════════════════════════════════════════════════

def check_daily_limit(user_id: int):
    """التحقق من الحد اليومي للتحميلات للمستخدم"""
    conn = get_connection()
    cursor = conn.cursor()
    
    today = datetime.now().date().isoformat()
    
    cursor.execute('''
        SELECT download_count
        FROM daily_downloads
        WHERE user_id = %s AND download_date = %s
    ''', (user_id, today))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return 0
    
    return result[0]

def increment_download_count(user_id: int):
    """زيادة عداد التحميلات اليومية للمستخدم"""
    conn = get_connection()
    cursor = conn.cursor()
    
    today = datetime.now().date().isoformat()
    
    cursor.execute('''
        INSERT INTO daily_downloads (user_id, download_date, download_count)
        VALUES (%s, %s, 1)
        ON CONFLICT(user_id, download_date) 
        DO UPDATE SET download_count = daily_downloads.download_count + 1
    ''', (user_id, today))
    
    conn.commit()
    conn.close()

def get_daily_limit():
    """الحصول على الحد اليومي للتحميلات"""
    return int(get_setting('daily_download_limit', '6'))

def set_daily_limit(limit: int):
    """تحديد الحد اليومي للتحميلات"""
    set_setting('daily_download_limit', str(limit))


# ═══════════════════════════════════════════════════════════════
# دوال اللغة - Language Functions
# ═══════════════════════════════════════════════════════════════

def get_user_language(user_id: int):
    """الحصول على لغة المستخدم"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT language
        FROM users
        WHERE user_id = %s
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0]:
        return result[0]
    
    return 'ar'  # Default to Arabic

def set_user_language(user_id: int, language: str):
    """تحديد لغة المستخدم"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO users (user_id, language)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET language = excluded.language
    ''', (user_id, language))
    
    conn.commit()
    conn.close()



