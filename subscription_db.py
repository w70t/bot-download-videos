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
import threading
import time
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
    _ensure_member_activity_schema()
    _ensure_referrals_table()
    _ensure_bonus_column()
    _ensure_total_downloads_column()
    _ensure_moderation_table()
    _ensure_survey_table()
    _ensure_questions_tables()
    _ensure_reminder_column()
    _ensure_payments_columns()
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


try:
    _ACTIVITY_TOUCH_SECONDS = max(
        30, int(os.getenv('MEMBER_ACTIVITY_TOUCH_SECONDS', '300'))
    )
except (TypeError, ValueError):
    _ACTIVITY_TOUCH_SECONDS = 300
_ACTIVITY_TOUCH_CACHE_MAX = 4096
_activity_touch_cache = {}
_activity_touch_lock = threading.Lock()


def add_or_update_user(user_id: int, username: str = None, first_name: str = None):
    """إضافة أو تحديث معلومات المستخدم"""
    # استخدام INSERT ON CONFLICT للحفاظ على بيانات الاشتراك
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_activity_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_activity_at = excluded.last_activity_at
        ''', (user_id, username, first_name))
    try:
        cache_user_id = int(user_id)
    except (TypeError, ValueError):
        cache_user_id = user_id
    with _activity_touch_lock:
        if (cache_user_id not in _activity_touch_cache
                and len(_activity_touch_cache) >= _ACTIVITY_TOUCH_CACHE_MAX):
            oldest_id = min(_activity_touch_cache,
                            key=_activity_touch_cache.get)
            _activity_touch_cache.pop(oldest_id, None)
        _activity_touch_cache[cache_user_id] = time.monotonic()


def touch_user_activity(user_id: int, minimum_interval=None) -> bool:
    """Refresh an existing member's activity timestamp with bounded writes.

    Telegram can emit several updates for one interaction.  The process-local
    debounce limits PostgreSQL to one write per member per configurable window
    (five minutes by default) while keeping the dashboard's day/week/month
    figures truthful.  This deliberately uses ``UPDATE`` rather than an upsert:
    a raw ``/start`` from a
    new member must not pre-empt the existing referral/language registration
    flow.

    Returns ``True`` only when a database row was refreshed.
    """
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return False
    interval = _ACTIVITY_TOUCH_SECONDS if minimum_interval is None else max(
        0, float(minimum_interval)
    )
    now = time.monotonic()
    with _activity_touch_lock:
        previous = _activity_touch_cache.get(user_id)
        if previous is not None and now - previous < interval:
            return False
        if (user_id not in _activity_touch_cache
                and len(_activity_touch_cache) >= _ACTIVITY_TOUCH_CACHE_MAX):
            stale_before = now - max(interval, _ACTIVITY_TOUCH_SECONDS)
            stale_ids = [cached_id for cached_id, touched_at
                         in _activity_touch_cache.items()
                         if touched_at < stale_before]
            for cached_id in stale_ids:
                _activity_touch_cache.pop(cached_id, None)
            if len(_activity_touch_cache) >= _ACTIVITY_TOUCH_CACHE_MAX:
                oldest_id = min(
                    _activity_touch_cache,
                    key=_activity_touch_cache.get,
                )
                _activity_touch_cache.pop(oldest_id, None)
        _activity_touch_cache[user_id] = now
    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(
                'UPDATE users SET last_activity_at = NOW() WHERE user_id = %s',
                (user_id,),
            )
            refreshed = cursor.rowcount != 0
    except Exception:
        # A transient database failure must be retried on the next interaction.
        with _activity_touch_lock:
            if _activity_touch_cache.get(user_id) == now:
                _activity_touch_cache.pop(user_id, None)
        raise
    if not refreshed:
        # The language-selection handler may create this new member immediately
        # after the generic activity handler; do not suppress that first touch.
        with _activity_touch_lock:
            if _activity_touch_cache.get(user_id) == now:
                _activity_touch_cache.pop(user_id, None)
    return refreshed

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

_DEPARTURE_REASONS = {'blocked', 'deactivated', 'unreachable'}


def delete_user(user_id: int, departure_reason: str = 'unreachable'):
    """حذف مستخدم نهائياً من قاعدة البيانات (عند حظره البوت أو حذف حسابه).

    يحذف البيانات التشغيلية والخاصة المرتبطة بالعضو، لكنه يُبقي سجلات الحظر
    والمدفوعات والإحالات. تُفصل هوية العضو عن سجل الدفع قبل حذف ملف المستخدم
    حتى يبقى سجل التدقيق من دون كسر قيد PostgreSQL. هذه الدالة تُستدعى أيضاً
    بعد فشل فحص العضو تلقائياً، لذلك لا يجوز أن يمحو خطأ مؤقت سجل إنفاذ أو
    تدقيق أو رصيد إحالات دائم."""
    with db_cursor(commit=True) as cursor:
        # امسح كل البيانات المرتبطة أولاً حتى لا تبقى روابط أو سجلات يتيمة.
        cursor.execute(
            'DELETE FROM member_answers WHERE question_id IN '
            '(SELECT id FROM admin_questions WHERE target_user = %s)',
            (user_id,),
        )
        cursor.execute('DELETE FROM member_answers WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM admin_questions WHERE target_user = %s', (user_id,))
        cursor.execute('DELETE FROM member_survey WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM download_history WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM daily_downloads WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM fsub_user_passed WHERE user_id = %s', (user_id,))
        cursor.execute('UPDATE payments SET user_id = NULL WHERE user_id = %s', (user_id,))
        cursor.execute('DELETE FROM users WHERE user_id = %s', (user_id,))
        deleted = cursor.rowcount > 0
        if deleted:
            # Aggregate-only event: deliberately no Telegram id, name, username,
            # URL or foreign key.  It answers "how many and why" without
            # retaining the departed person's identity.
            reason = (str(departure_reason).strip().lower()
                      if departure_reason is not None else 'unreachable')
            if reason not in _DEPARTURE_REASONS:
                reason = 'unreachable'
            cursor.execute(
                'INSERT INTO member_departures (reason) VALUES (%s)',
                (reason,),
            )
    with _cache_lock:
        _lang_cache.pop(user_id, None)   # لا نُبقِ لغة عضو محذوف في الذاكرة
    with _activity_touch_lock:
        _activity_touch_cache.pop(user_id, None)
    try:
        raw_exempt = get_setting('exempt_user_ids', '') or ''
        exempt_parts = [part.strip() for part in raw_exempt.split(',') if part.strip()]
        filtered_parts = [part for part in exempt_parts if part != str(user_id)]
        if filtered_parts != exempt_parts:
            set_setting('exempt_user_ids', ','.join(filtered_parts))
    except Exception as exc:
        logger.warning("تعذّر حذف المستخدم من قائمة الاستثناء: %s", exc)
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

# ═══════════════════════════════════════════════════════════════
# ذاكرة الإعدادات واللغات
# ‏psycopg2 متزامن، فكل استعلام من معالج async يُجمّد حلقة الأحداث لكل الأعضاء
# طوال رحلته. والإعدادات (الحد اليومي، المدة القصوى، معرّف Binance، مفاتيح
# التشغيل…) يغيّرها الأدمن بضغطة زر مرّة كل حين، ولغة العضو أندر تغيّراً — ومع
# ذلك كانت تُسأل عنها القاعدة عشرات المرات في الرسالة الواحدة.
#
# الصحّة مضمونة بالإبطال لا بالمهلة: كل كتابة (set_setting/set_user_language)
# تمسح مفتاحها فوراً، فلا يرى الأدمن قيمة قديمة بعد ضغط الزر أبداً. المهلة
# شبكة أمان للكتابات من خارج البوت (تعديل يدوي في القاعدة).
# ═══════════════════════════════════════════════════════════════
_SETTINGS_TTL = int(os.getenv('SETTINGS_CACHE_TTL', '60'))
_LANG_TTL = int(os.getenv('LANG_CACHE_TTL', '300'))
_LANG_CACHE_MAX = int(os.getenv('LANG_CACHE_MAX', '2000'))
_settings_cache = {}
_lang_cache = {}
_cache_lock = threading.Lock()


def clear_caches():
    """يفرغ ذاكرتَي الإعدادات واللغات (للاختبارات أو بعد استعادة نسخة)."""
    with _cache_lock:
        _settings_cache.clear()
        _lang_cache.clear()


def get_setting(key: str, default: str = None) -> str:
    """الحصول على قيمة إعداد (مخزَّن مؤقتاً — يُبطَل فوراً عند أي كتابة)."""
    now = time.monotonic()
    with _cache_lock:
        hit = _settings_cache.get(key)
        if hit is not None and now - hit[1] < _SETTINGS_TTL:
            return hit[0] if hit[0] is not None else default
    with db_cursor() as cursor:
        cursor.execute('SELECT value FROM settings WHERE key = %s', (key,))
        result = cursor.fetchone()
    value = result[0] if result else None
    with _cache_lock:
        _settings_cache[key] = (value, now)
    return value if value is not None else default

def set_setting(key: str, value: str):
    """تحديث قيمة إعداد (يُبطل الذاكرة فوراً فيسري التغيير في الحال)"""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO settings (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        ''', (key, value))
    with _cache_lock:
        _settings_cache[key] = (value, time.monotonic())
    logger.info(f"✅ تم تحديث الإعداد {key} = {value}")

