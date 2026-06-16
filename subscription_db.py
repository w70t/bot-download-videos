"""
نظام قاعدة البيانات للاشتراكات
==================================
إدارة المشتركين والدفوعات والإعدادات
PostgreSQL Database System
"""

import psycopg2
from psycopg2 import pool as pg_pool
from datetime import datetime, timedelta
from contextlib import contextmanager
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

# مجمّع اتصالات (Connection Pool) لإعادة استخدام الاتصالات بدل فتح/إغلاق
# اتصال جديد في كل استدعاء (تحسين أداء + تفادي استنزاف اتصالات PostgreSQL).
_POOL_MIN = int(os.getenv('POSTGRES_POOL_MIN', '1'))
_POOL_MAX = int(os.getenv('POSTGRES_POOL_MAX', '10'))
_connection_pool = None


def _get_pool():
    """ينشئ مجمّع الاتصالات عند أول استخدام (lazy) ويعيده."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pg_pool.ThreadedConnectionPool(
            _POOL_MIN, _POOL_MAX, **POSTGRES_CONFIG
        )
        logger.info("✅ تم إنشاء مجمّع اتصالات PostgreSQL (min=%d, max=%d)",
                    _POOL_MIN, _POOL_MAX)
    return _connection_pool


@contextmanager
def db_cursor(commit: bool = False):
    """مدير سياق يوفّر cursor من المجمّع ويضمن إرجاع الاتصال وإغلاق المؤشر
    دائماً (حتى عند حدوث خطأ)، مع commit/rollback تلقائي.

    Args:
        commit: نفّذ commit عند الخروج بنجاح (لعمليات الكتابة).
    """
    pool = _get_pool()
    conn = pool.getconn()
    cursor = None
    try:
        cursor = conn.cursor()
        yield cursor
        if commit:
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        pool.putconn(conn)


def init_db():
    """إنشاء قاعدة البيانات والجداول - PostgreSQL version"""
    # الجداول تُنشأ من setup_postgres.py؛ هنا نضمن وجود الجداول الإضافية
    _ensure_forced_channels_table()
    _ensure_fsub_passed_table()
    _ensure_media_cache_table()
    _ensure_history_table()
    _ensure_referrals_table()
    _ensure_bonus_column()
    _ensure_moderation_table()
    logger.info("✅ تم تجهيز قاعدة البيانات بنجاح")


def get_connection():
    """الحصول على اتصال خام بقاعدة البيانات (للتوافق مع أي كود قديم).
    يُفضّل استخدام db_cursor() بدلاً منه. على المستدعي إغلاق الاتصال."""
    return psycopg2.connect(**POSTGRES_CONFIG)

# ═══════════════════════════════════════════════════════════════
# دوال المستخدمين والاشتراكات
# ═══════════════════════════════════════════════════════════════

def is_user_subscribed(user_id: int) -> bool:
    """التحقق من اشتراك المستخدم"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT is_subscribed, subscription_end
            FROM users
            WHERE user_id = %s
        ''', (user_id,))
        result = cursor.fetchone()

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
    # استخدام INSERT ON CONFLICT للحفاظ على بيانات الاشتراك
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        ''', (user_id, username, first_name))

def activate_subscription(user_id: int, duration_days: int = 30, payment_method: str = 'manual'):
    """تفعيل اشتراك المستخدم"""
    end_date = datetime.now() + timedelta(days=duration_days)

    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            UPDATE users
            SET is_subscribed = 1, subscription_end = %s, payment_method = %s
            WHERE user_id = %s
        ''', (end_date.isoformat(), payment_method, user_id))
    logger.info(f"✅ تم تفعيل اشتراك المستخدم {user_id} حتى {end_date}")

def deactivate_subscription(user_id: int):
    """إلغاء اشتراك المستخدم (إلغاء الترقية)"""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            UPDATE users
            SET is_subscribed = 0, subscription_end = NULL, payment_method = NULL
            WHERE user_id = %s
        ''', (user_id,))
    logger.info(f"❌ تم إلغاء اشتراك المستخدم {user_id}")