def get_max_duration() -> int:
    """الحصول على الحد الأقصى لمدة الفيديو (بالدقائق)"""
    return int(get_setting('max_duration_minutes', '60'))

def set_max_duration(minutes: int):
    """تحديد الحد الأقصى لمدة الفيديو (بالدقائق)"""
    set_setting('max_duration_minutes', str(minutes))

def get_referral_minutes() -> int:
    """عدد الدقائق التي تُضاف لحدّ مدة الفيديو مقابل كل دعوة ناجحة (دائماً).
    القيمة تُدار من لوحة الأدمن؛ الافتراضي يؤخذ من REFERRAL_MINUTES أو 5."""
    return int(get_setting('referral_minutes', os.getenv('REFERRAL_MINUTES', '5')))

def set_referral_minutes(minutes: int):
    """تحديد عدد الدقائق الممنوحة لحدّ المدة مقابل كل دعوة ناجحة."""
    set_setting('referral_minutes', str(minutes))

# ── بوابة الدعوة الإجبارية (Mandatory invite gate) ──
# عند تفعيلها: لكل مستخدم غير مشترك عدد تحميلات مجاني، وبعد استنفاده يجب أن
# يدعو أصدقاءه عبر رابطه لفتح المزيد. لا يُفتح له إلا بانضمام صديق فعلي (يُتحقق
# تلقائياً عبر جدول الدعوات) فلا يمكن الالتفاف على الشرط.

def is_invite_gate_enabled() -> bool:
    """هل بوابة الدعوة الإجبارية مفعّلة؟ (يديرها الأدمن؛ الافتراضي متوقفة)."""
    return get_setting('invite_gate_enabled', '0') == '1'

def set_invite_gate_enabled(enabled: bool):
    """تفعيل/إيقاف بوابة الدعوة الإجبارية."""
    set_setting('invite_gate_enabled', '1' if enabled else '0')

def get_invite_gate_free() -> int:
    """عدد التحميلات المجانية المسموحة قبل أن تُطلب أول دعوة (≥ 0)."""
    try:
        return max(0, int(get_setting('invite_gate_free', '1')))
    except (TypeError, ValueError):
        return 1

def set_invite_gate_free(n: int):
    """تحديد عدد التحميلات المجانية قبل أول دعوة مطلوبة."""
    set_setting('invite_gate_free', str(max(0, int(n))))

def get_invite_gate_per_invite() -> int:
    """عدد التحميلات التي تُفتح مقابل كل دعوة ناجحة (≥ 1)."""
    try:
        return max(1, int(get_setting('invite_gate_per_invite', '1')))
    except (TypeError, ValueError):
        return 1

def set_invite_gate_per_invite(n: int):
    """تحديد عدد التحميلات المُتاحة مقابل كل دعوة ناجحة."""
    set_setting('invite_gate_per_invite', str(max(1, int(n))))

def get_invite_gate_mode() -> str:
    """نمط بوابة الدعوة: 'count' (حسب عدد التحميلات) أو 'period' (حسب الفترة الزمنية)."""
    m = get_setting('invite_gate_mode', 'count')
    return m if m in ('count', 'period') else 'count'

def set_invite_gate_mode(mode: str):
    """تحديد نمط بوابة الدعوة ('count' أو 'period')."""
    set_setting('invite_gate_mode', 'period' if mode == 'period' else 'count')

def get_invite_gate_period_days() -> int:
    """طول الفترة (بالأيام) في النمط الزمني: تُطلب دعوة جديدة كل هذه المدة (≥ 1)."""
    try:
        return max(1, int(get_setting('invite_gate_period_days', '3')))
    except (TypeError, ValueError):
        return 3