def delete_user(user_id: int):
    """حذف مستخدم نهائياً من قاعدة البيانات (عند حظره البوت أو حذف حسابه)"""
    with db_cursor(commit=True) as cursor:
        cursor.execute('DELETE FROM users WHERE user_id = %s', (user_id,))
    logger.info(f"🗑️ تم حذف المستخدم {user_id} من قاعدة البيانات")

def get_recent_users(limit: int = 50):
    """الحصول على آخر المستخدمين"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT user_id, username, first_name, is_subscribed
            FROM users
            ORDER BY user_id DESC
            LIMIT %s
        ''', (limit,))
        return cursor.fetchall()

def get_all_subscribers():
    """الحصول على قائمة جميع المشتركين"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT user_id, username, first_name, subscription_end, payment_method
            FROM users
            WHERE is_subscribed = 1
            ORDER BY subscription_end DESC
        ''')
        return cursor.fetchall()

# ═══════════════════════════════════════════════════════════════
# دوال الإعدادات
# ═══════════════════════════════════════════════════════════════

def get_setting(key: str, default: str = None) -> str:
    """الحصول على قيمة إعداد"""
    with db_cursor() as cursor:
        cursor.execute('SELECT value FROM settings WHERE key = %s', (key,))
        result = cursor.fetchone()
    return result[0] if result else default

def set_setting(key: str, value: str):
    """تحديث قيمة إعداد"""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO settings (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        ''', (key, value))
    logger.info(f"✅ تم تحديث الإعداد {key} = {value}")

def get_max_duration() -> int:
    """الحصول على الحد الأقصى لمدة الفيديو (بالدقائق)"""
    return int(get_setting('max_duration_minutes', '60'))

def set_max_duration(minutes: int):
    """تحديد الحد الأقصى لمدة الفيديو (بالدقائق)"""
    set_setting('max_duration_minutes', str(minutes))

# ═══════════════════════════════════════════════════════════════
# دوال الاشتراك الإجباري بالقنوات
# ═══════════════════════════════════════════════════════════════

def _ensure_forced_channels_table():
    """ينشئ جدول قنوات الاشتراك الإجباري إن لم يكن موجوداً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS forced_channels (
                id SERIAL PRIMARY KEY,
                chat_id TEXT NOT NULL UNIQUE,
                username TEXT,
                title TEXT,
                url TEXT,
                added_at TIMESTAMP DEFAULT NOW()
            )
        ''')

def add_forced_channel(chat_id, username, title, url) -> bool:
    """إضافة قناة اشتراك إجباري. يرجع False إذا كانت موجودة مسبقاً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('SELECT id FROM forced_channels WHERE chat_id = %s', (str(chat_id),))
        if cursor.fetchone():
            return False
        cursor.execute('''
            INSERT INTO forced_channels (chat_id, username, title, url)
            VALUES (%s, %s, %s, %s)
        ''', (str(chat_id), username, title, url))
    logger.info(f"✅ تمت إضافة قناة اشتراك إجباري: {title or username or chat_id}")
    return True

def get_forced_channels():
    """قائمة قنوات الاشتراك الإجباري: (id, chat_id, username, title, url)."""
    with db_cursor() as cursor:
        cursor.execute('SELECT id, chat_id, username, title, url FROM forced_channels ORDER BY id')
        return cursor.fetchall()

def remove_forced_channel(row_id) -> bool:
    """حذف قناة اشتراك إجباري حسب المعرّف الداخلي."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('DELETE FROM forced_channels WHERE id = %s', (row_id,))
        deleted = cursor.rowcount
    return deleted > 0

def _ensure_fsub_passed_table():
    """جدول إقرار المستخدمين بالقنوات غير القابلة للتحقق (البوت ليس مشرفاً)."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fsub_user_passed (
                user_id BIGINT NOT NULL,
                chat_id TEXT NOT NULL,
                PRIMARY KEY (user_id, chat_id)
            )
        ''')

def get_user_passed_channels(user_id: int):
    """مجموعة معرّفات القنوات التي أقرّ بها المستخدم (chat_id كنصوص)."""
    with db_cursor() as cursor:
        cursor.execute('SELECT chat_id FROM fsub_user_passed WHERE user_id = %s', (user_id,))
        rows = cursor.fetchall()
    return {str(r[0]) for r in rows}

def mark_user_passed_channel(user_id: int, chat_id):
    """تسجيل إقرار المستخدم باشتراكه في قناة غير قابلة للتحقق."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO fsub_user_passed (user_id, chat_id)
            VALUES (%s, %s) ON CONFLICT DO NOTHING
        ''', (user_id, str(chat_id)))

# ═══════════════════════════════════════════════════════════════
# دوال الدفوعات
# ═══════════════════════════════════════════════════════════════

def add_payment(user_id: int, payment_method: str, proof_file_id: str = None,
                proof_message_id: int = None, amount: float = None):
    """إضافة دفعة جديدة معلقة"""
    if amount is None:
        amount = float(get_setting('subscription_price', '10'))

    # PostgreSQL لا يدعم cursor.lastrowid؛ نستخدم RETURNING للحصول على المعرّف
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO payments (user_id, amount, payment_method, proof_file_id, proof_message_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING payment_id
        ''', (user_id, amount, payment_method, proof_file_id, proof_message_id))
        row = cursor.fetchone()
        payment_id = row[0] if row else None

    logger.info(f"💰 دفعة جديدة #{payment_id} من المستخدم {user_id} عبر {payment_method}")
    return payment_id

def approve_payment(payment_id: int, admin_id: int):
    """قبول الدفعة وتفعيل الاشتراك (في معاملة واحدة لضمان الذرّية)"""
    duration_days = int(get_setting('subscription_duration_days', '30'))

    with db_cursor(commit=True) as cursor:
        # الحصول على معلومات الدفعة
        cursor.execute('''
            SELECT user_id, payment_method, status
            FROM payments
            WHERE payment_id = %s
        ''', (payment_id,))
        result = cursor.fetchone()

        if not result:
            return False, "الدفعة غير موجودة"

        user_id, payment_method, status = result

        if status == 'approved':
            return False, "تم قبول هذه الدفعة مسبقاً"

        # تحديث حالة الدفعة
        cursor.execute('''
            UPDATE payments
            SET status = 'approved',
                approved_at = %s,
                approved_by = %s
            WHERE payment_id = %s
        ''', (datetime.now().isoformat(), admin_id, payment_id))

        # تفعيل الاشتراك ضمن نفس المعاملة
        end_date = datetime.now() + timedelta(days=duration_days)
        cursor.execute('''
            UPDATE users
            SET is_subscribed = 1, subscription_end = %s, payment_method = %s
            WHERE user_id = %s
        ''', (end_date.isoformat(), payment_method, user_id))

    logger.info(f"✅ تم قبول الدفعة #{payment_id} للمستخدم {user_id} وتفعيل الاشتراك حتى {end_date}")
    return True, "تم تفعيل الاشتراك بنجاح"

def reject_payment(payment_id: int):
    """رفض الدفعة"""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            UPDATE payments
            SET status = 'rejected'
            WHERE payment_id = %s
        ''', (payment_id,))
    logger.info(f"❌ تم رفض الدفعة #{payment_id}")