def set_invite_gate_period_days(days: int):
    """تحديد طول الفترة الزمنية (بالأيام) لطلب دعوة جديدة."""
    set_setting('invite_gate_period_days', str(max(1, int(days))))

def get_invite_gate_reset_at() -> float:
    """لحظة «اطلب دعوة من الجميع الآن» (epoch seconds)؛ 0 = لا يوجد طلب عام حالي."""
    try:
        return float(get_setting('invite_gate_reset_at', '0') or '0')
    except (TypeError, ValueError):
        return 0.0

def set_invite_gate_reset_now():
    """يضبط لحظة إعادة تعيين عامة: على كل عضو عمل دعوة جديدة بعد الآن ليكمل."""
    import time as _time
    set_setting('invite_gate_reset_at', str(_time.time()))

def clear_invite_gate_reset():
    """يلغي الطلب العام للدعوة (يعود للسلوك المعتاد للنمط الحالي)."""
    set_setting('invite_gate_reset_at', '0')

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

def _ensure_payments_columns():
    """يضيف عمود مدة الاشتراك للدفعة (شهري=30/سنوي=365) إن لم يكن موجوداً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('ALTER TABLE payments ADD COLUMN IF NOT EXISTS duration_days INTEGER DEFAULT 30')


def add_payment(user_id: int, payment_method: str, proof_file_id: str = None,
                proof_message_id: int = None, amount: float = None, duration_days: int = 30):
    """إضافة دفعة جديدة معلقة (مع مدة الاشتراك المختارة)."""
    if amount is None:
        amount = float(get_setting('price_monthly', get_setting('subscription_price', '10')))

    # PostgreSQL لا يدعم cursor.lastrowid؛ نستخدم RETURNING للحصول على المعرّف
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO payments (user_id, amount, payment_method, proof_file_id, proof_message_id, duration_days)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING payment_id
        ''', (user_id, amount, payment_method, proof_file_id, proof_message_id, duration_days))
        row = cursor.fetchone()
        payment_id = row[0] if row else None

    logger.info(f"💰 دفعة جديدة #{payment_id} من المستخدم {user_id} عبر {payment_method} ({duration_days} يوم)")
    return payment_id

def approve_payment(payment_id: int, admin_id: int):
    """قبول الدفعة وتفعيل الاشتراك (في معاملة واحدة لضمان الذرّية)"""
    with db_cursor(commit=True) as cursor:
        # الحصول على معلومات الدفعة (مع مدتها)
        cursor.execute('''
            SELECT user_id, payment_method, status, COALESCE(duration_days, 30)
            FROM payments
            WHERE payment_id = %s
            FOR UPDATE
        ''', (payment_id,))
        result = cursor.fetchone()

        if not result:
            return False, "الدفعة غير موجودة"

        user_id, payment_method, status, duration_days = result

        if status == 'approved':
            return False, "تم قبول هذه الدفعة مسبقاً"

        if user_id is None:
            return False, "صاحب الدفعة لم يعد موجوداً"

        # تفعيل الاشتراك ضمن نفس المعاملة (بمدة الدفعة)
        end_date = datetime.now() + timedelta(days=duration_days)
        cursor.execute('''
            UPDATE users
            SET is_subscribed = 1, subscription_end = %s, payment_method = %s
            WHERE user_id = %s
        ''', (end_date.isoformat(), payment_method, user_id))
        if cursor.rowcount != 1:
            return False, "صاحب الدفعة لم يعد موجوداً"

        # لا نعلن قبول الدفعة إلا بعد التأكد من تفعيل المستخدم فعلياً.
        cursor.execute('''
            UPDATE payments
            SET status = 'approved',
                approved_at = %s,
                approved_by = %s
            WHERE payment_id = %s
        ''', (datetime.now().isoformat(), admin_id, payment_id))

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

def count_new_users(hours=24):
    """عدد المستخدمين الجدد الذين دخلوا البوت خلال آخر (hours) ساعة."""
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')",
            (hours,)
        )
        row = cursor.fetchone()
    return row[0] if row else 0


def get_all_users():
    """الحصول على قائمة جميع المستخدمين"""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT user_id, username, first_name, is_subscribed, subscription_end
            FROM users
            ORDER BY created_at DESC
        ''')
        return cursor.fetchall()


def get_users_by_language(lang=None):
    """معرّفات المستخدمين حسب اللغة. lang='ar' يشمل من لغته غير محددة (الافتراضي
    عربي). lang='en' للإنجليزية. None/أي قيمة أخرى = الجميع."""
    with db_cursor() as cursor:
        if lang == 'ar':
            cursor.execute("SELECT user_id FROM users WHERE COALESCE(language, 'ar') = 'ar'")
        elif lang == 'en':
            cursor.execute("SELECT user_id FROM users WHERE language = 'en'")
        else:
            cursor.execute("SELECT user_id FROM users")
        return [r[0] for r in cursor.fetchall()]

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
    """الحصول على لغة المستخدم (مخزَّن مؤقتاً — أكثر استعلام تكراراً في البوت،
    ويُبطَل فوراً عند تغيير اللغة)."""
    now = time.monotonic()
    with _cache_lock:
        hit = _lang_cache.get(user_id)
        if hit is not None and now - hit[1] < _LANG_TTL:
            return hit[0]
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT language
            FROM users
            WHERE user_id = %s
        ''', (user_id,))
        result = cursor.fetchone()

    lang = result[0] if (result and result[0]) else 'ar'  # الافتراضي عربي
    with _cache_lock:
        if len(_lang_cache) >= _LANG_CACHE_MAX:
            _lang_cache.pop(next(iter(_lang_cache)), None)
        _lang_cache[user_id] = (lang, now)
    return lang

def set_user_language(user_id: int, language: str):
    """تحديد لغة المستخدم (يُبطل الذاكرة فوراً فتظهر اللغة الجديدة في الحال)"""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO users (user_id, language)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET language = excluded.language
        ''', (user_id, language))
    with _cache_lock:
        _lang_cache[user_id] = (language, time.monotonic())


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
    """يحذف صف كاش (يُستخدم عند فشل المعرّف القديم أو مسح محتوى خاطئ).
    يرجع True إذا حُذف صف فعلاً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            'DELETE FROM media_cache WHERE url_key = %s AND quality = %s',
            (url_key, quality)
        )
        return cursor.rowcount > 0


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


def _ensure_member_activity_schema():
    """Idempotently add real activity and anonymous departure aggregates."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ
        ''')
        # Existing members get the best real signal already held locally: their
        # latest successful download, falling back to their registration time.
        # The update runs only for rows not migrated before.
        cursor.execute('''
            UPDATE users u
            SET last_activity_at = COALESCE(
                (SELECT MAX(h.created_at) FROM download_history h
                 WHERE h.user_id = u.user_id),
                u.created_at,
                NOW()
            )
            WHERE u.last_activity_at IS NULL
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_users_last_activity_at
            ON users (last_activity_at DESC)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS member_departures (
                id BIGSERIAL PRIMARY KEY,
                reason VARCHAR(32) NOT NULL,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT member_departures_reason_check
                    CHECK (reason IN ('blocked', 'deactivated', 'unreachable'))
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_member_departures_occurred_at
            ON member_departures (occurred_at DESC)
        ''')
        # Events are identity-free, nevertheless retain only what the 30-day
        # dashboard needs (with a small operational margin).
        cursor.execute('''
            DELETE FROM member_departures
            WHERE occurred_at < NOW() - INTERVAL '90 days'
        ''')


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


def get_admin_telemetry_summary(recent_limit=12, top_limit=8, review_limit=20):
    """Return the real read-only dashboard aggregates in grouped SQL queries.

    The query intentionally never selects ``download_history.url`` or Telegram
    file identifiers.  Referral counts are grouped once for all referrers, so
    building the dashboard cannot degrade into one query per member.
    """
    recent_limit = max(1, min(int(recent_limit), 50))
    top_limit = max(1, min(int(top_limit), 25))
    review_limit = max(1, min(int(review_limit), 50))
    with db_cursor() as cursor:
        cursor.execute('''
            WITH user_counts AS (
                SELECT COUNT(*) AS members_total,
                       COUNT(*) FILTER (
                           WHERE is_subscribed = 1
                             AND (subscription_end IS NULL
                                  OR subscription_end > NOW())) AS subscribers,
                       COUNT(*) FILTER (
                           WHERE last_activity_at >= NOW()
                               - INTERVAL '24 hours') AS active_24h,
                       COUNT(*) FILTER (
                           WHERE last_activity_at >= NOW()
                               - INTERVAL '7 days') AS active_7d,
                       COUNT(*) FILTER (
                           WHERE last_activity_at >= NOW()
                               - INTERVAL '30 days') AS active_30d,
                       COUNT(*) FILTER (
                           WHERE last_activity_at IS NULL
                              OR last_activity_at < NOW()
                                  - INTERVAL '30 days') AS inactive_30d
                FROM users
            ), download_counts AS (
                SELECT COUNT(*) AS downloads_total,
                       COUNT(*) FILTER (
                           WHERE created_at >= CURRENT_DATE) AS downloads_today,
                       COUNT(*) FILTER (
                           WHERE created_at >= NOW()
                               - INTERVAL '24 hours') AS downloads_24h,
                       COUNT(*) FILTER (
                           WHERE created_at >= CURRENT_DATE
                             AND from_cache IS TRUE) AS cache_hits_today,
                       COALESCE(SUM(file_size_mb) FILTER (
                           WHERE created_at >= CURRENT_DATE
                             AND from_cache IS TRUE), 0) AS saved_mb_today
                FROM download_history
            ), cache_counts AS (
                SELECT COUNT(*) AS cache_items,
                       COALESCE(SUM(hits), 0) AS cache_hits
                FROM media_cache
            ), departure_counts AS (
                SELECT COUNT(*) FILTER (
                           WHERE occurred_at >= CURRENT_DATE) AS departures_today,
                       COUNT(*) FILTER (
                           WHERE occurred_at >= NOW()
                               - INTERVAL '7 days') AS departures_7d,
                       COUNT(*) FILTER (
                           WHERE occurred_at >= NOW() - INTERVAL '30 days'
                             AND reason = 'blocked') AS blocked_30d,
                       COUNT(*) FILTER (
                           WHERE occurred_at >= NOW() - INTERVAL '30 days'
                             AND reason = 'deactivated') AS deactivated_30d,
                       COUNT(*) FILTER (
                           WHERE occurred_at >= NOW() - INTERVAL '30 days'
                             AND reason = 'unreachable') AS unreachable_30d
                FROM member_departures
            )
            SELECT users.members_total, users.subscribers,
                   users.active_24h, users.active_7d, users.active_30d,
                   users.inactive_30d,
                   downloads.downloads_total, downloads.downloads_today,
                   downloads.downloads_24h,
                   cache.cache_items, cache.cache_hits,
                   downloads.cache_hits_today, downloads.saved_mb_today,
                   (SELECT COUNT(*) FROM payments WHERE status = 'pending'),
                   (SELECT COUNT(*) FROM referrals),
                   departures.departures_today, departures.departures_7d,
                   (departures.blocked_30d + departures.deactivated_30d
                    + departures.unreachable_30d),
                   departures.blocked_30d, departures.deactivated_30d,
                   departures.unreachable_30d,
                   pg_database_size(current_database()),
                   (SELECT value FROM settings
                    WHERE key = 'last_reachability_check_at')
            FROM user_counts users
            CROSS JOIN download_counts downloads
            CROSS JOIN cache_counts cache
            CROSS JOIN departure_counts departures
        ''')
        totals = cursor.fetchone() or (0,) * 23

        cursor.execute('''
            SELECT h.id, h.user_id, u.first_name, u.username, h.title,
                   h.quality, h.kind, h.platform, h.file_size_mb,
                   h.from_cache, h.created_at
            FROM download_history h
            LEFT JOIN users u ON u.user_id = h.user_id
            ORDER BY h.created_at DESC, h.id DESC
            LIMIT %s
        ''', (recent_limit,))
        recent_rows = cursor.fetchall()

        cursor.execute('''
            SELECT r.referrer_user_id, u.first_name, u.username,
                   COUNT(*) AS invites_total,
                   COUNT(invited.user_id) AS invites_current
            FROM referrals r
            LEFT JOIN users u ON u.user_id = r.referrer_user_id
            LEFT JOIN users invited ON invited.user_id = r.referred_user_id
            GROUP BY r.referrer_user_id, u.first_name, u.username
            ORDER BY invites_total DESC, r.referrer_user_id
            LIMIT %s
        ''', (top_limit,))
        referrer_rows = cursor.fetchall()

        # Review signal requested by the admin: the same member downloaded
        # audio, then later video, from the same source today.  The source URL
        # is used only as an in-database grouping key and is never selected or
        # returned to telemetry.
        cursor.execute('''
            SELECT h.user_id, u.first_name, u.username,
                   MIN(h.created_at) FILTER (WHERE h.kind = 'audio') AS audio_at,
                   MAX(h.created_at) FILTER (WHERE h.kind = 'video') AS video_at,
                   COUNT(*) AS occurrences
            FROM download_history h
            LEFT JOIN users u ON u.user_id = h.user_id
            WHERE h.created_at >= CURRENT_DATE
              AND h.url IS NOT NULL
              AND h.kind IN ('audio', 'video')
            GROUP BY h.user_id, h.url, u.first_name, u.username
            HAVING MIN(h.created_at) FILTER (WHERE h.kind = 'audio') IS NOT NULL
               AND MAX(h.created_at) FILTER (WHERE h.kind = 'video')
                   > MIN(h.created_at) FILTER (WHERE h.kind = 'audio')
            ORDER BY video_at DESC
            LIMIT %s
        ''', (review_limit,))
        review_rows = cursor.fetchall()

    recent = [{
        'id': row[0],
        'userId': row[1],
        'firstName': row[2],
        'username': row[3],
        'title': row[4],
        'quality': row[5],
        'kind': row[6],
        'platform': row[7],
        'sizeMb': row[8],
        'fromCache': bool(row[9]),
        'createdAt': row[10],
    } for row in recent_rows]
    top_referrers = [{
        'userId': row[0],
        'firstName': row[1],
        'username': row[2],
        'invitesTotal': row[3],
        'invitesCurrent': row[4],
        'invitesIncomplete': max(0, row[3] - row[4]),
    } for row in referrer_rows]
    review_items = [{
        'userId': row[0],
        'firstName': row[1],
        'username': row[2],
        'audioAt': row[3],
        'videoAt': row[4],
        'occurrences': row[5],
    } for row in review_rows]

    return {
        'membersTotal': totals[0],
        'subscribers': totals[1],
        'membersActive24h': totals[2],
        'membersActive7d': totals[3],
        'membersActive30d': totals[4],
        'membersInactive30d': totals[5],
        'downloadsTotal': totals[6],
        'downloadsToday': totals[7],
        'downloadsLast24h': totals[8],
        'cacheItems': totals[9],
        'cacheHits': totals[10],
        'cacheHitsToday': totals[11],
        # This is an estimate: a cache hit avoids re-downloading roughly the
        # recorded delivered file size.  The UI must label it accordingly.
        'savedMbTodayEstimate': float(totals[12] or 0),
        'pendingPayments': totals[13],
        'referralsTotal': totals[14],
        'departuresToday': totals[15],
        'departures7d': totals[16],
        'departures30d': totals[17],
        'departureReasons30d': [
            {'reason': 'blocked', 'count': totals[18]},
            {'reason': 'deactivated', 'count': totals[19]},
            {'reason': 'unreachable', 'count': totals[20]},
        ],
        # These two private operational values are moved into the system block
        # by admin_telemetry before the snapshot is sent.
        '_databaseSizeBytes': totals[21],
        'lastReachabilityCheckAt': totals[22],
        'recentDownloads': recent,
        'topReferrers': top_referrers,
        'reviewItems': review_items,
    }


def get_admin_telemetry_members(limit=100, offset=0):
    """Return one normalized member batch with grouped referral statistics.

    This is a single query per batch, regardless of how many members it
    returns.  It contains dashboard profile fields only—no links, answers,
    payment proof identifiers, cache references, or download titles.
    """
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    with db_cursor() as cursor:
        cursor.execute('''
            WITH referral_stats AS (
                SELECT r.referrer_user_id,
                       COUNT(*) AS invites_total,
                       COUNT(invited.user_id) AS invites_current
                FROM referrals r
                LEFT JOIN users invited
                       ON invited.user_id = r.referred_user_id
                GROUP BY r.referrer_user_id
            ), today AS (
                SELECT user_id, download_count
                FROM daily_downloads
                WHERE download_date = CURRENT_DATE
            )
            SELECT u.user_id, u.username, u.first_name,
                   COALESCE(u.language, 'ar'), survey.gender,
                   CASE WHEN u.is_subscribed = 1
                              AND (u.subscription_end IS NULL
                                   OR u.subscription_end > NOW())
                        THEN TRUE ELSE FALSE END,
                   u.subscription_end,
                   COALESCE(ref.invites_total, 0),
                   COALESCE(ref.invites_current, 0),
                   COALESCE(ref.invites_total - ref.invites_current, 0),
                   COALESCE(today.download_count, 0),
                   COALESCE(u.total_downloads, 0),
                   u.created_at,
                   u.last_activity_at
            FROM users u
            LEFT JOIN member_survey survey ON survey.user_id = u.user_id
            LEFT JOIN referral_stats ref ON ref.referrer_user_id = u.user_id
            LEFT JOIN today ON today.user_id = u.user_id
            ORDER BY u.user_id
            LIMIT %s OFFSET %s
        ''', (limit, offset))
        rows = cursor.fetchall()

    return [{
        'userId': row[0],
        'username': row[1],
        'firstName': row[2],
        'language': row[3],
        'gender': row[4],
        'isSubscribed': bool(row[5]),
        'subscriptionEnd': row[6],
        'invitesTotal': row[7],
        'invitesCurrent': row[8],
        'invitesIncomplete': row[9],
        'downloadsToday': row[10],
        'totalDownloads': row[11],
        'joinedAt': row[12],
        'lastActivityAt': row[13],
    } for row in rows]


def cleanup_expired_privacy_data(history_days=30, cache_days=30,
                                 departure_days=90):
    """Delete expired history/cache and anonymous departure aggregates.

    Member profiles and survey/gender data are intentionally not touched.
    Returns the number of deleted rows for operational verification.
    """
    history_days = max(1, int(history_days))
    cache_days = max(1, int(cache_days))
    departure_days = max(30, int(departure_days))

    with db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            DELETE FROM download_history
            WHERE created_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (history_days,),
        )
        deleted_history = cursor.rowcount

        cursor.execute(
            """
            DELETE FROM media_cache
            WHERE created_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (cache_days,),
        )
        deleted_cache = cursor.rowcount

        cursor.execute(
            """
            DELETE FROM member_departures
            WHERE occurred_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (departure_days,),
        )
        deleted_departures = cursor.rowcount

    return {
        'download_history': deleted_history,
        'media_cache': deleted_cache,
        'member_departures': deleted_departures,
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


def _ensure_total_downloads_column():
    """يضيف عمود إجمالي التحميلات (عدّاد تراكمي لبوابة الدعوة) إن لم يكن موجوداً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS total_downloads INTEGER DEFAULT 0'
        )