def get_pending_payments():
    """الحصول على قائمة الدفوعات المعلقة"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT p.payment_id, p.user_id, u.username, u.first_name,
                   p.payment_method, p.amount, p.proof_file_id, p.created_at
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at DESC
        ''')
        return cursor.fetchall()

def get_payment_by_id(payment_id: int):
    """الحصول على معلومات دفعة محددة"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT p.payment_id, p.user_id, u.username, u.first_name,
                   p.payment_method, p.amount, p.proof_file_id, p.status, p.created_at
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            WHERE p.payment_id = %s
        ''', (payment_id,))
        return cursor.fetchone()

# ═══════════════════════════════════════════════════════════════
# دوال إضافية للإدارة
# ═══════════════════════════════════════════════════════════════

def get_user_stats():
    """الحصول على إحصائيات المستخدمين"""
    with db_cursor() as cursor:
        # إجمالي المستخدمين
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]

        # المشتركون
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_subscribed = 1')
        subscribed_users = cursor.fetchone()[0]

    # العاديون
    free_users = total_users - subscribed_users

    return {
        'total': total_users,
        'subscribed': subscribed_users,
        'free': free_users
    }

def get_all_users():
    """الحصول على قائمة جميع المستخدمين"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT user_id, username, first_name, is_subscribed, subscription_end
            FROM users
            ORDER BY created_at DESC
        ''')
        return cursor.fetchall()

def find_user_by_id(user_id: int):
    """البحث عن مستخدم بواسطة ID"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT user_id, username, first_name, is_subscribed, subscription_end
            FROM users
            WHERE user_id = %s
        ''', (user_id,))
        return cursor.fetchone()

def find_user_by_username(username: str):
    """البحث عن مستخدم بواسطة Username"""
    # إزالة @ إذا كانت موجودة
    username = username.lstrip('@')

    with db_cursor() as cursor:
        cursor.execute('''
            SELECT user_id, username, first_name, is_subscribed, subscription_end
            FROM users
            WHERE username = %s
        ''', (username,))
        return cursor.fetchone()

def get_days_remaining(user_id: int):
    """الحصول على الأيام المتبقية للاشتراك"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT subscription_end
            FROM users
            WHERE user_id = %s AND is_subscribed = 1
        ''', (user_id,))
        result = cursor.fetchone()

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
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT subscription_end
            FROM users
            WHERE user_id = %s AND is_subscribed = 1
        ''', (user_id,))
        result = cursor.fetchone()

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
    today = datetime.now().date().isoformat()

    with db_cursor() as cursor:
        cursor.execute('''
            SELECT download_count
            FROM daily_downloads
            WHERE user_id = %s AND download_date = %s
        ''', (user_id, today))
        result = cursor.fetchone()

    if not result:
        return 0

    return result[0]

def increment_download_count(user_id: int):
    """زيادة عداد التحميلات اليومية للمستخدم"""
    today = datetime.now().date().isoformat()

    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO daily_downloads (user_id, download_date, download_count)
            VALUES (%s, %s, 1)
            ON CONFLICT(user_id, download_date)
            DO UPDATE SET download_count = daily_downloads.download_count + 1
        ''', (user_id, today))

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
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT language
            FROM users
            WHERE user_id = %s
        ''', (user_id,))
        result = cursor.fetchone()

    if result and result[0]:
        return result[0]

    return 'ar'  # Default to Arabic

def set_user_language(user_id: int, language: str):
    """تحديد لغة المستخدم"""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO users (user_id, language)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET language = excluded.language
        ''', (user_id, language))


# ═══════════════════════════════════════════════════════════════
# كاش الوسائط - Media cache (إعادة الإرسال الفوري عبر file_id)
# الفيديو لا يُخزَّن في قاعدة البيانات؛ نخزّن فقط معرّف الملف (file_id) من
# تيليجرام مربوطاً بالرابط (بعد التطبيع) والجودة، فيُعاد إرساله فوراً بلا تحميل.
# ═══════════════════════════════════════════════════════════════

def _ensure_media_cache_table():
    """ينشئ جدول كاش الوسائط إن لم يكن موجوداً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS media_cache (
                url_key TEXT NOT NULL,
                quality TEXT NOT NULL,
                kind TEXT NOT NULL,
                file_id TEXT NOT NULL,
                title TEXT,
                file_size_mb REAL,
                duration INTEGER,
                width INTEGER,
                height INTEGER,
                storage_chat_id BIGINT,
                storage_msg_id BIGINT,
                hits INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (url_key, quality)
            )
        ''')