def increment_total_downloads(user_id):
    """يزيد العدّاد التراكمي لتحميلات المستخدم (يُستخدم في بوابة الدعوة)."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO users (user_id, total_downloads)
            VALUES (%s, 1)
            ON CONFLICT (user_id) DO UPDATE SET
                total_downloads = COALESCE(users.total_downloads, 0) + 1
        ''', (user_id,))


def get_total_downloads(user_id) -> int:
    """إجمالي تحميلات المستخدم التراكمية."""
    with db_cursor() as cursor:
        cursor.execute('SELECT COALESCE(total_downloads, 0) FROM users WHERE user_id = %s',
                       (user_id,))
        row = cursor.fetchone()
    return row[0] if row else 0


def invite_gate_status(user_id) -> dict:
    """حالة بوابة الدعوة لمستخدم غير مشترك، بحسب النمط الحالي.

    النمط 'count' (حسب عدد التحميلات):
      allowed  = المجاني + (عدد دعواته الناجحة × التحميلات لكل دعوة)
      blocked  = استنفد رصيده (consumed ≥ allowed) → يجب أن يدعو ليكمل

    النمط 'period' (حسب الفترة الزمنية):
      blocked  = لم يعمل أي دعوة ناجحة خلال آخر (period_days) يوم → يجب دعوة جديدة
      (مع مهلة ترحيب للعضو الجديد قدر «المجاني» قبل أول دعوة مطلوبة)

    الطلب العام (reset): إذا ضغط الأدمن «اطلب دعوة من الجميع الآن» يجب على كل
    عضو سبق له التحميل أن يعمل دعوة جديدة بعد تلك اللحظة (يعمل في كِلا النمطين).
    """
    import time as _time
    now = _time.time()
    free = get_invite_gate_free()
    consumed = get_total_downloads(user_id)
    invites = get_referral_count(user_id)
    reset_at = get_invite_gate_reset_at()

    # طلب عام معلّق: يشمل فقط من سبق له التحميل (العضو الجديد يُترك لمسار العادة)
    reset_pending = (
        reset_at > 0 and consumed > 0
        and count_referrals_since(user_id, reset_at) == 0
    )

    mode = get_invite_gate_mode()

    if mode == 'period':
        period_days = get_invite_gate_period_days()
        # مهلة ترحيب للعضو الجديد قبل أول دعوة مطلوبة (ما لم يكن هناك طلب عام)
        if consumed < free and not reset_pending:
            blocked = False
        else:
            since = max(now - period_days * 86400, reset_at)
            blocked = count_referrals_since(user_id, since) == 0
        return {
            'mode': 'period',
            'blocked': blocked,
            'needed': 1 if blocked else 0,
            'consumed': consumed,
            'invites': invites,
            'per': 1,
            'free': free,
            'period_days': period_days,
            'reset_pending': reset_pending,
            'remaining': 0,
        }

    # النمط الافتراضي: حسب عدد التحميلات
    per = get_invite_gate_per_invite()
    allowed = free + invites * per
    blocked_count = consumed >= allowed
    blocked = blocked_count or reset_pending
    if blocked_count:
        needed = (consumed - allowed) // per + 1
    elif reset_pending:
        needed = 1
    else:
        needed = 0
    return {
        'mode': 'count',
        'blocked': blocked,
        'allowed': allowed,
        'consumed': consumed,
        'remaining': max(0, allowed - consumed),
        'invites': invites,
        'needed': needed,
        'per': per,
        'free': free,
        'reset_pending': reset_pending,
    }


def record_referral(referred_user_id, referrer_user_id) -> bool:
    """يسجّل دعوة بلا مكافأة، مع رفض الداعي غير الموجود.

    المسار التشغيلي يستخدم :func:`record_referral_and_reward` حتى يكون تسجيل
    الدعوة والمكافأة معاملة ذرّية واحدة. هذه الدالة باقية للتوافق فقط.
    """
    if int(referred_user_id) == int(referrer_user_id):
        return False  # لا يدعو المستخدم نفسه
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            'SELECT user_id FROM users WHERE user_id = %s FOR UPDATE',
            (referrer_user_id,),
        )
        if cursor.fetchone() is None:
            return False
        cursor.execute('''
            INSERT INTO referrals (referred_user_id, referrer_user_id)
            VALUES (%s, %s)
            ON CONFLICT (referred_user_id) DO NOTHING
            RETURNING referred_user_id
        ''', (referred_user_id, referrer_user_id))
        inserted = cursor.fetchone() is not None
    return inserted


def record_referral_and_reward(referred_user_id, referrer_user_id,
                               reward_amount) -> bool:
    """Atomically record one referral and reward an existing referrer.

    The referred member intentionally need not exist yet: Telegram's ``/start``
    arrives before language selection creates their profile.  The referrer must
    already exist and is row-locked, preventing both ghost profiles and a race
    with deletion.  Duplicate/self referrals return ``False`` and never reward.
    """
    try:
        referred_user_id = int(referred_user_id)
        referrer_user_id = int(referrer_user_id)
        reward_amount = max(0, int(reward_amount))
    except (TypeError, ValueError):
        return False
    if referred_user_id == referrer_user_id:
        return False

    with db_cursor(commit=True) as cursor:
        cursor.execute(
            'SELECT user_id FROM users WHERE user_id = %s FOR UPDATE',
            (referrer_user_id,),
        )
        if cursor.fetchone() is None:
            return False

        cursor.execute('''
            INSERT INTO referrals (referred_user_id, referrer_user_id)
            VALUES (%s, %s)
            ON CONFLICT (referred_user_id) DO NOTHING
            RETURNING referred_user_id
        ''', (referred_user_id, referrer_user_id))
        if cursor.fetchone() is None:
            return False

        cursor.execute('''
            UPDATE users
            SET bonus_downloads = COALESCE(bonus_downloads, 0) + %s
            WHERE user_id = %s
            RETURNING user_id
        ''', (reward_amount, referrer_user_id))
        if cursor.fetchone() is None:
            # The row lock makes this impossible in normal operation. Raising
            # is intentional: db_cursor rolls the referral insert back too.
            raise RuntimeError('referrer disappeared during referral reward')
    return True


def get_referral_count(referrer_user_id) -> int:
    """عدد المستخدمين الذين انضموا عبر رابط هذا المستخدم."""
    with db_cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM referrals WHERE referrer_user_id = %s',
            (referrer_user_id,)
        )
        return cursor.fetchone()[0]


def count_referrals_since(referrer_user_id, since_epoch) -> int:
    """عدد دعوات هذا المستخدم الناجحة بعد لحظة زمنية معيّنة (epoch seconds).

    يُستخدم في بوابة الدعوة الزمنية وفي الطلب العام: التحقّق أنّ المستخدم عمل
    دعوة حقيقية جديدة بعد بداية الفترة/لحظة الطلب (يعتمد على created_at الفعلي)."""
    try:
        since_dt = datetime.fromtimestamp(float(since_epoch or 0))
    except (TypeError, ValueError, OSError, OverflowError):
        since_dt = datetime.fromtimestamp(0)
    with db_cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM referrals WHERE referrer_user_id = %s AND created_at > %s',
            (referrer_user_id, since_dt)
        )
        return cursor.fetchone()[0]


def add_bonus_downloads(user_id, amount):
    """يضيف رصيداً لعضو موجود فقط؛ لا ينشئ ملفات أعضاء وهمية."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            UPDATE users
            SET bonus_downloads = COALESCE(bonus_downloads, 0) + %s
            WHERE user_id = %s
        ''', (amount, user_id))
        return cursor.rowcount > 0


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


# ═══════════════════════════════════════════════════════════════
# استبيان الأعضاء - Member survey (الجنس + سؤال الأدمن نعم/لا)
# ═══════════════════════════════════════════════════════════════

def _ensure_survey_table():
    """ينشئ جدول استبيان الأعضاء إن لم يكن موجوداً."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS member_survey (
                user_id BIGINT PRIMARY KEY,
                gender TEXT,
                q_answer TEXT,
                q_version INTEGER DEFAULT -1,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        # عمود الموافقة على الشروط (للقواعد الموجودة مسبقاً أيضاً)
        cursor.execute(
            'ALTER TABLE member_survey ADD COLUMN IF NOT EXISTS consent BOOLEAN DEFAULT FALSE')


def has_consent(user_id):
    """هل وافق العضو على شروط الاستخدام (منع المحتوى الإباحي)؟"""
    with db_cursor() as cursor:
        cursor.execute('SELECT consent FROM member_survey WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
    return bool(row[0]) if row and row[0] is not None else False


def set_consent(user_id):
    """يسجّل موافقة العضو على الشروط."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO member_survey (user_id, consent) VALUES (%s, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET consent = TRUE, updated_at = NOW()
        ''', (user_id,))


def get_survey(user_id):
    """يرجع {gender, q_answer, q_version} للمستخدم (قيم افتراضية إن لم يوجد)."""
    with db_cursor() as cursor:
        cursor.execute(
            'SELECT gender, q_answer, q_version FROM member_survey WHERE user_id = %s',
            (user_id,))
        row = cursor.fetchone()
    if not row:
        return {'gender': None, 'q_answer': None, 'q_version': -1}
    return {'gender': row[0], 'q_answer': row[1],
            'q_version': row[2] if row[2] is not None else -1}


def set_gender(user_id, gender):
    """يحفظ جنس المستخدم (male/female)."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO member_survey (user_id, gender) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET gender = EXCLUDED.gender, updated_at = NOW()
        ''', (user_id, gender))


def set_question_answer(user_id, answer, version):
    """يحفظ إجابة المستخدم على سؤال الأدمن مع رقم نسخة السؤال."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO member_survey (user_id, q_answer, q_version) VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                q_answer = EXCLUDED.q_answer, q_version = EXCLUDED.q_version, updated_at = NOW()
        ''', (user_id, answer, version))


def get_gender_stats():
    """إحصائية الجنس للأعضاء الموجودين فعلاً: {'male': n, 'female': n}.

    نربط مع جدول users فلا نعدّ صفوف استبيان لأعضاء غادروا/حُذفوا (تفادي
    الأرقام المنتفخة)."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT s.gender, COUNT(*)
            FROM member_survey s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.gender IS NOT NULL
            GROUP BY s.gender
        ''')
        rows = cursor.fetchall()
    d = {'male': 0, 'female': 0}
    for g, c in rows:
        if g in d:
            d[g] = c
    return d