def get_cached_media(url_key: str, quality: str):
    """يرجع صف الكاش (كقاموس) إن وُجد، وإلا None."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT kind, file_id, title, file_size_mb, duration, width, height,
                   storage_chat_id, storage_msg_id
            FROM media_cache
            WHERE url_key = %s AND quality = %s
        ''', (url_key, quality))
        row = cursor.fetchone()
    if not row:
        return None
    keys = ['kind', 'file_id', 'title', 'file_size_mb', 'duration', 'width',
            'height', 'storage_chat_id', 'storage_msg_id']
    return dict(zip(keys, row))


def save_cached_media(url_key: str, quality: str, kind: str, file_id: str,
                      title: str = None, file_size_mb: float = None,
                      duration: int = None, width: int = None, height: int = None,
                      storage_chat_id: int = None, storage_msg_id: int = None):
    """يحفظ/يحدّث معرّف ملف في الكاش."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO media_cache
                (url_key, quality, kind, file_id, title, file_size_mb, duration,
                 width, height, storage_chat_id, storage_msg_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url_key, quality) DO UPDATE SET
                kind = EXCLUDED.kind,
                file_id = EXCLUDED.file_id,
                title = EXCLUDED.title,
                file_size_mb = EXCLUDED.file_size_mb,
                duration = EXCLUDED.duration,
                width = EXCLUDED.width,
                height = EXCLUDED.height,
                storage_chat_id = EXCLUDED.storage_chat_id,
                storage_msg_id = EXCLUDED.storage_msg_id,
                created_at = NOW()
        ''', (url_key, quality, kind, file_id, title, file_size_mb, duration,
              width, height, storage_chat_id, storage_msg_id))


def bump_cache_hit(url_key: str, quality: str):
    """يزيد عداد الاستخدام لإحصاء استفادة الكاش."""
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            'UPDATE media_cache SET hits = hits + 1 WHERE url_key = %s AND quality = %s',
            (url_key, quality)
        )


def delete_cached_media(url_key: str, quality: str):
    """يحذف صف كاش (يُستخدم عند فشل المعرّف القديم)."""
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            'DELETE FROM media_cache WHERE url_key = %s AND quality = %s',
            (url_key, quality)
        )


def get_cache_stats():
    """إحصائيات الكاش: عدد العناصر وإجمالي مرات الاستفادة."""
    with db_cursor() as cursor:
        cursor.execute('SELECT COUNT(*), COALESCE(SUM(hits), 0) FROM media_cache')
        row = cursor.fetchone()
    return {'items': row[0] if row else 0, 'hits': row[1] if row else 0}


# ═══════════════════════════════════════════════════════════════
# سجل التحميلات والإحصائيات - Download history & statistics
# ═══════════════════════════════════════════════════════════════

def _ensure_history_table():
    """ينشئ جدول سجل التحميلات إن لم يكن موجوداً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS download_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                url TEXT,
                title TEXT,
                quality TEXT,
                kind TEXT,
                platform TEXT,
                file_size_mb REAL,
                from_cache BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_user ON download_history(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_date ON download_history(created_at)')


def add_download_history(user_id, url, title, quality, kind, platform,
                         file_size_mb=None, from_cache=False):
    """يسجّل عملية تحميل ناجحة في السجل."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO download_history
                (user_id, url, title, quality, kind, platform, file_size_mb, from_cache)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, url, title, quality, kind, platform, file_size_mb, from_cache))


def get_user_history(user_id, limit=10):
    """آخر تحميلات المستخدم: (id, title, quality, kind, created_at, url)."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT id, title, quality, kind, created_at, url
            FROM download_history
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT %s
        ''', (user_id, limit))
        return cursor.fetchall()