def get_question_stats(version):
    """(قديمة - للتوافق) إحصائية إجابات سؤال واحد حسب النسخة."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT q_answer, COUNT(*) FROM member_survey
            WHERE q_version = %s AND q_answer IS NOT NULL GROUP BY q_answer
        ''', (version,))
        rows = cursor.fetchall()
    d = {'yes': 0, 'no': 0}
    for a, c in rows:
        if a in d:
            d[a] = c
    return d


# ═══════════════════════════════════════════════════════════════
# أسئلة الأعضاء المتعددة - Multiple admin questions
# ═══════════════════════════════════════════════════════════════

def _ensure_questions_tables():
    """جداول الأسئلة المتعددة وإجابات الأعضاء، مع ترحيل السؤال القديم الواحد."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_questions (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                lang TEXT DEFAULT 'all',
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        cursor.execute("ALTER TABLE admin_questions ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'all'")
        cursor.execute("ALTER TABLE admin_questions ADD COLUMN IF NOT EXISTS gender TEXT DEFAULT 'all'")
        # target_user: إن كان محدَّداً يُطرح السؤال على هذا الشخص فقط
        cursor.execute("ALTER TABLE admin_questions ADD COLUMN IF NOT EXISTS target_user BIGINT")
        # options: خيارات إجابة مخصّصة مفصولة بـ | (فارغ = نعم/لا الافتراضية)
        cursor.execute("ALTER TABLE admin_questions ADD COLUMN IF NOT EXISTS options TEXT")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS member_answers (
                user_id BIGINT NOT NULL,
                question_id INTEGER NOT NULL,
                answer TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (user_id, question_id)
            )
        ''')
    # ترحيل السؤال القديم الواحد (إن وُجد ولا توجد أسئلة بعد)
    try:
        with db_cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM admin_questions')
            n = cursor.fetchone()[0]
        if n == 0:
            old = (get_setting('member_question', '') or '').strip()
            if old:
                add_question(old, get_setting('member_question_enabled', '0') == '1')
    except Exception:
        pass


def add_question(text, enabled=True, lang='all', gender='all', target_user=None, options=None):
    """يضيف سؤالاً جديداً ويرجع معرّفه.
    lang: all/ar/en | gender: all/male/female | target_user: آيدي شخص محدّد أو None
    options: خيارات إجابة مخصّصة مفصولة بـ | أو None (نعم/لا الافتراضية)."""
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            'INSERT INTO admin_questions (text, enabled, lang, gender, target_user, options) '
            'VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
            (text, enabled, lang, gender, target_user, options))
        return cursor.fetchone()[0]


def delete_question(qid):
    """يحذف سؤالاً وكل إجاباته."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('DELETE FROM admin_questions WHERE id = %s', (qid,))
        cursor.execute('DELETE FROM member_answers WHERE question_id = %s', (qid,))


def set_question_enabled(qid, enabled):
    with db_cursor(commit=True) as cursor:
        cursor.execute('UPDATE admin_questions SET enabled = %s WHERE id = %s', (enabled, qid))


def get_questions():
    """كل الأسئلة: (id, text, enabled, lang, gender, target_user, options)."""
    with db_cursor() as cursor:
        cursor.execute('SELECT id, text, enabled, lang, gender, target_user, options '
                       'FROM admin_questions ORDER BY id')
        return cursor.fetchall()


def get_question_options(qid):
    """خيارات الإجابة المخصّصة لسؤال (سلسلة مفصولة بـ |) أو None."""
    with db_cursor() as cursor:
        cursor.execute('SELECT options FROM admin_questions WHERE id = %s', (qid,))
        row = cursor.fetchone()
        return row[0] if row else None


def get_unanswered_questions(user_id):
    """أسئلة مفعّلة لم يجب عليها المستخدم: (id, text, options).
    سؤال الشخص المحدّد يُطرح عليه هو فقط (بلا قيود فئة/وقت)؛
    أسئلة الفئات تُطرح بعد انضمامه وتطابق لغته وجنسه (all يصل الجميع)."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT q.id, q.text, q.options FROM admin_questions q
            WHERE q.enabled = TRUE
              AND (
                q.target_user = %s
                OR (
                  q.target_user IS NULL
                  AND q.created_at >= COALESCE(
                        (SELECT created_at FROM users WHERE user_id = %s), NOW())
                  AND (COALESCE(q.lang, 'all') = 'all'
                       OR COALESCE(q.lang, 'all') = COALESCE(
                            (SELECT language FROM users WHERE user_id = %s), 'ar'))
                  AND (COALESCE(q.gender, 'all') = 'all'
                       OR COALESCE(q.gender, 'all') = (
                            SELECT gender FROM member_survey WHERE user_id = %s))
                )
              )
              AND NOT EXISTS (
                SELECT 1 FROM member_answers a
                WHERE a.user_id = %s AND a.question_id = q.id)
            ORDER BY q.id
        ''', (user_id, user_id, user_id, user_id, user_id))
        return cursor.fetchall()