def get_history_item(history_id, user_id):
    """يرجع عنصر سجل واحد يملكه المستخدم (للتأكد من الملكية قبل إعادة الإرسال)."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT url, quality, kind, title
            FROM download_history
            WHERE id = %s AND user_id = %s
        ''', (history_id, user_id))
        row = cursor.fetchone()
    if not row:
        return None
    return {'url': row[0], 'quality': row[1], 'kind': row[2], 'title': row[3]}


def get_download_stats():
    """إحصائيات شاملة للأدمن: عدد اليوم، الإجمالي، أكثر المنصات، أنشط المستخدمين."""
    today = datetime.now().date().isoformat()
    with db_cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM download_history')
        total = cursor.fetchone()[0]

        cursor.execute(
            'SELECT COUNT(*) FROM download_history WHERE created_at::date = %s',
            (today,)
        )
        today_count = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COALESCE(platform, 'غير معروف') AS p, COUNT(*) AS c
            FROM download_history
            GROUP BY p ORDER BY c DESC LIMIT 5
        ''')
        platforms = cursor.fetchall()

        cursor.execute('''
            SELECT h.user_id, u.first_name, COUNT(*) AS c
            FROM download_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            GROUP BY h.user_id, u.first_name
            ORDER BY c DESC LIMIT 5
        ''')
        top_users = cursor.fetchall()

    return {
        'today': today_count,
        'total': total,
        'platforms': platforms,
        'top_users': top_users,
    }


# ═══════════════════════════════════════════════════════════════
# نظام الدعوات والرصيد الإضافي - Referrals & bonus downloads
# ═══════════════════════════════════════════════════════════════

def _ensure_referrals_table():
    """ينشئ جدول الدعوات إن لم يكن موجوداً (كل مستخدم يُدعى مرة واحدة)."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                referred_user_id BIGINT PRIMARY KEY,
                referrer_user_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')


def _ensure_bonus_column():
    """يضيف عمود الرصيد الإضافي لجدول المستخدمين إن لم يكن موجوداً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_downloads INTEGER DEFAULT 0'
        )


def record_referral(referred_user_id, referrer_user_id) -> bool:
    """يسجّل دعوة جديدة. يرجع True إذا كانت دعوة جديدة فعلاً (تُمنح المكافأة مرة)."""
    if int(referred_user_id) == int(referrer_user_id):
        return False  # لا يدعو المستخدم نفسه
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO referrals (referred_user_id, referrer_user_id)
            VALUES (%s, %s)
            ON CONFLICT (referred_user_id) DO NOTHING
            RETURNING referred_user_id
        ''', (referred_user_id, referrer_user_id))
        inserted = cursor.fetchone() is not None
    return inserted


def get_referral_count(referrer_user_id) -> int:
    """عدد المستخدمين الذين انضموا عبر رابط هذا المستخدم."""
    with db_cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM referrals WHERE referrer_user_id = %s',
            (referrer_user_id,)
        )
        return cursor.fetchone()[0]


def add_bonus_downloads(user_id, amount):
    """يضيف رصيد تحميلات إضافي للمستخدم (يضمن وجود الصف)."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO users (user_id, bonus_downloads)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                bonus_downloads = COALESCE(users.bonus_downloads, 0) + %s
        ''', (user_id, amount, amount))


def get_bonus_downloads(user_id) -> int:
    """رصيد التحميلات الإضافية للمستخدم."""
    with db_cursor() as cursor:
        cursor.execute('SELECT COALESCE(bonus_downloads, 0) FROM users WHERE user_id = %s',
                       (user_id,))
        row = cursor.fetchone()
    return row[0] if row else 0


def consume_bonus_download(user_id) -> bool:
    """يستهلك تحميلاً واحداً من الرصيد الإضافي إن وُجد. يرجع True عند النجاح."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            UPDATE users SET bonus_downloads = bonus_downloads - 1
            WHERE user_id = %s AND COALESCE(bonus_downloads, 0) > 0
            RETURNING bonus_downloads
        ''', (user_id,))
        row = cursor.fetchone()
    return row is not None


# ═══════════════════════════════════════════════════════════════
# نظام العقوبات والحظر - Moderation / bans
# ═══════════════════════════════════════════════════════════════

def _ensure_moderation_table():
    """ينشئ جدول العقوبات إن لم يكن موجوداً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS moderation (
                user_id BIGINT PRIMARY KEY,
                banned BOOLEAN DEFAULT FALSE,
                reason TEXT,
                strikes INTEGER DEFAULT 0,
                pledged BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        ''')


def ban_user(user_id, reason: str) -> int:
    """يحظر المستخدم (يزيد عدّاد المخالفات). يرجع عدد المخالفات بعد الحظر."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO moderation (user_id, banned, reason, strikes)
            VALUES (%s, TRUE, %s, 1)
            ON CONFLICT (user_id) DO UPDATE SET
                banned = TRUE,
                reason = EXCLUDED.reason,
                strikes = moderation.strikes + 1,
                updated_at = NOW()
            RETURNING strikes
        ''', (user_id, reason))
        row = cursor.fetchone()
    return row[0] if row else 1


def is_user_banned(user_id) -> bool:
    """هل المستخدم محظور حالياً؟"""
    with db_cursor() as cursor:
        cursor.execute('SELECT banned FROM moderation WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
    return bool(row and row[0])


def get_ban_info(user_id):
    """معلومات الحظر: (banned, reason, strikes, pledged) أو None."""
    with db_cursor() as cursor:
        cursor.execute(
            'SELECT banned, reason, strikes, pledged FROM moderation WHERE user_id = %s',
            (user_id,))
        row = cursor.fetchone()
    if not row:
        return None
    return {'banned': row[0], 'reason': row[1], 'strikes': row[2], 'pledged': row[3]}


def pledge_unban(user_id) -> bool:
    """رفع الحظر عبر التعهّد (يُسمح به مرة واحدة فقط). يرجع True عند القبول."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            UPDATE moderation SET banned = FALSE, pledged = TRUE, updated_at = NOW()
            WHERE user_id = %s AND banned = TRUE AND pledged = FALSE
            RETURNING user_id
        ''', (user_id,))
        row = cursor.fetchone()
    return row is not None


def admin_unban(user_id) -> bool:
    """رفع الحظر من الأدمن (يبقي سجل المخالفات). يرجع True إن كان محظوراً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            UPDATE moderation SET banned = FALSE, updated_at = NOW()
            WHERE user_id = %s AND banned = TRUE
            RETURNING user_id
        ''', (user_id,))
        row = cursor.fetchone()
    return row is not None


def admin_ban(user_id, reason: str, permanent: bool = False):
    """حظر من الأدمن. permanent=True يجعله دائماً (لا يُرفع بالتعهّد، الأدمن فقط).
    permanent=False = حظر تحذيري يستطيع المستخدم رفعه بالتعهّد مرة واحدة."""
    pledged = bool(permanent)  # دائم → نعتبره "تعهّد مستهلك" فلا يُرفع بالتعهّد
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO moderation (user_id, banned, reason, strikes, pledged)
            VALUES (%s, TRUE, %s, 1, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                banned = TRUE,
                reason = EXCLUDED.reason,
                strikes = moderation.strikes + 1,
                pledged = EXCLUDED.pledged,
                updated_at = NOW()
        ''', (user_id, reason, pledged))


def get_banned_users():
    """قائمة المحظورين حالياً: (user_id, reason, strikes)."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT user_id, reason, strikes FROM moderation
            WHERE banned = TRUE ORDER BY updated_at DESC
        ''')
        return cursor.fetchall()