def get_target_users(gender='all', lang='all'):
    """معرّفات المستخدمين حسب الجنس واللغة معاً (للبث المستهدف).
    gender: all/male/female | lang: all/ar/en. العربية تشمل غير المحدد."""
    q = ("SELECT u.user_id FROM users u "
         "LEFT JOIN member_survey s ON u.user_id = s.user_id WHERE 1=1")
    params = []
    if lang == 'ar':
        q += " AND COALESCE(u.language, 'ar') = 'ar'"
    elif lang == 'en':
        q += " AND u.language = 'en'"
    if gender in ('male', 'female'):
        q += " AND s.gender = %s"
        params.append(gender)
    with db_cursor() as cursor:
        cursor.execute(q, tuple(params))
        return [r[0] for r in cursor.fetchall()]


def _ensure_reminder_column():
    """عمود يحفظ معرّف آخر رسالة تذكير لكل مستخدم (لحذفها قبل إرسال أحدث)."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reminder_msg_id BIGINT')


def get_inactive_users(days=7):
    """أعضاء خاملون: مرّ على انضمامهم ≥ days ولم يحمّلوا منذ ≥ days (أو أبداً).
    يرجع (user_id, language, last_reminder_msg_id)."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT u.user_id, COALESCE(u.language, 'ar'), u.last_reminder_msg_id
            FROM users u
            LEFT JOIN (
                SELECT user_id, MAX(created_at) AS last_dl
                FROM download_history GROUP BY user_id
            ) h ON u.user_id = h.user_id
            WHERE u.created_at < NOW() - (%s * INTERVAL '1 day')
              AND (h.last_dl IS NULL OR h.last_dl < NOW() - (%s * INTERVAL '1 day'))
        ''', (days, days))
        return cursor.fetchall()


def get_all_users_for_reminder():
    """كل الأعضاء بصيغة (user_id, language, last_reminder_msg_id) — لإرسال تذكير
    للجميع (بلا فلتر خمول)."""
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT user_id, COALESCE(language, 'ar'), last_reminder_msg_id FROM users"
        )
        return cursor.fetchall()


def set_last_reminder(user_id, msg_id):
    """يحفظ معرّف آخر رسالة تذكير أُرسلت للمستخدم."""
    with db_cursor(commit=True) as cursor:
        cursor.execute('UPDATE users SET last_reminder_msg_id = %s WHERE user_id = %s',
                       (msg_id, user_id))


def get_language_counts():
    """عدد المستخدمين حسب اللغة: {'ar': n, 'en': n} (غير المحدد يُحسب عربياً)."""
    with db_cursor() as cursor:
        cursor.execute("SELECT COALESCE(language, 'ar') AS l, COUNT(*) FROM users GROUP BY l")
        rows = cursor.fetchall()
    d = {'ar': 0, 'en': 0}
    for l, c in rows:
        if l == 'en':
            d['en'] += c
        else:
            d['ar'] += c
    return d


def save_question_answer(user_id, qid, answer):
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT INTO member_answers (user_id, question_id, answer)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, question_id) DO UPDATE SET answer = EXCLUDED.answer
        ''', (user_id, qid, answer))


def get_question_answer_stats(qid):
    """إحصائية إجابات سؤال محدد: {'yes': n, 'no': n}."""
    with db_cursor() as cursor:
        cursor.execute('SELECT answer, COUNT(*) FROM member_answers WHERE question_id = %s GROUP BY answer',
                       (qid,))
        rows = cursor.fetchall()
    d = {'yes': 0, 'no': 0}
    for a, c in rows:
        if a in d:
            d[a] = c
    return d


def get_question_answer_breakdown(qid):
    """توزيع إجابات سؤال حسب النص الفعلي: [(answer, count), ...] بترتيب تنازلي."""
    with db_cursor() as cursor:
        cursor.execute('SELECT answer, COUNT(*) FROM member_answers WHERE question_id = %s '
                       'GROUP BY answer ORDER BY COUNT(*) DESC', (qid,))
        return cursor.fetchall()


def get_member_answers(user_id):
    """إجابات عضو على كل الأسئلة: (text, answer)."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT q.text, a.answer FROM member_answers a
            JOIN admin_questions q ON a.question_id = q.id
            WHERE a.user_id = %s ORDER BY a.question_id
        ''', (user_id,))
        return cursor.fetchall()
