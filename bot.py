"""
Telegram Video Downloader Bot - Standalone Version
===================================================
✅ يرفع حتى 2GB
✅ نجح في تحميل فيديو 3 ساعات (694MB)

التشغيل:
    python3 bot_standalone.py
"""

import os
import sys
import glob  # للبحث عن الملفات وحذفها
import time  # Added import os
import html  # تأمين النصوص داخل رسائل HTML للقناة
import uuid  # مجلد مؤقت فريد لكل عملية تحميل
import shutil  # حذف مجلد التحميل المؤقت بالكامل
import subprocess  # توليد المصغّر وضبط تاريخ الفيديو عبر ffmpeg
import logging
import asyncio
import yt_dlp
import traceback
import contextvars  # نقل سبب فشل الاستخراج (محتوى مقيّد) للمستدعي بأمان مع التزامن
from datetime import datetime
from pyrogram import Client, filters, enums, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import (
    UserIsBlocked, InputUserDeactivated, PeerIdInvalid,
    UserDeactivated, UserDeactivatedBan, FloodWait, UserNotParticipant
)

# أخطاء تعني أن المستخدم لم يعد متاحاً (حظر البوت أو حُذف حسابه) فنحذفه
GONE_USER_ERRORS = (
    UserIsBlocked, InputUserDeactivated, PeerIdInvalid,
    UserDeactivated, UserDeactivatedBan,
)
from dotenv import load_dotenv
import subscription_db as subdb
from translations import t
from queue_manager import DownloadQueueManager, DownloadTask
import pg_backup

from url_utils import (
    PLATFORM_URL_MARKERS, is_safe_url, cache_key_for_url,
    _platform_of, extract_first_url, _url_host,
)
from cookies_manager import (
    COOKIES_PLATFORMS, get_cookie_file_for_url, validate_platform_cookies,
)
from link_resolvers import (
    resolve_snapchat_spotlight, _is_music_link, resolve_music_link,
    resolve_instagram_media, instagram_mirror_lookup, resolve_tiktok_media,
    twitter_mirror_lookup, twitter_mirror_media,
    resolve_tiktok_images, resolve_pinterest_media, resolve_pinterest_images,
    is_substack_note, resolve_substack_note, all_mirror_hosts,
)
from content_filter import (
    ADULT_DOMAINS, _custom_adult_domains, _custom_adult_keywords,
    _add_to_setting_list, _remove_from_setting_list,
    is_adult_url, is_adult_info, _blocked_accounts,
    is_blocked_url, is_blocked_account,
    adult_filter_enabled, downloads_enabled,
)
from video_processing import (
    get_file_size_mb, generate_video_thumbnail, finalize_video, probe_video,
)
from download_errors import (
    _is_drm_error, _is_geo_restricted_error, _is_youtube_cookie_issue,
    _is_facebook_cookie_issue, _is_cookie_file_issue, _is_restricted_content_error,
)
# ملاحظة نشر: بعض عمليات التحديث تزامن bot.py فقط دون download_errors.py،
# لذا نستورد المصنّفات الأحدث دفاعياً مع بديل محلي إن كان الملف قديماً — حتى
# لا يفشل إقلاع البوت باستيراد دالة غير موجودة.
try:
    from download_errors import _is_http_403_error
except ImportError:
    def _is_http_403_error(err):
        """بديل محلي: خطأ HTTP 403 Forbidden أثناء تنزيل بيانات الفيديو."""
        msg = str(err).lower()
        return '403' in msg and ('forbidden' in msg or 'download video data' in msg)


# ═══════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_standalone.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════
load_dotenv()

API_ID = os.getenv("PYROGRAM_API_ID")
API_HASH = os.getenv("PYROGRAM_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# التحقق من شهادة TLS عند التحميل: مُعطّل افتراضياً (كثير من مواقع الفيديو
# تفشل عبر yt-dlp مع التحقق الصارم). يمكن تفعيله بضبط YTDLP_VERIFY_TLS=1
_YTDLP_NO_CHECK_CERT = os.getenv("YTDLP_VERIFY_TLS", "0") != "1"

if not API_ID or not API_HASH or not BOT_TOKEN:
    print("=" * 60)
    print("❌ المتغيرات البيئية ناقصة!")
    print("=" * 60)
    print("الرجاء إنشاء ملف .env وإضافة المتغيرات التالية:")
    print("")
    print("PYROGRAM_API_ID=your_api_id")
    print("PYROGRAM_API_HASH=your_api_hash")
    print("BOT_TOKEN=your_bot_token")
    print("")
    print("راجع ملف .env.example و README.md للتعليمات الكاملة")
    print("=" * 60)
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# Pyrogram Client
# ═══════════════════════════════════════════════════════════════
app = Client(
    "video_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ═══════════════════════════════════════════════════════════════
# مساعدات الصلاحيات والأمان - Auth & security helpers
# ═══════════════════════════════════════════════════════════════

def get_admin_id():
    """يرجع معرّف الأدمن كنص (أو None إن لم يكن مضبوطاً)."""
    return os.getenv("ADMIN_ID")


def is_admin(user_id) -> bool:
    """نقطة تحقق واحدة من صلاحية الأدمن. تفشل بأمان إذا لم يُضبط ADMIN_ID."""
    admin_id = os.getenv("ADMIN_ID")
    return bool(admin_id) and str(user_id) == str(admin_id)


# Initialize Queue Manager
queue_manager = DownloadQueueManager(cooldown_seconds=10)

# تخزين الروابط
pending_downloads = {}

# روابط قوائم التشغيل المنتظِرة تأكيد المستخدم {user_id: [urls]}
pending_playlists = {}

# عدد التحميلات الافتراضي عند الدعوة، وأقصى عدد مقاطع لقائمة التشغيل
# كل دعوة ناجحة تزيد الحد اليومي للداعي بهذا المقدار (دائماً)
REFERRAL_BONUS = int(os.getenv("REFERRAL_BONUS", "1"))
# ملاحظة: دقائق مكافأة الدعوة لحدّ مدة الفيديو تُدار الآن من لوحة الأدمن
# عبر subdb.get_referral_minutes() (الافتراضي 5، مع REFERRAL_MINUTES في .env كقيمة أولية فقط)
PLAYLIST_MAX = int(os.getenv("PLAYLIST_MAX", "5"))

# أقصى عدد صور تُحمَّل من منشور إنستغرام/تيك توك (كاروسيل/سلايدشو)
GALLERY_DL_MAX_IMAGES = int(os.getenv("GALLERY_DL_MAX_IMAGES", "30"))
# امتدادات الصور التي نرسلها كألبوم
_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.gif')

# حالة المحادثة بين الأدمن والأعضاء عبر زر الرد
# {user_id: target_user_id} أي أن user_id ينتظر كتابة رد ليُرسَل إلى target_user_id
conversation_state = {}

# استبيانات البث الجماعي مع إحصائية حيّة
# {broadcast_id: {'admin_id', 'total', 'yes': {uid:name}, 'no': {uid:name},
#                 'stats_chat', 'stats_msg_id', 'last_edit'}}
broadcast_polls = {}
broadcast_counter = 0


def _blocked_list_view():
    """يبني (نص، أزرار) القائمة المحظورة المخصصة مع زر حذف خاص لكل عنصر."""
    domains = _custom_adult_domains()
    keywords = _custom_adult_keywords()
    text = "📋 **القائمة المحظورة المخصصة**\n\nاضغط 🗑️ بجانب أي عنصر لحذفه وحده.\n"
    rows = []
    if domains:
        text += "\n🌐 **المواقع:**\n" + "\n".join(f"• `{d}`" for d in domains) + "\n"
        for i, d in enumerate(domains):
            rows.append([InlineKeyboardButton(f"🗑️ 🌐 {d[:40]}", callback_data=f"sub_deldom_{i}")])
    if keywords:
        text += "\n🔤 **الكلمات:**\n" + "\n".join(f"• `{k}`" for k in keywords) + "\n"
        for i, k in enumerate(keywords):
            rows.append([InlineKeyboardButton(f"🗑️ 🔤 {k[:40]}", callback_data=f"sub_delkw_{i}")])
    if not domains and not keywords:
        text += "\n— لا يوجد عناصر مخصصة —\n"
    text += f"\n💡 النطاقات/الكلمات المدمجة مسبقاً ({len(ADULT_DOMAINS)} موقع) مفعّلة دائماً."
    if domains or keywords:
        rows.append([InlineKeyboardButton("🗑️ مسح الكل", callback_data="sub_clear_blocked")])
    rows.append([InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")])
    return text, InlineKeyboardMarkup(rows)


def _banned_list_view():
    """يبني (نص، أزرار) قائمة المحظورين: لكل واحد الاسم والمعرّف والجنس + زر رفع حظر."""
    rows_data = subdb.get_banned_users()
    if not rows_data:
        return ("✅ لا يوجد مستخدمون محظورون حالياً.",
                InlineKeyboardMarkup([[InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]]))
    text = f"🚫 **المحظورون ({len(rows_data)})**\n\n"
    kb = []
    for uid, reason, strikes in rows_data[:30]:
        u = subdb.find_user_by_id(uid)
        name = (u[2] if u and len(u) > 2 else None) or "مستخدم"
        gender = _gender_label(subdb.get_survey(uid).get('gender'))
        text += f"👤 {name} | 🆔 `{uid}` | {gender} | مخالفات: {strikes}\n"
        kb.append([InlineKeyboardButton(f"✅ رفع حظر: {name[:18]} ({uid})",
                                        callback_data=f"sub_unbanlist_{uid}")])
    if len(rows_data) > 30:
        text += f"\n… و{len(rows_data) - 30} آخرين."
    kb.append([InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")])
    return text, InlineKeyboardMarkup(kb)


def _binance_support_keyboard(binance_id, lang):
    """زر واحد لدعم المطور يَنسخ معرّف Binance تلقائياً عند الضغط (إن كان
    إصدار Pyrogram يدعم copy_text)، وإلا يعرض المعرّف في تنبيه لنسخه يدوياً."""
    label = t('support_dev_binance', lang)
    try:
        button = InlineKeyboardButton(label, copy_text=str(binance_id))
    except Exception:
        button = InlineKeyboardButton(label, callback_data="binance_info")
    return InlineKeyboardMarkup([[button]])


# ═══════════════════════════════════════════════════════════════
# الاشتراك الإجباري بالقنوات - Forced channel subscription
# ═══════════════════════════════════════════════════════════════

def _forced_channel_target(chat_id):
    """يحوّل chat_id المخزّن (نص) إلى صيغة مناسبة لـ Pyrogram (رقم أو @يوزر)."""
    s = str(chat_id)
    return int(s) if s.lstrip('-').isdigit() else s


async def _channel_is_verifiable(client, chat_id):
    """هل يستطيع البوت التحقق من أعضاء هذه القناة؟ (أي أنه مشرف فيها)."""
    try:
        me = await client.get_me()
        m = await client.get_chat_member(_forced_channel_target(chat_id), me.id)
        return m.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER)
    except Exception:
        return False


async def get_missing_forced_channels(client, user_id):
    """القنوات التي لم يشترك بها المستخدم فعلياً — تحقق حقيقي فقط.

    التحقق من العضوية في تلجرام يتطلب أن يكون البوت مشرفاً في القناة. لذلك:
    - قناة البوت مشرف فيها → تحقق حقيقي (يُمنع من ليس عضواً).
    - قناة لا يستطيع البوت التحقق منها (ليس مشرفاً) → تُتجاهَل ولا تُفرض،
      بدلاً من تمرير المستخدم تمريراً وهمياً (هذا كان سبب الخطأ السابق).
    """
    missing = []
    for ch in subdb.get_forced_channels():
        target = _forced_channel_target(ch[1])
        try:
            member = await client.get_chat_member(target, user_id)
            if member.status in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED):
                missing.append(ch)
        except UserNotParticipant:
            missing.append(ch)
        except Exception as e:
            # البوت ليس مشرفاً → لا يمكن التحقق → نتجاهل القناة (بلا تمرير وهمي)
            logger.warning(f"⚠️ تخطّي قناة اشتراك إجباري {ch[1]} (البوت ليس مشرفاً؟): {e}")
            continue
    return missing



def _forced_sub_keyboard(channels, lang):
    """يبني أزرار الاشتراك (زر لكل قناة) + زر التحقق."""
    rows = []
    for idx, ch in enumerate(channels, 1):
        username, url = ch[2], ch[4]
        link = url or (f"https://t.me/{username}" if username else None)
        if link:
            rows.append([InlineKeyboardButton(t('fsub_join_btn', lang, n=idx), url=link)])
    rows.append([InlineKeyboardButton(t('fsub_check_btn', lang), callback_data="fsub_check")])
    return InlineKeyboardMarkup(rows)


def forced_sub_enabled():
    """هل الاشتراك الإجباري مُفعّل؟ (افتراضياً مُفعّل)."""
    return subdb.get_setting('forced_sub_enabled', '1') == '1'


# ═══════════════════════════════════════════════════════════════
# قائمة الاستثناء (VIP) — أعضاء يحدّدهم الأدمن (أهل/أصدقاء):
# لا يصلهم البث الجماعي ولا رسائل التذكير (فلا يعرفون ما يُرسل للأعضاء)،
# ومعفيون من الاشتراك الإجباري. تُدار من لوحة الأدمن أو بأمر /exempt.
# ═══════════════════════════════════════════════════════════════

def _exempt_ids():
    """معرّفات أعضاء قائمة الاستثناء (من إعداد exempt_user_ids المفصول بفواصل)."""
    raw = subdb.get_setting('exempt_user_ids', '') or ''
    return {int(x) for x in (p.strip() for p in raw.split(',')) if x.isdigit()}


def _save_exempt_ids(ids):
    subdb.set_setting('exempt_user_ids', ','.join(str(i) for i in sorted(ids)))


def _add_exempt(uid):
    """يضيف عضواً لقائمة الاستثناء. يرجع True إن أُضيف (False إن كان موجوداً)."""
    ids = _exempt_ids()
    if uid in ids:
        return False
    ids.add(uid)
    _save_exempt_ids(ids)
    return True


def _remove_exempt(uid):
    """يحذف عضواً من قائمة الاستثناء. يرجع True إن حُذف."""
    ids = _exempt_ids()
    if uid not in ids:
        return False
    ids.discard(uid)
    _save_exempt_ids(ids)
    return True


def _broadcast_targets(gender='all', lang='all'):
    """جمهور البث الجماعي بعد استبعاد قائمة الاستثناء — تُستخدم في عدّادات
    شاشات البث وفي الإرسال الفعلي حتى تتطابق الأرقام مع الواقع."""
    exempt = _exempt_ids()
    return [u for u in subdb.get_target_users(gender, lang) if u not in exempt]


def _resolve_member_ref(ref):
    """يحوّل مدخل الأدمن (ID رقمي أو @username) إلى (user_id, الاسم).
    المعرّف الرقمي يُقبل حتى لو لم يكن العضو في قاعدة البيانات (يعمل الإعفاء
    فور دخوله)، أما اليوزر فيجب أن يكون عضواً معروفاً. يرجع (None, None) عند الفشل."""
    ref = (ref or '').strip()
    if ref.lstrip('-').isdigit():
        uid = int(ref)
        row = subdb.find_user_by_id(uid)
        return uid, (row[2] if row else None)
    row = subdb.find_user_by_username(ref)
    if row:
        return row[0], row[2]
    return None, None


async def enforce_forced_subscription(client, message, user_id, lang):
    """يفحص الاشتراك الإجباري؛ إن كان ناقصاً يعرض شاشة الاشتراك ويُرجع True
    (أي يجب إيقاف المعالجة). الأدمن وقائمة الاستثناء مُعفون، ويُحترم زر التفعيل/الإيقاف."""
    if not forced_sub_enabled():
        return False
    if is_admin(user_id):
        return False
    if user_id in _exempt_ids():
        return False
    missing = await get_missing_forced_channels(client, user_id)
    if not missing:
        return False
    await message.reply_text(
        t('fsub_required', lang),
        reply_markup=_forced_sub_keyboard(missing, lang)
    )
    return True


async def add_forced_channel_from_admin(client, message, user_id):
    """يضيف أي قناة/قروب (عام أو خاص) من رسالة الأدمن: @username أو رابط دعوة
    أو توجيه رسالة. يكتشف تلقائياً إن كان البوت مشرفاً (تحقق حقيقي) أم لا
    (قناة إعلانية)."""
    pending_downloads.pop(user_id, None)
    raw = (message.text or '').strip()

    chat_id = username = title = url = None

    # 1) توجيه رسالة من القناة/القروب (أفضل مصدر للمعلومات)
    fc = getattr(message, 'forward_from_chat', None)
    if fc:
        chat_id, username, title = fc.id, fc.username, fc.title
        url = f"https://t.me/{username}" if username else None
        if not url:
            # 🔒 قروب/قناة خاصة (بلا @username): ولّد رابط دعوة ليظهر زر
            # الانضمام للأعضاء — يتطلب أن يكون البوت مشرفاً بصلاحية «إضافة
            # أعضاء». مع المعرّف الحقيقي من التوجيه يصير الفرض تحققاً حقيقياً.
            try:
                url = await client.export_chat_invite_link(chat_id)
            except Exception as e:
                logger.warning(f"⚠️ تعذّر توليد رابط دعوة للخاص {chat_id}: {e}")
                await message.reply_text(
                    "🔒 هذا قروب/قناة **خاصة**، ولأعرضها للأعضاء أحتاج توليد "
                    "رابط دعوة — ولم أستطع.\n\n"
                    "✅ الحل: اجعل البوت **مشرفاً** فيها بصلاحية "
                    "**«دعوة المستخدمين عبر رابط»** ثم أعد توجيه رسالة منها، "
                    "وسيُفرض الاشتراك فيها بتحقق حقيقي."
                )
                return

    # 2) نص: رابط دعوة خاص أو @username/رابط عام
    if not chat_id and raw:
        token = raw
        if 't.me/' in token:
            token = token.split('t.me/')[-1].strip('/')
        if token.startswith('+') or token.startswith('joinchat/'):
            url = raw if raw.startswith('http') else f"https://t.me/{token}"
            # 🔒 جرّب حلّ رابط الدعوة لمعرّف حقيقي (ينجح إن كان البوت داخل
            # القروب) → فرض بتحقق حقيقي. وإلا يبقى زراً إعلانياً كما السابق.
            try:
                chat = await client.get_chat(url)
                chat_id, username, title = chat.id, chat.username, chat.title
            except Exception:
                chat_id = url  # المعرّف الفريد هو الرابط نفسه (إعلاني فقط)
                title = None
        else:
            uname = token.split('/')[0].split('?')[0].lstrip('@')
            try:
                chat = await client.get_chat('@' + uname)
                chat_id, username, title = chat.id, chat.username, chat.title
                url = f"https://t.me/{chat.username}"
            except Exception:
                # تعذّر الوصول → خزّنه كرابط عام (إعلاني)
                username, chat_id = uname, ('https://t.me/' + uname)
                url = 'https://t.me/' + uname

    if not url or not chat_id:
        await message.reply_text(
            "❌ لم أتعرّف على القناة/القروب.\n"
            "أرسل `@username` أو رابط الدعوة أو وجّه رسالة منها."
        )
        return

    # اكتشاف صلاحية البوت تلقائياً (هل يمكنه التحقق من الأعضاء؟)
    verifiable = False
    try:
        me = await client.get_me()
        await client.get_chat_member(_forced_channel_target(chat_id), me.id)
        verifiable = True
    except Exception:
        verifiable = False

    if verifiable:
        note = "✅ البوت مشرف هنا → **تحقق حقيقي** من اشتراك الأعضاء."
    else:
        note = ("⚠️ البوت **ليس مشرفاً** هنا، ولا يمكن التحقق من الاشتراك (قيد تلجرام).\n"
                "هذه القناة **لن تُفرض** حتى تجعل البوت مشرفاً فيها.")
        if isinstance(chat_id, str) and chat_id.startswith('http'):
            # رابط دعوة خاص لم يُحل لمعرّف حقيقي — أرشد الأدمن للطريقة المضمونة
            note += ("\n\n🔒 لقروب خاص بتحقق حقيقي: اجعل البوت مشرفاً فيه "
                     "ثم **وجّه لي رسالة منه** بدل رابط الدعوة.")

    if subdb.add_forced_channel(chat_id, username, title, url):
        label = title or (f"@{username}" if username else url)
        await message.reply_text(f"✅ **تمت الإضافة:** {label}\n\n{note}")
    else:
        await message.reply_text("ℹ️ هذه القناة/القروب مُضافة مسبقاً.")


# نظام تتبع الأخطاء
user_errors = {}  # {error_id: {'user_id': ..., 'error': ..., 'url': ..., 'time': ..., 'status': 'pending'}}
error_counter = 0


def get_channel_id(env_key):
    """يقرأ معرّف القناة من .env ويحوّله إلى رقم صحيح.

    Pyrogram يرفض معرّف القناة الرقمي إذا مُرّر كنص (سلسلة أرقام) ويُظهر
    PEER_ID_INVALID. لذا نحوّل '-1001234567890' إلى int. أما اسم المستخدم
    (مثل @channel) فيُترك كما هو.
    """
    value = (os.getenv(env_key) or '').strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value  # اسم مستخدم للقناة مثل @mychannel

async def send_error_to_admin(user_id, user_name, error_message, url, error_traceback=None):
    """إرسال تنبيه لقناة سجلات الأخطاء عند حدوث خطأ للمستخدم"""
    global error_counter
    error_counter += 1
    error_id = f"err_{error_counter}"
    
    # حفظ الخطأ
    user_errors[error_id] = {
        'user_id': user_id,
        'user_name': user_name,
        'error': error_message,
        'url': url,
        'traceback': error_traceback,
        'time': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'status': 'pending'
    }
    
    # إرسال لقناة سجلات الأخطاء
    error_channel_id = get_channel_id("ERROR_LOG_CHANNEL_ID")
    
    if not error_channel_id:
        logger.warning("⚠️ ERROR_LOG_CHANNEL_ID غير موجود في .env")
        return
    
    # Verify bot has access to error log channel
    try:
        await app.get_chat(error_channel_id)
    except Exception as access_error:
        logger.error(f"❌ البوت لا يملك صلاحيات لقناة الأخطاء {error_channel_id}: {access_error}")
        logger.info(f"💡 تأكد من إضافة البوت كمدير في قناة سجلات الأخطاء")
        return
    
    # User link (blue clickable name) - مؤمّن من رموز HTML
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(str(user_name or "مستخدم"))}</a>'

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تم الإصلاح", callback_data=f"resolve_{error_id}")]
    ])

    try:
        # بناء الرسالة الأساسية (HTML بالكامل + تأمين كل القيم بـ html.escape
        # حتى لا يكسر الرابط/نص الخطأ/الـtraceback تحليل HTML — مثل <module>)
        error_text = (
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔔 <b>خطأ جديد من مستخدم</b>\n\n"
            f"👤 <b>المستخدم:</b> {user_link}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"🔗 <b>الرابط:</b> <code>{html.escape(str(url))}</code>\n\n"
            f"❌ <b>الخطأ:</b>\n<code>{html.escape(str(error_message)[:300])}</code>\n\n"
        )

        # إضافة traceback إذا كان متوفراً
        if error_traceback:
            # تقصير traceback إذا كان طويلاً جداً (Telegram limit)
            traceback_text = error_traceback[:800] if len(error_traceback) > 800 else error_traceback
            error_text += f"📋 <b>سجلات الخطأ (Traceback):</b>\n<code>{html.escape(traceback_text)}</code>\n\n"

        error_text += (
            f"🆔 Error ID: <code>{error_id}</code>\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        await app.send_message(
            chat_id=error_channel_id,
            text=error_text,
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.HTML
        )
        logger.info(f"📨 تم إرسال تنبيه خطأ لقناة السجلات: {error_id}")
    except Exception as e:
        logger.error(f"فشل إرسال تنبيه لقناة الأخطاء: {e}")

async def send_new_member_notification(user_id, user_name, username, join_time):
    """إرسال إشعار لقناة الأعضاء الجدد عند انضمام عضو جديد"""
    try:
        channel_id = get_channel_id('NEW_MEMBERS_CHANNEL_ID')
        
        if not channel_id:
            logger.warning("⚠️ NEW_MEMBERS_CHANNEL_ID غير موجود في .env")
            return
        
        # Try to get chat to verify bot has access
        try:
            await app.get_chat(channel_id)
        except Exception as access_error:
            logger.error(f"❌ البوت لا يملك صلاحيات للقناة {channel_id}: {access_error}")
            logger.info(f"💡 تأكد من إضافة البوت كمدير في القناة")
            return
        
        # Format username (مؤمّن من رموز HTML)
        username_text = f"@{html.escape(str(username))}" if username else "⚠️ لا يوجد يوزر"

        # User link (blue clickable name) - مع تأمين الاسم
        user_link = f'<a href="tg://user?id={user_id}">{html.escape(str(user_name or "مستخدم"))}</a>'

        # Message text
        notification = f"""━━━━━━━━━━━━━━━━━━━━━━
🎉 عضو جديد انضم للبوت!

👤 معلومات العضو
╔═ الاسم: {user_link}
╠═ اليوزر: {username_text}
╚═ ID: <code>{user_id}</code>

🕐 وقت الانضمام: {join_time}
━━━━━━━━━━━━━━━━━━━━━━"""
        
        await app.send_message(
            chat_id=channel_id,
            text=notification,
            parse_mode=enums.ParseMode.HTML
        )
        
        logger.info(f"✅ تم إرسال إشعار عضو جديد للقناة: {user_name} ({user_id})")
        
    except Exception as e:
        logger.error(f"❌ خطأ في إرسال إشعار العضو الجديد: {str(e)}")


# حالة انتظار cookies من الأدمن
waiting_for_cookies = {}  # {user_id: platform}

# تتبع صلاحية الـ cookies
cookies_expiry = {}  # {platform: {'uploaded': timestamp, 'expires': timestamp, 'notified': bool}}

# ═══════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════


# عملاء يوتيوب: android_vr لا يتطلب PO token؛ نتجنّب 'tv' لأنه يبلّغ DRM زوراً بدون كوكيز
# و'web_embedded' يسبب خطأ إعداد. formats=missing_pot يسمح باستخدام الصيغ المحجوبة بلا توكن.
# عملاء يوتيوب: قابلة للضبط عبر .env (YT_PLAYER_CLIENTS) لموازنة السرعة/النجاح.
# تقليل العدد يسرّع ظهور أزرار الجودة (كل عميل = طلب شبكة)، لكن قد يقلّل النجاح
# لبعض الفيديوهات. الافتراضي عملاء قليلون وسريعون نسبياً.
_yt_clients_env = os.getenv("YT_PLAYER_CLIENTS", "").strip()
YT_PLAYER_CLIENTS = [c.strip() for c in _yt_clients_env.split(',') if c.strip()] \
    or ['default', 'android_vr', 'web_safari', 'mweb']

# عدد أجزاء التحميل المتوازية (يسرّع تحميل يوتيوب/الأجزاء). قيمة معتدلة تتفادى
# الحظر من المنصة (>16 من نفس الـIP قد يُحظر).
YTDLP_CONCURRENT_FRAGMENTS = max(1, int(os.getenv("YTDLP_CONCURRENT_FRAGMENTS", "4")))


def _youtube_extractor_args():
    return {'youtube': {'player_client': list(YT_PLAYER_CLIENTS), 'formats': ['missing_pot']}}


# سبب فشل آخر استخراج ضمن نفس المهمة (task) — يُقرأ فور رجوع get_video_info.
# ContextVar معزول لكل مهمة async، فلا يتداخل بين المستخدمين المتزامنين.
_last_info_error = contextvars.ContextVar('_last_info_error', default=None)


def _extract_direct_media(direct_url: str, title: str = 'Video'):
    """يستخرج معلومات yt-dlp من رابط وسائط مباشر (mp4) ويمنحه عنواناً نظيفاً.
    يُستدعى داخل executor (طلب شبكي متزامن)."""
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True,
            'nocheckcertificate': _YTDLP_NO_CHECK_CERT}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(direct_url, download=False)
    if info is not None:
        # عنوان CDN معرّف طويل غير مفيد → عنوان واضح للمستخدم
        info['title'] = title
    return info


async def resolve_instagram_direct(url: str):
    """يحل رابط إنستغرام إلى رابط الفيديو المباشر عبر مرآة عامة (بلا كوكيز).
    يعيد رابط mp4 المباشر أو None. طلب شبكي متزامن يُنفَّذ خارج حلقة الأحداث."""
    if _platform_of(url) != 'instagram':
        return None
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, resolve_instagram_media, url)


async def _instagram_video_fallback(url: str):
    """خطة بديلة لإنستغرام عند فشل yt-dlp (الوصول المجهول محجوب): يحل الرابط
    لملف فيديو مباشر عبر مرآة عامة ثم يستخرج معلوماته. يعيد dict أو None.

    حين تحيل المرآة لصفحة إنستغرام نفسها (جدار الدخول) فالمنشور خاص/محذوف —
    يُسجَّل ذلك في _last_info_error ليعرض البوت رسالة واضحة بدل «رابط غير صحيح»."""
    if _platform_of(url) != 'instagram':
        return None
    loop = asyncio.get_event_loop()
    direct, unavailable = await loop.run_in_executor(
        None, instagram_mirror_lookup, url)
    if not direct:
        if unavailable:
            _last_info_error.set('ig_unavailable')
        return None
    try:
        info = await loop.run_in_executor(
            None, lambda: _extract_direct_media(direct, 'Instagram Video')
        )
        if info:
            logger.info("✅ إنستغرام عبر المرآة العامة (بديل yt-dlp، بلا كوكيز)")
        return info
    except Exception as e:
        logger.warning(f"⚠️ فشل استخراج إنستغرام البديل: {e}")
        return None


async def resolve_tiktok_direct(url: str):
    """يحل رابط تيك توك إلى رابط الفيديو المباشر عبر مرآة عامة (بلا كوكيز).
    يعيد رابط mp4 المباشر أو None. طلب شبكي متزامن يُنفَّذ خارج حلقة الأحداث."""
    if _platform_of(url) != 'tiktok':
        return None
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, resolve_tiktok_media, url)


async def _tiktok_video_fallback(url: str):
    """خطة بديلة لتيك توك عند فشل yt-dlp (حجب IP الخادم): يحل الرابط لملف فيديو
    مباشر عبر مرآة عامة ثم يستخرج معلوماته. يعيد dict أو None."""
    direct = await resolve_tiktok_direct(url)
    if not direct:
        return None
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(
            None, lambda: _extract_direct_media(direct, 'TikTok Video')
        )
        if info:
            logger.info("✅ تيك توك عبر المرآة العامة (بديل yt-dlp، بلا كوكيز)")
        return info
    except Exception as e:
        logger.warning(f"⚠️ فشل استخراج تيك توك البديل: {e}")
        return None


async def _twitter_video_fallback(url: str):
    """خطة بديلة لتويتر/X عند فشل yt-dlp (حجب/تقييد): يحل الرابط لملف فيديو مباشر
    عبر مرآة عامة ثم يستخرج معلوماته. يعيد dict أو None.

    🔞 حماية: yt-dlp يفشل مع التغريدات الحسّاسة (NSFW) بلا كوكيز، فكانت المرآة
    تعيد الفيديو بمعلومات نظيفة (بلا age_limit/عنوان) يعبر فلتر المحتوى. الآن
    نقرأ علم الحساسية من رد المرآة نفسه ونرفض المحتوى الحسّاس ما دام فلتر
    المحتوى الإباحي مفعّلاً — فيصل المستخدم رسالة «محتوى مقيّد» الواضحة."""
    if _platform_of(url) != 'twitter':
        return None
    loop = asyncio.get_event_loop()
    direct, sensitive = await loop.run_in_executor(None, twitter_mirror_lookup, url)
    if not direct:
        return None
    if sensitive and adult_filter_enabled():
        logger.info("🔞 تغريدة حسّاسة (NSFW) — رُفض مسار المرآة (فلتر المحتوى مفعّل)")
        _last_info_error.set('restricted')
        return None
    try:
        info = await loop.run_in_executor(
            None, lambda: _extract_direct_media(direct, 'Twitter Video')
        )
        if info:
            logger.info("✅ تويتر عبر المرآة العامة (بديل yt-dlp، بلا كوكيز)")
        return info
    except Exception as e:
        logger.warning(f"⚠️ فشل استخراج تويتر البديل: {e}")
        return None


async def resolve_pinterest_direct(url: str):
    """يحل رابط Pin بينتريست إلى رابط الفيديو المباشر عبر واجهة بينتريست العامة
    (بلا كوكيز). يعيد الرابط المباشر أو None. طلب شبكي متزامن يُنفَّذ خارج حلقة الأحداث."""
    if _platform_of(url) != 'pinterest':
        return None
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, resolve_pinterest_media, url)


async def _pinterest_video_fallback(url: str):
    """خطة بديلة لبينتريست عند فشل yt-dlp (تغييرات الموقع/حجب): يحل الرابط لملف
    فيديو مباشر عبر واجهة بينتريست العامة ثم يستخرج معلوماته. يعيد dict أو None."""
    direct = await resolve_pinterest_direct(url)
    if not direct:
        return None
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(
            None, lambda: _extract_direct_media(direct, 'Pinterest Video')
        )
        if info:
            logger.info("✅ بينتريست عبر الواجهة العامة (بديل yt-dlp، بلا كوكيز)")
        return info
    except Exception as e:
        logger.warning(f"⚠️ فشل استخراج بينتريست البديل: {e}")
        return None


async def resolve_substack_direct(url: str):
    """يحل رابط ملاحظة Substack إلى رابط الفيديو المباشر (وسيط /src) عبر واجهة
    Substack العامة بلا كوكيز. يعيد الرابط أو None (ومنه المحتوى الصريح حين
    يكون فلتر المحتوى الإباحي مفعّلاً). طلب شبكي خارج حلقة الأحداث."""
    if not is_substack_note(url):
        return None
    loop = asyncio.get_event_loop()
    direct, _title, explicit = await loop.run_in_executor(None, resolve_substack_note, url)
    if direct and explicit and adult_filter_enabled():
        logger.info("🔞 فيديو Substack صريح — رُفض (فلتر المحتوى مفعّل)")
        return None
    return direct


async def _substack_video_fallback(url: str):
    """خطة بديلة لملاحظات Substack: yt-dlp لا يدعمها أصلاً (صفحة جافاسكربت
    وفيديو Mux موقّع) → واجهة Substack العامة تعطي رابط الفيديو + العنوان.
    الوسائط المصنّفة صريحة لدى Substack تُرفض ما دام فلتر المحتوى مفعّلاً."""
    if not is_substack_note(url):
        return None
    loop = asyncio.get_event_loop()
    direct, title, explicit = await loop.run_in_executor(None, resolve_substack_note, url)
    if not direct:
        return None
    if explicit and adult_filter_enabled():
        logger.info("🔞 فيديو Substack صريح — رُفض مسار الواجهة (فلتر المحتوى مفعّل)")
        _last_info_error.set('restricted')
        return None
    try:
        info = await loop.run_in_executor(
            None, lambda: _extract_direct_media(direct, title or 'Substack Video')
        )
        if info:
            logger.info("✅ ملاحظة Substack عبر الواجهة العامة (بلا كوكيز)")
        return info
    except Exception as e:
        logger.warning(f"⚠️ فشل استخراج ملاحظة Substack: {e}")
        return None


async def get_video_info(url: str):
    """استخراج معلومات الفيديو"""
    _last_info_error.set(None)
    try:
        # حماية SSRF: ارفض الروابط غير http/https أو التي تشير لعنوان داخلي
        if not is_safe_url(url):
            logger.warning(f"🚫 رابط غير آمن أو داخلي مرفوض: {url[:100]}")
            return None
        # اختيار ملف cookies المطابق لمنصة الرابط (مهم للستوري الخاص)
        cookie_file = get_cookie_file_for_url(url)
        is_youtube = any(m in url.lower() for m in PLATFORM_URL_MARKERS['youtube'])
        is_facebook = any(m in url.lower() for m in PLATFORM_URL_MARKERS['facebook'])
        is_instagram = any(m in url.lower() for m in PLATFORM_URL_MARKERS['instagram'])

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'socket_timeout': 30,  # تقليل timeout لاستجابة أسرع
            'extract_flat': False,  # نحتاج معلومات كاملة
            'nocheckcertificate': _YTDLP_NO_CHECK_CERT,
            # رابط فيديو ضمن قائمة (watch?v=..&list=..) يُعامل كفيديو واحد؛
            # فقط روابط القوائم الصِّرفة تُرجع entries. ونحدّ عدد المقاطع المستخرَجة.
            'noplaylist': True,
            'playlistend': PLAYLIST_MAX,
            # لا تفشل استخراج المعلومات بسبب مشاكل الصيغ (مهم ليوتيوب مع الكوكيز)
            'ignore_no_formats_error': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
        }

        # استخدام cookies المنصة للتعرف على الفيديو (يشمل الستوري الذي يتطلب تسجيل دخول)
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file
            logger.info(f"🍪 Using cookies for video info extraction: {cookie_file}")

        # ليوتيوب: جرّب عملاء متعددين + السماح بالصيغ المحجوبة لتفادي حجب الصيغ (PO token)
        if is_youtube:
            ydl_opts['extractor_args'] = _youtube_extractor_args()

        loop = asyncio.get_event_loop()

        def extract(use_cookies=True):
            o = dict(ydl_opts)
            if not use_cookies:
                o.pop('cookiefile', None)
            with yt_dlp.YoutubeDL(o) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            if is_facebook and cookie_file:
                # كوكيز تسجيل الدخول تجعل فيسبوك يحقن فيديو إعلان بدل الفيديو
                # المطلوب أحياناً → جرّب بدون كوكيز أولاً (يكفي للمحتوى العام
                # وبدون دخول لا إعلانات)، وعند الفشل (ستوري/محتوى يتطلب
                # تسجيل دخول) أعد المحاولة بالكوكيز.
                try:
                    return await loop.run_in_executor(None, lambda: extract(False))
                except Exception:
                    logger.warning("⚠️ فشل فيسبوك بدون كوكيز، إعادة المحاولة بالكوكيز...")
                    return await loop.run_in_executor(None, lambda: extract(True))
            return await loop.run_in_executor(None, lambda: extract(True))
        except Exception as e:
            # يوتيوب مع الكوكيز قد يفشل بسبب حجب الصيغ → أعد المحاولة بدون كوكيز
            if cookie_file and is_youtube and _is_youtube_cookie_issue(e):
                logger.warning("⚠️ فشل يوتيوب مع الكوكيز، إعادة المحاولة بدون كوكيز...")
                return await loop.run_in_executor(None, lambda: extract(False))
            # فيسبوك بكوكيز فاسدة قد يكسر استخراج المحتوى العام → أعد المحاولة بدون كوكيز
            if cookie_file and is_facebook and _is_facebook_cookie_issue(e):
                logger.warning("⚠️ فشل فيسبوك مع الكوكيز (Cannot parse data)، إعادة المحاولة بدون كوكيز...")
                return await loop.run_in_executor(None, lambda: extract(False))
            # ملف كوكيز تالف (صيغة غير صحيحة) يفشل لأي منصة → أعد المحاولة بدون كوكيز
            if cookie_file and _is_cookie_file_issue(e):
                logger.warning(f"⚠️ ملف الكوكيز تالف/غير صالح ({cookie_file})، إعادة المحاولة بدون كوكيز...")
                return await loop.run_in_executor(None, lambda: extract(False))
            # إنستغرام: كوكيز منتهية/خارج الحساب تُرجع 404 لمنشور عام يعمل بلا كوكيز
            # → أعد المحاولة بدون كوكيز قبل اللجوء للمرايا (أدقّ وأضمن للفيديو الأصلي).
            # إن كان المحتوى خاصاً فعلاً فستفشل بلا كوكيز أيضاً فنكمل للمعالج الخارجي.
            if cookie_file and is_instagram:
                logger.warning("⚠️ فشل إنستغرام مع الكوكيز، إعادة المحاولة بدون كوكيز...")
                try:
                    return await loop.run_in_executor(None, lambda: extract(False))
                except Exception:
                    pass
            raise
    except Exception as e:
        error_msg = str(e)
        # محتوى مقيّد بالعمر/حسّاس على المنصة → سجّل السبب ليعرضه المستدعي بوضوح
        if _is_restricted_content_error(error_msg):
            _last_info_error.set('restricted')
            logger.warning(f"🔞 محتوى مقيّد/حسّاس يتعذّر استخراجه: {error_msg[:200]}")
            return None
        # 🔞 خطأ NSFW صريح (تغريدات X الحسّاسة: "NSFW tweet requires
        #    authentication") مع فلتر المحتوى مفعّلاً → أوقف كل مسارات المرايا
        #    البديلة قبل أن تعيد الفيديو بمعلومات نظيفة تعبر الفلتر
        if adult_filter_enabled() and 'nsfw' in error_msg.lower():
            _last_info_error.set('restricted')
            logger.warning(f"🔞 محتوى NSFW محجوب (الفلتر مفعّل): {error_msg[:150]}")
            return None
        # معالجة خاصة لأخطاء Facebook parsing
        if 'Cannot parse data' in error_msg or 'facebook' in error_msg.lower():
            logger.error(f"خطأ Facebook parse: {error_msg[:200]}")
        else:
            logger.error(f"خطأ في استخراج المعلومات: {e}")
        # 🎯 خطة بديلة لإنستغرام: الوصول المجهول محجوب فيعجز yt-dlp عن الريلز/
        #    المنشورات → جرّب مرآة عامة تعيد رابط الفيديو المباشر (بلا كوكيز)
        ig = await _instagram_video_fallback(url)
        if ig:
            return ig
        # 🎯 خطة بديلة لتيك توك: حجب IP الخادم ("Your IP address is blocked")
        #    يفشل yt-dlp حتى مع كوكيز → جرّب مرآة عامة بعنوان IP مختلف
        tk = await _tiktok_video_fallback(url)
        if tk:
            return tk
        # 🎯 خطة بديلة لتويتر/X: حجب/تقييد يفشل yt-dlp → جرّب مرآة عامة (mp4 مباشر)
        tw = await _twitter_video_fallback(url)
        if tw:
            return tw
        # 🎯 خطة بديلة لبينتريست: فشل yt-dlp (تغييرات الموقع/حجب) → واجهة بينتريست
        #    العامة تعيد رابط الفيديو المباشر بلا كوكيز
        pn = await _pinterest_video_fallback(url)
        if pn:
            return pn
        # 🎯 ملاحظات Substack: yt-dlp لا يدعمها → واجهة Substack العامة (بلا كوكيز)
        sb = await _substack_video_fallback(url)
        if sb:
            return sb
        return None


# ═══════════════════════════════════════════════════════════════
# تحميل صور إنستغرام/تيك توك/بينتريست (كاروسيل/سلايدشو) عبر gallery-dl
# yt-dlp يتجاهل الصور (يسقط الصيغ والمصغّرات للمنشورات المصوّرة)، لذا
# نستخدم gallery-dl المتخصص في معارض الصور ثم نرسلها كألبوم في تلجرام.
# ═══════════════════════════════════════════════════════════════

def _fmts_have_video(formats):
    """هل ضمن الصيغ صيغةُ فيديو؟

    نعتبر أي صيغة فيديو إلا إذا كانت صوتاً صريحاً (vcodec=='none')، لأن بعض
    منصات الفيديو (مثل ريلز إنستغرام) قد لا تضبط vcodec فتظهر None. أما
    منشورات الصور فلا تملك صيغاً إطلاقاً (إنستغرام) أو صيغة صوت سلايدشو فقط
    (تيك توك، vcodec=='none')، فيرجع False ونوجّهها لمسار الصور.
    """
    for f in formats or []:
        vcodec = (f.get('vcodec') or '').lower()
        if vcodec == 'none':
            continue  # صوت صريح فقط (مثل صوت سلايدشو تيك توك)
        return True
    return False


def _info_has_video(info):
    """يحدّد إن كان منشور yt-dlp يحتوي فيديو فعلياً.

    للمنشورات المصوّرة فقط (سلايدشو تيك توك / كاروسيل صور إنستغرام) لا توجد
    صيغة فيديو، فنوجّهها لمسار الصور. أما المنشورات المختلطة (صور+فيديو) فتبقى
    على مسار الفيديو الحالي دون تغيير في السلوك.
    """
    if not info:
        return False
    entries = info.get('entries')
    if entries:
        for e in entries:
            if e and _fmts_have_video(e.get('formats')):
                return True
        return False
    return _fmts_have_video(info.get('formats'))


def _download_images_with_gallery_dl(url, dest_dir, cookie_file=None):
    """ينزّل صور المنشور عبر gallery-dl إلى dest_dir (بشكل مسطّح) ويعيد قائمة
    مسارات الصور مرتبة. الفيديو/الصوت/الأغلفة معطّلة فنحصل على الصور فقط؛
    إن لم تكن هناك صور (منشور فيديو) تعود القائمة فارغة."""
    os.makedirs(dest_dir, exist_ok=True)
    cmd = [
        sys.executable, '-m', 'gallery_dl',
        '--quiet', '--no-mtime',
        '--directory', dest_dir,        # ضع كل الملفات مباشرة هنا (مسطّح)
        '--range', f'1-{GALLERY_DL_MAX_IMAGES}',
        '-o', 'tiktok.videos=false',
        '-o', 'tiktok.audio=false',
        '-o', 'tiktok.covers=false',
        '-o', 'instagram.videos=false',
        '-o', 'pinterest.videos=false',
        '-o', 'twitter.videos=false',
    ]
    if cookie_file:
        cmd += ['--cookies', cookie_file]
    cmd.append(url)
    proc = None
    try:
        proc = subprocess.run(cmd, timeout=180, capture_output=True)
    except subprocess.TimeoutExpired:
        logger.warning("⏱️ انتهت مهلة gallery-dl أثناء تحميل الصور")
    except Exception as e:
        logger.error(f"❌ خطأ في تشغيل gallery-dl: {e}")
    try:
        files = [
            os.path.join(dest_dir, f) for f in os.listdir(dest_dir)
            if f.lower().endswith(_IMAGE_EXTS)
            and os.path.isfile(os.path.join(dest_dir, f))
        ]
    except FileNotFoundError:
        files = []
    files.sort()
    # لم يجلب gallery-dl أي صورة: سجّل سببه الحقيقي (تسجيل دخول مطلوب/حجب IP/
    # منشور فيديو) بدل ابتلاعه بصمت — يظهر الخطأ في السجلات بدل "رابط غير صحيح"
    if not files and proc is not None:
        err = (proc.stderr or b'').decode('utf-8', 'ignore').strip()
        out = (proc.stdout or b'').decode('utf-8', 'ignore').strip()
        detail = (err or out or 'لا مخرجات').replace('\n', ' | ')[:400]
        has_cookies = 'نعم' if cookie_file else 'لا'
        logger.warning(
            f"🖼️ gallery-dl لم يُرجع صوراً (rc={proc.returncode}, كوكيز={has_cookies}) "
            f"لـ {url[:80]} — السبب: {detail}"
        )
    return files


def _download_images_from_urls(image_urls, dest_dir):
    """ينزّل قائمة روابط صور مباشرة إلى dest_dir ويعيد مسارات الملفات مرتّبة.
    يُستخدم كبديل لصور تيك توك/إنستغرام عبر المرآة حين يفشل gallery-dl."""
    import urllib.request
    os.makedirs(dest_dir, exist_ok=True)
    ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    paths = []
    for i, src in enumerate(image_urls[:GALLERY_DL_MAX_IMAGES], 1):
        try:
            ext = os.path.splitext(src.split('?', 1)[0])[1].lower()
            if ext not in _IMAGE_EXTS:
                ext = '.jpg'
            dest = os.path.join(dest_dir, f"{i:03d}{ext}")
            req = urllib.request.Request(src, headers={'User-Agent': ua})
            with urllib.request.urlopen(req, timeout=30) as resp, open(dest, 'wb') as fh:
                shutil.copyfileobj(resp, fh)
            if os.path.getsize(dest) > 0:
                paths.append(dest)
        except Exception as e:
            logger.warning(f"⚠️ فشل تنزيل صورة من المرآة العامة: {e}")
    return paths


# امتدادات الفيديو المقبولة لوسائط التغريدة المباشرة (غيرها يُحفظ mp4)
_TWEET_VIDEO_EXTS = ('.mp4', '.mov', '.webm')


def _download_tweet_media_files(items, dest_dir):
    """ينزّل وسائط تغريدة (صور وفيديوهات معاً) من روابطها المباشرة إلى dest_dir
    بترتيبها الأصلي في التغريدة، ويعيد قائمة (النوع، المسار). كل عنصر
    {'type': 'photo'|'video', 'url': ...} كما تعيده twitter_mirror_media.
    العنصر الذي يفشل تنزيله يُتخطّى (لا نُفشِل الألبوم كله)."""
    import urllib.request
    os.makedirs(dest_dir, exist_ok=True)
    ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    out = []
    for i, it in enumerate(items[:GALLERY_DL_MAX_IMAGES], 1):
        kind, src = it.get('type'), it.get('url')
        if kind not in ('photo', 'video') or not src:
            continue
        try:
            ext = os.path.splitext(src.split('?', 1)[0])[1].lower()
            if kind == 'photo' and ext not in _IMAGE_EXTS:
                ext = '.jpg'
            elif kind == 'video' and ext not in _TWEET_VIDEO_EXTS:
                ext = '.mp4'
            dest = os.path.join(dest_dir, f"{i:03d}{ext}")
            req = urllib.request.Request(src, headers={'User-Agent': ua})
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, 'wb') as fh:
                shutil.copyfileobj(resp, fh)
            if os.path.getsize(dest) > 0:
                out.append((kind, dest))
        except Exception as e:
            logger.warning(f"⚠️ فشل تنزيل وسيط تغريدة ({kind}): {e}")
    return out


# مرايا إنستغرام العامة (InstaFix) لجلب صور الكاروسيل بلا كوكيز — نفس المرايا
# المستخدمة للفيديو. تُضبط بمتغيّر البيئة INSTAGRAM_PROXY_HOSTS (مفصولة بفواصل).
_INSTAGRAM_IMG_PROXY_HOSTS = [
    h.strip() for h in os.getenv(
        'INSTAGRAM_PROXY_HOSTS', 'kkinstagram.com'
    ).split(',') if h.strip()
]


def _fetch_mirror_image_url(proxy_url, ua, timeout):
    """يطلب رابط مرآة إنستغرام ويعيد رابط الصورة النهائي على CDN إن كان المحتوى
    صورة فعلاً وآمناً، وإلا None (404/صفحة هبوط/فيديو)."""
    import urllib.request
    try:
        req = urllib.request.Request(proxy_url, headers={
            'User-Agent': ua, 'Accept': '*/*',
        })
        # urlopen يتبع التوجيه؛ geturl() = الرابط النهائي للصورة على CDN
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get_content_type() or '').lower()
            final = resp.geturl()
    except Exception:
        return None
    if ctype.startswith('image/') and is_safe_url(final):
        return final
    return None


def _is_instagram_video_only_url(url):
    """هل الرابط ريل/IGTV إنستغرام (reel|reels|tv)؟ هذه الأنواع فيديو دائماً وليست
    منشور صور، فنستبعدها من مسار الصور كي لا تُرسَل صورة الغلاف بدل الفيديو."""
    import re
    from urllib.parse import urlparse as _urlparse
    if _platform_of(url) != 'instagram':
        return False
    try:
        path = _urlparse(url).path
    except Exception:
        return False
    return bool(re.search(r'/(?:reel|reels|tv)/[A-Za-z0-9_-]+', path, re.I))


def resolve_instagram_images(url, timeout=20):
    """يعيد قائمة روابط صور منشور إنستغرام عبر مرآة InstaFix العامة بلا كوكيز،
    لتُحمَّل حين يعجز gallery-dl عن جلبها (تسجيل دخول مطلوب/حجب IP).

    تختلف المرايا: بعضها يدعم فهرسة الكاروسيل (/p/{sc}/{n}) فنجمع كل الصور، وبعضها
    (مثل kkinstagram) يعطي أول صورة فقط عبر المسار المجرّد (/p/{sc}). لذا:
      1) نجرّب الفهرسة على كل مرآة — أول مرآة تدعمها تعيد الألبوم كاملاً.
      2) وإلا نجلب أول صورة عبر المسار المجرّد (أفضل من رسالة فشل).

    تعيد قائمة فارغة لغير روابط المنشورات أو عند أي فشل، فيبقى السلوك دون تغيير."""
    import re
    from urllib.parse import urlparse as _urlparse
    low = (url or '').lower()
    if not any(h in low for h in ('instagram.com', 'instagr.am')):
        return []
    try:
        path = _urlparse(url).path
    except Exception:
        return []
    # الريلز/IGTV (reel|reels|tv) فيديو دائماً — لو أخفق مسار الفيديو فإعادة صورة
    # الغلاف من المرآة تضلّل المستخدم (يستقبل "صورة" بدل فيديو). لذا نقتصر هنا على
    # منشورات /p/ وحدها (كاروسيل صور/صورة)، ونترك الريلز لمسار الفيديو ورسالة الفشل.
    m = re.search(r'/p/([A-Za-z0-9_-]+)', path, re.I)
    if not m:
        return []  # ريل/IGTV/ستوري/بروفايل — ليس منشور صور، لا مرآة صور له
    shortcode = m.group(1)
    ua = 'Mozilla/5.0 (compatible; TelegramBot)'

    # (1) مرايا تدعم فهرسة الكاروسيل: اجمع كل عناصرها حتى أول فشل
    for host in _INSTAGRAM_IMG_PROXY_HOSTS:
        image_urls, seen = [], set()
        for n in range(1, GALLERY_DL_MAX_IMAGES + 1):
            final = _fetch_mirror_image_url(
                f"https://{host}/p/{shortcode}/{n}", ua, timeout)
            if not final or final in seen:
                break  # نهاية الكاروسيل أو مرآة لا تدعم الفهرسة
            seen.add(final)
            image_urls.append(final)
        if image_urls:
            logger.info(
                f"🎯 صور إنستغرام عبر {host} (مفهرس): {len(image_urls)} صورة (بلا كوكيز)")
            return image_urls

    # (2) مرآة بلا فهرسة (kkinstagram): على الأقل أول صورة من المسار المجرّد
    for host in _INSTAGRAM_IMG_PROXY_HOSTS:
        final = _fetch_mirror_image_url(
            f"https://{host}/p/{shortcode}", ua, timeout)
        if final:
            logger.info(
                f"🎯 صورة إنستغرام عبر {host} (أول صورة فقط، بلا كوكيز): {final[:80]}")
            return [final]
    return []


def resolve_instagram_images_ytdlp(url):
    """يستخرج روابط كل صور كاروسيل إنستغرام عبر yt-dlp بلا كوكيز، ويعيدها مرتّبة.

    لماذا هذا المسار: gallery-dl يتطلّب تسجيل دخول (يُحوّل لصفحة الدخول بلا كوكيز
    وللرئيسية بكوكيز منتهية)، ومرايا InstaFix العامة تعيد أول صورة فقط أو ماتت.
    أما yt-dlp — مع ignore_no_formats_error لأن الصور ليست "صيغ فيديو" — فيعيد
    منشور الكاروسيل كعناصر (entries)، لكل عنصر رابط صورة CDN مستقل. وبلا كوكيز
    لأن كوكيز الدخول المنتهية تكسر المحتوى العام (نفس سبب فشل الفيديو).

    يعيد قائمة روابط صور (حتى GALLERY_DL_MAX_IMAGES)، أو فارغة لغير إنستغرام/عند
    الفشل — فيُكمل المتصل لمرآة الصورة الواحدة كخطة أخيرة."""
    if _platform_of(url) != 'instagram':
        return []
    opts = {
        'quiet': True, 'no_warnings': True, 'skip_download': True,
        'ignore_no_formats_error': True,  # منشور الصور لا يملك صيغة فيديو
        'extract_flat': False, 'noplaylist': False,
        'socket_timeout': 30, 'nocheckcertificate': _YTDLP_NO_CHECK_CERT,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36',
        },
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر استخراج صور إنستغرام عبر yt-dlp: {e}")
        return []
    if not info:
        return []
    entries = info.get('entries') or [info]
    out, seen = [], set()
    for e in entries:
        if not e:
            continue
        img = e.get('url') or e.get('display_url')
        if not img:
            thumbs = e.get('thumbnails') or []
            img = thumbs[-1].get('url') if thumbs else None
        if img and img not in seen and is_safe_url(img):
            seen.add(img)
            out.append(img)
    if out:
        logger.info(f"🎯 صور إنستغرام عبر yt-dlp (بلا كوكيز): {len(out)} صورة")
    return out[:GALLERY_DL_MAX_IMAGES]


# الصيغ التي يقبلها تلجرام كصورة (photo). غير ذلك (webp/heic/gif) يُرفض بخطأ
# [400 PHOTO_EXT_INVALID] فنحوّله إلى JPEG قبل الإرسال.
_TG_PHOTO_EXTS = ('.jpg', '.jpeg', '.png')


def _normalize_images_for_telegram(files):
    """يحوّل أي صورة بامتداد لا يقبله تلجرام كصورة (webp/heic/gif) إلى JPEG عبر
    ffmpeg، لتفادي خطأ [400 PHOTO_EXT_INVALID] في send_photo/send_media_group.

    الصور بصيغة jpg/jpeg/png تُترك كما هي. الصورة التي يتعذّر تحويلها تُتخطّى
    (لا نُفشِل الألبوم كله). يحافظ على ترتيب الصور الأصلي (ترتيب الكاروسيل)."""
    out = []
    for fpath in files:
        ext = os.path.splitext(fpath)[1].lower()
        if ext in _TG_PHOTO_EXTS:
            out.append(fpath)
            continue
        jpg_path = os.path.splitext(fpath)[0] + '_tg.jpg'
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-i', fpath, '-frames:v', '1', jpg_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60
            )
            if os.path.isfile(jpg_path) and os.path.getsize(jpg_path) > 0:
                out.append(jpg_path)
                logger.info(f"🔄 حُوّلت صورة {ext} إلى JPEG لتلجرام: {os.path.basename(fpath)}")
            else:
                logger.warning(
                    f"⚠️ تعذّر تحويل صورة {ext} إلى JPEG (ستُتخطّى): {os.path.basename(fpath)}")
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تحويل صورة {ext} إلى JPEG (ستُتخطّى): {e}")
    return out


def _ensure_video_has_audio(file_path):
    """يضيف مسار صوت صامت للفيديو الذي لا صوت فيه، حتى لا يعرضه تلجرام كـ"صورة
    متحركة" (GIF) صامتة تُعاد تلقائياً بدل فيديو حقيقي بزر تشغيل. كثير من مقاطع
    تيك توك/إنستغرام/تويتر تُنزَّل بلا مسار صوت.

    مكتفٍ ذاتياً داخل bot.py (يستدعي ffprobe/ffmpeg مباشرة) ليعمل حتى حين تُزامَن
    bot.py وحدها دون video_processing.py — كنمط الاستيراد الدفاعي أعلى الملف.
    آمن وخامل (idempotent): لا يفعل شيئاً إن كان للفيديو صوت أصلاً (بما فيه صوت
    صامت أضافه finalize_video)، ولا إن تعذّر الفحص (فلا يُسقط صوتاً موجوداً)."""
    import json
    try:
        out = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a',
             '-show_entries', 'stream=codec_type', '-of', 'json', file_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60
        ).stdout.decode('utf-8', 'ignore')
        streams = json.loads(out or '{}').get('streams')
    except Exception as e:
        logger.warning(f"⚠️ تعذّر فحص صوت الفيديو (يُترك كما هو): {e}")
        return
    # streams=None ⇒ فشل الفحص فلا نلمس الملف؛ قائمة غير فارغة ⇒ فيه صوت.
    if streams is None or any(s.get('codec_type') == 'audio' for s in streams):
        return

    logger.info("🔇 الفيديو بلا صوت — إضافة مسار صوت صامت لمنع عرضه كصورة متحركة")
    tmp = os.path.splitext(file_path)[0] + '.snd.mp4'
    try:
        cmd = [
            'ffmpeg', '-y', '-i', file_path,
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-map', '0:v:0', '-map', '1:a:0',
            # الفيديو مُجهّز مسبقاً (H.264/faststart) فيكفي نسخه؛ نضيف صوتاً فقط
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-shortest',
            '-movflags', '+faststart', tmp,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, file_path)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر إضافة صوت صامت للفيديو: {e}")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


async def upload_media_with_progress(client, chat_id, file_path, caption, status_msg, user_id, is_video=True):
    """Upload media with progress tracking"""
    try:
        upload_progress = UploadProgress(status_msg, user_id, asyncio.get_event_loop())
        
        if is_video:
            message = await client.send_video(
                chat_id=chat_id,
                video=file_path,
                caption=caption,
                progress=upload_progress
            )
        else:
            message = await client.send_audio(
                chat_id=chat_id,
                audio=file_path,
                caption=caption,
                progress=upload_progress
            )
        
        return message
    except Exception as e:
        logger.error(f"خطأ في رفع الوسائط: {e}")
        raise
# Upload progress tracking
class UploadProgress:
    def __init__(self, status_msg, user_id, event_loop):
        self.status_msg = status_msg
        self.user_id = user_id
        self.event_loop = event_loop  # Store the event loop
        self.last_edit = 0
        self.last_current = 0
        self.last_time = time.time()
        self.speed = 0
    
    def __call__(self, current, total):
        """Sync callback for Pyrogram - creates async task for updates"""
        try:
            now = time.time()
            
            # Update speed calculation
            time_diff = now - self.last_time
            if time_diff >= 1:  # Update speed every second
                bytes_diff = current - self.last_current
                self.speed = bytes_diff / time_diff
                self.last_time = now
                self.last_current = current
            
            if now - self.last_edit < 1: # Update message every second
                return
            
            self.last_edit = now
            
            # Calculate progress
            percentage = (current / total) * 100
            current_mb = current / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            speed_mb = self.speed / (1024 * 1024) if self.speed > 0 else 0
            filled = int(percentage // 10)
            progress_bar = '▰' * filled + '▱' * (10 - filled)
            remaining_bytes = total - current
            eta = int(remaining_bytes / self.speed) if self.speed > 0 else 0
            
            # Get user language
            lang = subdb.get_user_language(self.user_id)
            
            upload_msg = t('uploading', lang,
                          percent=f'{percentage:.1f}',
                          current_mb=f'{current_mb:.1f}',
                          total_mb=f'{total_mb:.1f}',
                          speed_mb=f'{speed_mb:.1f}',
                          eta=eta,
                          progress_bar=progress_bar)
            
            # Use run_coroutine_threadsafe to schedule in the correct event loop
            asyncio.run_coroutine_threadsafe(
                self._update_message(upload_msg),
                self.event_loop
            )
        except Exception as e:
            logger.error(f"❌ Upload progress error: {e}")
    
    async def _update_message(self, text):
        """Async helper to update Telegram message"""
        try:
            await self.status_msg.edit_text(text)
        except Exception as e:
            logger.error(f"❌ Message edit error: {e}")


async def forward_to_log_channel(client, message, sent_message, user_id, user_name, username, url, 
                               video_info, duration, file_size_mb):
    """تحويل الفيديو إلى قناة السجلات مع معلومات تفصيلية"""
    try:
        channel_id = get_channel_id('LOG_CHANNEL_ID')

        if not channel_id:
            return None
        
        # Format username
        username_text = f"@{html.escape(str(username))}" if username else "⚠️ لا يوجد يوزر"

        # User link (blue clickable name) - مع تأمين الاسم من رموز HTML
        user_link = f'<a href="tg://user?id={user_id}">{html.escape(str(user_name or "مستخدم"))}</a>'

        # Video title كاملاً (بحد آمن) ومؤمّن من رموز HTML
        title = (video_info.get('title') if video_info else None) or 'فيديو'
        title = html.escape(title[:300])
        
        # Platform detection
        if 'youtube' in url or 'youtu.be' in url:
            platform, icon = 'YouTube', '📺'
        elif 'facebook' in url or 'fb.watch' in url:
            platform, icon = 'Facebook', '📘'
        elif 'threads.net' in url or 'threads.com' in url:
            platform, icon = 'Threads', '🧵'
        elif 'instagram' in url:
            platform, icon = 'Instagram', '📷'
        elif 'twitter' in url or 'x.com' in url:
            platform, icon = 'Twitter/X', '🐦'
        elif 'tiktok' in url:
            platform, icon = 'TikTok', '🎵'
        else:
            platform, icon = 'رابط', '🔗'

        # حساب المصدر (الناشر) — يساعد الأدمن على حظره بـ /blockacc إن لزم
        src_account = ''
        if video_info:
            acc = video_info.get('uploader_id') or video_info.get('uploader') \
                or video_info.get('channel')
            if acc:
                src_account = f"\n👤 الحساب: <code>{html.escape(str(acc).lstrip('@'))}</code>"

        # Views formatting
        views = video_info.get('view_count', 'N/A') if video_info else 'N/A'
        if isinstance(views, int):
            views_text = f"{views/1_000_000:.1f}M" if views >= 1_000_000 else f"{views/1_000:.1f}K" if views >= 1_000 else str(views)
        else:
            views_text = 'N/A'
        
        # Duration & Quality
        duration_text = f"{int(duration)//60:02d}:{int(duration)%60:02d}" if duration else "N/A"
        quality = video_info.get('resolution', 'N/A') if video_info else 'N/A'
        
        # Timestamp
        from datetime import datetime
        date_text = datetime.now().strftime("%d/%m/%Y • %H:%M UTC")
        
        # Caption with user info
        caption = f"""━━━━━━━━━━━━━━━━━━━━━━
🎬 تحميل جديد

👤 المستخدم
╔═ الاسم: {user_link}
╠═ اليوزر: {username_text}  
╚═ ID: <code>{user_id}</code>

🔗 المصدر: {icon} {platform}{src_account}
📎 {html.escape(url)}

🎞️ العنوان
<code>{title}</code>

📊 تفاصيل الفيديو
├─ 📹 المدة: {duration_text}
├─ 💾 الحجم: {file_size_mb:.2f} MB
├─ 🎯 الجودة: {quality}
└─ 👁️ المشاهدات: {views_text}

🕐 {date_text}
━━━━━━━━━━━━━━━━━━━━━━"""
        
        # أزرار تحكّم الأدمن (حظر/رفع حظر) أسفل رسالة السجل — لا تظهر للأدمن نفسه
        admin_kb = None if is_admin(user_id) else _admin_ban_buttons(user_id)

        # نسخ الفيديو إلى القناة مع كل التفاصيل كوصف في رسالة واحدة مرتبة
        # (copy_message يستخدم نفس file_id فلا يعيد رفع الفيديو = فوري)
        # نُرجع رسالة السجل لإعادة استخدام نسختها الدائمة في الكاش.
        log_msg = None
        try:
            log_msg = await client.copy_message(
                chat_id=channel_id,
                from_chat_id=sent_message.chat.id,
                message_id=sent_message.id,
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=admin_kb
            )
        except Exception as copy_err:
            # احتياطياً عند فشل النسخ: حوّل الفيديو ثم أرسل التفاصيل تحته
            logger.warning(f"⚠️ تعذّر نسخ الفيديو للقناة، استخدام التحويل: {copy_err}")
            try:
                fwd = await client.forward_messages(
                    chat_id=channel_id,
                    from_chat_id=sent_message.chat.id,
                    message_ids=sent_message.id
                )
                log_msg = fwd[0] if isinstance(fwd, list) else fwd
            except Exception:
                log_msg = None
            await client.send_message(
                chat_id=channel_id,
                text=caption,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=admin_kb
            )

        logger.info(f"✅ تم إرسال الفيديو والمعلومات إلى القناة في رسالة واحدة")
        return log_msg

    except Exception as e:
        logger.error(f"❌ خطأ في تحويل الفيديو إلى القناة: {str(e)}")
        return None


async def forward_images_to_log_channel(client, message, sent_messages, user_id,
                                        user_name, username, url, video_info, title):
    """تحويل كل صور المنشور إلى قناة السجلات كألبوم مع تفاصيل العضو.

    يستخدم النسخ (copy) بمعرّف الملف — لا إعادة رفع — تماماً كمسار الفيديو،
    فلا يضغط على الجهاز (Raspberry Pi). ينسخ الصور المُرسلة أصلاً للمستخدم إلى
    القناة، ويضع كل التفاصيل (شامل جنس العضو الذي حمّلها: رجل/امرأة) في كابشن
    أول صورة. يعيد قائمة رسائل القناة المنسوخة (لاستخدام معرّفاتها في الكاش)."""
    try:
        channel_id = get_channel_id('LOG_CHANNEL_ID')
        if not channel_id or not sent_messages:
            return []

        # معلومات العضو (شامل الجنس المُخزّن في الاستبيان الإجباري)
        username_text = f"@{html.escape(str(username))}" if username else "⚠️ لا يوجد يوزر"
        user_link = f'<a href="tg://user?id={user_id}">{html.escape(str(user_name or "مستخدم"))}</a>'
        gender_txt = _gender_label(subdb.get_survey(user_id).get('gender'))

        title_txt = html.escape((title or 'صور')[:300])

        # Platform detection
        if 'instagram' in url:
            platform, icon = 'Instagram', '📷'
        elif 'tiktok' in url:
            platform, icon = 'TikTok', '🎵'
        elif 'twitter' in url or 'x.com' in url:
            platform, icon = 'Twitter/X', '🐦'
        elif 'facebook' in url or 'fb.watch' in url:
            platform, icon = 'Facebook', '📘'
        elif 'threads.net' in url or 'threads.com' in url:
            platform, icon = 'Threads', '🧵'
        else:
            platform, icon = 'رابط', '🔗'

        # حساب المصدر (الناشر)
        src_account = ''
        if video_info:
            acc = video_info.get('uploader_id') or video_info.get('uploader') \
                or video_info.get('channel')
            if acc:
                src_account = f"\n👤 الحساب: <code>{html.escape(str(acc).lstrip('@'))}</code>"

        from datetime import datetime
        date_text = datetime.now().strftime("%d/%m/%Y • %H:%M UTC")

        caption = f"""━━━━━━━━━━━━━━━━━━━━━━
🖼️ تحميل صور جديد

👤 المستخدم
╔═ الاسم: {user_link}
╠═ اليوزر: {username_text}
╠═ 👥 الجنس: {gender_txt}
╚═ ID: <code>{user_id}</code>

🔗 المصدر: {icon} {platform}{src_account}
📎 {html.escape(url)}

🖼️ العنوان
<code>{title_txt}</code>

📊 التفاصيل
└─ 📷 عدد الصور: {len(sent_messages)}

🕐 {date_text}
━━━━━━━━━━━━━━━━━━━━━━"""

        # نجمّع الرسائل حسب مجموعة الوسائط (media_group_id) للحفاظ على شكل الألبوم
        # عند النسخ. كل ألبوم أرسلناه للمستخدم يُنسخ كوحدة واحدة بمعرّف رسالته.
        groups = []
        last_gid = None
        for m in sent_messages:
            gid = getattr(m, 'media_group_id', None)
            if gid is not None and gid == last_gid and groups:
                groups[-1].append(m)
            else:
                groups.append([m])
            last_gid = gid

        # ننسخ كل مجموعة إلى القناة بمعرّف الملف (بلا إعادة رفع = بلا ضغط)،
        # والكابشن الكامل على أول صورة من أول مجموعة فقط.
        log_messages = []
        first_log_msg = None
        for gi, group in enumerate(groups):
            from_chat = group[0].chat.id
            if len(group) == 1:
                cap = caption if gi == 0 else None
                m = await client.copy_message(
                    chat_id=channel_id, from_chat_id=from_chat,
                    message_id=group[0].id, caption=cap,
                    parse_mode=(enums.ParseMode.HTML if cap else None)
                )
                log_messages.append(m)
                if gi == 0:
                    first_log_msg = m
            else:
                copied = await client.copy_media_group(
                    chat_id=channel_id, from_chat_id=from_chat,
                    message_id=group[0].id
                )
                copied_list = copied if isinstance(copied, list) else [copied]
                log_messages.extend(copied_list)
                if gi == 0 and copied_list:
                    first_log_msg = copied_list[0]
                    # copy_media_group لا يقبل parse_mode، فنحرّر الكابشن بـ HTML
                    try:
                        await client.edit_message_caption(
                            chat_id=channel_id, message_id=copied_list[0].id,
                            caption=caption, parse_mode=enums.ParseMode.HTML
                        )
                    except Exception:
                        pass

        # أزرار حظر الأدمن: الألبوم لا يدعم الأزرار المضمّنة، فنرسلها كرسالة
        # رد على أول صورة (تظهر أسفل الألبوم) — لا تظهر إن كان المُحمِّل أدمن.
        if not is_admin(user_id) and first_log_msg is not None:
            try:
                await client.send_message(
                    chat_id=channel_id,
                    text=f"🛡️ إدارة العضو: {user_link}",
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=_admin_ban_buttons(user_id),
                    reply_to_message_id=first_log_msg.id
                )
            except Exception:
                pass

        logger.info(f"✅ تم تحويل {len(sent_messages)} صورة إلى قناة السجلات (نسخ)")
        return log_messages

    except Exception as e:
        logger.error(f"❌ خطأ في تحويل الصور إلى القناة: {str(e)}")
        return []


async def process_download_from_queue(task: DownloadTask):
    """
    Process a download task from the queue.
    
    Args:
        task: DownloadTask containing download information
    """
    user_id = task.user_id
    url = task.url
    message = task.message
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    try:
        # Send processing notification
        status = await message.reply_text(t('queue_processing_current', lang))
        
        # Get video info
        info = await get_video_info(url)
        
        if not info:
            user_name = message.from_user.first_name or "User"
            # 🖼️ قد يفشل yt-dlp تماماً في استخراج سلايدشو تيك توك / كاروسيل
            #    إنستغرام/بينتريست (منشور صور بلا فيديو، خاصة الروابط المختصرة)
            #    فيرجع None. جرّب مسار الصور عبر gallery-dl قبل اعتبار الرابط فاشلاً.
            if _platform_of(url) in ('instagram', 'tiktok', 'pinterest'):
                if await download_and_send_images(
                    app, message, url, status, user_id, user_name,
                    message.from_user.username, lang
                ):
                    return
            # 🐦 تغريدة X بلا فيديو قابل للاستخراج: yt-dlp يفشل لتغريدات الصور
            #    بـ"No video could be found in this tweet" → اجلب وسائط التغريدة
            #    (صور، أو صور + فيديو) من المرآة العامة وأرسلها كألبوم.
            elif _platform_of(url) == 'twitter':
                if await download_and_send_tweet_media(
                    app, message, url, status, user_id, user_name,
                    message.from_user.username, lang
                ):
                    return
            # محتوى مقيّد بالعمر/حسّاس → رسالة واضحة بدل "رابط غير صحيح" المضلّلة
            if _last_info_error.get() == 'restricted':
                await send_error_to_admin(user_id, user_name, "Restricted/sensitive content", url)
                await status.edit_text(t('content_restricted', lang))
                return
            # منشور إنستغرام خاص/محذوف (المرآة أُحيلت لجدار الدخول) → رسالة واضحة
            if _last_info_error.get() == 'ig_unavailable':
                await send_error_to_admin(user_id, user_name, "Instagram post private/removed", url)
                await status.edit_text(t('post_unavailable', lang))
                return
            await send_error_to_admin(user_id, user_name, "Failed to extract video info", url)
            await status.edit_text(t('invalid_url', lang))
            return

        # 🔞 محتوى إباحي/حساب محظور بعد الاستخراج → عاقِب المستخدم (حظر + تعهّد)
        if (adult_filter_enabled() and is_adult_info(info)) or is_blocked_account(info):
            logger.info(f"🔞 Adult/blocked content (queue) from user {user_id}: {info.get('uploader')}")
            ban_text, ban_kb = await _apply_adult_ban(app, user_id, lang)
            await status.edit_text(ban_text, reply_markup=ban_kb)
            return

        # 🐦 تغريدة X مختلطة (صور + فيديو) أو متعددة الفيديو في تغريدة واحدة:
        #    yt-dlp يستخرج الفيديو فقط ويُسقط الصور → أرسل كل وسائط التغريدة
        #    كألبوم واحد. تغريدة الفيديو الواحد تعود False فتُكمل مسار الجودة
        #    المعتاد، وكذلك عند تعطّل المرآة (السلوك القديم بلا تغيير).
        if _platform_of(url) == 'twitter':
            tw_name = message.from_user.first_name or "User"
            if await download_and_send_tweet_media(
                app, message, url, status, user_id, tw_name,
                message.from_user.username, lang, info
            ):
                return

        # 📃 كشف قوائم التشغيل: عرض زر لتحميل أول N مقاطع (للمشتركين/الأدمن)
        # كاروسيل الصور (بلا فيديو) يُستثنى هنا ليُعالَج كألبوم صور لاحقاً.
        entries = [e for e in (info.get('entries') or []) if e]
        if entries and _info_has_video(info):
            if not (subdb.is_user_subscribed(user_id) or is_admin(user_id)):
                await status.edit_text(t('playlist_subscribers_only', lang))
                return
            urls = []
            for e in entries[:PLAYLIST_MAX]:
                u = e.get('webpage_url') or e.get('url')
                if u and str(u).startswith('http') and is_safe_url(u):
                    urls.append(u)
            if urls:
                pending_playlists[user_id] = urls
                await status.edit_text(
                    t('playlist_detected', lang, count=len(entries), max=len(urls)),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t('playlist_btn', lang, n=len(urls)),
                                              callback_data='playlist_dl')]
                    ])
                )
                return
            # لا روابط صالحة → تابع كفيديو واحد

        title = info.get('title', 'Video')[:50]
        duration = info.get('duration', 0)
        duration_str = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else "0:00"

        # Add or update user info
        username = message.from_user.username
        first_name = message.from_user.first_name
        subdb.add_or_update_user(user_id, username, first_name)
        
        # Check subscription and video duration
        is_subscribed = subdb.is_user_subscribed(user_id)
        
        # Check daily limit for non-subscribers (الحد = الأساس + دعواته الدائمة)
        if not is_subscribed:
            base_limit = subdb.get_daily_limit()

            if base_limit != -1:
                effective_limit = base_limit + subdb.get_bonus_downloads(user_id)
                daily_count = subdb.check_daily_limit(user_id)

                if daily_count >= effective_limit:
                    await status.edit_text(
                        t('daily_limit_exceeded', lang, limit=effective_limit, count=daily_count),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(t('subscribe_now', lang), callback_data="show_plans")],
                            [_invite_button(lang)],
                            [InlineKeyboardButton(t('contact_developer', lang), url=f"https://t.me/{subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))}")]
                        ])
                    )
                    return
        
        # 🖼️ منشور مصوّر بلا فيديو (كاروسيل إنستغرام / سلايدشو تيك توك) → ألبوم صور
        if _platform_of(url) in ('instagram', 'tiktok') and not _info_has_video(info):
            img_user_name = message.from_user.first_name or "User"
            handled = await download_and_send_images(
                app, message, url, status, user_id, img_user_name,
                message.from_user.username, lang, info
            )
            if handled:
                return
            await status.edit_text(t('no_media_found', lang))
            return

        # الحد الأقصى للمدة = الأساس + مكافأة دعوات المستخدم (كل دعوة +REFERRAL_MINUTES دقيقة)
        max_duration_minutes = _user_max_duration_minutes(user_id)
        max_duration_seconds = max_duration_minutes * 60

        # If not subscribed and exceeds max duration
        if not is_subscribed and duration and duration > max_duration_seconds:
            await show_subscription_screen(app, status, user_id, title, duration, max_duration_minutes)
            return
        
        # Show download type (video / audio)
        keyboard = [
            [InlineKeyboardButton(t('btn_video', lang), callback_data="quality_best"),
             InlineKeyboardButton(t('btn_audio', lang), callback_data="quality_audio")],
        ]

        await status.edit_text(
            t('choose_quality', lang, title=title, duration=duration_str),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Store URL for quality callback
        pending_downloads[user_id] = url
        
    except Exception as e:
        logger.error(f"Error in process_download_from_queue for user {user_id}: {e}", exc_info=True)
        # Notify user of error
        try:
            await message.reply_text(t('error_occurred', lang, error=str(e)[:100]))
        except Exception:
            pass


def cleanup_downloaded_files(file_path=None):
    """
    حذف جميع الملفات المحملة من المجلد الحالي ومجلدات التحميل.
    
    Args:
        file_path: المسار المحدد للملف المراد حذفه (اختياري)
    """
    try:
        deleted_count = 0
        
        # حذف الملف المحدد إذا كان موجود
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"🗑️ تم حذف الملف: {file_path}")
                deleted_count += 1
            except Exception as e:
                logger.error(f"❌ خطأ في حذف {file_path}: {e}")
        
        # أنواع الملفات المراد حذفها
        video_extensions = ['*.mp4', '*.mkv', '*.webm', '*.avi', '*.mov', '*.flv', '*.wmv', '*.m4v']
        audio_extensions = ['*.mp3', '*.m4a', '*.opus', '*.ogg', '*.wav', '*.flac', '*.aac']
        temp_extensions = ['*.part', '*.ytdl', '*.temp', '*.tmp']
        all_extensions = video_extensions + audio_extensions + temp_extensions
        
        # المجلدات المراد تنظيفها
        directories_to_clean = [
            '.',  # المجلد الحالي
            'downloads',
            'videos'
        ]
        
        # تنظيف كل مجلد
        for directory in directories_to_clean:
            if not os.path.exists(directory):
                continue
                
            for extension in all_extensions:
                pattern = os.path.join(directory, extension)
                for file in glob.glob(pattern):
                    try:
                        # تجنب حذف watermark.png
                        if 'watermark' in file.lower():
                            continue
                        os.remove(file)
                        logger.info(f"🗑️ تم حذف: {file}")
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"❌ خطأ في حذف {file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ تم حذف {deleted_count} ملف من المجلدات")
        
    except Exception as e:
        logger.error(f"❌ خطأ في cleanup_downloaded_files: {e}")


def cleanup_download_dir(dl_dir):
    """حذف مجلد التحميل المؤقت الخاص بعملية واحدة (آمن مع التزامن).
    لا يلمس ملفات أو مجلدات تحميلات أخرى."""
    if not dl_dir:
        return
    try:
        if os.path.isdir(dl_dir):
            shutil.rmtree(dl_dir, ignore_errors=True)
            logger.info(f"🗑️ تم حذف مجلد التحميل المؤقت: {dl_dir}")
    except Exception as e:
        logger.error(f"❌ خطأ في حذف مجلد التحميل {dl_dir}: {e}")


_PLATFORM_TITLE_LABELS = {
    'instagram': 'Instagram', 'tiktok': 'TikTok', 'twitter': 'Twitter/X',
    'facebook': 'Facebook', 'youtube': 'YouTube', 'snapchat': 'Snapchat',
    'reddit': 'Reddit', 'pinterest': 'Pinterest', 'threads': 'Threads',
}


def _looks_like_media_id(title: str) -> bool:
    """هل العنوان معرّف CDN/هاش قبيح لا اسم مقروء؟ (كلمة واحدة طويلة تخلط حروفاً
    وأرقاماً بلا مسافات — مثل اسم ملف إنستغرام عبر المرآة AQM4FbWDo4mvcl...)."""
    s = (title or '').strip()
    if not s or ' ' in s:
        return False  # فارغ أو فيه مسافات (كلمات مقروءة) → ليس معرّفاً
    core = s.replace('_', '').replace('-', '')
    return (len(s) >= 24 and core.isalnum()
            and any(c.isalpha() for c in core)
            and any(c.isdigit() for c in core))


def _clean_media_title(raw_title, url):
    """عنوان عرض ودود موحّد بين المنصات: يُبقي العناوين المقروءة كما هي، لكن
    يستبدل العناوين الفارغة أو معرّفات CDN القبيحة (شائعة لإنستغرام عبر المرآة)
    باسم منصة نظيف مثل 'Instagram Video' — تماماً كما تظهر تيك توك/تويتر."""
    title = (raw_title or '').strip()
    if title and not _looks_like_media_id(title):
        return title
    label = _PLATFORM_TITLE_LABELS.get(_platform_of(url))
    return f"{label} Video" if label else 'فيديو'


def _build_media_caption(title, file_size_mb, duration, user_name, bot_username=None):
    """وصف الوسائط الموحّد: العنوان قابل للنسخ (monospace) + الحجم والمدة +
    يوزر البوت (يبقى مع الفيديو عند إعادة إرساله)."""
    safe_title = (title or 'فيديو').replace('`', "'")[:300]
    dur_line = f"⏱️ {int(duration)//60}:{int(duration)%60:02d}\n" if duration else ""
    promo = f"\n\n📥 @{bot_username}" if bot_username else ""
    return (
        f"🎬 `{safe_title}`\n\n"
        f"📊 {file_size_mb:.1f} MB\n"
        f"{dur_line}"
        f"👤 {user_name}"
        f"{promo}"
    )


async def _send_daily_remaining_notice(message, user_id, lang):
    """يزيد عداد الحد اليومي لغير المشتركين ويعرض المتبقي (مشترك بين المسارين)."""
    if subdb.is_user_subscribed(user_id):
        return
    subdb.increment_download_count(user_id)
    base_limit = subdb.get_daily_limit()
    if base_limit != -1:
        effective_limit = base_limit + subdb.get_bonus_downloads(user_id)
        daily_count = subdb.check_daily_limit(user_id)
        remaining = effective_limit - daily_count
        if remaining > 0:
            await message.reply_text(t('downloads_remaining', lang, remaining=remaining))


async def _edit_send_progress(msg, title, done, total, sent, fail, removed):
    """يحدّث رسالة عدّاد الإرسال الحيّ (للبث/التذكير). يتجاهل أخطاء التعديل."""
    try:
        await msg.edit_text(
            f"{title}\n\n"
            f"📊 التقدّم: **{done}/{total}**\n"
            f"✅ وصلت: **{sent}**\n"
            f"❌ فشلت: **{fail}**\n"
            f"🗑️ حُذفوا (غادروا): **{removed}**"
        )
    except Exception:
        pass


async def _send_reminder_batch(client, progress_msg, targets):
    """يرسل رسالة التذكير لقائمة (user_id, language, last_reminder_msg_id): يحذف
    التذكير السابق لكل عضو ثم يرسل الأحدث بلغته، مع عدّاد حيّ ومعالجة الأخطاء
    (FloodWait، ومن غادر يُحذف). يعيد (وصلت، فشلت، حُذفوا). مشترك بين إرسال
    التذكير للخاملين وللجميع."""
    total = len(targets)
    sent_n = fail_n = removed_n = 0
    for idx, (uid, ulang, old_msg) in enumerate(targets, 1):
        try:
            # احذف التذكير السابق ليبقى الأحدث فقط
            if old_msg:
                try:
                    await client.delete_messages(uid, old_msg)
                except Exception:
                    pass
            m = await client.send_message(uid, t('reminder_inactive', ulang or 'ar'))
            subdb.set_last_reminder(uid, m.id)
            sent_n += 1
            await asyncio.sleep(0.05)
        except FloodWait as e:
            await asyncio.sleep(getattr(e, 'value', 5))
            fail_n += 1
        except GONE_USER_ERRORS:
            try:
                subdb.delete_user(uid)
                removed_n += 1
            except Exception:
                pass
            fail_n += 1
        except Exception:
            fail_n += 1
        # عدّاد حيّ يتحدّث كل 15 عضواً
        if idx % 15 == 0:
            await _edit_send_progress(progress_msg, "📨 جاري إرسال التذكير...",
                                      idx, total, sent_n, fail_n, removed_n)
    return sent_n, fail_n, removed_n


async def _try_send_from_cache(client, message, status_msg, ckey, quality,
                               user_id, user_name, user_username, url, lang):
    """يحاول إعادة إرسال الوسائط من الكاش بلا تحميل. يرجع True إن نجح ذلك."""
    try:
        cached = subdb.get_cached_media(ckey, quality)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر قراءة الكاش: {e}")
        return False
    if not cached:
        return False

    title = cached.get('title') or 'فيديو'
    fsize = cached.get('file_size_mb') or 0.0
    cdur = cached.get('duration')
    caption = _build_media_caption(title, fsize, cdur, user_name,
                                   bot_username=await _get_bot_username(client))

    try:
        if cached['kind'] == 'audio':
            sent_msg = await client.send_audio(
                chat_id=message.chat.id, audio=cached['file_id'],
                caption=caption, duration=cdur
            )
        else:
            binance_id = subdb.get_setting('binance_pay_id', os.getenv('BINANCE_PAY_ID', ''))
            sent_msg = await client.send_video(
                chat_id=message.chat.id, video=cached['file_id'], caption=caption,
                duration=cdur, width=cached.get('width'), height=cached.get('height'),
                supports_streaming=True,
                reply_markup=_binance_support_keyboard(binance_id, lang)
            )
    except Exception as e:
        # المعرّف القديم لم يعد صالحاً → احذف الصف وأعد التحميل عادياً
        logger.warning(f"⚠️ فشل الإرسال من الكاش ({ckey}/{quality})، سيُعاد التحميل: {e}")
        try:
            subdb.delete_cached_media(ckey, quality)
        except Exception:
            pass
        return False

    try:
        await status_msg.delete()
    except Exception:
        pass
    try:
        subdb.bump_cache_hit(ckey, quality)
    except Exception:
        pass
    logger.info(f"⚡ كاش: أُعيد إرسال {ckey} ({quality}) للمستخدم {user_id} بلا تحميل")

    try:
        await forward_to_log_channel(
            client=client, message=message, sent_message=sent_msg,
            user_id=user_id, user_name=user_name, username=user_username,
            url=url, video_info={'title': title}, duration=cdur or 0,
            file_size_mb=fsize
        )
    except Exception as log_error:
        logger.error(f"⚠️ خطأ في إرسال للقناة (كاش): {log_error}")

    await _send_daily_remaining_notice(message, user_id, lang)
    try:
        subdb.add_download_history(user_id, url, title, quality, cached['kind'],
                                   _platform_of(url), fsize, from_cache=True)
    except Exception:
        pass
    return True


async def _save_media_to_cache(sent_msg, log_msg, ckey, quality, kind, title,
                               file_size_mb, duration, width=None, height=None):
    """يحفظ معرّف الملف في الكاش. يعيد استخدام نسخة قناة السجلات (log_msg)
    كمرجع دائم إن توفّرت، وإلا يستخدم رسالة المستخدم. لا حاجة لقناة أرشيف منفصلة."""
    try:
        def _file_id_of(msg):
            if not msg:
                return None
            media = getattr(msg, 'audio', None) if kind == 'audio' \
                else getattr(msg, 'video', None)
            return getattr(media, 'file_id', None)

        # فضّل نسخة قناة السجلات (دائمة)، ثم رسالة المستخدم
        storage_chat_id = storage_msg_id = None
        file_id = _file_id_of(log_msg)
        if file_id:
            storage_chat_id = getattr(getattr(log_msg, 'chat', None), 'id', None)
            storage_msg_id = getattr(log_msg, 'id', None)
        else:
            file_id = _file_id_of(sent_msg)
        if not file_id:
            return

        subdb.save_cached_media(
            url_key=ckey, quality=quality, kind=kind, file_id=file_id,
            title=title, file_size_mb=file_size_mb, duration=duration,
            width=width, height=height,
            storage_chat_id=storage_chat_id, storage_msg_id=storage_msg_id
        )
        logger.info(f"💾 حُفظ في الكاش: {ckey} ({quality})")
    except Exception as e:
        logger.warning(f"⚠️ تعذّر حفظ الكاش: {e}")


# مفتاح ثابت لجودة كاش الصور (المنشورات المصوّرة لا جودة/دقة لها)
IMAGE_CACHE_QUALITY = 'image'


async def _try_send_images_from_cache(client, message, status_msg, ckey,
                                      user_id, user_name, user_username, url, lang):
    """يعيد إرسال صور منشور من الكاش بمعرّفات الملفات (بلا أي تحميل) كما في
    مسار الفيديو. الصور محفوظة على خوادم تلجرام، فنرسلها فوراً كألبوم.
    يعيد True إن نجح، وFalse إن لا كاش (فيُكمل التحميل العادي)."""
    from pyrogram.types import InputMediaPhoto
    try:
        cached = subdb.get_cached_media(ckey, IMAGE_CACHE_QUALITY)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر قراءة كاش الصور: {e}")
        return False
    if not cached or cached.get('kind') != 'image':
        return False

    # معرّفات الصور مخزّنة مفصولة بسطر (file_id تلجرام لا يحوي أسطراً)
    file_ids = [fid for fid in (cached.get('file_id') or '').split('\n') if fid]
    if not file_ids:
        return False

    title = cached.get('title') or 'صور'
    bot_username = await _get_bot_username(client)
    caption = t('images_caption', lang, title=title, count=len(file_ids),
                user=user_name,
                promo=(f"\n\n📥 @{bot_username}" if bot_username else ""))

    try:
        sent_messages = []
        chunks = [file_ids[i:i + 10] for i in range(0, len(file_ids), 10)]
        for ci, chunk in enumerate(chunks):
            if len(chunk) == 1 and len(chunks) == 1:
                m = await client.send_photo(
                    chat_id=message.chat.id, photo=chunk[0], caption=caption
                )
                sent_messages.append(m)
            else:
                media = []
                for fi, fid in enumerate(chunk):
                    cap = caption if (ci == 0 and fi == 0) else None
                    media.append(InputMediaPhoto(fid, caption=cap))
                msgs = await client.send_media_group(
                    chat_id=message.chat.id, media=media
                )
                sent_messages.extend(msgs if isinstance(msgs, list) else [msgs])
    except Exception as e:
        # معرّفات قديمة لم تعد صالحة → احذف الكاش وأعد التحميل عادياً
        logger.warning(f"⚠️ فشل إرسال صور الكاش ({ckey})، سيُعاد التحميل: {e}")
        try:
            subdb.delete_cached_media(ckey, IMAGE_CACHE_QUALITY)
        except Exception:
            pass
        return False

    try:
        await status_msg.delete()
    except Exception:
        pass
    try:
        subdb.bump_cache_hit(ckey, IMAGE_CACHE_QUALITY)
    except Exception:
        pass
    logger.info(f"⚡ كاش صور: أُعيد إرسال {ckey} ({len(file_ids)} صورة) بلا تحميل")

    # تحويل للقناة (نسخ بمعرّف الملف) — سجل كامل مع الجنس، بلا إعادة رفع
    try:
        await forward_images_to_log_channel(
            client=client, message=message, sent_messages=sent_messages,
            user_id=user_id, user_name=user_name, username=user_username,
            url=url, video_info={'title': title}, title=title
        )
    except Exception as log_error:
        logger.error(f"⚠️ خطأ في إرسال صور الكاش للقناة: {log_error}")

    await _send_daily_remaining_notice(message, user_id, lang)
    try:
        subdb.add_download_history(user_id, url, title, 'best', 'image',
                                   _platform_of(url), 0, from_cache=True)
    except Exception:
        pass
    return True


async def download_and_send_images(client, message, url, status_msg,
                                   user_id, user_name, user_username, lang, info=None,
                                   fallback_image_urls=None):
    """ينزّل صور منشور إنستغرام/تيك توك/بينتريست/تويتر (كاروسيل/سلايدشو) ويرسلها
    كألبوم. fallback_image_urls (اختياري): روابط صور مباشرة جاهزة تُستخدم حين
    يفشل gallery-dl — يمرّرها مسار التغريدة من مرآة fx/vxtwitter العامة.

    يعيد True إذا عُثر على صور وأُرسلت، وFalse إن لم يكن منشوراً مصوّراً
    (فيرجع المتصل لمسار الفيديو المعتاد). لا يكسر أي سلوك للفيديو القائم.
    """
    from pyrogram.types import InputMediaPhoto

    # 🎥 حارس: ريلز/IGTV إنستغرام (reel|reels|tv) فيديو دائماً — ليست منشور صور.
    # نمنع مسار الصور بالكامل لها حتى لا يُرسَل غلاف الريل كصورة (سواء من
    # gallery-dl بخيار videos=false أو من المرآة العامة). فتبقى على مسار الفيديو
    # ورسالة الفشل الواضحة عند تعذّر التحميل.
    if _is_instagram_video_only_url(url):
        logger.info("🎥 رابط ريل/IGTV إنستغرام — تخطّي مسار الصور (فيديو حصراً)")
        return False

    dl_dir = os.path.join('videos', 'img_' + uuid.uuid4().hex)
    ckey = cache_key_for_url(url)
    try:
        # ⚡ كاش الصور: إن كان نفس الرابط محمّلاً سابقاً، أعِد إرساله فوراً من
        # معرّفات الملفات بلا أي تحميل (كما في المنصات الأخرى للفيديو).
        if await _try_send_images_from_cache(
            client, message, status_msg, ckey,
            user_id, user_name, user_username, url, lang
        ):
            return True

        await status_msg.edit_text(t('downloading_images', lang))
        cookie_file = get_cookie_file_for_url(url)
        loop = asyncio.get_event_loop()
        # تويتر/X بلا كوكيز: gallery-dl يفشل حتماً (X يتطلّب تسجيل دخول لواجهته)
        # — نوفّر مهلة الفشل وننتقل مباشرة لروابط صور المرآة العامة
        skip_gallery = _platform_of(url) == 'twitter' and not cookie_file
        files = [] if skip_gallery else await loop.run_in_executor(
            None, lambda: _download_images_with_gallery_dl(url, dl_dir, cookie_file)
        )

        # 🎯 بديل صور تيك توك: gallery-dl يفشل عند حجب IP الخادم → اجلب روابط
        #    الصور من مرآة عامة (بلا كوكيز) ونزّلها بعنوان IP مختلف
        if not files and _platform_of(url) == 'tiktok':
            image_urls = await loop.run_in_executor(
                None, lambda: resolve_tiktok_images(url))
            if image_urls:
                files = await loop.run_in_executor(
                    None, lambda: _download_images_from_urls(image_urls, dl_dir))
                if files:
                    logger.info(
                        f"✅ صور تيك توك عبر المرآة العامة ({len(files)} صورة، بلا كوكيز)")

        # 🎯 بديل صور إنستغرام: gallery-dl يتطلّب تسجيل دخول (يُحوّل لصفحة الدخول
        #    بلا كوكيز وللرئيسية بكوكيز منتهية). نجلب الروابط بترتيب أفضلية:
        #    (أ) yt-dlp بلا كوكيز — يعيد كل صور الكاروسيل (الأدقّ والأكمل)،
        #    (ب) مرآة InstaFix العامة — أول صورة فقط كخطة أخيرة.
        if not files and _platform_of(url) == 'instagram':
            image_urls = await loop.run_in_executor(
                None, lambda: resolve_instagram_images_ytdlp(url))
            src = 'yt-dlp'
            if not image_urls:
                image_urls = await loop.run_in_executor(
                    None, lambda: resolve_instagram_images(url))
                src = 'المرآة العامة'
            if image_urls:
                files = await loop.run_in_executor(
                    None, lambda: _download_images_from_urls(image_urls, dl_dir))
                if files:
                    logger.info(
                        f"✅ صور إنستغرام عبر {src} ({len(files)} صورة، بلا كوكيز)")

        # 🎯 بديل صور بينتريست: gallery-dl قد يفشل (حجب/تغييرات الموقع) → اجلب
        #    روابط الصور (كاروسيل/Idea Pin/مفردة) من واجهة بينتريست العامة بلا كوكيز
        if not files and _platform_of(url) == 'pinterest':
            image_urls = await loop.run_in_executor(
                None, lambda: resolve_pinterest_images(url))
            if image_urls:
                files = await loop.run_in_executor(
                    None, lambda: _download_images_from_urls(image_urls, dl_dir))
                if files:
                    logger.info(
                        f"✅ صور بينتريست عبر الواجهة العامة ({len(files)} صورة، بلا كوكيز)")

        # 🎯 روابط صور مباشرة جاهزة من المتصل (تغريدات X عبر مرآة fx/vxtwitter)
        if not files and fallback_image_urls:
            files = await loop.run_in_executor(
                None, lambda: _download_images_from_urls(fallback_image_urls, dl_dir))
            if files:
                logger.info(
                    f"✅ صور عبر المرآة العامة ({len(files)} صورة، بلا كوكيز)")

        if not files:
            return False  # ليست صوراً → ارجع لمسار الفيديو

        # حوّل أي صورة بصيغة لا يقبلها تلجرام (webp/heic/gif) إلى JPEG لتفادي
        # خطأ [400 PHOTO_EXT_INVALID] عند الإرسال كألبوم/صورة
        files = _normalize_images_for_telegram(files)
        if not files:
            logger.warning("⚠️ لم تبقَ صور صالحة للإرسال بعد التحويل لتلجرام")
            return False

        title = ((info or {}).get('title') or 'صور').replace('`', "'")[:200]
        bot_username = await _get_bot_username(client)
        caption = t('images_caption', lang,
                    title=title, count=len(files), user=user_name,
                    promo=(f"\n\n📥 @{bot_username}" if bot_username else ""))

        sent_messages = []
        # تلجرام يسمح بحد أقصى 10 وسائط في الألبوم الواحد
        chunks = [files[i:i + 10] for i in range(0, len(files), 10)]
        for ci, chunk in enumerate(chunks):
            if len(chunks) > 1:
                try:
                    await status_msg.edit_text(t('uploading_images', lang,
                                                 current=ci + 1, total=len(chunks)))
                except Exception:
                    pass
            if len(chunk) == 1 and len(chunks) == 1:
                # صورة واحدة: أرسلها مباشرة مع الكابشن
                msg = await client.send_photo(
                    chat_id=message.chat.id, photo=chunk[0], caption=caption
                )
                sent_messages.append(msg)
            else:
                # الكابشن على أول صورة من أول ألبوم فقط
                media = []
                for fi, fpath in enumerate(chunk):
                    cap = caption if (ci == 0 and fi == 0) else None
                    media.append(InputMediaPhoto(fpath, caption=cap))
                msgs = await client.send_media_group(
                    chat_id=message.chat.id, media=media
                )
                sent_messages.extend(msgs if isinstance(msgs, list) else [msgs])

        try:
            await status_msg.delete()
        except Exception:
            pass
        logger.info(f"✅ تم إرسال {len(files)} صورة للمستخدم {user_id}")

        # تحويل كل الصور لقناة السجلات كألبوم مع تفاصيل العضو (شامل الجنس)
        # — نسخاً بمعرّف الملف (بلا إعادة رفع). نُعيد نسخ القناة لاستخدام
        # معرّفاتها الدائمة في الكاش.
        log_messages = []
        if sent_messages:
            try:
                log_messages = await forward_images_to_log_channel(
                    client=client, message=message, sent_messages=sent_messages,
                    user_id=user_id, user_name=user_name, username=user_username,
                    url=url, video_info=(info or {'title': title}), title=title
                ) or []
            except Exception as log_error:
                logger.error(f"⚠️ خطأ في إرسال الصور للقناة: {log_error}")

        # 💾 حفظ معرّفات الصور في الكاش لإعادة الإرسال لاحقاً بلا تحميل.
        # نفضّل نسخ القناة (دائمة) إن اكتملت، وإلا رسائل المستخدم.
        try:
            def _photo_id(m):
                p = getattr(m, 'photo', None)
                return getattr(p, 'file_id', None) if p else None
            src_msgs = log_messages if len(log_messages) == len(sent_messages) \
                else sent_messages
            file_ids = [fid for fid in (_photo_id(m) for m in src_msgs) if fid]
            if file_ids:
                subdb.save_cached_media(
                    url_key=ckey, quality=IMAGE_CACHE_QUALITY, kind='image',
                    file_id="\n".join(file_ids), title=title,
                    file_size_mb=0, duration=0
                )
                logger.info(f"💾 حُفظت صور الكاش: {ckey} ({len(file_ids)} صورة)")
        except Exception as e:
            logger.warning(f"⚠️ تعذّر حفظ كاش الصور: {e}")

        # تسجيل في سجل التحميلات (للإحصائيات و"تحميلاتي")
        try:
            subdb.add_download_history(user_id, url, title, 'best', 'image',
                                       _platform_of(url), 0, from_cache=False)
        except Exception:
            pass

        # عدّاد الحد اليومي + رسالة المتبقي (لغير المشتركين)
        await _send_daily_remaining_notice(message, user_id, lang)
        return True

    except Exception as e:
        logger.error(f"❌ خطأ في تحميل الصور: {e}")
        error_traceback = traceback.format_exc()
        await send_error_to_admin(user_id, user_name, str(e), url, error_traceback)
        try:
            await status_msg.edit_text(t('download_failed', lang))
        except Exception:
            pass
        return True  # عولج (بخطأ) — لا تكمل لمسار الفيديو
    finally:
        cleanup_download_dir(dl_dir)


# مفتاح ثابت لجودة كاش ألبوم التغريدة المختلط (صور + فيديو في تغريدة واحدة)
ALBUM_CACHE_QUALITY = 'album'


async def _send_media_album(client, chat_id, entries, caption):
    """يرسل قائمة وسائط مختلطة (صور + فيديو) كألبومات تلجرام (حد 10 للمجموعة)
    مع الكابشن على أول وسيط فقط. كل عنصر (النوع، المصدر) والمصدر مسار ملف أو
    file_id من الكاش. لفيديو من ملف نقرأ الأبعاد والمدة (ffprobe) كي يعرضه
    تلجرام بنسبة صحيحة. يعيد قائمة الرسائل المُرسلة."""
    from pyrogram.types import InputMediaPhoto, InputMediaVideo

    def _video_kwargs(src):
        if not (isinstance(src, str) and os.path.isfile(src)):
            return {}  # file_id من الكاش — تلجرام يعرف بياناته أصلاً
        _vc, _ac, width, height, duration = probe_video(src)
        return {k: v for k, v in
                (('width', width), ('height', height), ('duration', duration)) if v}

    sent = []
    chunks = [entries[i:i + 10] for i in range(0, len(entries), 10)]
    for ci, chunk in enumerate(chunks):
        if len(chunk) == 1 and len(chunks) == 1:
            kind, src = chunk[0]
            if kind == 'photo':
                msg = await client.send_photo(
                    chat_id=chat_id, photo=src, caption=caption)
            else:
                msg = await client.send_video(
                    chat_id=chat_id, video=src, caption=caption,
                    **_video_kwargs(src))
            sent.append(msg)
            continue
        media = []
        for fi, (kind, src) in enumerate(chunk):
            cap = caption if (ci == 0 and fi == 0) else None
            if kind == 'photo':
                media.append(InputMediaPhoto(src, caption=cap))
            else:
                media.append(InputMediaVideo(src, caption=cap, **_video_kwargs(src)))
        msgs = await client.send_media_group(chat_id=chat_id, media=media)
        sent.extend(msgs if isinstance(msgs, list) else [msgs])
    return sent


def _album_cache_lines(messages):
    """يحوّل رسائل ألبوم مُرسلة إلى أسطر كاش «النوع:file_id» (يتجاهل ما سواهما)."""
    lines = []
    for m in messages:
        photo = getattr(m, 'photo', None)
        video = getattr(m, 'video', None)
        if photo and getattr(photo, 'file_id', None):
            lines.append('photo:' + photo.file_id)
        elif video and getattr(video, 'file_id', None):
            lines.append('video:' + video.file_id)
    return lines


async def _try_send_album_from_cache(client, message, status_msg, ckey,
                                     user_id, user_name, user_username, url, lang):
    """يعيد إرسال ألبوم تغريدة مختلط من الكاش بمعرّفات الملفات (بلا أي تحميل)
    كمسار كاش الصور. كل سطر معرّف بصيغة «النوع:file_id» لتمييز الصور عن
    الفيديو عند إعادة البناء. يعيد True إن نجح، وFalse إن لا كاش."""
    try:
        cached = subdb.get_cached_media(ckey, ALBUM_CACHE_QUALITY)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر قراءة كاش الألبوم: {e}")
        return False
    if not cached or cached.get('kind') != 'album':
        return False

    entries = []
    for line in (cached.get('file_id') or '').split('\n'):
        kind, _, fid = line.partition(':')
        if fid and kind in ('photo', 'video'):
            entries.append((kind, fid))
    if not entries:
        return False

    title = cached.get('title') or 'Twitter/X'
    bot_username = await _get_bot_username(client)
    caption = t('album_caption', lang, title=title, count=len(entries),
                user=user_name,
                promo=(f"\n\n📥 @{bot_username}" if bot_username else ""))

    try:
        sent_messages = await _send_media_album(
            client, message.chat.id, entries, caption)
    except Exception as e:
        # معرّفات قديمة لم تعد صالحة → احذف الكاش وأعد التحميل عادياً
        logger.warning(f"⚠️ فشل إرسال ألبوم الكاش ({ckey})، سيُعاد التحميل: {e}")
        try:
            subdb.delete_cached_media(ckey, ALBUM_CACHE_QUALITY)
        except Exception:
            pass
        return False

    try:
        await status_msg.delete()
    except Exception:
        pass
    try:
        subdb.bump_cache_hit(ckey, ALBUM_CACHE_QUALITY)
    except Exception:
        pass
    logger.info(f"⚡ كاش ألبوم: أُعيد إرسال {ckey} ({len(entries)} وسيطاً) بلا تحميل")

    try:
        await forward_images_to_log_channel(
            client=client, message=message, sent_messages=sent_messages,
            user_id=user_id, user_name=user_name, username=user_username,
            url=url, video_info={'title': title}, title=title
        )
    except Exception as log_error:
        logger.error(f"⚠️ خطأ في إرسال ألبوم الكاش للقناة: {log_error}")

    await _send_daily_remaining_notice(message, user_id, lang)
    try:
        subdb.add_download_history(user_id, url, title, 'best', 'album',
                                   'twitter', 0, from_cache=True)
    except Exception:
        pass
    return True


async def download_and_send_tweet_media(client, message, url, status_msg,
                                        user_id, user_name, user_username,
                                        lang, info=None):
    """يعالج تغريدة X متعددة/مختلطة الوسائط عبر مرآة fx/vxtwitter العامة:
    - صور فقط → ألبوم صور (مسار الصور القائم نفسه بكاشه وتطبيعه).
    - صور + فيديو أو أكثر من فيديو في تغريدة واحدة → ألبوم مختلط واحد
      بترتيب الوسائط الأصلي (yt-dlp يستخرج الفيديو فقط ويُسقط الصور).

    يعيد True إذا عُولجت التغريدة (أُرسلت وسائطها أو عُرضت رسالة واضحة)،
    وFalse ليُكمل المتصل المسار المعتاد دون أي تغيير في السلوك — تغريدة
    الفيديو الواحد (أزرار الجودة/الصوت) أو مرآة معطّلة/تغريدة بلا وسائط."""
    if _platform_of(url) != 'twitter':
        return False
    loop = asyncio.get_event_loop()
    try:
        items, sensitive = await loop.run_in_executor(
            None, lambda: twitter_mirror_media(url, timeout=10))
    except Exception as e:
        logger.warning(f"⚠️ تعذّر جلب وسائط التغريدة من المرآة: {e}")
        return False
    if not items:
        return False

    # 🔞 التغريدات الحسّاسة (NSFW) تُرفض ما دام فلتر المحتوى مفعّلاً — نفس
    # حماية مسار فيديو المرآة (رسالة «محتوى مقيّد» الواضحة بدل التحميل)
    if sensitive and adult_filter_enabled():
        logger.info("🔞 تغريدة حسّاسة (NSFW) — رُفض مسار الألبوم (فلتر المحتوى مفعّل)")
        await send_error_to_admin(user_id, user_name, "Restricted/sensitive content", url)
        await status_msg.edit_text(t('content_restricted', lang))
        return True

    photos = [it for it in items if it['type'] == 'photo']
    videos = [it for it in items if it['type'] == 'video']

    # صور فقط → مسار ألبوم الصور القائم (كاش الصور/gallery-dl/تطبيع تلجرام)
    if not videos:
        return await download_and_send_images(
            client, message, url, status_msg, user_id, user_name,
            user_username, lang, info,
            fallback_image_urls=[it['url'] for it in photos])

    # فيديو واحد بلا صور → مسار الفيديو المعتاد (أزرار الجودة/الصوت والكاش)
    if len(videos) == 1 and not photos:
        return False

    # تغريدة مختلطة (صور + فيديو) أو متعددة الفيديو → ألبوم واحد
    dl_dir = os.path.join('videos', 'alb_' + uuid.uuid4().hex)
    ckey = cache_key_for_url(url)
    try:
        # ⚡ كاش الألبوم: نفس الرابط محمّل سابقاً → أعِد إرساله فوراً بلا تحميل
        if await _try_send_album_from_cache(
            client, message, status_msg, ckey,
            user_id, user_name, user_username, url, lang
        ):
            return True

        await status_msg.edit_text(t('downloading_album', lang))
        files = await loop.run_in_executor(
            None, lambda: _download_tweet_media_files(items, dl_dir))
        if not files:
            return False  # فشل التنزيل بالكامل → أكمل المسار المعتاد

        # طبّع الصور لصيغ تلجرام المقبولة، واضمن مسار صوت في كل فيديو (GIF
        # التغريدات mp4 بلا صوت فيُعرض كصورة متحركة بدل فيديو)
        entries = []
        for kind, path in files:
            if kind == 'photo':
                norm = _normalize_images_for_telegram([path])
                if norm:
                    entries.append(('photo', norm[0]))
            else:
                await loop.run_in_executor(
                    None, lambda p=path: _ensure_video_has_audio(p))
                entries.append(('video', path))
        if not entries:
            return False

        title = _clean_media_title((info or {}).get('title'), url).replace('`', "'")[:200]
        bot_username = await _get_bot_username(client)
        caption = t('album_caption', lang, title=title, count=len(entries),
                    user=user_name,
                    promo=(f"\n\n📥 @{bot_username}" if bot_username else ""))

        sent_messages = await _send_media_album(
            client, message.chat.id, entries, caption)

        try:
            await status_msg.delete()
        except Exception:
            pass
        n_photos = sum(1 for k, _ in entries if k == 'photo')
        logger.info(f"✅ أُرسل ألبوم تغريدة للمستخدم {user_id}: "
                    f"{n_photos} صورة + {len(entries) - n_photos} فيديو")

        # تحويل الألبوم لقناة السجلات نسخاً بمعرّف الملف (بلا إعادة رفع)،
        # ونفضّل نسخ القناة الدائمة للكاش إن اكتملت
        log_messages = []
        if sent_messages:
            try:
                log_messages = await forward_images_to_log_channel(
                    client=client, message=message, sent_messages=sent_messages,
                    user_id=user_id, user_name=user_name, username=user_username,
                    url=url, video_info=(info or {'title': title}), title=title
                ) or []
            except Exception as log_error:
                logger.error(f"⚠️ خطأ في إرسال الألبوم للقناة: {log_error}")

        # 💾 حفظ معرّفات الوسائط (النوع:file_id لكل سطر) لإعادة الإرسال بلا تحميل
        try:
            src_msgs = log_messages if len(log_messages) == len(sent_messages) \
                else sent_messages
            lines = _album_cache_lines(src_msgs)
            if lines:
                subdb.save_cached_media(
                    url_key=ckey, quality=ALBUM_CACHE_QUALITY, kind='album',
                    file_id="\n".join(lines), title=title,
                    file_size_mb=0, duration=0
                )
                logger.info(f"💾 حُفظ كاش الألبوم: {ckey} ({len(lines)} وسيطاً)")
        except Exception as e:
            logger.warning(f"⚠️ تعذّر حفظ كاش الألبوم: {e}")

        try:
            subdb.add_download_history(user_id, url, title, 'best', 'album',
                                       'twitter', 0, from_cache=False)
        except Exception:
            pass

        await _send_daily_remaining_notice(message, user_id, lang)
        return True

    except Exception as e:
        logger.error(f"❌ خطأ في تحميل ألبوم التغريدة: {e}")
        error_traceback = traceback.format_exc()
        await send_error_to_admin(user_id, user_name, str(e), url, error_traceback)
        try:
            await status_msg.edit_text(t('download_failed', lang))
        except Exception:
            pass
        return True  # عولج (بخطأ) — لا تكمل لمسار الفيديو
    finally:
        cleanup_download_dir(dl_dir)


class PreviewStatus:
    """يلفّ رسالة المعاينة (صورة المصغّرة) لتعمل كرسالة حالة موحّدة:
    كل تحديثات التقدم تُكتب في تسمية الصورة (edit_caption) بدل رسالة منفصلة،
    وبقية العمليات (delete/reply/...) تمرّ للرسالة الأصلية كما هي."""

    def __init__(self, msg):
        self._msg = msg

    def __getattr__(self, name):
        return getattr(self._msg, name)

    async def edit_text(self, text, reply_markup=None, parse_mode=None, **_ignored):
        # تسمية الصورة محدودة بـ1024 محرفاً في تلجرام
        kwargs = {'reply_markup': reply_markup}
        if parse_mode is not None:
            kwargs['parse_mode'] = parse_mode
        return await self._msg.edit_caption(str(text)[:1024], **kwargs)


async def download_and_upload(client, message, url, quality, callback_query=None,
                              status_msg=None):
    """تحميل ورفع الفيديو.

    status_msg (اختياري): رسالة موجودة تُستخدم لعرض التقدم بدل إنشاء رسالة
    جديدة — تُمرَّر رسالة المعاينة (المصغّرة) من زر فيديو/صوت حتى تندمج
    المعاينة والتقدم في رسالة واحدة."""
    # الحصول على معلومات المستخدم من callback_query إذا كان موجوداً
    if callback_query:
        user_id = callback_query.from_user.id
        user_name = callback_query.from_user.first_name
        user_username = callback_query.from_user.username
    else:
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        user_username = message.from_user.username

    # Get user language
    lang = subdb.get_user_language(user_id)
    if status_msg is None:
        status_msg = await message.reply_text(t('processing', lang))
    else:
        if getattr(status_msg, 'photo', None):
            status_msg = PreviewStatus(status_msg)
        try:
            await status_msg.edit_text(t('processing', lang))
        except Exception:
            pass

    # ⏸️ إيقاف التحميل العام (الأدمن مُعفى)
    if not is_admin(user_id) and not downloads_enabled():
        await status_msg.edit_text(t('downloads_paused', lang))
        return

    # 🚫 مستخدم محظور: اعرض شاشة الحظر/التعهّد ولا تكمل (الأدمن مُعفى)
    if not is_admin(user_id) and subdb.is_user_banned(user_id):
        ban_text, ban_kb = _banned_block_content(user_id, lang)
        await status_msg.edit_text(ban_text, reply_markup=ban_kb)
        return

    is_audio = (quality == 'audio')
    ckey = cache_key_for_url(url)

    # ⚡ كاش: إن كان نفس الرابط+الجودة محمّلاً سابقاً، أعِد إرساله فوراً من
    # معرّف الملف (file_id) بلا أي تحميل (الفيديو محفوظ على خوادم تيليجرام).
    if await _try_send_from_cache(client, message, status_msg, ckey, quality,
                                  user_id, user_name, user_username, url, lang):
        return

    # مجلد تحميل مؤقت فريد لكل عملية: يمنع تضارب الأسماء وحذف ملفات تحميلات
    # متزامنة لمستخدمين آخرين (كان الحذف سابقاً يمسح كل الملفات في المجلد).
    dl_dir = os.path.join('videos', uuid.uuid4().hex)

    try:
        os.makedirs(dl_dir, exist_ok=True)
        # إعدادات التحميل
        # نُفضّل ترميز H.264 + صوت AAC (m4a) لأنه متوافق 100% مع مشغّل تلجرام؛
        # ترميز HEVC/H.265 وVP9/AV1 داخل MP4 يشغّله تلجرام بلا صوت على كثير من
        # الأجهزة (أو يجمّد الصورة). المنصات ذات الصيغ المدمجة (فيديو+صوت في صيغة
        # واحدة) مثل تيك توك تُصدّرها yt-dlp باسم ترميز "h264"/"h265" لا "avc1"،
        # فمُحدِّد bestvideo[vcodec^=avc1] لا يطابقها فيسقط إلى best العام الذي
        # يختار H.265 (bytevc1) الأعلى بت-ريت ⇒ فيديو بلا صوت متقطّع. لذا نضيف
        # فرعاً صريحاً يفضّل H.264 المدمج داخل حدّ الدقة نفسه قبل best العام.
        # سلسلة احتياطية تنازلية لضمان نجاح التحميل دائماً.
        quality_formats = {
            'best': (
                'bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/'
                "best[height<=1080][vcodec~='^(avc1|h264)']/"
                'best[height<=1080][ext=mp4]/best[height<=1080]/best'
            ),
            'medium': (
                'bestvideo[height<=720][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/'
                "best[height<=720][vcodec~='^(avc1|h264)']/"
                'best[height<=720][ext=mp4]/best[height<=720]/best'
            ),
            '480': (
                'bestvideo[height<=480][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/'
                "best[height<=480][vcodec~='^(avc1|h264)']/"
                'best[height<=480][ext=mp4]/best[height<=480]/best'
            ),
            '360': (
                'bestvideo[height<=360][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/'
                "best[height<=360][vcodec~='^(avc1|h264)']/"
                'best[height<=360][ext=mp4]/best[height<=360]/best'
            ),
            'audio': 'bestaudio/best'  # النسخة الناجحة - تحميل أفضل جودة صوت
        }
        
        is_audio = (quality == 'audio')
        
        # الحصول على event loop مبكراً
        loop = asyncio.get_event_loop()
        
        # دالة تتبع تقدم التحميل
        last_edit_time = 0
        
        def download_progress_hook(d):
            nonlocal last_edit_time
            if d['status'] == 'downloading':
                try:
                    now = time.time()
                    if now - last_edit_time < 2:  # تحديث كل 2 ثانية
                        return
                        
                    last_edit_time = now
                    
                    total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded_bytes = d.get('downloaded_bytes', 0)
                    
                    if total_bytes > 0:
                        percentage = (downloaded_bytes / total_bytes) * 100
                        current_mb = downloaded_bytes / (1024 * 1024)
                        total_mb = total_bytes / (1024 * 1024)
                        speed = d.get('speed', 0) or 0
                        speed_mb = speed / (1024 * 1024)
                        eta = d.get('eta', 0) or 0
                        
                        filled = int(percentage // 10)
                        progress_bar = '▰' * filled + '▱' * (10 - filled)
                        
                        # DEBUG: Log the language being used
                        logger.info(f"📥 Download progress for user {user_id}, lang={lang}")
                        
                        msg_text = t('downloading', lang, 
                                    percent=f'{percentage:.1f}',
                                    current_mb=f'{current_mb:.1f}',
                                    total_mb=f'{total_mb:.1f}',
                                    speed_mb=f'{speed_mb:.1f}',
                                    eta=eta,
                                    progress_bar=progress_bar)
                        
                        # تحديث الرسالة من thread منفصل
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                status_msg.edit_text(msg_text),
                                loop
                            )
                            # لا ننتظر النتيجة لتجنب الحظر
                        except Exception:
                            pass
                            
                except Exception as e:
                    logger.error(f"خطأ في progress hook: {e}")
        
        # دالة تتبع مرحلة المعالجة (post-processing)
        def postprocessor_hook(d):
            try:
                status = d.get('status')
                logger.info(f"🔄 Post-processor status: {status}")
                
                if status == 'started':
                    postprocessor = d.get('postprocessor', 'Unknown')
                    logger.info(f"🔧 بدء المعالجة: {postprocessor}")
                    # تم إزالة رسالة المعالجة - المستخدم لا يريدها
                        
                elif status == 'finished':
                    logger.info(f"✅ اكتملت المعالجة")
                    
            except Exception as e:
                logger.error(f"خطأ في postprocessor hook: {e}")


        # تحسين إعدادات التحميل للسرعة والاستقرار
        logger.info("🚀 Using optimized download settings for better performance")
        
        ydl_opts = {
            'format': quality_formats.get(quality, 'best'),
            # حدّ طول العنوان بالبايت (B) لا بالأحرف: الأحرف العربية/الإيموجي
            # تأخذ عدة بايتات، وحدّ اسم الملف في لينكس 255 بايت. 150B يترك
            # مساحة كافية للاحقات yt-dlp المؤقتة (.fXXX/.part) والامتداد.
            # [%(id)s] يضمن اسماً صالحاً وفريداً حتى لو كان العنوان فارغاً.
            # نحدّ الـ id أيضاً بالبايت لأن بعض المنصات (سناب) تجعله ضخماً
            # (يحوي كل معاملات الرابط) فيتجاوز اسم الملف 255 بايت ويفشل التحميل.
            'outtmpl': os.path.join(dl_dir, '%(title).120B [%(id).50B].%(ext)s'),
            # أمان شامل: حدّ أقصى لطول اسم الملف مهما طال العنوان/المعرّف
            'trim_file_name': 200,
            'progress_hooks': [download_progress_hook],
            'postprocessor_hooks': [postprocessor_hook],  # تتبع مرحلة المعالجة
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'retries': 15,
            'fragment_retries': 15,
            # تحميل أجزاء DASH/HLS بالتوازي = أسرع بكثير ليوتيوب والمنصات المجزّأة
            'concurrent_fragment_downloads': YTDLP_CONCURRENT_FRAGMENTS,
            'noplaylist': True,  # نزّل الفيديو الواحد فقط حتى لو الرابط ضمن قائمة
            'nocheckcertificate': _YTDLP_NO_CHECK_CERT,
            # لا تضبط تاريخ الملف على تاريخ رفع الفيديو الأصلي القديم
            # حتى يظهر المقطع بترتيب وقت التحميل في معرض الهاتف
            'updatetime': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
        }
        
        # اختيار ملف cookies المطابق لمنصة الرابط (ضروري لستوري فيسبوك/إنستغرام)
        cookie_file = get_cookie_file_for_url(url)
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file
            logger.info(f"🍪 استخدام cookies للتحميل: {cookie_file}")

        # ليوتيوب: جرّب عملاء متعددين + السماح بالصيغ المحجوبة لتفادي حجب الصيغ (PO token)
        if any(m in url.lower() for m in PLATFORM_URL_MARKERS['youtube']):
            ydl_opts['extractor_args'] = _youtube_extractor_args()

        # للملفات الصوتية: تحويل إلى MP3 فقط إذا لم يكن MP3 بالفعل
        if is_audio:
            # تحويل إلى MP3 بجودة عالية (192kbps) - سريع جداً!
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',  # جودة عالية
            }]
            logger.info("🎵 استخراج الصوت بجودة عالية (192kbps)")
        # لا نحتاج FFmpegVideoConvertor لأن merge_output_format=mp4 تكفي
        # وإضافته تسبب مشاكل conversion مع الملفات الكبيرة
        
        
        # التحميل - استخدام نظام الترجمة
        await status_msg.edit_text(t('start_downloading', lang))
        
        is_youtube_url = any(m in url.lower() for m in PLATFORM_URL_MARKERS['youtube'])
        is_facebook_url = any(m in url.lower() for m in PLATFORM_URL_MARKERS['facebook'])
        is_instagram_url = _platform_of(url) == 'instagram'
        is_tiktok_url = _platform_of(url) == 'tiktok'
        is_pinterest_url = _platform_of(url) == 'pinterest'

        def download(use_cookies=True, fmt=None, url_override=None, yt_clients=None):
            o = dict(ydl_opts)
            if fmt:
                o['format'] = fmt
            if not use_cookies:
                o.pop('cookiefile', None)
            # فرض مجموعة عملاء مشغّل بديلة ليوتيوب (لإعادة الاستخراج بروابط جديدة)
            if yt_clients and is_youtube_url:
                o['extractor_args'] = {
                    'youtube': {'player_client': list(yt_clients),
                                'formats': ['missing_pot']}
                }
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url_override or url, download=True)
                return info, ydl.prepare_filename(info)

        # عملاء مشغّل بديلون ليوتيوب عند خطأ 403 (روابط صيغ محظورة/منتهية):
        # إعادة الاستخراج بهؤلاء تعطي روابط تنزيل جديدة غير محظورة.
        YT_403_FALLBACK_CLIENTS = ['tv', 'ios', 'web_safari', 'mweb', 'android']

        # صيغة متساهلة احتياطية عند فشل المُحدّد الصارم (بلا فلترة ترميز/امتداد)
        fallback_fmt = 'bestaudio/best' if is_audio else 'bv*+ba/b/best'

        try:
            if ydl_opts.get('cookiefile') and is_facebook_url:
                # فيسبوك مع كوكيز الدخول قد يحمّل فيديو إعلان محقون بدل
                # المطلوب → بدون كوكيز أولاً، وبالكوكيز عند الفشل (ستوري/خاص)
                try:
                    info, file_path = await loop.run_in_executor(None, lambda: download(False))
                except Exception:
                    logger.warning("⚠️ فشل تحميل فيسبوك بدون كوكيز، إعادة المحاولة بالكوكيز...")
                    info, file_path = await loop.run_in_executor(None, lambda: download(True))
            else:
                info, file_path = await loop.run_in_executor(None, lambda: download(True))
        except Exception as dl_err:
            msg = str(dl_err).lower()
            # يوتيوب مع الكوكيز قد يفشل بسبب حجب الصيغ → أعد المحاولة بدون كوكيز
            if ydl_opts.get('cookiefile') and is_youtube_url and _is_youtube_cookie_issue(dl_err):
                logger.warning("⚠️ فشل تحميل يوتيوب مع الكوكيز، إعادة المحاولة بدون كوكيز...")
                try:
                    info, file_path = await loop.run_in_executor(None, lambda: download(False))
                except Exception as e2:
                    if 'requested format is not available' in str(e2).lower() or 'no video formats' in str(e2).lower():
                        logger.warning("⚠️ الصيغة غير متوفرة، إعادة المحاولة بأفضل صيغة متاحة (بلا كوكيز)")
                        info, file_path = await loop.run_in_executor(None, lambda: download(False, fallback_fmt))
                    else:
                        raise
            # يوتيوب: خطأ 403 عند تنزيل بيانات الفيديو = روابط صيغ محظورة/منتهية
            # لعميل المشغّل الحالي → أعد الاستخراج بعملاء بدلاء (روابط جديدة) وبلا كوكيز
            elif is_youtube_url and _is_http_403_error(dl_err):
                logger.warning("⚠️ فشل تحميل يوتيوب بخطأ 403، إعادة المحاولة بعملاء مشغّل بدلاء...")
                try:
                    info, file_path = await loop.run_in_executor(
                        None, lambda: download(False, yt_clients=YT_403_FALLBACK_CLIENTS))
                except Exception:
                    logger.warning("⚠️ استمرار فشل يوتيوب 403، إعادة المحاولة بأفضل صيغة متاحة")
                    info, file_path = await loop.run_in_executor(
                        None, lambda: download(False, fallback_fmt,
                                               yt_clients=YT_403_FALLBACK_CLIENTS))
            # فيسبوك بكوكيز فاسدة قد يكسر تحميل المحتوى العام → أعد المحاولة بدون كوكيز
            elif ydl_opts.get('cookiefile') and is_facebook_url and _is_facebook_cookie_issue(dl_err):
                logger.warning("⚠️ فشل تحميل فيسبوك مع الكوكيز (Cannot parse data)، إعادة المحاولة بدون كوكيز...")
                info, file_path = await loop.run_in_executor(None, lambda: download(False))
            # ملف كوكيز تالف (صيغة غير صحيحة) يفشل لأي منصة → أعد المحاولة بدون كوكيز
            elif ydl_opts.get('cookiefile') and _is_cookie_file_issue(dl_err):
                logger.warning(f"⚠️ ملف الكوكيز تالف/غير صالح ({ydl_opts.get('cookiefile')})، إعادة المحاولة بدون كوكيز...")
                info, file_path = await loop.run_in_executor(None, lambda: download(False))
            # 🎯 إنستغرام مع كوكيز: كوكيز منتهية/خارج الحساب تُرجع 404 لمنشور عام
            #    يعمل بلا كوكيز → أعد المحاولة بدون كوكيز (تنجح غالباً للمحتوى العام).
            #    إن فشلت أيضاً (محتوى خاص فعلاً) جرّب المرآة العامة كخطة أخيرة.
            elif ydl_opts.get('cookiefile') and is_instagram_url:
                logger.warning("⚠️ فشل تحميل إنستغرام مع الكوكيز، إعادة المحاولة بدون كوكيز...")
                try:
                    info, file_path = await loop.run_in_executor(None, lambda: download(False))
                except Exception:
                    _direct = await resolve_instagram_direct(url)
                    if _direct:
                        logger.info("✅ تحميل إنستغرام عبر المرآة العامة (بديل، بلا كوكيز)")
                        info, file_path = await loop.run_in_executor(
                            None, lambda: download(url_override=_direct))
                    else:
                        raise
            # 🎯 إنستغرام (بلا كوكيز): الوصول المجهول محجوب فيعجز yt-dlp → حل الرابط
            #    لملف فيديو مباشر عبر مرآة عامة (بلا كوكيز) وحمّله منها
            elif is_instagram_url and (_direct := await resolve_instagram_direct(url)):
                logger.info("✅ تحميل إنستغرام عبر المرآة العامة (بديل yt-dlp، بلا كوكيز)")
                info, file_path = await loop.run_in_executor(
                    None, lambda: download(url_override=_direct))
            # 🎯 تيك توك: فشل yt-dlp لحجب IP الخادم أو محتوى حسّاس يتطلّب تسجيل دخول
            #    ("This post may not be comfortable...") → حل الرابط لملف فيديو مباشر
            #    عبر مرآة عامة (بلا كوكيز) وحمّله منها. يعالج نفس الحالة الموجودة
            #    في get_video_info لكنها كانت مفقودة هنا فيفشل التحميل رغم نجاح المعاينة.
            elif is_tiktok_url and (_direct := await resolve_tiktok_direct(url)):
                logger.info("✅ تحميل تيك توك عبر المرآة العامة (بديل yt-dlp، بلا كوكيز)")
                info, file_path = await loop.run_in_executor(
                    None, lambda: download(url_override=_direct))
            # 🎯 بينتريست: فشل yt-dlp (تغييرات الموقع/حجب) → حل الرابط لملف فيديو
            #    مباشر عبر واجهة بينتريست العامة (بلا كوكيز) وحمّله منها
            elif is_pinterest_url and (_direct := await resolve_pinterest_direct(url)):
                logger.info("✅ تحميل بينتريست عبر الواجهة العامة (بديل yt-dlp، بلا كوكيز)")
                info, file_path = await loop.run_in_executor(
                    None, lambda: download(url_override=_direct))
            # 🎯 ملاحظات Substack: yt-dlp لا يدعم صفحاتها → حمّل من وسيط الفيديو
            #    الموقّع عبر واجهة Substack العامة (بلا كوكيز)
            elif is_substack_note(url) and (_direct := await resolve_substack_direct(url)):
                logger.info("✅ تحميل ملاحظة Substack عبر الواجهة العامة (بلا كوكيز)")
                info, file_path = await loop.run_in_executor(
                    None, lambda: download(url_override=_direct))
            # الصيغة المطلوبة غير متوفرة → أعد المحاولة بأفضل صيغة متاحة
            elif 'requested format is not available' in msg or 'no video formats' in msg:
                logger.warning("⚠️ الصيغة المطلوبة غير متوفرة، إعادة المحاولة بأفضل صيغة متاحة")
                info, file_path = await loop.run_in_executor(None, lambda: download(True, fallback_fmt))
            else:
                raise

        # 🔞 شبكة أمان: امنع المحتوى الحساس/المحظور قبل الرفع (يغطي القوائم وإعادة
        # التحميل وأي مسار)، حتى لو فات الفحص الأول. لا نرفعه ولا نخزّنه في الكاش.
        if (adult_filter_enabled() and is_adult_info(info)) or is_blocked_account(info):
            logger.info(f"🚫 Blocked at download stage for user {user_id}: {info.get('uploader')}")
            ban_text, ban_kb = await _apply_adult_ban(client, user_id, lang)
            await status_msg.edit_text(ban_text, reply_markup=ban_kb)
            return

        # ⚠️ إذا كان تحميل صوتي، FFmpegExtractAudio يغير الامتداد إلى .mp3
        # لذلك نحتاج إلى تحديث file_path للملف الحقيقي
        if is_audio:
            # تحويل الامتداد إلى .mp3 (FFmpeg يفعل ذلك تلقائياً)
            base_name = os.path.splitext(file_path)[0]
            mp3_file = f"{base_name}.mp3"
            
            if os.path.exists(mp3_file):
                file_path = mp3_file
                logger.info(f"✅ تم العثور على ملف MP3: {file_path}")
            else:
                logger.warning(f"⚠️ لم يتم العثور على {mp3_file}, استخدام المسار الأصلي")
        
        if not os.path.exists(file_path):
            logger.error(f"❌ الملف غير موجود: {file_path}")
            
            # محاولة البحث عن أي ملف صوتي تم تحميله حديثاً
            if is_audio:
                logger.info("🔍 البحث عن ملفات صوتية تم تحميلها...")
                audio_files = []
                for ext in ['*.mp3', '*.m4a', '*.opus', '*.ogg']:
                    audio_files.extend(glob.glob(os.path.join(dl_dir, ext)))
                
                if audio_files:
                    # استخدام أحدث ملف (آخر ملف تم تعديله)
                    latest_file = max(audio_files, key=os.path.getmtime)
                    logger.info(f"✅ تم العثور على ملف صوتي: {latest_file}")
                    file_path = latest_file
                else:
                    logger.error("❌ لم يتم العثور على أي ملفات صوتية")
                    await status_msg.edit_text(t('download_failed', lang))
                    return
            else:
                await status_msg.edit_text(t('download_failed', lang))
                return
        
        # معلومات الملف
        file_size_mb = get_file_size_mb(file_path)
        duration = info.get('duration', 0)
        # العنوان: اسم نظيف موحّد بين المنصات (يستبدل معرّفات CDN القبيحة مثل
        # إنستغرام عبر المرآة)، مع إزالة ` حتى لا يكسر تنسيق النسخ وحد آمن للوصف
        title = _clean_media_title(info.get('title'), url).replace('`', "'")[:300]
        
        logger.info(f"📊 حجم الملف النهائي: {file_size_mb:.2f} MB")

        # التحقق من الحجم
        if file_size_mb > 2000:
            await status_msg.edit_text(t('file_too_large', lang, size=f"{file_size_mb:.1f}"))
            os.remove(file_path)
            return
        # Upload
        lang = subdb.get_user_language(user_id)
        # Initial upload message with progress bar at 0%
        initial_progress = t('uploading', lang,
                           percent='0.0',
                           current_mb='0.0',
                           total_mb=f'{file_size_mb:.1f}',
                           speed_mb='0.0',
                           eta=0,
                           progress_bar='▱▱▱▱▱▱▱▱▱▱')
        await status_msg.edit_text(initial_progress)
        
        # الوصف الموحّد: العنوان قابل للنسخ + يوزر البوت (يبقى مع الفيديو)
        caption = _build_media_caption(
            title, file_size_mb, duration, user_name,
            bot_username=await _get_bot_username(client)
        )
        
        if is_audio:
            # التأكد من duration صحيح
            audio_duration = int(duration) if duration and duration > 0 else None
            
            # Create upload progress tracker instance with event loop
            upload_progress_tracker = UploadProgress(status_msg, user_id, loop)
            
            # إرسال كملف صوتي عادي (Audio) - يدعم ملفات كبيرة حتى 2GB
            logger.info(f"📤 إرسال كملف صوتي (Audio): {file_size_mb:.1f}MB, duration={audio_duration}s")
            
            sent_msg = await client.send_audio(
                chat_id=message.chat.id,
                audio=file_path,
                caption=caption,
                duration=audio_duration,
                progress=upload_progress_tracker
            )
            logger.info(f"✅ نجح إرسال الملف الصوتي: {file_size_mb:.1f}MB")
            cache_kind, cache_dur, cache_w, cache_h = 'audio', audio_duration, None, None


        else:
            # تجهيز الفيديو لكل المنصات: H.264/AAC + faststart (يمنع تجمّد الصورة)
            # + تاريخ التحميل، ويرجع الأبعاد/المدة الحقيقية من الملف نفسه
            probed_w, probed_h, probed_dur = await loop.run_in_executor(
                None, lambda: finalize_video(file_path)
            )

            # يضمن وجود مسار صوت (يضيف صمتاً إن غاب) حتى لا يعرض تلجرام الفيديو
            # كصورة متحركة. مكتفٍ ذاتياً في bot.py ليعمل مع مزامنة bot.py وحدها،
            # وخامل إن كان finalize_video قد أضاف الصوت أصلاً (لا عمل مكرر).
            await loop.run_in_executor(None, lambda: _ensure_video_has_audio(file_path))

            # الأبعاد/المدة من الملف أولاً ثم من معلومات yt-dlp (مهم للمنصات
            # التي لا توفّر أبعاداً مثل فيسبوك، فغيابها يُظهر صورة متجمّدة)
            video_width = probed_w or (int(info['width']) if info.get('width') else None)
            video_height = probed_h or (int(info['height']) if info.get('height') else None)
            _dur = probed_dur or duration
            video_duration = int(_dur) if _dur and _dur > 0 else None

            # توليد مصغّر ثابت لمنع ظهور إطار أسود/متجمّد في تلجرام
            thumb_path = await loop.run_in_executor(
                None, lambda: generate_video_thumbnail(file_path, video_duration)
            )

            logger.info(f"📹 Sending video: duration={video_duration}, width={video_width}, height={video_height}, thumb={bool(thumb_path)}")

            # زر واحد لدعم المطور: يَنسخ معرّف Binance عند الضغط
            binance_id = subdb.get_setting('binance_pay_id', os.getenv('BINANCE_PAY_ID', ''))
            lang = subdb.get_user_language(user_id)
            support_keyboard = _binance_support_keyboard(binance_id, lang)
            
            # Create upload progress tracker instance with event loop
            upload_progress_tracker = UploadProgress(status_msg, user_id, loop)
            
            try:
                sent_msg = await client.send_video(
                    chat_id=message.chat.id,
                    video=file_path,
                    caption=caption,
                    duration=video_duration,
                    width=video_width,
                    height=video_height,
                    thumb=thumb_path,
                    supports_streaming=True,
                    reply_markup=support_keyboard,
                    progress=upload_progress_tracker
                )
            except Exception as send_error:
                logger.error(f"❌ خطأ في send_video: {send_error}")
                # محاولة بدون أي معاملات إضافية
                logger.info("🔄 Retrying with minimal parameters...")
                sent_msg = await client.send_video(
                    chat_id=message.chat.id,
                    video=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    supports_streaming=True
                )
            finally:
                # حذف ملف المصغّر المؤقت بعد الرفع
                if thumb_path and os.path.exists(thumb_path):
                    try:
                        os.remove(thumb_path)
                    except Exception:
                        pass
            cache_kind, cache_dur, cache_w, cache_h = 'video', video_duration, video_width, video_height

        await status_msg.delete()
        logger.info(f"✅ نجح رفع {file_size_mb:.1f}MB للمستخدم {user_id}")
        
        # تحويل الفيديو إلى قناة السجلات (نلتقط رسالة السجل لإعادة استخدامها كمرجع كاش)
        log_msg = None
        try:
            log_msg = await forward_to_log_channel(
                client=client,
                message=message,
                sent_message=sent_msg,
                user_id=user_id,
                user_name=user_name,
                username=user_username,
                url=url,
                video_info=info,
                duration=duration,
                file_size_mb=file_size_mb
            )
        except Exception as log_error:
            logger.error(f"⚠️ خطأ في إرسال للقناة: {log_error}")

        # 💾 حفظ في الكاش لإعادة الإرسال الفوري مستقبلاً (بلا تحميل)
        # نعيد استخدام نسخة قناة السجلات نفسها (لا قناة أرشيف منفصلة)
        await _save_media_to_cache(
            sent_msg, log_msg, ckey, quality, cache_kind, title,
            file_size_mb, cache_dur, cache_w, cache_h
        )

        # 📝 تسجيل في سجل التحميلات (للإحصائيات و"تحميلاتي")
        try:
            subdb.add_download_history(user_id, url, title, quality, cache_kind,
                                       _platform_of(url), file_size_mb, from_cache=False)
        except Exception:
            pass

        # تنظيف مجلد التحميل المؤقت (يتم أيضاً في finally كضمان)
        cleanup_download_dir(dl_dir)

        # زيادة عداد التحميلات اليومية للمستخدمين غير المشتركين
        if not subdb.is_user_subscribed(user_id):
            subdb.increment_download_count(user_id)
            
            # عرض رسالة التحميلات المتبقية (الحد = الأساس + دعواته)
            base_limit = subdb.get_daily_limit()
            if base_limit != -1:  # فقط إذا لم يكن غير محدود
                effective_limit = base_limit + subdb.get_bonus_downloads(user_id)
                daily_count = subdb.check_daily_limit(user_id)
                remaining = effective_limit - daily_count

                if remaining > 0:
                    # الحصول على لغة المستخدم
                    lang = subdb.get_user_language(user_id)
                    await message.reply_text(
                        t('downloads_remaining', lang, remaining=remaining)
                    )

        
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        
        # إذا كان الخطأ to_bytes، يعني الفيديو نجح لكن مشكلة metadata
        if 'to_bytes' in str(e):
            # الفيديو تم رفعه بنجاح، فقط نحذف الرسالة والملفات
            try:
                await status_msg.delete()
                logger.info(f"✅ نجح رفع {file_size_mb:.1f}MB للمستخدم {user_id} (تم تجاهل خطأ metadata)")
            except Exception:
                pass
        else:
            # خطأ حقيقي - إرسال تنبيه للأدمن
            # ملاحظة: user_name مضبوط صحيحاً في بداية الدالة (من callback_query
            # أو message)؛ لا نعيد ضبطه من message.from_user لأنها قد تكون رسالة
            # البوت نفسه عند التحميل عبر أزرار الجودة (فيظهر الخطأ باسم البوت).

            # الحصول على traceback الكامل
            error_traceback = traceback.format_exc()
            
            # إرسال الخطأ مع traceback إلى القناة
            await send_error_to_admin(user_id, user_name, str(e), url, error_traceback)
            
            error_text = str(e)
            
            # تنظيف رسالة الخطأ من ANSI codes
            import re
            error_text = re.sub(r'\x1b\[[0-9;]*m', '', error_text)
            
            # Get user language for error messages
            lang = subdb.get_user_language(user_id)

            # رسائل مخصصة لأخطاء معينة
            if _is_geo_restricted_error(error_text, url):
                await status_msg.edit_text(t('geo_restricted', lang))
            elif _is_drm_error(error_text):
                await status_msg.edit_text(t('drm_protected', lang))
            elif 'Cannot parse data' in error_text and 'facebook' in error_text.lower():
                await status_msg.edit_text(t('facebook_unavailable', lang))
            elif 'Pinterest' in error_text and ('Connection reset' in error_text or 'Unable to download' in error_text):
                await status_msg.edit_text(t('pinterest_unavailable', lang))
            else:
                # تقصير رسالة الخطأ
                short_error = error_text.split('\n')[0][:100]
                await status_msg.edit_text(t('generic_error', lang, error=short_error))

    finally:
        # ضمان حذف مجلد التحميل المؤقت في كل الحالات (نجاح أو فشل)
        cleanup_download_dir(dl_dir)



# ═══════════════════════════════════════════════════════════════
# Handlers
# ═══════════════════════════════════════════════════════════════

_bot_username = None


async def _get_bot_username(client):
    """اسم مستخدم البوت (يُجلب مرة ويُخزَّن) لبناء روابط الدعوة."""
    global _bot_username
    if _bot_username is None:
        try:
            me = await client.get_me()
            _bot_username = me.username
        except Exception:
            _bot_username = None
    return _bot_username


async def _process_referral_start(client, message, new_user_id):
    """يعالج رابط الدعوة (?start=ref_<id>) لمستخدم جديد: يمنح الداعي رصيداً مرة واحدة."""
    try:
        parts = getattr(message, 'command', None) or []
        if len(parts) < 2 or not str(parts[1]).startswith('ref_'):
            return
        referrer_id = int(str(parts[1])[4:])
    except (ValueError, TypeError):
        return
    if not subdb.record_referral(new_user_id, referrer_id):
        return  # دعوة مكررة أو دعوة النفس
    subdb.add_bonus_downloads(referrer_id, REFERRAL_BONUS)
    # الحد اليومي الجديد للداعي = الأساس + مجموع دعواته
    base = subdb.get_daily_limit()
    new_limit = (base + subdb.get_bonus_downloads(referrer_id)) if base != -1 else '∞'
    # الحد الجديد لمدة الفيديو للداعي (يزيد +REFERRAL_MINUTES دقيقة مع كل دعوة)
    new_max_minutes = _user_max_duration_minutes(referrer_id)
    logger.info(
        f"🎁 دعوة جديدة: {new_user_id} عبر {referrer_id} "
        f"(الحد اليومي {new_limit}، مدة الفيديو {new_max_minutes} دقيقة)"
    )
    try:
        r_lang = subdb.get_user_language(referrer_id)
        await client.send_message(
            referrer_id,
            t('referral_granted', r_lang, bonus=REFERRAL_BONUS, limit=new_limit,
              bonus_min=subdb.get_referral_minutes(), max_minutes=new_max_minutes)
        )
    except Exception:
        pass


async def _show_history(client, message):
    """يعرض آخر تحميلات المستخدم كأزرار؛ الضغط يعيد الإرسال فوراً من الكاش."""
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    rows = subdb.get_user_history(user_id, 10)
    if not rows:
        await message.reply_text(t('history_empty', lang))
        return
    qmap = {'best': '1080p', 'medium': '720p', '480': '480p', '360': '360p', 'audio': 'MP3'}
    buttons = []
    for hid, title, quality, kind, created, url in rows:
        qd = 'MP3' if kind == 'audio' else qmap.get(quality, quality or '')
        label = f"{(title or 'فيديو')[:35]} • {qd}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"redl_{hid}")])
    await message.reply_text(
        t('history_title', lang) + "\n" + t('history_tap_hint', lang),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@app.on_callback_query(filters.regex(r'^redl_'))
async def handle_redownload(client, callback_query):
    """يعيد إرسال فيديو من السجل: فوراً من الكاش إن وُجد، وإلا يحمّله من جديد."""
    await callback_query.answer()
    user_id = callback_query.from_user.id
    lang = subdb.get_user_language(user_id)
    try:
        history_id = int(callback_query.data.replace('redl_', ''))
    except ValueError:
        return
    item = subdb.get_history_item(history_id, user_id)
    if not item or not item.get('url'):
        await callback_query.message.reply_text(
            t('error_occurred', lang, error="not found")
        )
        return
    # 🔞 فلتر المحتوى يسري على إعادة التحميل من السجل أيضاً — يلتقط النطاقات
    # والكلمات التي أضافها الأدمن بعد التحميل الأصلي
    if adult_filter_enabled() and is_adult_url(item['url']):
        await callback_query.message.reply_text(t('adult_blocked', lang))
        return
    # 🖼️ عنصر صور: أعد تحميله عبر مسار الصور (gallery-dl) لا مسار الفيديو
    if item.get('kind') == 'image':
        u = callback_query.from_user
        status = await callback_query.message.reply_text(t('processing', lang))
        await download_and_send_images(
            client, callback_query.message, item['url'], status,
            user_id, u.first_name or "User", u.username, lang, None
        )
        return
    # download_and_upload يفحص الكاش أولاً (إرسال فوري) وإلا يحمّل من جديد
    await download_and_upload(client, callback_query.message,
                             item['url'], item['quality'] or 'best', callback_query)


async def _build_invite_text(client, user_id, lang):
    """يبني نص رابط الدعوة وإحصاءاته (أو None إذا تعذّر جلب اسم البوت)."""
    uname = await _get_bot_username(client)
    if not uname:
        return None
    link = f"https://t.me/{uname}?start=ref_{user_id}"
    count = subdb.get_referral_count(user_id)
    base = subdb.get_daily_limit()
    limit = (base + subdb.get_bonus_downloads(user_id)) if base != -1 else '∞'
    max_minutes = _user_max_duration_minutes(user_id)
    return t('invite_info', lang, link=link, bonus=REFERRAL_BONUS,
             count=count, limit=limit, bonus_min=subdb.get_referral_minutes(),
             max_minutes=max_minutes)


def _invite_button(lang):
    """زر الدعوة الذي يظهر عند انتهاء الحد اليومي."""
    return InlineKeyboardButton(t('btn_invite', lang), callback_data="show_invite")


def _user_max_duration_minutes(user_id) -> int:
    """أقصى مدة فيديو مسموحة لهذا المستخدم بالدقائق.
    = الأساس (إعداد الأدمن) + (عدد أصدقائه الذين انضموا عبر رابطه × مكافأة الدعوة).
    كل دعوة ناجحة ترفع الحد دائماً بمقدار دقائق الدعوة (يُدار من لوحة الأدمن)."""
    base = subdb.get_max_duration()
    return base + subdb.get_referral_count(user_id) * subdb.get_referral_minutes()


# ═══════════════════════════════════════════════════════════════
# نظام العقوبات: حظر بسبب الإباحية + تعهّد للعودة
# ═══════════════════════════════════════════════════════════════

def _ban_screen_content(lang, ban_info):
    """يبني (نص، أزرار) شاشة الحظر حسب الحالة (أول مخالفة أم حظر دائم)."""
    # نقض التعهّد سابقاً (pledged) ثم حُظر مجدداً = حظر دائم (الأدمن فقط يرفعه)
    if ban_info and ban_info.get('pledged'):
        return t('banned_permanent', lang), InlineKeyboardMarkup([[_invite_button(lang)]])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('btn_pledge', lang), callback_data='pledge_unban')],
        [_invite_button(lang)],
    ])
    return t('banned_screen', lang), keyboard


async def _apply_adult_ban(client, user_id, lang):
    """يحظر المستخدم بسبب محاولة تحميل إباحي ويرجع (نص، أزرار) لشاشة الحظر.
    الأدمن مُعفى (لا يُحظر، يُعرض له الرفض فقط)."""
    if is_admin(user_id):
        return t('adult_blocked', lang), None
    strikes = subdb.ban_user(user_id, t('ban_reason_adult', lang))
    logger.info(f"🚫 حظر المستخدم {user_id} بسبب الإباحية (مخالفة #{strikes})")
    return _ban_screen_content(lang, subdb.get_ban_info(user_id))


def _banned_block_content(user_id, lang):
    """شاشة الحظر لمستخدم محظور أصلاً (للتذكير عند محاولته الاستخدام)."""
    return _ban_screen_content(lang, subdb.get_ban_info(user_id))


@app.on_callback_query(filters.regex(r'^pledge_unban$'))
async def handle_pledge_unban(client, callback_query):
    """رفع الحظر عبر التعهّد (مرة واحدة). نقضه لاحقاً = حظر دائم."""
    await callback_query.answer()
    user_id = callback_query.from_user.id
    lang = subdb.get_user_language(user_id)
    if subdb.pledge_unban(user_id):
        logger.info(f"✋ المستخدم {user_id} تعهّد ورُفع حظره")
        await callback_query.message.edit_text(t('pledge_accepted', lang))
    else:
        await callback_query.message.edit_text(t('pledge_denied', lang))


@app.on_message(filters.command("unban"))
async def cmd_unban(client, message):
    """رفع الحظر عن مستخدم (أدمن)."""
    if not is_admin(message.from_user.id):
        return
    parts = getattr(message, 'command', []) or []
    if len(parts) < 2:
        await message.reply_text("الاستخدام: /unban <معرّف المستخدم>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await message.reply_text("❌ معرّف غير صالح.")
        return
    if subdb.admin_unban(uid):
        await message.reply_text(f"✅ تم رفع الحظر عن المستخدم {uid}")
        try:
            await client.send_message(uid, t('pledge_accepted', subdb.get_user_language(uid)))
        except Exception:
            pass
    else:
        await message.reply_text(f"ℹ️ المستخدم {uid} غير محظور.")


@app.on_message(filters.command("banned"))
async def cmd_banned(client, message):
    """قائمة المحظورين (أدمن)."""
    if not is_admin(message.from_user.id):
        return
    rows = subdb.get_banned_users()
    if not rows:
        await message.reply_text("✅ لا يوجد مستخدمون محظورون.")
        return
    body = "\n".join(
        f"  • <code>{uid}</code> — {html.escape(str(reason or ''))} (مخالفات: {strikes})"
        for uid, reason, strikes in rows
    )
    await message.reply_text(
        f"🚫 <b>المحظورون ({len(rows)}):</b>\n{body}\n\nلرفع الحظر: /unban &lt;المعرّف&gt;",
        parse_mode=enums.ParseMode.HTML
    )


def _admin_ban_buttons(uid):
    """أزرار تحكّم الأدمن لحظر/رفع حظر مستخدم (تظهر في قناة السجلات)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔨 حظر دائم", callback_data=f"permban_{uid}"),
         InlineKeyboardButton("⚠️ تحذير", callback_data=f"warnban_{uid}")],
        [InlineKeyboardButton("✅ رفع الحظر", callback_data=f"adminunban_{uid}")],
    ])


async def _notify_user_ban_state(client, uid, permanent):
    """يُشعر المستخدم بحالته الجديدة (حظر دائم/تحذيري) مع شاشة التعهّد إن أمكن."""
    try:
        ulang = subdb.get_user_language(uid)
        if permanent:
            await client.send_message(uid, t('banned_permanent', ulang))
        else:
            text, kb = _banned_block_content(uid, ulang)
            await client.send_message(uid, text, reply_markup=kb)
    except Exception:
        pass


@app.on_callback_query(filters.regex(r'^permban_'))
async def handle_admin_permban(client, callback_query):
    """حظر دائم لمستخدم (زر أدمن في قناة السجلات)."""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("للمشرفين فقط!", show_alert=True)
        return
    try:
        uid = int(callback_query.data.split('_', 1)[1])
    except (ValueError, IndexError):
        return
    subdb.admin_ban(uid, "حظر دائم من الأدمن", permanent=True)
    logger.info(f"🔨 الأدمن حظر المستخدم {uid} حظراً دائماً")
    await callback_query.answer(f"🔨 تم حظر {uid} حظراً دائماً", show_alert=True)
    await _notify_user_ban_state(client, uid, permanent=True)


@app.on_callback_query(filters.regex(r'^warnban_'))
async def handle_admin_warnban(client, callback_query):
    """حظر تحذيري (يستطيع المستخدم رفعه بالتعهّد) — زر أدمن."""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("للمشرفين فقط!", show_alert=True)
        return
    try:
        uid = int(callback_query.data.split('_', 1)[1])
    except (ValueError, IndexError):
        return
    subdb.admin_ban(uid, "حظر تحذيري من الأدمن", permanent=False)
    logger.info(f"⚠️ الأدمن حظر المستخدم {uid} حظراً تحذيرياً")
    await callback_query.answer(f"⚠️ تم تحذير وحظر {uid} (يمكنه التعهّد)", show_alert=True)
    await _notify_user_ban_state(client, uid, permanent=False)


@app.on_callback_query(filters.regex(r'^adminunban_'))
async def handle_admin_unban_btn(client, callback_query):
    """رفع الحظر عن مستخدم (زر أدمن)."""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("للمشرفين فقط!", show_alert=True)
        return
    try:
        uid = int(callback_query.data.split('_', 1)[1])
    except (ValueError, IndexError):
        return
    if subdb.admin_unban(uid):
        logger.info(f"✅ الأدمن رفع الحظر عن المستخدم {uid}")
        await callback_query.answer(f"✅ تم رفع الحظر عن {uid}", show_alert=True)
        try:
            await client.send_message(uid, t('pledge_accepted', subdb.get_user_language(uid)))
        except Exception:
            pass
    else:
        await callback_query.answer(f"ℹ️ {uid} غير محظور", show_alert=True)


# ═══════════════════════════════════════════════════════════════
# استبيان الأعضاء الإجباري قبل التحميل (الجنس + سؤال الأدمن)
# ═══════════════════════════════════════════════════════════════

def _has_active_questions():
    return any(q[2] for q in subdb.get_questions())


def _lang_flag(lang):
    return {'ar': '🇸🇦', 'en': '🇬🇧'}.get(lang, '🌐')


def _gender_flag(gender):
    return {'male': '👨', 'female': '👩'}.get(gender, '👥')


def _gender_keyboard(lang):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t('gender_male', lang), callback_data='gender_male'),
        InlineKeyboardButton(t('gender_female', lang), callback_data='gender_female'),
    ]])


def _parse_options(options):
    """يحوّل سلسلة الخيارات المفصولة بـ | إلى قائمة نظيفة (أو [] إن لا خيارات)."""
    if not options:
        return []
    return [o.strip() for o in options.split('|') if o.strip()]


def _question_keyboard(qid, lang, options=None):
    """أزرار الإجابة: خيارات مخصّصة (زرّان بالصف) أو نعم/لا الافتراضية."""
    opts = _parse_options(options)
    if opts:
        buttons = [InlineKeyboardButton(o, callback_data=f'qans_{qid}_o{i}')
                   for i, o in enumerate(opts)]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        return InlineKeyboardMarkup(rows)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t('answer_yes', lang), callback_data=f'qans_{qid}_yes'),
        InlineKeyboardButton(t('answer_no', lang), callback_data=f'qans_{qid}_no'),
    ]])


def _question_target_label(q_target, q_gender='all', q_lang='all'):
    """وصف جمهور السؤال: شخص محدّد أو فئة (جنس + لغة)."""
    if q_target:
        return f"👤 شخص محدّد (`{q_target}`)"
    glabel = {'all': '👥 الجميع', 'male': '👨 رجال', 'female': '👩 نساء'}.get(q_gender, '👥 الجميع')
    llabel = {'all': '🌐 كل اللغات', 'ar': '🇸🇦 العربية', 'en': '🇬🇧 الإنجليزية'}.get(q_lang, '🌐 كل اللغات')
    return f"{glabel} | {llabel}"


def _question_preview_kb(options):
    """لوحة معاينة الأزرار: أزرار الإجابة (كما ستظهر) + إرسال + رجوع."""
    opts = _parse_options(options)
    if opts:
        buttons = [InlineKeyboardButton(o, callback_data='sub_qprev') for o in opts]
    else:
        buttons = [InlineKeyboardButton('نعم', callback_data='sub_qprev'),
                   InlineKeyboardButton('لا', callback_data='sub_qprev')]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton('✅ إرسال وتفعيل', callback_data='sub_qsave')])
    rows.append([InlineKeyboardButton('« رجوع', callback_data='sub_qcancel')])
    return InlineKeyboardMarkup(rows)


def _question_preview_text(data):
    """نص رسالة المعاينة قبل تأكيد إضافة السؤال."""
    audience = _question_target_label(
        data.get('q_target'), data.get('q_gender', 'all'), data.get('q_lang', 'all'))
    options = data.get('q_options')
    ans_txt = " / ".join(_parse_options(options)) if options else "نعم / لا"
    return (
        "👁️ **معاينة السؤال**\n\n"
        f"🎯 {audience}\n"
        f"🔘 الإجابات: {ans_txt}\n\n"
        f"❓ {data.get('q_text', '')}\n\n"
        "هكذا ستظهر الأزرار للعضو 👇\n"
        "اضغط **✅ إرسال وتفعيل** إن أعجبك، أو **« رجوع** للإلغاء."
    )


async def _prompt_survey_if_needed(send_func, user_id):
    """يعرض الخطوة الناقصة من البوابة: الجنس ثم الأسئلة.
    يرجع True إذا عُرضت خطوة (أي يجب إيقاف التحميل)، وإلا False (اكتملت البوابة)."""
    lang = subdb.get_user_language(user_id)
    if not subdb.get_survey(user_id).get('gender'):
        await send_func(t('ask_gender', lang), reply_markup=_gender_keyboard(lang))
        return True
    pending = subdb.get_unanswered_questions(user_id)
    if pending:
        qid, qtext, qoptions = pending[0]
        await send_func(f"❓ {qtext}", reply_markup=_question_keyboard(qid, lang, qoptions))
        return True
    return False


def _gender_label(gender):
    return '👨 رجل' if gender == 'male' else ('👩 امرأة' if gender == 'female' else '— غير محدد')


def _user_link(uid, name):
    """اسم قابل للضغط (أزرق) يفتح محادثة المستخدم حتى بلا يوزر."""
    return f'<a href="tg://user?id={uid}">{html.escape(str(name or "مستخدم"))}</a>'


def _member_header_html(user):
    """رأس موحّد لرسائل العضو في القناة: الاسم + اليوزر + الجنس + المعرّف."""
    uid = user.id
    name = html.escape(str(getattr(user, 'first_name', None) or 'مستخدم'))
    uname = f"@{html.escape(user.username)}" if getattr(user, 'username', None) else '⚠️ لا يوجد'
    gender_txt = _gender_label(subdb.get_survey(uid).get('gender'))
    return (f"👤 <a href=\"tg://user?id={uid}\">{name}</a>\n"
            f"📛 اليوزر: {uname}\n"
            f"👥 الجنس: {gender_txt}\n"
            f"🆔 ID: <code>{uid}</code>")


async def _post_survey_result(client, user):
    """ينشر إجابات العضو على الاستبيان في قناة الاستبيان (إن وُجدت) مع زر رد مباشر."""
    channel_id = get_channel_id('SURVEY_CHANNEL_ID')
    if not channel_id:
        return
    uid = user.id
    lines = ["📋 <b>إجابات عضو على الاستبيان</b>\n", _member_header_html(user)]
    answers = subdb.get_member_answers(uid)
    for qtext, ans in answers:
        if ans == 'yes':
            ans_txt = '✅ نعم'
        elif ans == 'no':
            ans_txt = '❌ لا'
        else:
            ans_txt = f'📝 {html.escape(str(ans))}'
        lines.append(f"❓ {html.escape(qtext)}: {ans_txt}")
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 رد على العضو", callback_data=f"reply_msg_{uid}")
    ]])
    try:
        await client.send_message(channel_id, "\n".join(lines),
                                  parse_mode=enums.ParseMode.HTML, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"❌ تعذّر نشر إجابات الاستبيان للقناة: {e}")


def _questions_panel_view():
    """يبني (نص، أزرار) لوحة إدارة أسئلة الأعضاء المتعددة (تفعيل/حذف/إضافة)."""
    questions = subdb.get_questions()
    gs = subdb.get_gender_stats()
    lc = subdb.get_language_counts()
    text = (
        "❓ **أسئلة الأعضاء**\n\n"
        f"👥 الجنس (يُسأل دائماً): 👨 {gs['male']} | 👩 {gs['female']}\n"
        f"🌐 اللغة: 🇸🇦 {lc['ar']} | 🇬🇧 {lc['en']}\n"
        f"عدد الأسئلة: {len(questions)}\n\n"
    )
    rows = []
    if not questions:
        text += ("— لا توجد أسئلة بعد. أضف سؤالاً (تفاعلي) ليُطرح على الأعضاء.\n"
                 "ℹ️ يُطرح على الأعضاء الحاليين فقط حسب لغتهم — من ينضمّ لاحقاً لا يراه.")
    else:
        text += ("كل سؤال يُطرح على الموجودين وقت إضافته حسب الجمهور (🌐/🇸🇦/🇬🇧):\n\n")
        for qid, qtext, enabled, qlang, qgender, qtarget, qoptions in questions:
            state = '✅' if enabled else '🔕'
            # عنوان الجمهور: شخص محدّد أو فئة (لغة+جنس)
            if qtarget:
                audience = f"👤 `{qtarget}`"
            else:
                audience = f"{_lang_flag(qlang)}{_gender_flag(qgender)}"
            text += f"{state} {audience} {qtext}\n"
            opts = _parse_options(qoptions)
            if opts:
                # سؤال بخيارات مخصّصة: نعرض توزيع الإجابات الفعلي
                counts = dict(subdb.get_question_answer_breakdown(qid))
                parts = [f"{o} {counts.get(o, 0)}" for o in opts]
                text += "   (" + " | ".join(parts) + ")\n\n"
            else:
                st = subdb.get_question_answer_stats(qid)
                text += f"   (✅ نعم {st['yes']} | ❌ لا {st['no']})\n\n"
            rows.append([
                InlineKeyboardButton("🔕 إيقاف" if enabled else "🔔 تفعيل",
                                     callback_data=f"sub_qtoggle_{qid}"),
                InlineKeyboardButton("🗑️ حذف", callback_data=f"sub_qdel_{qid}"),
            ])
    rows.append([InlineKeyboardButton("➕ إضافة سؤال", callback_data="sub_qadd")])
    rows.append([InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")])
    return text, InlineKeyboardMarkup(rows)


@app.on_callback_query(filters.regex(r'^gender_(male|female)$'))
async def handle_gender(client, callback_query):
    """يحفظ جنس العضو ثم ينتقل للسؤال التالي أو ينهي الاستبيان."""
    await callback_query.answer()
    uid = callback_query.from_user.id
    lang = subdb.get_user_language(uid)
    subdb.set_gender(uid, 'male' if callback_query.data == 'gender_male' else 'female')
    if not await _prompt_survey_if_needed(callback_query.message.edit_text, uid):
        await callback_query.message.edit_text(t('survey_done', lang))
        await _post_survey_result(client, callback_query.from_user)


@app.on_callback_query(filters.regex(r'^editgender_(male|female)$'))
async def handle_edit_gender(client, callback_query):
    """تعديل العضو لجنسه — يحدّث قاعدة البيانات فوراً (بدون متابعة الاستبيان)."""
    await callback_query.answer()
    uid = callback_query.from_user.id
    lang = subdb.get_user_language(uid)
    gender = 'male' if callback_query.data == 'editgender_male' else 'female'
    subdb.set_gender(uid, gender)
    await callback_query.message.edit_text(
        f"{t('gender_updated', lang)}\n\n👥 {_gender_label(gender)}"
    )


@app.on_callback_query(filters.regex(r'^qans_'))
async def handle_question_answer(client, callback_query):
    """يحفظ إجابة العضو على سؤال محدد ثم ينتقل للسؤال التالي أو ينهي الاستبيان."""
    await callback_query.answer()
    uid = callback_query.from_user.id
    lang = subdb.get_user_language(uid)
    try:
        _, qid_str, ans = callback_query.data.split('_', 2)
        qid = int(qid_str)
    except (ValueError, IndexError):
        return
    if ans.startswith('o') and ans[1:].isdigit():
        # إجابة على خيار مخصّص: نحفظ نصّه الفعلي
        opts = _parse_options(subdb.get_question_options(qid))
        idx = int(ans[1:])
        answer_value = opts[idx] if 0 <= idx < len(opts) else ans
    else:
        answer_value = 'yes' if ans == 'yes' else 'no'
    subdb.save_question_answer(uid, qid, answer_value)
    if not await _prompt_survey_if_needed(callback_query.message.edit_text, uid):
        await callback_query.message.edit_text(t('survey_done', lang))
        await _post_survey_result(client, callback_query.from_user)


@app.on_callback_query(filters.regex(r'^show_invite$'))
async def handle_show_invite(client, callback_query):
    """يعرض رابط الدعوة عند الضغط على زر 'ادعُ أصدقاءك'."""
    await callback_query.answer()
    user_id = callback_query.from_user.id
    lang = subdb.get_user_language(user_id)
    text = await _build_invite_text(client, user_id, lang)
    if text:
        await callback_query.message.reply_text(text)
    else:
        await callback_query.message.reply_text(
            t('error_occurred', lang, error="bot username unavailable")
        )


@app.on_message(filters.command("history"))
async def cmd_history(client, message):
    await _show_history(client, message)


@app.on_message(filters.command("dlstats"))
async def cmd_dlstats(client, message):
    """إحصائيات التحميل للأدمن."""
    if not is_admin(message.from_user.id):
        return
    lang = subdb.get_user_language(message.from_user.id)
    s = subdb.get_download_stats()
    cache = subdb.get_cache_stats()
    gs = subdb.get_gender_stats()
    platforms = "\n".join(f"  • {p}: {c}" for p, c in s['platforms']) or "  —"
    top_users = "\n".join(
        f"  • {(name or uid)}: {c}" for uid, name, c in s['top_users']
    ) or "  —"
    await message.reply_text(
        t('dlstats_title', lang, today=s['today'], total=s['total'],
          cache_hits=cache['hits'], cache_items=cache['items'],
          platforms=platforms, top_users=top_users)
        + f"\n\n👥 **الجنس:** 👨 {gs['male']} | 👩 {gs['female']}"
        + f"\n🌐 **اللغة:** 🇸🇦 {subdb.get_language_counts()['ar']} | 🇬🇧 {subdb.get_language_counts()['en']}"
    )


def _health_check_binary(name):
    """يفحص وجود أداة خارجية (ffmpeg/ffprobe) عبر تشغيل -version."""
    try:
        r = subprocess.run([name, '-version'], capture_output=True, timeout=10)
        if r.returncode == 0:
            first = (r.stdout.decode('utf-8', 'ignore').splitlines() or [''])[0]
            return True, first[:50]
        return False, f"exit {r.returncode}"
    except FileNotFoundError:
        return False, "غير مثبّت"
    except Exception as e:
        return False, str(e)[:50]


def _health_check_db():
    """يتحقق من الاتصال بقاعدة البيانات عبر استعلام رخيص."""
    try:
        subdb.get_setting('__health_check__')  # SELECT خفيف
        return True, "متصلة"
    except Exception as e:
        return False, str(e)[:80]


def _health_check_host(host, timeout=8):
    """يتحقق من إمكانية الوصول لمضيف مرآة (أي رد HTTP = يوصل)."""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(
            f"https://{host}/", method='HEAD',
            headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {getattr(r, 'status', 200)}"
    except urllib.error.HTTPError as e:
        return True, f"HTTP {e.code}"  # رد بكود = المضيف يوصل
    except Exception as e:
        return False, type(e).__name__


# أسباب فشل الكوكيز بصياغة عربية مختصرة (بدل الرمز الإنجليزي الخام)
_COOKIE_REASON_AR = {
    'empty': 'الملف فارغ/مفقود', 'unparseable': 'صيغة غير صالحة',
    'wrong_platform': 'كوكيز منصة خاطئة', 'not_logged_in': 'غير مسجّل دخول',
    'expired': 'منتهية الصلاحية', 'unknown_platform': 'منصة غير معروفة',
}


def _run_health_checks():
    """يشغّل كل فحوص الصحّة (متزامنة) ويعيد نص التقرير جاهزاً. يُنفَّذ في executor.

    التنسيق مُصمَّم ليقرأ بوضوح في العربية (RTL): كل عنوان قسم عربي في سطره،
    وكل عنصر يبدأ برمز الحالة ثم اسم لاتيني فقط (منصة/مضيف) بلا خلط عربي داخل
    السطر — تفادياً لتشوّه ترتيب النص ثنائي الاتجاه."""
    parts = ["🩺 **فحص صحّة البوت**", ""]

    # الأدوات الخارجية — نعرض رقم النسخة فقط (لا سطر Copyright الطويل)
    parts.append("⚙️ **الأدوات:**")
    for bin_name in ('ffmpeg', 'ffprobe'):
        ok, detail = _health_check_binary(bin_name)
        ver = ''
        if ok and 'version' in detail:
            ver = ' ' + detail.split('version', 1)[1].strip().split('-')[0].split()[0]
        parts.append(f"{'✅' if ok else '❌'} {bin_name}{ver if ok else ' — ' + detail}")

    db_ok, db_detail = _health_check_db()
    parts.append(f"{'✅' if db_ok else '❌'} قاعدة البيانات — " +
                 ("متصلة" if db_ok else db_detail))

    # الكوكيز: افحص فقط المنصات التي رُفع لها ملف كوكيز فعلاً
    cookie_lines = []
    for pid, data in COOKIES_PLATFORMS.items():
        if pid == 'other':
            continue
        path = data.get('file', '')
        if not os.path.exists(path) or os.path.getsize(path) <= 100:
            continue
        res = validate_platform_cookies(pid)
        if res.get('ok'):
            cookie_lines.append(f"✅ {pid}")
        else:
            reason = _COOKIE_REASON_AR.get(res.get('reason'), res.get('reason', ''))
            cookie_lines.append(f"⚠️ {pid} — {reason}")
    parts.append("")
    parts.append("🍪 **الكوكيز:**")
    parts.extend(cookie_lines or ["— لا كوكيز مرفوعة"])

    # المرايا: نعرض الوصول فقط (يعمل/لا يصل) بلا أكواد HTTP المربكة (403/404 تعني
    # أن المضيف يوصل فعلاً)
    parts.append("")
    parts.append("🌐 **المرايا:**")
    for platform, host in all_mirror_hosts():
        ok, _ = _health_check_host(host)
        parts.append(f"{'✅' if ok else '❌'} {host}" +
                     ("" if ok else " — لا يصل"))

    return "\n".join(parts)[:4096]


async def run_health_report(client, message):
    """يعرض تقرير صحّة البوت (مشترك بين أمر /health وزر اللوحة)."""
    status = await message.reply_text("🩺 **جارٍ فحص صحّة البوت…**")
    loop = asyncio.get_event_loop()
    try:
        report = await loop.run_in_executor(None, _run_health_checks)
    except Exception as e:
        report = f"❌ تعذّر إكمال فحص الصحّة: {str(e)[:200]}"
    await status.edit_text(report)


@app.on_message(filters.command("health"))
async def cmd_health(client, message):
    """فحص صحّة البوت للأدمن: ffmpeg + قاعدة البيانات + الكوكيز + وصول المرايا."""
    if not is_admin(message.from_user.id):
        return
    await run_health_report(client, message)


async def run_realusers_check(client, message):
    """فحص فوري للأعضاء مع عدّاد حيّ: يحذف من حظر البوت ويعرض العدد الحقيقي
    والداخلين اليوم. مشترك بين أمر /realusers وزر «👥 فحص العدد الحقيقي» في اللوحة."""
    total_before = len(subdb.get_all_users())
    try:
        joined = subdb.count_new_users(24)
    except Exception:
        joined = 0

    status = await message.reply_text(
        f"🔍 **جارٍ فحص الأعضاء…**\n\n📦 في القاعدة: {total_before}\n⏳ التقدّم: 0/{total_before}"
    )

    # خنق سرعة تعديل العدّاد زمنياً (تفادي حدود تلجرام) — تعديل كل ~3 ثوانٍ
    last_edit = {'t': 0.0}

    async def _progress(done, total, alive, removed):
        now = time.monotonic()
        if now - last_edit['t'] < 3.0:
            return
        last_edit['t'] = now
        pct = int(done * 100 / total) if total else 0
        try:
            await status.edit_text(
                "🔍 **جارٍ فحص الأعضاء…**\n\n"
                f"⏳ التقدّم: **{done}/{total}** ({pct}%)\n"
                f"✅ موجودون: **{alive}**\n"
                f"🔴 خرجوا/حظروا: **{removed}**"
            )
        except Exception:
            pass

    try:
        alive, removed, _ = await probe_and_cleanup_users(client, progress_cb=_progress)
        _record_realcheck(alive)
        net = joined - removed
        net_txt = f"+{net}" if net > 0 else str(net)
        await status.edit_text(
            "📊 **فحص فوري للأعضاء (اكتمل)**\n\n"
            f"🟢 دخلوا اليوم (آخر 24 ساعة): **{joined}**\n"
            f"🔴 خرجوا/حظروا (حُذفوا الآن): **{removed}**\n"
            f"⚖️ صافي التغيّر: **{net_txt}**\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👥 قبل الفحص: **{total_before}**\n"
            f"✅ العدد الحقيقي الآن: **{alive}**"
        )
    except Exception as e:
        logger.error(f"❌ خطأ في فحص الأعضاء: {e}")
        await status.edit_text(f"❌ تعذّر إكمال الفحص: {str(e)[:100]}")


@app.on_message(filters.command("realusers"))
async def cmd_realusers(client, message):
    """فحص فوري للأعضاء (أمر). للأدمن فقط — نفس فحص الـ3 فجراً لكن عند الطلب."""
    if not is_admin(message.from_user.id):
        return
    await run_realusers_check(client, message)


@app.on_message(filters.command("blockacc"))
async def cmd_blockacc(client, message):
    """حظر حساب (X/تويتر أو غيره) ليُرفض كل محتواه. للأدمن فقط."""
    if not is_admin(message.from_user.id):
        return
    parts = getattr(message, 'command', []) or []
    if len(parts) < 2:
        await message.reply_text("الاستخدام: /blockacc <اسم الحساب أو معرّفه>\nمثال: /blockacc someuser")
        return
    acc = parts[1].strip().lstrip('@').lower()
    added = _add_to_setting_list('blocked_accounts', acc)
    await message.reply_text(
        (f"✅ تم حظر الحساب: <code>{html.escape(acc)}</code>\nلن يُسمح بتحميل أي محتوى منه."
         if added else f"ℹ️ الحساب محظور مسبقاً: <code>{html.escape(acc)}</code>"),
        parse_mode=enums.ParseMode.HTML
    )


@app.on_message(filters.command("unblockacc"))
async def cmd_unblockacc(client, message):
    """رفع الحظر عن حساب. للأدمن فقط."""
    if not is_admin(message.from_user.id):
        return
    parts = getattr(message, 'command', []) or []
    if len(parts) < 2:
        await message.reply_text("الاستخدام: /unblockacc <اسم الحساب>")
        return
    acc = parts[1].strip().lstrip('@').lower()
    raw = subdb.get_setting('blocked_accounts', '') or ''
    items = [x.strip() for x in raw.split(',') if x.strip()]
    new_items = [x for x in items if x.lower().lstrip('@') != acc]
    if len(new_items) == len(items):
        await message.reply_text(f"ℹ️ الحساب ليس في قائمة الحظر: {acc}")
        return
    subdb.set_setting('blocked_accounts', ','.join(new_items))
    await message.reply_text(f"✅ تم رفع الحظر عن: {acc}")


@app.on_message(filters.command("blockedaccs"))
async def cmd_blockedaccs(client, message):
    """عرض قائمة الحسابات المحظورة. للأدمن فقط."""
    if not is_admin(message.from_user.id):
        return
    accs = sorted(_blocked_accounts())
    if not accs:
        await message.reply_text("📋 لا توجد حسابات محظورة.\nأضِف حساباً بـ: /blockacc <الحساب>")
        return
    body = "\n".join(f"  • {a}" for a in accs)
    await message.reply_text(f"📋 **الحسابات المحظورة ({len(accs)}):**\n{body}\n\nلرفع الحظر: /unblockacc <الحساب>")


@app.on_message(filters.command("exempt"))
async def cmd_exempt(client, message):
    """إضافة عضو لقائمة الاستثناء: لا بث/تذكير + إعفاء من الاشتراك الإجباري. للأدمن فقط."""
    if not is_admin(message.from_user.id):
        return
    parts = getattr(message, 'command', []) or []
    if len(parts) < 2:
        await message.reply_text(
            "الاستخدام: /exempt <ID أو @username>\n"
            "مثال: /exempt 123456789 أو /exempt @someuser\n\n"
            "العضو المستثنى: 🔕 لا يصله بث ولا تذكير، ✅ معفى من الاشتراك الإجباري.\n"
            "القائمة: /exemptlist — الحذف: /unexempt"
        )
        return
    uid, name = _resolve_member_ref(parts[1])
    if not uid:
        await message.reply_text(
            "❌ لم يتم العثور على العضو. أرسل ID رقمياً (يُقبل دائماً) "
            "أو @username لعضو استخدم البوت مسبقاً."
        )
        return
    if _add_exempt(uid):
        shown = name or "غير معروف بعد (يُفعّل الإعفاء فور دخوله)"
        await message.reply_text(
            f"⭐ أُضيف لقائمة الاستثناء: {shown} (`{uid}`)\n"
            "🔕 لن يصله بث أو تذكير، و✅ معفى من الاشتراك الإجباري."
        )
    else:
        await message.reply_text(f"ℹ️ العضو `{uid}` في قائمة الاستثناء مسبقاً.")


@app.on_message(filters.command("unexempt"))
async def cmd_unexempt(client, message):
    """حذف عضو من قائمة الاستثناء. للأدمن فقط."""
    if not is_admin(message.from_user.id):
        return
    parts = getattr(message, 'command', []) or []
    if len(parts) < 2:
        await message.reply_text("الاستخدام: /unexempt <ID أو @username>")
        return
    uid, name = _resolve_member_ref(parts[1])
    if not uid:
        await message.reply_text("❌ لم يتم العثور على العضو.")
        return
    if _remove_exempt(uid):
        await message.reply_text(
            f"✅ حُذف من قائمة الاستثناء: {name or uid} (`{uid}`)\n"
            "سيصله البث والتذكير ويُطبّق عليه الاشتراك الإجباري كأي عضو."
        )
    else:
        await message.reply_text(f"ℹ️ العضو `{uid}` ليس في قائمة الاستثناء.")


@app.on_message(filters.command("exemptlist"))
async def cmd_exemptlist(client, message):
    """عرض قائمة الاستثناء. للأدمن فقط."""
    if not is_admin(message.from_user.id):
        return
    ids = sorted(_exempt_ids())
    if not ids:
        await message.reply_text(
            "⭐ قائمة الاستثناء فارغة.\nأضِف عضواً بـ: /exempt <ID أو @username>")
        return
    lines = []
    for uid in ids:
        row = subdb.find_user_by_id(uid)
        name = (row[2] if row and row[2] else None) or (
            f"@{row[1]}" if row and row[1] else "غير معروف بعد")
        lines.append(f"  • `{uid}` — {name}")
    await message.reply_text(
        f"⭐ **قائمة الاستثناء ({len(ids)}):**\n" + "\n".join(lines) +
        "\n\n🔕 لا يصلهم بث/تذكير، ✅ معفيون من الاشتراك الإجباري.\n"
        "للحذف: /unexempt <ID>"
    )


@app.on_message(filters.text & filters.regex(
    r'^(📥 تحميلاتي|📥 My Downloads|🎁 ادعُ أصدقاءك|🎁 Invite Friends|🧍 تعديل جنسي|🧍 Edit my gender)$'))
async def handle_feature_buttons(client, message):
    """أزرار 'تحميلاتي' و'ادعُ أصدقاءك' و'تعديل جنسي' (عربي/إنجليزي)."""
    text = (message.text or '').strip()
    lang = subdb.get_user_language(message.from_user.id)
    if text in ('📥 تحميلاتي', '📥 My Downloads'):
        await _show_history(client, message)
    elif text in ('🧍 تعديل جنسي', '🧍 Edit my gender'):
        await message.reply_text(
            t('edit_gender_prompt', lang),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(t('gender_male', lang), callback_data='editgender_male'),
                InlineKeyboardButton(t('gender_female', lang), callback_data='editgender_female'),
            ]])
        )
    else:
        txt = await _build_invite_text(client, message.from_user.id, lang)
        await message.reply_text(
            txt or t('error_occurred', lang, error="bot username unavailable")
        )


@app.on_message(filters.command("start"))
async def start(client, message):
    user_id = message.from_user.id
    
    # التحقق من وجود لغة محددة للمستخدم
    lang = subdb.get_user_language(user_id)
    
    # إذا كانت أول مرة (لغة غير محددة أو قيمة افتراضية)
    # نتحقق إذا كان موجود في قاعدة البيانات
    user_exists = subdb.find_user_by_id(user_id)
    
    if not user_exists:
        # مستخدم جديد - إرسال إشعار للقناة
        join_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await send_new_member_notification(
            user_id=user_id,
            user_name=message.from_user.first_name,
            username=message.from_user.username,
            join_time=join_time
        )

        # 🎁 معالجة الدعوة إن جاء عبر رابط دعوة (مستخدم جديد فقط)
        await _process_referral_start(client, message, user_id)

        # عرض اختيار اللغة
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🇮🇶 العربية", callback_data="lang_ar"),
                InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")
            ]
        ])
        
        await message.reply_text(
            t('choose_language', 'ar'),
            reply_markup=keyboard
        )
        return
    
    # مستخدم موجود - عرض الرسالة الترحيبية
    keyboard = None
    admin_id = os.getenv("ADMIN_ID")
    
    if admin_id and str(user_id) == admin_id:
        from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton(t('btn_cookies', lang)), KeyboardButton(t('btn_daily_report', lang))],
            [KeyboardButton(t('btn_health', lang)), KeyboardButton(t('btn_subscription', lang))],
            [KeyboardButton(t('btn_change_language', lang)), KeyboardButton(t('btn_update_ytdlp', lang))]
        ], resize_keyboard=True)
    else:
        # للمستخدمين العاديين - التحقق من الاشتراك
        from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
        
        # التحقق من حالة الاشتراك
        is_subscribed = subdb.is_user_subscribed(user_id)
        
        if is_subscribed:
            # مشترك - عرض زر الاشتراك + تحميلاتي/الدعوة + تغيير اللغة
            keyboard = ReplyKeyboardMarkup([
                [KeyboardButton(t('btn_my_subscription', lang))],
                [KeyboardButton(t('btn_my_downloads', lang)), KeyboardButton(t('btn_invite', lang))],
                [KeyboardButton(t('btn_change_language', lang))]
            ], resize_keyboard=True)
        else:
            # غير مشترك - تحميلاتي/الدعوة + تغيير اللغة
            keyboard = ReplyKeyboardMarkup([
                [KeyboardButton(t('btn_my_downloads', lang)), KeyboardButton(t('btn_invite', lang))],
                [KeyboardButton(t('btn_change_language', lang))]
            ], resize_keyboard=True)
    
    await message.reply_text(
        t('welcome', lang, name=message.from_user.first_name),
        reply_markup=keyboard
    )

    # 📋 اسأل العضو الاستبيان (الجنس + الأسئلة) إن لم يجب بعد — الأدمن مُعفى
    if not is_admin(user_id):
        await _prompt_survey_if_needed(message.reply_text, user_id)


async def run_ytdlp_update(client, message):
    """تحديث yt-dlp فعلياً من داخل البوت (زر/أمر أدمن).

    يشغّل pip في بيئة البوت نفسها (خارج حلقة الأحداث حتى لا يجمّد البوت)،
    وعند تغيّر الإصدار يعيد تشغيل العملية بـ os.execv لتحميل الإصدار الجديد
    (الوحدة المستوردة في الذاكرة لا تتحدث بدون إعادة تشغيل)."""
    status = await message.reply_text("🔄 **جاري تحديث yt-dlp...**")
    loop = asyncio.get_event_loop()

    def _pip(*args):
        cmd = [sys.executable, '-m', 'pip', *args]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=600)
        # بايثون النظام في Debian يمنع pip افتراضياً (PEP 668)؛ نتجاوز المنع
        # لأن هذه هي بيئة تشغيل البوت الفعلية نفسها (وليست بيئة أخرى)
        if r.returncode != 0 and 'externally-managed-environment' in (r.stdout or ''):
            r = subprocess.run(cmd + ['--break-system-packages'],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, timeout=600)
        return r

    def _pip_version():
        r = _pip('show', 'yt-dlp')
        for line in (r.stdout or '').splitlines():
            if line.startswith('Version:'):
                return line.split(':', 1)[1].strip()
        return None

    # المقارنة قبل/بعد من pip نفسه — مقارنة إصدار الوحدة المحمّلة بإصدار pip
    # تعطي فرقاً وهمياً لأن pip يوحّد الصيغة (2026.06.30 → 2026.6.30.dev0)
    old_v = await loop.run_in_executor(None, _pip_version) \
        or getattr(getattr(yt_dlp, 'version', None), '__version__', '؟')
    try:
        r = await loop.run_in_executor(None, lambda: _pip('install', '-U', 'yt-dlp'))
    except Exception as e:
        await status.edit_text(f"❌ **فشل تشغيل pip:**\n`{str(e)[:300]}`")
        return
    if r.returncode != 0:
        await status.edit_text(f"❌ **فشل التحديث:**\n`{(r.stdout or '')[-500:]}`")
        return

    new_v = await loop.run_in_executor(None, _pip_version) or old_v

    if new_v == old_v:
        await status.edit_text(
            f"✅ **yt-dlp محدّث أصلاً** (الإصدار `{old_v}`)\nلا حاجة لإعادة التشغيل.")
        return

    await status.edit_text(
        f"✅ **تم تحديث yt-dlp:** `{old_v}` ← `{new_v}`\n"
        f"♻️ جاري إعادة تشغيل البوت لتفعيل الإصدار الجديد..."
    )
    logger.info(f"♻️ إعادة تشغيل البوت لتفعيل yt-dlp {new_v} (كان {old_v})")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


@app.on_message(filters.command("update"))
async def cmd_update_ytdlp(client, message):
    """أمر أدمن: تحديث yt-dlp فعلياً (نفس زر 🔄 تحديث yt-dlp)."""
    if not message.from_user or not is_admin(message.from_user.id):
        return
    await run_ytdlp_update(client, message)


@app.on_message(filters.command("uncache"))
async def cmd_uncache(client, message):
    """أمر أدمن: مسح رابط من الكاش ليُعاد تحميله من جديد.

    الاستخدام: /uncache <الرابط>
    مفيد عندما يُخزَّن محتوى خاطئ (مثل إعلان فيسبوك محقون بدل الفيديو)."""
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or '').split(maxsplit=1)
    url = extract_first_url(parts[1] if len(parts) > 1 else '')
    if not url:
        await message.reply_text("الاستخدام: `/uncache <الرابط>`")
        return
    ckey = cache_key_for_url(url)
    removed = []
    for q in ('best', 'medium', '480', '360', 'audio', IMAGE_CACHE_QUALITY):
        try:
            if subdb.delete_cached_media(ckey, q):
                removed.append(q)
        except Exception:
            pass
    if removed:
        await message.reply_text(
            f"🗑️ **تم مسح الرابط من الكاش** ({', '.join(removed)})\n"
            f"أعد إرسال الرابط وسيُحمَّل من جديد.")
    else:
        await message.reply_text("ℹ️ هذا الرابط غير موجود في الكاش أصلاً.")


# معالج الأزرار السريعة
@app.on_message(filters.text & filters.regex(r'^(🍪 Cookies|📊 التقرير اليومي|📊 Daily Report|🩺 فحص الصحّة|🩺 Health Check|💎 إعدادات الاشتراك|💎 Subscription Settings|📁 نسخ احتياطي|🔄 تحديث yt-dlp|🔄 Update yt-dlp)$'))
async def handle_quick_buttons(client, message):
    """معالج الأزرار السريعة"""
    if not message.from_user:
        return
    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    txt = message.text
    if txt == "🍪 Cookies":
        await cookies_panel(client, message)
    elif txt in ("📊 التقرير اليومي", "📊 Daily Report"):
        await send_daily_report(client, message.from_user.id)
    elif txt in ("🩺 فحص الصحّة", "🩺 Health Check"):
        await run_health_report(client, message)
    elif txt in ("💎 إعدادات الاشتراك", "💎 Subscription Settings"):
        await subscription_settings_panel(client, message)
    elif txt == "📁 نسخ احتياطي":
        await send_database_backup(client, message)
    elif txt in ("🔄 تحديث yt-dlp", "🔄 Update yt-dlp"):
        await run_ytdlp_update(client, message)


# معالج زر اشتراكي - Subscription Status Button Handler
@app.on_message(filters.text & filters.regex(r'^💎 اشتراكي$|^💎 My Subscription$'))
async def handle_my_subscription(client, message):
    """معالج زر حالة الاشتراك للمستخدمين"""
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    
    # التحقق من حالة الاشتراك
    if not subdb.is_user_subscribed(user_id):
        await message.reply_text(t('not_subscribed', lang))
        return
    
    # الحصول على معلومات الاشتراك
    time_info = subdb.get_time_remaining(user_id)
    
    if not time_info:
        await message.reply_text(t('not_subscribed', lang))
        return
    
    # عرض معلومات الاشتراك
    await message.reply_text(
        t('subscription_status', lang,
          end_date=time_info['end_date_formatted'],
          days=time_info['days'],
          hours=time_info['hours'])
    )



async def send_daily_report(client, admin_id):
    """إرسال التقرير اليومي"""
    now = datetime.now()
    report_text = f"📊 **تقرير فحص الكوكيز اليومي**\n\n"
    report_text += f"📅 **التاريخ:** {now.strftime('%d-%m-%Y %H:%M:%S')}\n\n"
    
    valid_cookies = []
    expired_cookies = []
    missing_cookies = []
    
    for platform_id, data in COOKIES_PLATFORMS.items():
        if os.path.exists(data['file']):
            file_time = os.path.getmtime(data['file'])
            uploaded_date = datetime.fromtimestamp(file_time)
            days_ago = (now - uploaded_date).days
            days_left = max(0, 30 - days_ago)
            
            if days_left > 0:
                valid_cookies.append((data['name'], days_left))
            else:
                expired_cookies.append(data['name'])
        else:
            missing_cookies.append(data['name'])
    
    # الكوكيز الصالحة
    report_text += f"✅ **الكوكيز الصالحة ({len(valid_cookies)}):**\n"
    if valid_cookies:
        for name, days in valid_cookies:
            report_text += f"• {name}: {days} يوم\n"
    else:
        report_text += "⚠️ لا توجد\n"
    
    report_text += "\n"
    
    # الكوكيز المنتهية
    if expired_cookies:
        report_text += f"❌ **منتهية ({len(expired_cookies)}):**\n"
        for name in expired_cookies:
            report_text += f"• {name}\n"
        report_text += "\n"
    
    # الغير موجودة
    if missing_cookies:
        report_text += f"⚠️ **غير موجودة ({len(missing_cookies)}):**\n"
        for name in missing_cookies:
            report_text += f"• {name}\n"
        report_text += "\n"
    
    # إحصائيات
    total = len(COOKIES_PLATFORMS)
    checked = len(valid_cookies) + len(expired_cookies)
    success_rate = (len(valid_cookies) / total * 100) if total > 0 else 0
    
    report_text += f"📈 **الإحصائيات:**\n"
    report_text += f"• تم الفحص: {checked} منصة\n"
    report_text += f"• معدل النجاح: {success_rate:.1f}%"
    
    await client.send_message(admin_id, report_text)


# مهمة خلفية للتقرير اليومي
# أسماء المنصات مع أيقوناتها لعرض لوحة الصحّة
_PLATFORM_LABEL = {
    'facebook': '📘 فيسبوك', 'instagram': '📷 إنستغرام', 'tiktok': '🎵 تيك توك',
    'youtube': '📺 يوتيوب', 'twitter': '🐦 تويتر/X', 'threads': '🧵 ثريدز',
    'reddit': '👽 ريديت', 'snapchat': '👻 سناب', 'pinterest': '📌 بينتريست',
    'other': '🌐 أخرى',
}


def _error_category(msg: str):
    """يصنّف رسالة الخطأ إلى نوع مختصر + تلميح للسبب الجذري (أو None)."""
    low = (msg or '').lower()
    if 'cannot parse data' in low:
        return 'Cannot parse data', 'ثبّت curl_cffi وحدّث كوكيز فيسبوك'
    if 'no video formats' in low or 'failed to extract video info' in low:
        return 'لا صيغة فيديو / فشل الاستخراج', 'قد يكون منشور صور أو خاص أو منصة غير مدعومة'
    if any(k in low for k in ('sign in', 'log in', 'login required', 'private', 'rate-limit', 'rate limit', 'cookies')):
        return 'يتطلب تسجيل دخول / كوكيز', 'حدّث كوكيز المنصة'
    if 'unsupported url' in low:
        return 'رابط غير مدعوم', 'المنصة غير مدعومة في yt-dlp'
    if 'unavailable' in low or 'not available' in low or 'deleted' in low:
        return 'المحتوى غير متاح', 'حُذف المنشور أو مقيّد جغرافياً'
    return (msg or 'خطأ').split('\n')[0][:45], None


async def show_errors(client, message):
    """لوحة صحّة المنصات: تجمع الأخطاء المعلقة حسب المنصة + نوع الخطأ مع
    تلميح للسبب الجذري، فيرى الأدمن النمط بنظرة واحدة بدل أخطاء فردية."""
    pending = {k: v for k, v in user_errors.items() if v['status'] == 'pending'}

    if not pending:
        await message.reply_text("✅ **لا توجد أخطاء معلقة!**\n\nكل المنصات تعمل بشكل سليم.")
        return

    # تجميع حسب المنصة ثم نوع الخطأ
    groups = {}
    for e in pending.values():
        plat = _platform_of(e.get('url', ''))
        cat, hint = _error_category(e.get('error', ''))
        g = groups.setdefault(plat, {'count': 0, 'types': {}, 'hints': set(), 'sample': None})
        g['count'] += 1
        g['types'][cat] = g['types'].get(cat, 0) + 1
        if hint:
            g['hints'].add(hint)
        g['sample'] = e.get('url')  # أحدث رابط كمثال (كامل، قابل للنسخ)

    text = "🩺 **لوحة صحّة المنصات**\n\n"
    for plat, g in sorted(groups.items(), key=lambda kv: kv[1]['count'], reverse=True):
        dot = '🔴' if g['count'] >= 3 else '🟡'
        label = _PLATFORM_LABEL.get(plat, f'🌐 {plat}')
        text += f"{dot} **{label}** — {g['count']} خطأ\n"
        for cat, n in sorted(g['types'].items(), key=lambda kv: kv[1], reverse=True):
            text += f"   • {cat} ×{n}\n"
        for hint in g['hints']:
            text += f"   💡 {hint}\n"
        if g['sample']:
            text += f"   مثال: `{g['sample']}`\n"
        text += "\n"

    text += f"📊 **الإجمالي:** {len(pending)} خطأ معلّق"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 مسح كل الأخطاء", callback_data="clear_errors")]
    ])
    await message.reply_text(text, reply_markup=kb)


@app.on_callback_query(filters.regex(r'^resolve_'))
async def handle_resolve_error(client, callback_query):
    """معالج زر تم الإصلاح"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    error_id = callback_query.data.replace('resolve_', '')
    
    if error_id not in user_errors:
        await callback_query.answer("❌ الخطأ غير موجود!", show_alert=True)
        return
    
    error_data = user_errors[error_id]
    
    if error_data['status'] == 'resolved':
        await callback_query.answer("✅ تم حل هذا الخطأ مسبقاً", show_alert=True)
        return
    
    # تحديث الحالة
    user_errors[error_id]['status'] = 'resolved'
    
    # إرسال رسالة للمستخدم
    try:
        u_lang = subdb.get_user_language(error_data['user_id'])
        await client.send_message(
            chat_id=error_data['user_id'],
            text=t('problem_fixed', u_lang, url=f"{error_data['url'][:50]}...")
        )
        logger.info(f"✅ تم إرسال إشعار الحل للمستخدم {error_data['user_id']}")
    except Exception as e:
        logger.error(f"فشل إرسال إشعار للمستخدم: {e}")
    
    # تحديث الرسالة
    await callback_query.message.edit_text(
        callback_query.message.text + f"\n\n✅ **تم الحل بواسطة الأدمن**",
        reply_markup=None
    )
    
    await callback_query.answer("✅ تم إرسال إشعار للمستخدم", show_alert=True)


@app.on_callback_query(filters.regex(r'^clear_errors$'))
async def handle_clear_errors(client, callback_query):
    """مسح كل الأخطاء المعلقة دفعة واحدة من لوحة صحّة المنصات."""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    n = 0
    for v in user_errors.values():
        if v['status'] == 'pending':
            v['status'] = 'resolved'
            n += 1
    await callback_query.message.edit_text(
        f"✅ **تم مسح {n} خطأ معلّق.**\n\nاللوحة الآن نظيفة.",
        reply_markup=None
    )
    await callback_query.answer(f"🗑 تم مسح {n} خطأ", show_alert=True)


# تقرير يومي تلقائي
async def daily_report_task():
    """مهمة خلفية لإرسال التقرير يومياً"""
    from datetime import timedelta
    
    while True:
        now = datetime.now()
        # إرسال في الساعة 9 صباحاً
        target_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
        
        if now > target_time:
            # إذا مرت الساعة 9، اذهب لليوم التالي
            target_time = target_time + timedelta(days=1)
        
        wait_seconds = (target_time - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        
        # إرسال التقرير
        admin_id = int(os.getenv("ADMIN_ID"))
        await send_daily_report(app, admin_id)

        # انتظر يوم كامل
        await asyncio.sleep(86400)


async def probe_and_cleanup_users(client, progress_cb=None):
    """فحص صامت لكل الأعضاء لمعرفة من بقي ومن غادر، وحذف الغائبين.

    يستخدم send_chat_action (مؤشر "يكتب…") وهو فحص صامت تماماً لا يرى العضو
    أي رسالة. إن نجح فالعضو موجود، وإن فشل بخطأ "غادر" نحذفه من قاعدة البيانات.
    يُعيد (alive, removed, removed_ids).

    progress_cb (اختياري): دالة async تُستدعى دورياً بـ (done, total, alive,
    removed) لعرض عدّاد حيّ. تُستدعى كل 20 عضواً (وعند النهاية).
    """
    users = subdb.get_all_users()
    total = len(users)
    alive = 0
    removed = 0
    removed_ids = []

    for idx, u in enumerate(users, 1):
        uid = u[0]
        try:
            # فحص صامت: مؤشر كتابة يختفي فوراً ولا يُرسل رسالة مرئية
            await client.send_chat_action(uid, enums.ChatAction.TYPING)
            alive += 1
            await asyncio.sleep(0.05)  # تفادي flood
        except FloodWait as e:
            # انتظر المدة المطلوبة ثم اعتبره موجوداً
            await asyncio.sleep(getattr(e, 'value', 5))
            alive += 1
        except GONE_USER_ERRORS:
            # العضو حظر البوت أو حُذف حسابه → احذفه
            try:
                subdb.delete_user(uid)
                removed += 1
                removed_ids.append(uid)
            except Exception as del_err:
                logger.error(f"تعذّر حذف المستخدم {uid}: {del_err}")
        except Exception as e:
            # خطأ مؤقت/غير معروف → نُبقي العضو احتياطاً
            logger.warning(f"فحص العضو {uid} أعطى خطأً غير حاسم: {e}")

        # عدّاد حيّ كل 20 عضواً (والدالة نفسها تخنق سرعة التعديل زمنياً)
        if progress_cb and (idx % 20 == 0):
            try:
                await progress_cb(idx, total, alive, removed)
            except Exception:
                pass

    return alive, removed, removed_ids


async def daily_cleanup_task():
    """مهمة يومية الساعة 3 فجراً: فحص الأعضاء وحذف الغائبين وإبلاغ الأدمن"""
    from datetime import timedelta

    while True:
        now = datetime.now()
        target_time = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now > target_time:
            target_time = target_time + timedelta(days=1)

        await asyncio.sleep((target_time - now).total_seconds())

        try:
            admin_id = int(os.getenv("ADMIN_ID"))
            total_before = len(subdb.get_all_users())
            # الداخلون الجدد خلال آخر 24 ساعة (قبل حذف الغائبين)
            try:
                joined = subdb.count_new_users(24)
            except Exception:
                joined = 0
            logger.info(f"🧹 بدء الفحص اليومي للأعضاء ({total_before})...")

            alive, removed, removed_ids = await probe_and_cleanup_users(app)
            _record_realcheck(alive)

            # صافي التغيّر خلال اليوم = الداخلون - الخارجون
            net = joined - removed
            net_txt = f"+{net}" if net > 0 else str(net)

            await app.send_message(
                admin_id,
                "📊 **التقرير اليومي للأعضاء (3 فجراً)**\n\n"
                f"🟢 دخلوا اليوم (آخر 24 ساعة): **{joined}**\n"
                f"🔴 خرجوا/حظروا: **{removed}**\n"
                f"⚖️ صافي التغيّر: **{net_txt}**\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👥 قبل الفحص: **{total_before}**\n"
                f"✅ العدد الحقيقي الآن: **{alive}**"
            )
            logger.info(f"🧹 انتهى الفحص: دخل {joined}، خرج {removed}، الحقيقي {alive}")
        except Exception as e:
            logger.error(f"❌ خطأ في الفحص اليومي: {e}")

        # انتظر يوماً كاملاً قبل الفحص التالي
        await asyncio.sleep(86400)


async def send_database_backup(client, message):
    """إرسال نسخة احتياطية من قاعدة البيانات PostgreSQL"""
    user_id = message.from_user.id
    
    # التحقق من صلاحيات الأدمن
    admin_id = os.getenv("ADMIN_ID")
    if not admin_id or str(user_id) != admin_id:
        await message.reply_text("❌ **غير مصرح!**\n\nهذا الأمر للمشرفين فقط.")
        return
    
    try:
        # رسالة انتظار
        status_msg = await message.reply_text(
            "⏳ **جاري إنشاء النسخة الاحتياطية...**\n\n"
            "هذا قد يستغرق بضع ثوانٍ... ⏰"
        )
        
        # إنشاء النسخة الاحتياطية
        logger.info(f"🔄 الأدمن {user_id} طلب نسخة احتياطية من قاعدة البيانات")
        success, result = pg_backup.create_backup(prefer_sql=True)
        
        if not success:
            await status_msg.edit_text(
                f"❌ **فشل إنشاء النسخة الاحتياطية!**\n\n"
                f"**الخطأ:** `{result}`\n\n"
                f"تواصل مع مطور البوت للمساعدة."
            )
            logger.error(f"❌ فشل إنشاء النسخة الاحتياطية: {result}")
            return
        
        backup_file_path = result
        file_size_mb = os.path.getsize(backup_file_path) / (1024 * 1024)
        file_type = "SQL" if backup_file_path.endswith(".sql") else "JSON"
        
        # تحديث الرسالة
        await status_msg.edit_text(
            f"📤 **جاري رفع النسخة الاحتياطية...**\n\n"
            f"📦 النوع: {file_type}\n"
            f"💾 الحجم: {file_size_mb:.2f} MB"
        )
        
        # إرسال الملف
        caption = (
            f"📁 **نسخة احتياطية من قاعدة البيانات**\n\n"
            f"📦 **النوع:** {file_type}\n"
            f"💾 **الحجم:** {file_size_mb:.2f} MB\n"
            f"📅 **التاريخ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🗄️ **قاعدة البيانات:** PostgreSQL\n\n"
            f"✅ يمكنك استخدام هذا الملف لاستعادة البيانات في حالة الطوارئ."
        )
        
        await client.send_document(
            chat_id=user_id,
            document=backup_file_path,
            caption=caption
        )
        
        # حذف رسالة الحالة
        await status_msg.delete()
        
        # حذف الملف المؤقت
        try:
            os.remove(backup_file_path)
            logger.info(f"🗑️ تم حذف الملف المؤقت: {backup_file_path}")
        except Exception as e:
            logger.warning(f"⚠️ فشل حذف الملف المؤقت: {e}")
        
        # تنظيف الملفات القديمة
        pg_backup.cleanup_old_backups(max_age_hours=1)
        
        logger.info(f"✅ تم إرسال النسخة الاحتياطية بنجاح للأدمن {user_id}")
        
    except Exception as e:
        logger.error(f"❌ خطأ في send_database_backup: {e}", exc_info=True)
        try:
            await message.reply_text(
                f"❌ **حدث خطأ أثناء إنشاء النسخة الاحتياطية!**\n\n"
                f"**الخطأ:** `{str(e)[:200]}`"
            )
        except Exception:
            pass


async def _send_backup_to_channel(client, notify_chat=None):
    """ينشئ نسخة احتياطية JSON كاملة ويرفعها إلى قناة النسخ الاحتياطي."""
    channel_id = get_channel_id('BACKUP_CHANNEL_ID')
    if not channel_id:
        if notify_chat:
            await client.send_message(notify_chat, "⚠️ لم يُضبط BACKUP_CHANNEL_ID في ملف .env")
        return False
    loop = asyncio.get_event_loop()
    success, result = await loop.run_in_executor(None, lambda: pg_backup.create_json_backup())
    if not success:
        logger.error(f"❌ فشل إنشاء نسخة القناة: {result}")
        if notify_chat:
            await client.send_message(notify_chat, f"❌ فشل إنشاء النسخة: {result}")
        return False
    path = result
    try:
        size_kb = os.path.getsize(path) / 1024
        caption = (
            "💾 **نسخة احتياطية كاملة (JSON)**\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"💾 {size_kb:.1f} KB\n\n"
            "♻️ للاستعادة: أعد إرسال هذا الملف إلى البوت (من الأدمن)."
        )
        await client.send_document(chat_id=channel_id, document=path, caption=caption)
        logger.info("✅ تم رفع نسخة احتياطية كاملة لقناة النسخ الاحتياطي")
        return True
    except Exception as e:
        logger.error(f"❌ تعذّر رفع النسخة للقناة: {e}")
        if notify_chat:
            await client.send_message(notify_chat, f"❌ تعذّر الرفع للقناة: {e}")
        return False
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


@app.on_message(filters.document, group=3)
async def handle_backup_restore(client, message):
    """استعادة البيانات عندما يرسل الأدمن ملف نسخة احتياطية JSON."""
    if not message.from_user or not is_admin(message.from_user.id):
        return
    # لا تتعارض مع رفع الكوكيز
    if message.from_user.id in waiting_for_cookies:
        return
    doc = message.document
    name = (getattr(doc, 'file_name', '') or '').lower()
    is_json = name.endswith('.json') and 'backup' in name
    is_sql = name.endswith('.sql')
    if not (is_json or is_sql):
        return  # ليس ملف نسخة احتياطية
    status = await message.reply_text("⏳ **جاري استعادة البيانات من الملف...**")
    path = None
    try:
        path = await message.download()
        loop = asyncio.get_event_loop()
        if is_sql:
            ok, result = await loop.run_in_executor(None, lambda: pg_backup.restore_from_sql(path))
            if ok:
                await status.edit_text(
                    "✅ **تم استيراد ملف SQL.**\n"
                    "تحقّق من قائمة الأعضاء/الإحصائيات للتأكد.\n\n"
                    f"<code>{html.escape(str(result)[:400])}</code>",
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await status.edit_text(f"❌ **فشل استيراد SQL:** {result}")
        else:
            ok, result = await loop.run_in_executor(None, lambda: pg_backup.restore_from_json(path))
            if ok:
                summary = "\n".join(f"• {tbl}: {cnt} صف" for tbl, cnt in result.items()) or "—"
                await status.edit_text(f"✅ **تمت الاستعادة بنجاح:**\n{summary}")
            else:
                await status.edit_text(f"❌ **فشلت الاستعادة:** {result}")
    except Exception as e:
        logger.error(f"❌ خطأ في استعادة النسخة: {e}", exc_info=True)
        await status.edit_text(f"❌ خطأ في الاستعادة: {str(e)[:200]}")
    finally:
        if path:
            try:
                os.remove(path)
            except Exception:
                pass


async def _auto_backup_loop(client):
    """مهمة خلفية: ترفع نسخة احتياطية لقناة النسخ تلقائياً كل فترة."""
    interval_hours = int(os.getenv("AUTO_BACKUP_HOURS", "12"))
    if interval_hours <= 0 or not get_channel_id('BACKUP_CHANNEL_ID'):
        return
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            await _send_backup_to_channel(client)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ خطأ في النسخ التلقائي: {e}")


@app.on_message(filters.command("cookies"))
async def cookies_panel(client, message):
    """لوحة إدارة الـ cookies (للأدمن فقط)"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.reply_text("❌ هذا الأمر للمشرفين فقط!")
        return
    
    # بناء الأزرار
    keyboard = []
    for platform_id, data in COOKIES_PLATFORMS.items():
        keyboard.append([
            InlineKeyboardButton(data['name'], callback_data=f"cookies_{platform_id}")
        ])
    
    # زر مراجعة حالة الـ cookies
    keyboard.append([
        InlineKeyboardButton("📊 حالة جميع الـ Cookies", callback_data="cookies_status")
    ])
    
    await message.reply_text(
        "🍪 **إدارة Cookies**\n\n"
        "اختر المنصة لإضافة أو اختبار الـ cookies:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@app.on_callback_query(filters.regex(r'^cookies_(?!back$|status$)'))
async def cookies_platform_handler(client, callback_query):
    """معالج اختيار المنصة"""
    user_id = callback_query.from_user.id
    
    if not is_admin(user_id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    # استخراج اسم المنصة من callback_data
    platform_id = callback_query.data.replace('cookies_', '')
    
    if platform_id not in COOKIES_PLATFORMS:
        await callback_query.answer("❌ منصة غير صحيحة!")
        return
    
    platform = COOKIES_PLATFORMS[platform_id]
    cookie_exists = os.path.exists(platform['file'])
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة Cookies", callback_data=f"add_cookie_{platform_id}")],
        [InlineKeyboardButton("✅ اختبار Cookies", callback_data=f"test_cookie_{platform_id}")],
        [InlineKeyboardButton("« رجوع", callback_data="cookies_back")]
    ])
    
    status = "✅ موجود" if cookie_exists else "❌ غير موجود"
    
    # إضافة معلومات الصلاحية
    expiry_info = ""
    if cookie_exists:
        file_time = os.path.getmtime(platform['file'])
        uploaded_date = datetime.fromtimestamp(file_time)
        days_ago = (datetime.now() - uploaded_date).days
        days_left = max(0, 30 - days_ago)
        
        expiry_info = f"\n⏱️ **رفع قبل:** {days_ago} يوم\n📅 **باقي:** {days_left} يوم"
    
    await callback_query.message.edit_text(
        f"🍪 **{platform['name']}**\n\n"
        f"📊 **الحالة:** {status}{expiry_info}\n\n"
        "اختر الإجراء:",
        reply_markup=keyboard
    )
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^cookies_status$'))
async def cookies_status_handler(client, callback_query):
    """معالج عرض حالة جميع الـ Cookies"""
    user_id = callback_query.from_user.id
    
    if not is_admin(user_id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    status_text = "📊 **حالة جميع الـ Cookies**\n\n"
    
    for platform_id, data in COOKIES_PLATFORMS.items():
        cookie_exists = os.path.exists(data['file'])
        
        if cookie_exists:
            file_time = os.path.getmtime(data['file'])
            uploaded_date = datetime.fromtimestamp(file_time)
            days_ago = (datetime.now() - uploaded_date).days
            
            # افتراض صلاحية 30 يوم
            days_left = 30 - days_ago
            
            if days_left > 7:
                status_icon = "✅"
            elif days_left > 0:
                status_icon = "⚠️"
            else:
                status_icon = "❌"
            
            status_text += f"{status_icon} **{data['name']}**\n"
            status_text += f"   ⏱️ رفع قبل: {days_ago} يوم\n"
            status_text += f"   📅 باقي: {max(0, days_left)} يوم\n\n"
        else:
            status_text += f"❌ **{data['name']}**\n"
            status_text += f"   ⚠️ غير موجود\n\n"
    
    await callback_query.message.edit_text(
        status_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("« رجوع", callback_data="cookies_back")]
        ])
    )
    
    await callback_query.answer()


@app.on_message(filters.command("backup"))
async def backup_command(client, message):
    """معالج أمر /backup - لإنشاء نسخة احتياطية من قاعدة البيانات"""
    await send_database_backup(client, message)


@app.on_callback_query(filters.regex(r'^add_cookie_'))
async def add_cookie_handler(client, callback_query):
    """طلب إضافة cookies"""
    user_id = callback_query.from_user.id
    
    if not is_admin(user_id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    platform_id = callback_query.data.replace('add_cookie_', '')
    platform = COOKIES_PLATFORMS[platform_id]
    
    waiting_for_cookies[user_id] = platform_id
    
    await callback_query.message.edit_text(
        f"🍪 **إضافة Cookies - {platform['name']}**\n\n"
        "📝 **كيفية الحصول على Cookies:**\n"
        "1. افتح المنصة في المتصفح\n"
        "2. سجل دخول لحسابك\n"
        "3. استخدم إضافة **Get cookies.txt** أو **EditThisCookie**\n"
        "4. صدّر الـ cookies بصيغة Netscape\n"
        "5. أرسل الملف هنا\n\n"
        "⚠️ **ملاحظة:** استخدم ملف .txt فقط (Netscape format)"
    )
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^test_cookie_'))
async def test_cookie_handler(client, callback_query):
    """اختبار cookies"""
    user_id = callback_query.from_user.id
    
    if not is_admin(user_id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    platform_id = callback_query.data.replace('test_cookie_', '')
    platform = COOKIES_PLATFORMS[platform_id]
    
    if not os.path.exists(platform['file']):
        await callback_query.answer("❌ لا توجد cookies لهذه المنصة!", show_alert=True)
        return
    
    await callback_query.answer("⏳ جاري الفحص...")

    # فحص حقيقي لمحتوى ملف الكوكيز الخاص بهذه المنصة تحديداً
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, validate_platform_cookies, platform_id)

    header = (
        f"🍪 **المنصة:** {platform['name']}\n"
        f"📂 **الملف:** {platform['file']}\n"
    )

    if result.get('ok'):
        count = result.get('cookie_count', 0)
        if result.get('has_auth'):
            auth_line = "🔐 **تسجيل الدخول:** ✅ كوكيز الجلسة موجودة\n"
        else:
            auth_line = "🔐 **تسجيل الدخول:** ℹ️ لا توجد كوكيز جلسة معروفة لهذه المنصة\n"
        warn = ""
        if result.get('expired'):
            warn = (f"\n⚠️ بعض الكوكيز الثانوية منتهية: "
                    f"{', '.join(result['expired'][:5])}")
        await callback_query.message.edit_text(
            f"✅ **الكوكيز صالحة!**\n\n"
            f"{header}"
            f"📊 **عدد الكوكيز للمنصة:** {count}\n"
            f"{auth_line}"
            f"📊 **الحالة:** ✅ جاهزة للاستخدام (بما فيها الستوري){warn}"
        )
        return

    reason = result.get('reason')
    if reason == 'empty':
        body = "❌ الملف فارغ أو حجمه صغير جداً. أعد رفع ملف كوكيز صحيح."
    elif reason == 'unparseable':
        body = ("❌ تعذّر قراءة الملف — الصيغة غير صحيحة.\n"
                "تأكد أنه بصيغة **Netscape** (txt) المصدّرة من إضافة Get cookies.txt.")
    elif reason == 'wrong_platform':
        found = '، '.join(result.get('found_domains', [])) or 'غير معروف'
        body = (f"❌ هذا الملف لا يحتوي كوكيز **{platform['name']}**!\n"
                f"النطاقات الموجودة في الملف: {found}\n"
                f"يبدو أنك رفعت كوكيز منصة أخرى بالخطأ.")
    elif reason == 'not_logged_in':
        missing = '، '.join(result.get('missing', []))
        body = (f"❌ الكوكيز لا تتضمن تسجيل دخول!\n"
                f"كوكيز الجلسة الناقصة: `{missing}`\n"
                f"سجّل الدخول للحساب في المتصفح ثم صدّر الكوكيز من جديد.\n"
                f"⚠️ بدون تسجيل الدخول لن يعمل تحميل الستوري والمحتوى الخاص.")
    elif reason == 'expired':
        expired = '، '.join(result.get('expired', [])[:5])
        body = (f"❌ كوكيز تسجيل الدخول **منتهية الصلاحية**!\n"
                f"المنتهية: `{expired}`\n"
                f"سجّل الدخول مجدداً في المتصفح وصدّر كوكيز جديدة.")
    else:
        body = "❌ تعذّر التحقق من الكوكيز."

    await callback_query.message.edit_text(
        f"⚠️ **الكوكيز غير صالحة**\n\n"
        f"{header}\n"
        f"{body}"
    )


@app.on_callback_query(filters.regex(r'^cookies_back$'))
async def cookies_back_handler(client, callback_query):
    """العودة لقائمة المنصات"""
    user_id = callback_query.from_user.id
    
    if not is_admin(user_id):
        return
    
    keyboard = []
    for platform_id, data in COOKIES_PLATFORMS.items():
        keyboard.append([
            InlineKeyboardButton(data['name'], callback_data=f"cookies_{platform_id}")
        ])
    
    keyboard.append([
        InlineKeyboardButton("📊 حالة جميع الـ Cookies", callback_data="cookies_status")
    ])
    
    await callback_query.message.edit_text(
        "🍪 **إدارة Cookies**\n\n"
        "اختر المنصة لإضافة أو اختبار الـ cookies:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await callback_query.answer()


@app.on_message(filters.document)
async def handle_cookie_file(client, message):
    """معالج ملفات الـ cookies"""
    if not message.from_user:
        return
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    if user_id not in waiting_for_cookies:
        return
    
    platform_id = waiting_for_cookies[user_id]
    platform = COOKIES_PLATFORMS[platform_id]
    
    # التحقق من نوع الملف
    if not message.document.file_name.endswith('.txt'):
        await message.reply_text("❌ يجب أن يكون الملف بصيغة .txt!")
        return
    
    status_msg = await message.reply_text("⏳ جاري حفظ الـ cookies...")
    
    try:
        # تحميل الملف
        file_path = await client.download_media(message.document.file_id)
        
        # نسخ الملف إلى مجلد cookies
        import shutil
        shutil.move(file_path, platform['file'])
        
        del waiting_for_cookies[user_id]
        
        await status_msg.edit_text(
            f"✅ **تم حفظ Cookies بنجاح!**\n\n"
            f"🍪 **المنصة:** {platform['name']}\n"
            f"📂 **الملف:** {platform['file']}\n\n"
            "يمكنك الآن استخدام /cookies لاختبارها."
        )
        
        logger.info(f"✅ الأدمن {user_id} أضاف cookies لـ {platform_id}")
        
    except Exception as e:
        await status_msg.edit_text(f"❌ فشل حفظ الملف: {str(e)}")
        logger.error(f"خطأ في حفظ cookies: {e}")


# أسماء المنصات للعرض في رسالة المعاينة
PLATFORM_DISPLAY_NAMES = {
    'youtube': 'YouTube', 'facebook': 'Facebook', 'instagram': 'Instagram',
    'threads': 'Threads', 'twitter': 'X (Twitter)', 'reddit': 'Reddit',
    'snapchat': 'Snapchat', 'pinterest': 'Pinterest', 'tiktok': 'TikTok',
}


def _best_thumbnail_url(info):
    """يرجع رابط أفضل صورة مصغّرة من معلومات الفيديو (أو None).

    نفضّل الصيغ التي يقبلها تلجرام برابط مباشر (jpg/png)؛ بعض المنصات ترجع
    webp فيرفضه تلجرام أحياناً — عندها نسقط لأول رابط متاح ويتكفّل المستدعي
    بالتراجع لرسالة نصية إذا فشل الإرسال."""
    if not info:
        return None
    urls = []
    if info.get('thumbnail'):
        urls.append(str(info['thumbnail']))
    # قائمة thumbnails مرتّبة تصاعدياً بالجودة في yt-dlp — الأخيرة الأكبر
    for th in reversed(info.get('thumbnails') or []):
        u = th.get('url') if isinstance(th, dict) else None
        if u:
            urls.append(str(u))
    urls = [u for u in urls if u.startswith(('http://', 'https://'))]
    for u in urls:
        if '.webp' not in u.lower():
            return u
    return urls[0] if urls else None


@app.on_message(filters.text & filters.regex(r'https?://\S+'))
async def handle_url(client, message):
    if not message.from_user:
        return
    
    # استخرج الرابط النظيف من النص (قد يحتوي كلاماً/إيموجي/أسطراً حول الرابط)
    url = extract_first_url(message.text)
    user_id = message.from_user.id

    # لم يُعثر على رابط صالح داخل النص → لا تكمل بنص غير صالح
    if not url:
        lang = subdb.get_user_language(user_id)
        await message.reply_text(t('invalid_url', lang))
        return

    # إن كان الأدمن في وضع إضافة قناة اشتراك إجباري وأرسل رابط t.me، عالِجه هنا
    # (لأن معالج الروابط يلتقط أي رسالة فيها http قبل معالج إدخال الأدمن)
    if is_admin(user_id):
        _pend = pending_downloads.get(user_id)
        if isinstance(_pend, dict) and _pend.get('waiting_for') == 'add_forced_channel':
            await add_forced_channel_from_admin(client, message, user_id)
            return

    # Get user language FIRST
    lang = subdb.get_user_language(user_id)

    # ⏸️ إيقاف التحميل العام (الأدمن مُعفى)
    if not is_admin(user_id) and not downloads_enabled():
        await message.reply_text(t('downloads_paused', lang))
        return

    # 🚫 مستخدم محظور أصلاً: اعرض شاشة الحظر/التعهّد (الأدمن مُعفى)
    if not is_admin(user_id) and subdb.is_user_banned(user_id):
        ban_text, ban_kb = _banned_block_content(user_id, lang)
        await message.reply_text(ban_text, reply_markup=ban_kb)
        return

    # 📋 استبيان إجباري قبل التحميل (الجنس + الأسئلة) — الأدمن مُعفى
    if not is_admin(user_id):
        if await _prompt_survey_if_needed(message.reply_text, user_id):
            return

    # 🔞 محتوى إباحي/حساب محظور → عاقِب المستخدم (حظر + تعهّد)
    if (adult_filter_enabled() and is_adult_url(url)) or is_blocked_url(url):
        logger.info(f"🔞 Adult/blocked URL from user {user_id}: {_url_host(url)}")
        ban_text, ban_kb = await _apply_adult_ban(client, user_id, lang)
        await message.reply_text(ban_text, reply_markup=ban_kb)
        return

    # 🚫 حماية SSRF: ارفض الروابط الداخلية/غير http(s) قبل تمريرها لـ yt-dlp
    if not is_safe_url(url):
        logger.warning(f"🚫 Blocked unsafe/internal URL from user {user_id}: {url[:100]}")
        await message.reply_text(t('invalid_url', lang))
        return

    # 🎯 سناب سبوت لايت: استخرج الفيديو الخام (أنظف نسخة، غالباً بلا لوقو) قبل
    #    التحميل. طلب شبكي متزامن فيُنفَّذ خارج حلقة الأحداث. عند الفشل يبقى الرابط.
    if 'snapchat.com' in url.lower():
        _resolved = await asyncio.get_event_loop().run_in_executor(
            None, resolve_snapchat_spotlight, url)
        if _resolved and _resolved != url:
            url = _resolved

    # 🎵 روابط الأغاني (Shazam/Apple Music/Spotify) لا تُحمّل مباشرة →
    #    استخرج اسم الأغنية وابحث عنها في يوتيوب، ثم أكمل التحميل على رابط يوتيوب.
    if _is_music_link(url):
        _mmsg = await message.reply_text(t('music_searching', lang))
        _yt = await asyncio.get_event_loop().run_in_executor(
            None, resolve_music_link, url)
        if not _yt:
            await _mmsg.edit_text(t('music_not_found', lang))
            return
        logger.info(f"🎵 رابط أغنية ({_url_host(url)}) → {_yt}")
        await _mmsg.delete()
        url = _yt

    # 📢 الاشتراك الإجباري بالقنوات قبل أي تحميل (تحقق حقيقي)
    if await enforce_forced_subscription(client, message, user_id, lang):
        return

    # Check rate limiting
    is_limited, seconds_remaining = queue_manager.is_rate_limited(user_id)
    if is_limited:
        await message.reply_text(
            t('queue_rate_limit', lang, seconds=int(seconds_remaining) + 1)
        )
        return
    
    # Mark request time immediately for rate limiting (even during quality selection)
    queue_manager.mark_request(user_id)
    
    # Check if user already has downloads in queue
    queue_size = queue_manager.get_queue_size(user_id)
    is_processing = queue_manager.is_processing(user_id)
    
    if is_processing or queue_size > 0:
        # User has active downloads, add to queue
        # Create download task
        task = DownloadTask(
            url=url,
            message=message,
            user_id=user_id,
            quality="pending"  # Will be set when quality is chosen
        )
        
        # Add to queue
        position = await queue_manager.add_to_queue(
            user_id=user_id,
            task=task,
            process_func=process_download_from_queue
        )
        
        # Notify user
        await message.reply_text(
            t('queue_position', lang, position=position)
        )
        return
    
    # No active downloads, process normally
    pending_downloads[user_id] = url
    
    status = await message.reply_text(t('processing', lang))
    
    try:
        info = await get_video_info(url)
        
        if not info:
            # Send alert to admin
            user_name = message.from_user.first_name or "User"
            # 🖼️ قد يفشل yt-dlp تماماً في استخراج سلايدشو تيك توك / كاروسيل
            #    إنستغرام/بينتريست (منشور صور بلا فيديو، خاصة الروابط المختصرة)
            #    فيرجع None. جرّب مسار الصور عبر gallery-dl قبل اعتبار الرابط فاشلاً.
            if _platform_of(url) in ('instagram', 'tiktok', 'pinterest'):
                if await download_and_send_images(
                    client, message, url, status, user_id, user_name,
                    message.from_user.username, lang
                ):
                    pending_downloads.pop(user_id, None)
                    return
            # محتوى مقيّد بالعمر/حسّاس → رسالة واضحة بدل "رابط غير صحيح" المضلّلة
            if _last_info_error.get() == 'restricted':
                await send_error_to_admin(user_id, user_name, "Restricted/sensitive content", url)
                await status.edit_text(t('content_restricted', lang))
                return
            # منشور إنستغرام خاص/محذوف (المرآة أُحيلت لجدار الدخول) → رسالة واضحة
            if _last_info_error.get() == 'ig_unavailable':
                await send_error_to_admin(user_id, user_name, "Instagram post private/removed", url)
                await status.edit_text(t('post_unavailable', lang))
                return
            await send_error_to_admin(user_id, user_name, "Failed to extract video info", url)
            await status.edit_text(t('invalid_url', lang))
            return
    except Exception as e:
        # Unexpected error
        user_name = message.from_user.first_name or "User"
        await send_error_to_admin(user_id, user_name, str(e), url)
        await status.edit_text(t('error_occurred', lang, error=str(e)[:100]))
        return

    # 🔞 حظر المحتوى الإباحي بعد الاستخراج (فحص العنوان/الوصف/الفئات/الفئة العمرية)
    if adult_filter_enabled() and is_adult_info(info):
        logger.info(f"🔞 Blocked adult content from user {user_id}: {info.get('title')}")
        await status.edit_text(t('adult_blocked', lang))
        return

    title = info.get('title', 'Video')[:50]
    duration = info.get('duration', 0)
    duration_str = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else "0:00"
    
    # Add or update user info
    username = message.from_user.username
    first_name = message.from_user.first_name
    subdb.add_or_update_user(user_id, username, first_name)
    
    # Check subscription and video duration
    is_subscribed = subdb.is_user_subscribed(user_id)
    
    # فحص الحد اليومي للمستخدمين غير المشتركين
    # Check daily limit for non-subscribers
    if not is_subscribed:
        base_limit = subdb.get_daily_limit()

        # فقط فحص إذا كان الحد ليس "غير محدود" (-1)
        if base_limit != -1:
            effective_limit = base_limit + subdb.get_bonus_downloads(user_id)
            daily_count = subdb.check_daily_limit(user_id)

            if daily_count >= effective_limit:
                await status.edit_text(
                    t('daily_limit_exceeded', lang, limit=effective_limit, count=daily_count),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t('subscribe_now', lang), callback_data="show_plans")],
                        [_invite_button(lang)],
                        [InlineKeyboardButton(t('contact_developer', lang), url=f"https://t.me/{subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))}")]
                    ])
                )
                return
    
    # 🖼️ منشور مصوّر بلا فيديو (كاروسيل إنستغرام/بينتريست / سلايدشو تيك توك) →
    #    أرسل الصور كألبوم عبر gallery-dl. المنشورات المختلطة (صور+فيديو) تبقى
    #    على مسار الفيديو المعتاد دون أي تغيير في سلوكه.
    if _platform_of(url) in ('instagram', 'tiktok', 'pinterest') and not _info_has_video(info):
        img_user_name = message.from_user.first_name or "User"
        handled = await download_and_send_images(
            client, message, url, status, user_id, img_user_name, username, lang, info
        )
        pending_downloads.pop(user_id, None)
        if handled:
            return
        # لا فيديو ولا صور صالحة في الرابط
        await status.edit_text(t('no_media_found', lang))
        return

    # الحد الأقصى للمدة = الأساس + مكافأة دعوات المستخدم (كل دعوة +REFERRAL_MINUTES دقيقة)
    max_duration_minutes = _user_max_duration_minutes(user_id)
    max_duration_seconds = max_duration_minutes * 60

    # If not subscribed and exceeds max duration
    if not is_subscribed and duration and duration > max_duration_seconds:
        await show_subscription_screen(client, status, user_id, title, duration, max_duration_minutes)
        return

    # معاينة مرتّبة: صورة مصغّرة + معلومات المقطع + زرا فيديو/صوت
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('btn_video', lang), callback_data="quality_best"),
         InlineKeyboardButton(t('btn_audio', lang), callback_data="quality_audio")],
    ])

    details = t('preview_duration', lang, duration=duration_str)
    platform = _platform_of(url)
    if platform != 'other':
        details += '\n' + t('preview_platform', lang,
                            platform=PLATFORM_DISPLAY_NAMES.get(platform, platform))
    uploader = str(info.get('uploader') or info.get('channel') or '').strip()
    if uploader:
        details += '\n' + t('preview_uploader', lang, uploader=uploader[:40])
    caption = t('link_preview', lang, title=title, details=details)

    thumb = _best_thumbnail_url(info)
    if thumb:
        try:
            await message.reply_photo(thumb, caption=caption, reply_markup=keyboard)
            await status.delete()
            return
        except Exception as e:
            # تلجرام قد يرفض جلب المصغّر (صيغة/حجم/انتهاء الرابط) → معاينة نصية
            logger.info(f"⚠️ تعذّر إرسال المعاينة بصورة مصغّرة ({_url_host(url)}): {e}")
    await status.edit_text(caption, reply_markup=keyboard)



@app.on_callback_query(filters.regex(r'^quality_'))
async def handle_quality(client, callback_query):
    await callback_query.answer()
    
    user_id = callback_query.from_user.id
    quality = callback_query.data.replace("quality_", "")
    
    # رسالة المعاينة قد تكون صورة (مصغّرة) → تعديلها يكون بـ edit_caption
    async def _edit_preview(msg, text):
        try:
            if msg.photo:
                await msg.edit_caption(text)
            else:
                await msg.edit_text(text)
        except Exception as e:
            logger.warning(f"⚠️ تعذّر تعديل رسالة المعاينة: {e}")

    if user_id not in pending_downloads:
        lang = subdb.get_user_language(user_id)
        await _edit_preview(callback_query.message,
                            t('error_occurred', lang, error="Session expired. Send link again."))
        return

    url = pending_downloads[user_id]
    lang = subdb.get_user_language(user_id)

    # رسالة المعاينة نفسها تصير رسالة التقدم (معاينة + تقدم مدموجة في رسالة
    # واحدة)؛ عند النجاح تُحذف من داخل download_and_upload، وعند الفشل يظهر
    # الخطأ عليها مباشرة.
    await download_and_upload(client, callback_query.message, url, quality,
                              callback_query, status_msg=callback_query.message)

    # Safe deletion - prevents KeyError if user clicks multiple quality buttons
    pending_downloads.pop(user_id, None)


@app.on_callback_query(filters.regex(r'^playlist_dl$'))
async def handle_playlist_download(client, callback_query):
    """تحميل مقاطع قائمة التشغيل تتابعياً (بأفضل جودة)."""
    await callback_query.answer()
    user_id = callback_query.from_user.id
    lang = subdb.get_user_language(user_id)

    urls = pending_playlists.pop(user_id, None)
    if not urls:
        await callback_query.message.edit_text(
            t('error_occurred', lang, error="Session expired. Send link again.")
        )
        return

    await callback_query.message.edit_text(t('playlist_started', lang, n=len(urls)))
    for u in urls:
        try:
            await download_and_upload(client, callback_query.message, u, 'best', callback_query)
        except Exception as e:
            logger.error(f"❌ خطأ في تحميل مقطع من القائمة ({u[:60]}): {e}")


# ═══════════════════════════════════════════════════════════════
# Subscription System Handlers
# ═══════════════════════════════════════════════════════════════

def _plan_prices():
    """يرجع (سعر الشهري، سعر السنوي) من الإعدادات (مع توافق السعر القديم)."""
    pm = subdb.get_setting('price_monthly', subdb.get_setting('subscription_price', '10'))
    py = subdb.get_setting('price_yearly', '100')
    return pm, py


def _price_value(price):
    try:
        return float(price)
    except (TypeError, ValueError):
        return 0.0


def _price_text(price, lang):
    return t('free_label', lang) if _price_value(price) <= 0 else f"${price}"


def _plans_keyboard(lang):
    """أزرار خطط الاشتراك (شهري/سنوي بالأسعار) + تواصل."""
    pm, py = _plan_prices()
    telegram_support = subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{t('plan_monthly', lang)} — {_price_text(pm, lang)}",
                              callback_data="plan_monthly")],
        [InlineKeyboardButton(f"{t('plan_yearly', lang)} — {_price_text(py, lang)}",
                              callback_data="plan_yearly")],
        [InlineKeyboardButton(t('telegram_contact', lang), url=f"https://t.me/{telegram_support}")],
    ])


async def show_subscription_screen(client, message, user_id, title, duration, max_minutes):
    """عرض شاشة الاشتراك (الخطط: شهري/سنوي) للمستخدمين غير المشتركين"""
    duration_minutes = int(duration) // 60
    lang = subdb.get_user_language(user_id)

    text = (
        t('subscription_required', lang, title=title, duration=duration_minutes, max_duration=max_minutes) +
        "\n\n" +
        t('unlock_by_invite', lang, minutes=subdb.get_referral_minutes()) +
        "\n\n━━━━━━━━━━━━━━━━\n\n" +
        t('subscription_benefits', lang) +
        "\n\n" +
        t('choose_plan', lang)
    )

    # خياران للمستخدم: يشترك (خطط الدفع) أو يدعو أصدقاءه (مجاناً) لرفع حدّ المدة
    keyboard = InlineKeyboardMarkup(
        _plans_keyboard(lang).inline_keyboard + [[_invite_button(lang)]]
    )
    await message.edit_text(text, reply_markup=keyboard)


@app.on_callback_query(filters.regex(r'^show_plans$'))
async def handle_show_plans(client, callback_query):
    """يعرض خطط الاشتراك (يُستخدم من زر 'اشترك الآن')."""
    lang = subdb.get_user_language(callback_query.from_user.id)
    text = t('subscription_benefits', lang) + "\n\n" + t('choose_plan', lang)
    try:
        await callback_query.message.edit_text(text, reply_markup=_plans_keyboard(lang))
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=_plans_keyboard(lang))
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^plan_(monthly|yearly)$'))
async def handle_plan_choice(client, callback_query):
    """اختيار الخطة: إن كانت مجانية يُفعّل فوراً، وإلا يعرض طرق الدفع."""
    await callback_query.answer()
    user_id = callback_query.from_user.id
    lang = subdb.get_user_language(user_id)
    plan = 'monthly' if callback_query.data == 'plan_monthly' else 'yearly'
    pm, py = _plan_prices()
    price = pm if plan == 'monthly' else py
    duration = 30 if plan == 'monthly' else 365

    # خطة مجانية → تفعيل فوري بلا دفع
    if _price_value(price) <= 0:
        subdb.activate_subscription(user_id, duration, 'free')
        await callback_query.message.edit_text(t('plan_activated_free', lang, days=duration))
        return

    # خطة مدفوعة → احفظ الخطة واعرض طرق الدفع
    pending_downloads[user_id] = {'plan': plan, 'duration': duration, 'price': price}
    telegram_support = subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))
    plan_label = t('plan_monthly', lang) if plan == 'monthly' else t('plan_yearly', lang)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('binance_pay', lang), callback_data="pay_binance")],
        [InlineKeyboardButton(t('visa_card', lang), callback_data="pay_visa"),
         InlineKeyboardButton(t('mastercard', lang), callback_data="pay_mastercard")],
        [InlineKeyboardButton(t('telegram_contact', lang), url=f"https://t.me/{telegram_support}")],
    ])
    await callback_query.message.edit_text(
        f"💎 {plan_label} — ${price}\n\n{t('choose_payment_method', lang)}",
        reply_markup=keyboard
    )


@app.on_callback_query(filters.regex(r'^pay_'))
async def handle_payment_method(client, callback_query):
    """معالج طرق الدفع"""
    user_id = callback_query.from_user.id
    payment_method = callback_query.data.replace('pay_', '')
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    binance_id = subdb.get_setting('binance_pay_id', os.getenv('BINANCE_PAY_ID', ''))
    telegram_support = subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))
    # السعر/المدة من الخطة المختارة (إن وُجدت)، وإلا الخطة الشهرية افتراضياً
    _pdata = pending_downloads.get(user_id) if isinstance(pending_downloads.get(user_id), dict) else {}
    pm, _py = _plan_prices()
    price = _pdata.get('price') or pm
    plan = _pdata.get('plan', 'monthly')
    duration = _pdata.get('duration', 30)

    if payment_method == 'binance':
        text = (
            f"{t('payment_binance_title', lang)}\n\n"
            f"{t('payment_amount', lang, price=price)}\n"
            f"🆔 **Binance Pay ID:** `{binance_id}`\n\n"
            f"{t('payment_binance_steps', lang, binance_id=binance_id)}"
        )
    elif payment_method == 'visa':
        text = (
            f"{t('payment_visa_title', lang)}\n\n"
            f"{t('payment_amount', lang, price=price)}\n\n"
            f"{t('payment_visa_instructions', lang, support_username=telegram_support)}"
        )
    elif payment_method == 'mastercard':
        text = (
            f"{t('payment_mastercard_title', lang)}\n\n"
            f"{t('payment_amount', lang, price=price)}\n\n"
            f"{t('payment_mastercard_instructions', lang, support_username=telegram_support)}"
        )
    
    # حفظ طريقة الدفع المختارة مع الخطة (لتطبيق المدة الصحيحة عند القبول)
    pending_downloads[user_id] = {'payment_method': payment_method,
                                  'plan': plan, 'duration': duration, 'price': price}

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('contact_developer', lang), url=f"https://t.me/{telegram_support}")],
        [InlineKeyboardButton(t('back', lang), callback_data="back_to_subscription")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=keyboard)
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^binance_id_info$'))
async def handle_binance_id_info(client, callback_query):
    """معالج زر معلومات Binance ID"""
    binance_id = subdb.get_setting('binance_pay_id', os.getenv('BINANCE_PAY_ID', ''))
    await callback_query.answer(
        f"💵 Binance Pay ID: {binance_id}\n\n"
        f"يمكنك دعم المطور عبر إرسال أي مبلغ!",
        show_alert=True
    )


@app.on_callback_query(filters.regex(r'^binance_info$'))
async def handle_binance_info_copy(client, callback_query):
    """زر دعم المطور (احتياطي لإصدارات Pyrogram التي لا تدعم النسخ التلقائي):
    يعرض المعرّف في تنبيه لنسخه."""
    binance_id = subdb.get_setting('binance_pay_id', os.getenv('BINANCE_PAY_ID', ''))
    await callback_query.answer(
        f"✅ تم النسخ\nPay ID: {binance_id}",
        show_alert=True
    )


@app.on_callback_query(filters.regex(r'^fsub_check$'))
async def handle_fsub_check(client, callback_query):
    """تحقق حقيقي من الاشتراك الإجباري؛ عند النجاح يحذف الرسالة ويعرض الشكر."""
    user_id = callback_query.from_user.id
    lang = subdb.get_user_language(user_id)

    # تحقق حقيقي من العضوية في القنوات (التي يكون البوت مشرفاً فيها)
    missing = await get_missing_forced_channels(client, user_id)
    if missing:
        await callback_query.answer(t('fsub_not_yet', lang), show_alert=True)
        return

    # نجح التحقق: احذف رسالة الاشتراك كاملة وأظهر رسالة الشكر
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await client.send_message(user_id, t('fsub_thanks', lang))
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^back_to_subscription$'))
async def handle_back_to_subscription(client, callback_query):
    """معالج الرجوع لشاشة الاشتراك"""
    user_id = callback_query.from_user.id
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    # الرجوع لاختيار الخطة (الشهري/السنوي)
    text = (
        t('subscription_benefits', lang) +
        "\n\n" +
        t('choose_plan', lang)
    )

    await callback_query.message.edit_text(
        text,
        reply_markup=_plans_keyboard(lang)
    )
    await callback_query.answer()


async def notify_admin_contact(client, user_id, user, payment_method):
    """إرسال إشعار للمطور عند محاولة المستخدم التواصل"""
    try:
        admin_id = int(os.getenv("ADMIN_ID"))
        username = user.username or "لا يوجد"
        first_name = user.first_name or "مستخدم"
        
        text = (
            f"📞 **طلب اشتراك جديد!**\n\n"
            f"👤 **المستخدم:** {first_name}\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"📱 **Username:** @{username}\n"
            f"💳 **الطريقة المطلوبة:** {payment_method}\n\n"
            f"المستخدم يريد الاشتراك ويحتاج للتواصل معك! 💬"
        )
        
        await client.send_message(admin_id, text)
        logger.info(f"📞 إشعار تواصل من {user_id} للأدمن")
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار التواصل: {e}")



@app.on_message(filters.photo)
async def handle_payment_proof(client, message):
    """معالج إثبات الدفع (الصور)"""
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    
    # التحقق إذا كان المستخدم في عملية دفع
    if user_id not in pending_downloads:
        # رد فوري: البوت لا يدعم الصور إلا لإثبات الدفع
        await message.reply_text(t('unsupported_media_photo', lang))
        return
    
    payment_data = pending_downloads.get(user_id)
    if not isinstance(payment_data, dict) or 'payment_method' not in payment_data:
        # رد فوري: البوت لا يدعم الصور إلا لإثبات الدفع
        await message.reply_text(t('unsupported_media_photo', lang))
        return
    
    payment_method = payment_data['payment_method']
    plan_duration = payment_data.get('duration', 30)
    plan_price = payment_data.get('price')

    # حفظ الدفعة في قاعدة البيانات (مع المدة والسعر حسب الخطة)
    payment_id = subdb.add_payment(
        user_id=user_id,
        payment_method=payment_method,
        proof_file_id=message.photo.file_id,
        proof_message_id=message.id,
        amount=_price_value(plan_price) if plan_price else None,
        duration_days=plan_duration
    )
    
    # حذف من pending
    del pending_downloads[user_id]
    
    # إرسال إشعار للمستخدم بلغته
    await message.reply_text(t('payment_received', subdb.get_user_language(user_id)))
    
    # إرسال إشعار للأدمن
    admin_id = int(os.getenv("ADMIN_ID"))
    username = message.from_user.username or "لا يوجد"
    first_name = message.from_user.first_name or "مستخدم"
    
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ قبول", callback_data=f"approve_payment_{payment_id}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"reject_payment_{payment_id}")]
    ])
    
    await client.send_photo(
        chat_id=admin_id,
        photo=message.photo.file_id,
        caption=(
            f"💰 **دفعة جديدة!**\n\n"
            f"👤 **المستخدم:** {first_name}\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"📱 **Username:** @{username}\n"
            f"💳 **طريقة الدفع:** {payment_method}\n"
            f"🔖 **رقم الدفعة:** #{payment_id}\n\n"
            f"**قرار:**"
        ),
        reply_markup=admin_keyboard
    )
    
    logger.info(f"💰 دفعة جديدة #{payment_id} من {user_id} عبر {payment_method}")


@app.on_message(filters.video)
async def handle_video_upload(client, message):
    """معالج الفيديوهات المرفوعة - الرد التلقائي"""
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    
    # البوت لا يدعم رفع الفيديوهات، فقط تحميلها من الروابط
    await message.reply_text(t('unsupported_media_video', lang))


@app.on_message(filters.audio | filters.voice | filters.animation | filters.sticker)
async def handle_other_media(client, message):
    """معالج الوسائط الأخرى - الرد التلقائي"""
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = subdb.get_user_language(user_id)
    
    # البوت يدعم تحميل الفيديوهات من الروابط فقط
    await message.reply_text(t('unsupported_media_general', lang))


@app.on_callback_query(filters.regex(r'^approve_payment_'))
async def handle_approve_payment(client, callback_query):
    """معالج قبول الدفع من الأدمن"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    payment_id = int(callback_query.data.replace('approve_payment_', ''))
    admin_id = callback_query.from_user.id
    
    success, message_text = subdb.approve_payment(payment_id, admin_id)
    
    if success:
        # الحصول على معلومات الدفعة
        payment_info = subdb.get_payment_by_id(payment_id)
        if payment_info:
            user_id = payment_info[1]
            
            # إرسال إشعار للمستخدم
            try:
                # Get user's preferred language
                user_lang = subdb.get_user_language(user_id)
                
                await client.send_message(
                    chat_id=user_id,
                    text=t('subscription_activated', user_lang)
                )
            except Exception:
                pass
        
        await callback_query.message.edit_caption(
            callback_query.message.caption + "\n\n✅ **تم القبول والتفعيل**",
            reply_markup=None
        )
        await callback_query.answer("✅ تم تفعيل الاشتراك بنجاح!", show_alert=True)
    else:
        await callback_query.answer(f"❌ {message_text}", show_alert=True)


@app.on_callback_query(filters.regex(r'^reject_payment_'))
async def handle_reject_payment(client, callback_query):
    """معالج رفض الدفع من الأدمن"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    payment_id = int(callback_query.data.replace('reject_payment_', ''))
    
    # الحصول على معلومات الدفعة
    payment_info = subdb.get_payment_by_id(payment_id)
    if payment_info:
        user_id = payment_info[1]
        
        # رفض الدفعة
        subdb.reject_payment(payment_id)
        
        # إرسال إشعار للمستخدم
        try:
            telegram_support = subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))
            await client.send_message(
                chat_id=user_id,
                text=t('payment_rejected', subdb.get_user_language(user_id), support=telegram_support)
            )
        except Exception:
            pass
        
        await callback_query.message.edit_caption(
            callback_query.message.caption + "\n\n❌ **تم الرفض**",
            reply_markup=None
        )
        await callback_query.answer("❌ تم رفض الدفعة", show_alert=True)


# زر الرجوع الموحّد لكل شاشات إعدادات الاشتراك
def _sub_settings_back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]
    ])


async def show_forced_sub_panel(client, callback_query):
    """لوحة إدارة الاشتراك الإجباري: القنوات + إحصائيات الأعضاء + حذف/إضافة."""
    channels = subdb.get_forced_channels()
    enabled = forced_sub_enabled()
    state = "✅ مُفعّل" if enabled else "❌ متوقف"
    text = f"📢 **الاشتراك الإجباري بالقنوات**\n\nالحالة: {state}\n\n"
    rows = [[InlineKeyboardButton(
        f"🔔 {'إيقاف' if enabled else 'تفعيل'} الاشتراك الإجباري",
        callback_data="sub_fsub_toggle"
    )]]
    if not channels:
        text += "لا توجد قنوات حالياً.\nأضف قناة/قروب ليُطلب من الأعضاء الاشتراك قبل التحميل."
    else:
        text += (
            f"عدد القنوات: {len(channels)}\n"
            "✅ = البوت مشرف (تحقق حقيقي) | ⚠️ = ليس مشرفاً (لا يُفرض)\n\n"
        )
        for ch in channels:
            row_id, chat_id, username, title = ch[0], ch[1], ch[2], ch[3]
            name = title or (f"@{username}" if username else str(chat_id))
            # عدد المشتركين الحقيقي + حالة صلاحية البوت (هل التحقق فعّال؟)
            count = "?"
            try:
                chat = await client.get_chat(_forced_channel_target(chat_id))
                count = getattr(chat, 'members_count', None) or "?"
            except Exception:
                pass
            verifiable = await _channel_is_verifiable(client, chat_id)
            status = "✅" if verifiable else "⚠️"
            text += f"{status} {name} — 👥 {count} مشترك\n"
            rows.append([InlineKeyboardButton(f"🗑️ حذف: {name[:25]}", callback_data=f"sub_fsubdel_{row_id}")])
        text += "\n⚠️ القنوات التي ليس البوت مشرفاً فيها لا يمكن التحقق منها (قيد تلجرام) فلا تُفرض. اجعل البوت مشرفاً ليعمل التحقق."

    rows.append([InlineKeyboardButton("➕ إضافة قناة/قروب", callback_data="sub_fsub_add")])
    rows.append([InlineKeyboardButton("⭐ قائمة الاستثناء (معفيون)", callback_data="sub_exempt")])
    rows.append([InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")])
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
    await callback_query.answer()


async def show_exempt_panel(client, callback_query):
    """لوحة قائمة الاستثناء: عرض الأعضاء المستثنين مع حذف لكل عضو، إضافة عضو،
    وبث خاص للمستثنين فقط. المستثنون لا يصلهم البث/التذكير ومعفيون من
    الاشتراك الإجباري."""
    ids = sorted(_exempt_ids())
    text = (
        "⭐ **قائمة الاستثناء**\n\n"
        "الأعضاء هنا:\n"
        "• 🔕 لا يصلهم البث الجماعي\n"
        "• 🔕 لا تصلهم رسائل التذكير\n"
        "• ✅ معفيون من الاشتراك الإجباري\n\n"
    )
    rows = []
    if not ids:
        text += "القائمة فارغة حالياً."
    else:
        text += f"👥 المستثنون ({len(ids)}):\n"
        for uid in ids:
            row = subdb.find_user_by_id(uid)
            name = (row[2] if row and row[2] else None) or (
                f"@{row[1]}" if row and row[1] else "غير معروف بعد")
            text += f"• `{uid}` — {name}\n"
            rows.append([InlineKeyboardButton(
                f"🗑️ حذف: {str(name)[:20]} ({uid})",
                callback_data=f"sub_exemptdel_{uid}")])
    rows.append([InlineKeyboardButton("➕ إضافة عضو", callback_data="sub_exempt_add")])
    if ids:
        rows.append([InlineKeyboardButton(
            f"📨 إرسال للمستثنين فقط ({len(ids)})", callback_data="sub_exempt_send")])
    rows.append([InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")])
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
    await callback_query.answer()


def _record_realcheck(alive=None):
    """يحفظ وقت آخر فحص فعلي + العدد الحقيقي الواصل (لعرضه في اللوحة).

    alive: عدد الأعضاء الذين ردّوا على الفحص الصامت (العدد الحقيقي الفعلي)."""
    try:
        subdb.set_setting('last_realcheck_at', datetime.now().strftime('%Y-%m-%d %H:%M'))
        if alive is not None:
            subdb.set_setting('last_realcheck_alive', str(alive))
    except Exception:
        pass


def _get_realcheck_alive():
    """العدد الحقيقي الواصل من آخر فحص، أو None إن لم يُجرَ فحص بعد."""
    try:
        rv = subdb.get_setting('last_realcheck_alive', '') or ''
        return int(rv) if rv else None
    except Exception:
        return None


def _last_realcheck_line():
    """سطر يوضّح متى جرى آخر فحص فعلي (حذف من حظر البوت)."""
    try:
        ts = subdb.get_setting('last_realcheck_at', '') or ''
    except Exception:
        ts = ''
    return f"🕐 آخر فحص فعلي: {ts}" if ts else "🕐 لم يُجرَ فحص فعلي بعد"


def _current_member_count():
    """المصدر الموحّد لعدد الأعضاء الحاليين المعروض في كل اللوحات (زر الفحص،
    التذكير، الإعدادات): العدد الحقيقي من آخر فحص إن وُجد، وإلا عدد قاعدة
    البيانات — فيظهر الرقم نفسه في كل مكان."""
    alive = _get_realcheck_alive()
    if alive is not None:
        return alive
    try:
        return subdb.get_user_stats()['total']
    except Exception:
        return 0


async def subscription_settings_panel(client, message, user_id=None, edit=False):
    """لوحة إعدادات الاشتراك للأدمن.

    user_id: معرّف الأدمن الفعلي (مهم عند الاستدعاء من زر رجوع لأن
    message.from_user حينها هو البوت وليس الأدمن).
    edit: True لتعديل الرسالة الحالية بدل إرسال رسالة جديدة.
    """
    if user_id is None:
        user_id = message.from_user.id if message.from_user else None

    if not is_admin(user_id):
        await message.reply_text("❌ هذا الأمر للمشرفين فقط!")
        return

    max_duration = subdb.get_max_duration()
    _pm, _py = _plan_prices()
    price_m = "مجاني" if _price_value(_pm) <= 0 else f"${_pm}"
    price_y = "مجاني" if _price_value(_py) <= 0 else f"${_py}"
    stats = subdb.get_user_stats()
    # العدد الحقيقي من آخر فحص (يستبعد من حظر البوت/غير المتفاعلين). إن وُجد
    # نعرضه كـ«المجموع»، وإلا نعرض عدد قاعدة البيانات.
    real_alive = _get_realcheck_alive()
    total_display = _current_member_count()
    free_display = max(0, total_display - stats['subscribed'])
    db_note = (f"📦 في القاعدة: {stats['total']} (للتنظيف)\n"
               if real_alive is not None and real_alive != stats['total'] else "")
    try:
        gs = subdb.get_gender_stats()
    except Exception:
        gs = {'male': 0, 'female': 0}
    try:
        lc = subdb.get_language_counts()
    except Exception:
        lc = {'ar': 0, 'en': 0}
    adult_on = adult_filter_enabled()
    adult_label = f"🔞 حظر المحتوى الإباحي: {'✅ مُفعّل' if adult_on else '❌ متوقف'}"
    dl_on = downloads_enabled()
    dl_label = "⏸️ إيقاف التحميل للجميع" if dl_on else "▶️ تشغيل التحميل للجميع"

    keyboard = InlineKeyboardMarkup([
        # — التحكم العام —
        [InlineKeyboardButton(dl_label, callback_data="sub_toggle_downloads")],
        [InlineKeyboardButton(adult_label, callback_data="sub_toggle_adult")],
        # — إعدادات الاشتراك —
        [InlineKeyboardButton("⏱️ المدة القصوى", callback_data="sub_set_duration"),
         InlineKeyboardButton("💰 الأسعار", callback_data="sub_set_price")],
        [InlineKeyboardButton("📢 الاشتراك الإجباري", callback_data="sub_fsub"),
         InlineKeyboardButton("💳 الدفوعات", callback_data="sub_pending_payments")],
        # — المحتوى المحظور والأسئلة —
        [InlineKeyboardButton("➕ موقع محظور", callback_data="sub_add_domain"),
         InlineKeyboardButton("➕ كلمة محظورة", callback_data="sub_add_keyword")],
        [InlineKeyboardButton("📋 القائمة المحظورة", callback_data="sub_list_blocked"),
         InlineKeyboardButton("❓ سؤال للأعضاء", callback_data="sub_member_question")],
        # — الأعضاء —
        [InlineKeyboardButton("👥 فحص العدد الحقيقي", callback_data="sub_realcheck")],
        [InlineKeyboardButton("👥 المشتركون", callback_data="sub_view_subscribers"),
         InlineKeyboardButton("📊 آخر 50 عضو", callback_data="sub_recent_users")],
        [InlineKeyboardButton("📊 إحصائيات الأعضاء", callback_data="sub_member_stats"),
         InlineKeyboardButton("🔍 بحث عن عضو", callback_data="sub_search_user")],
        # — الإدارة —
        [InlineKeyboardButton("✏️ ترقية عضو", callback_data="sub_promote_user"),
         InlineKeyboardButton("❌ إلغاء ترقية", callback_data="sub_demote_user")],
        [InlineKeyboardButton("🚫 معاقبة عضو", callback_data="sub_punish_user"),
         InlineKeyboardButton("📛 المحظورون", callback_data="sub_banned_list")],
        # — التواصل والنظام —
        [InlineKeyboardButton("✉️ مراسلة عضو", callback_data="msg_direct_user"),
         InlineKeyboardButton("📢 بث جماعي", callback_data="sub_broadcast")],
        [InlineKeyboardButton("📨 تذكير غير النشطين", callback_data="sub_remind_inactive"),
         InlineKeyboardButton("💾 نسخة احتياطية", callback_data="sub_backup_channel")],
        [InlineKeyboardButton("⭐ قائمة الاستثناء", callback_data="sub_exempt")],
    ])

    text = (
        f"💎 **إعدادات الاشتراك**\n\n"
        f"⏱️ الحد المجاني: **{max_duration}** دقيقة\n"
        f"💰 الأسعار: شهري {price_m} · سنوي {price_y}\n"
        f"📅 المدد: 30 · 365 يوم\n"
        f"🔞 الحظر الإباحي: {'✅ مُفعّل' if adult_on else '❌ متوقف'}\n"
        f"⏯️ التحميل: {'▶️ يعمل' if dl_on else '⏸️ متوقف'}\n\n"
        f"👥 **الأعضاء: {total_display}**{' ✅' if real_alive is not None else ''}\n"
        f"💎 مشتركون: {stats['subscribed']} · 🆓 عاديون: {free_display}\n"
        f"👨 رجال: {gs['male']} · 👩 نساء: {gs['female']}\n"
        f"🇸🇦 عربي: {lc['ar']} · 🇬🇧 إنجليزي: {lc['en']}\n"
        f"{db_note}"
        f"{_last_realcheck_line()}\n\n"
        f"**اختر الإعداد:**"
    )

    if edit:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.reply_text(text, reply_markup=keyboard)


@app.on_callback_query(filters.regex(r'^sub_'))
async def handle_subscription_settings(client, callback_query):
    """معالج إعدادات الاشتراك"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    action = callback_query.data[len('sub_'):]  # إزالة البادئة فقط (لا كل التكرارات)

    if action == 'realcheck':
        # فحص فوري (بعدّاد حيّ) يحذف من حظر البوت، ثم نحدّث اللوحة بالأرقام الحقيقية
        await callback_query.answer("🔍 بدأ الفحص… تابع العدّاد في الأسفل")
        await run_realusers_check(client, callback_query.message)
        try:
            await subscription_settings_panel(
                client, callback_query.message,
                user_id=callback_query.from_user.id, edit=True
            )
        except Exception:
            pass
        return

    if action == 'toggle_downloads':
        new_state = '0' if downloads_enabled() else '1'
        subdb.set_setting('downloads_enabled', new_state)
        await callback_query.answer(
            "▶️ تم تشغيل التحميل للجميع" if new_state == '1'
            else "⏸️ تم إيقاف التحميل للجميع (الأدمن غير متأثر)",
            show_alert=True
        )
        await subscription_settings_panel(
            client, callback_query.message,
            user_id=callback_query.from_user.id, edit=True
        )
        return

    if action == 'toggle_adult':
        new_state = '0' if adult_filter_enabled() else '1'
        subdb.set_setting('block_adult_content', new_state)
        await callback_query.answer(
            "🔞 تم تفعيل حظر المحتوى الإباحي" if new_state == '1'
            else "🔞 تم إيقاف حظر المحتوى الإباحي",
            show_alert=True
        )
        # تحديث اللوحة لإظهار الحالة الجديدة
        await subscription_settings_panel(
            client, callback_query.message,
            user_id=callback_query.from_user.id, edit=True
        )
        return

    if action == 'add_domain':
        await callback_query.message.edit_text(
            "➕ **إضافة موقع محظور**\n\n"
            "أرسل اسم نطاق الموقع المراد حظره (مثال: `example.com`).\n"
            "سيُحظر الموقع ونطاقاته الفرعية تلقائياً.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'add_adult_domain'}
        await callback_query.answer()
        return

    if action == 'add_keyword':
        await callback_query.message.edit_text(
            "➕ **إضافة كلمة محظورة**\n\n"
            "أرسل الكلمة المراد حظرها. أي رابط أو عنوان فيديو يحتوي عليها سيُمنع.\n"
            "يمكنك إرسال أكثر من كلمة مفصولة بفواصل.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'add_adult_keyword'}
        await callback_query.answer()
        return

    if action == 'list_blocked':
        text, kb = _blocked_list_view()
        await callback_query.message.edit_text(text, reply_markup=kb)
        await callback_query.answer()
        return

    if action.startswith('deldom_') or action.startswith('delkw_'):
        key = 'adult_custom_domains' if action.startswith('deldom_') else 'adult_custom_keywords'
        try:
            idx = int(action.split('_', 1)[1])
        except (ValueError, IndexError):
            idx = -1
        removed = _remove_from_setting_list(key, idx)
        await callback_query.answer(f"🗑️ حُذف: {removed}" if removed else "تعذّر الحذف")
        text, kb = _blocked_list_view()
        try:
            await callback_query.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        return

    if action == 'clear_blocked':
        subdb.set_setting('adult_custom_domains', '')
        subdb.set_setting('adult_custom_keywords', '')
        await callback_query.answer("🗑️ تم مسح القائمة المخصصة", show_alert=True)
        await subscription_settings_panel(
            client, callback_query.message,
            user_id=callback_query.from_user.id, edit=True
        )
        return

    if action == 'member_question':
        text, kb = _questions_panel_view()
        await callback_query.message.edit_text(text, reply_markup=kb)
        await callback_query.answer()
        return

    if action == 'qadd':
        # الخطوة 1: اختيار الجمهور المستهدف (فئة أو شخص محدّد)
        await callback_query.message.edit_text(
            "➕ **إضافة سؤال — لمن؟**\n\nاختر الجمهور:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 الجميع", callback_data="sub_qaddg_all")],
                [InlineKeyboardButton("👨 رجال", callback_data="sub_qaddg_male"),
                 InlineKeyboardButton("👩 نساء", callback_data="sub_qaddg_female")],
                [InlineKeyboardButton("👤 شخص محدّد", callback_data="sub_qaddg_person")],
                [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")],
            ])
        )
        await callback_query.answer()
        return

    if action == 'qaddg_person':
        # سؤال لشخص محدّد: نطلب الآيدي أو اليوزر
        await callback_query.message.edit_text(
            "👤 **سؤال لشخص محدّد**\n\nأرسل آيدي المستخدم (ID) أو يوزره (@username).",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {
            'waiting_for': 'add_question_person'}
        await callback_query.answer()
        return

    if action == 'qprev':
        # ضغط على زر معاينة (غير فعّال) — تنبيه فقط
        await callback_query.answer("🔎 هذه معاينة — اضغط «✅ إرسال وتفعيل» للتأكيد", show_alert=True)
        return

    if action == 'qsave':
        # تأكيد إضافة السؤال من شاشة المعاينة
        pdata = pending_downloads.get(callback_query.from_user.id)
        if not isinstance(pdata, dict) or pdata.get('waiting_for') != 'confirm_question':
            await callback_query.answer("انتهت الجلسة، ابدأ الإضافة من جديد.", show_alert=True)
            return
        q = pdata.get('q_text', '')
        q_lang = pdata.get('q_lang', 'all')
        q_gender = pdata.get('q_gender', 'all')
        q_target = pdata.get('q_target')
        options = pdata.get('q_options')
        subdb.add_question(q, True, q_lang, q_gender, q_target, options)
        pending_downloads.pop(callback_query.from_user.id, None)
        audience = _question_target_label(q_target, q_gender, q_lang)
        ans_txt = " / ".join(_parse_options(options)) if options else "نعم / لا"
        await callback_query.message.edit_text(
            f"✅ **تمت إضافة السؤال وتفعيله**\n🎯 {audience}\n🔘 الإجابات: {ans_txt}\n\n"
            f"❓ {q}\n\nسيُطلب من العضو المطابق قبل التحميل."
        )
        await callback_query.answer("✅ تم الإرسال")
        return

    if action == 'qcancel':
        # إلغاء الإضافة والرجوع للوحة الأسئلة
        pending_downloads.pop(callback_query.from_user.id, None)
        text, kb = _questions_panel_view()
        await callback_query.message.edit_text(text, reply_markup=kb)
        await callback_query.answer("أُلغيت الإضافة")
        return

    if action.startswith('qaddg_'):
        g = action.split('_', 1)[1]  # all/male/female
        if g not in ('all', 'male', 'female'):
            g = 'all'
        # الخطوة 2: اختيار اللغة المستهدفة
        await callback_query.message.edit_text(
            f"➕ **سؤال للفئة:** {_gender_flag(g)}\n\nالآن اختر اللغة:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 كل اللغات", callback_data=f"sub_qaddl_{g}_all")],
                [InlineKeyboardButton("🇸🇦 العربية", callback_data=f"sub_qaddl_{g}_ar"),
                 InlineKeyboardButton("🇬🇧 الإنجليزية", callback_data=f"sub_qaddl_{g}_en")],
                [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")],
            ])
        )
        await callback_query.answer()
        return

    if action.startswith('qaddl_'):
        # sub_qaddl_<gender>_<lang>
        parts = action.split('_')  # ['qaddl', gender, lang]
        g = parts[1] if len(parts) > 1 and parts[1] in ('all', 'male', 'female') else 'all'
        qlang = parts[2] if len(parts) > 2 and parts[2] in ('all', 'ar', 'en') else 'all'
        await callback_query.message.edit_text(
            f"➕ **سؤال جديد إلى:** {_gender_flag(g)} {_lang_flag(qlang)}\n\n"
            "أرسل الآن نص السؤال.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {
            'waiting_for': 'add_question', 'q_lang': qlang, 'q_gender': g}
        await callback_query.answer()
        return

    if action.startswith('qtoggle_'):
        try:
            qid = int(action.split('_', 1)[1])
        except (ValueError, IndexError):
            qid = None
        if qid:
            current = dict((q[0], q[2]) for q in subdb.get_questions()).get(qid)
            subdb.set_question_enabled(qid, not current)
            await callback_query.answer("تم التحديث")
        text, kb = _questions_panel_view()
        try:
            await callback_query.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        return

    if action.startswith('qdel_'):
        try:
            qid = int(action.split('_', 1)[1])
        except (ValueError, IndexError):
            qid = None
        if qid:
            subdb.delete_question(qid)
            await callback_query.answer("🗑️ حُذف السؤال")
        text, kb = _questions_panel_view()
        try:
            await callback_query.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        return

    if action == 'banned_list':
        text, kb = _banned_list_view()
        await callback_query.message.edit_text(text, reply_markup=kb)
        await callback_query.answer()
        return

    if action == 'exempt':
        await show_exempt_panel(client, callback_query)
        return

    if action == 'exempt_add':
        await callback_query.message.edit_text(
            "⭐ **إضافة عضو لقائمة الاستثناء**\n\n"
            "أرسل **User ID** أو **@username** للعضو.\n\n"
            "**أمثلة:**\n• `123456789`\n• `@username`\n\n"
            "بعد الإضافة: لن يصله أي بث أو تذكير، ويُعفى من الاشتراك الإجباري.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'exempt_add'}
        await callback_query.answer()
        return

    if action.startswith('exemptdel_'):
        try:
            uid = int(action.replace('exemptdel_', ''))
        except ValueError:
            uid = None
        if uid and _remove_exempt(uid):
            await callback_query.answer(f"✅ حُذف {uid} من قائمة الاستثناء")
        else:
            await callback_query.answer("ℹ️ ليس في القائمة")
        await show_exempt_panel(client, callback_query)
        return

    if action == 'exempt_send':
        ids = _exempt_ids()
        if not ids:
            await callback_query.answer("ℹ️ القائمة فارغة", show_alert=True)
            return
        await callback_query.message.edit_text(
            f"📨 **إرسال للمستثنين فقط** ({len(ids)} عضو)\n\n"
            "هذه الرسالة تصل **فقط** لأعضاء قائمة الاستثناء — "
            "لن يصل شيء لبقية الأعضاء.\n\n"
            "أرسل الآن نص الرسالة:",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {
            'waiting_for': 'broadcast_message', 'target_exempt': True}
        await callback_query.answer()
        return

    if action == 'remind_inactive':
        days = int(os.getenv("REMINDER_INACTIVE_DAYS", "7"))
        exempt = _exempt_ids()
        inactive = [x for x in subdb.get_inactive_users(days) if x[0] not in exempt]
        total_members = _current_member_count()
        rows = []
        if inactive:
            rows.append([InlineKeyboardButton(
                f"📨 إرسال للخاملين ({len(inactive)})", callback_data="sub_do_remind")])
        # زر إرسال التذكير لكل الأعضاء (بلا فلتر خمول، عدا قائمة الاستثناء)
        rows.append([InlineKeyboardButton(
            f"📢 إرسال للجميع ({total_members})", callback_data="sub_do_remind_all")])
        rows.append([InlineKeyboardButton(
            f"⭐ قائمة الاستثناء ({len(exempt)})", callback_data="sub_exempt")])
        rows.append([InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")])
        body = (
            f"📨 **تذكير الأعضاء**\n\n"
            f"👥 الأعضاء: **{total_members}**\n"
            f"⏳ الخمول: ≥ {days} أيام\n"
            f"😴 غير النشطين: **{len(inactive)}** عضو\n\n"
            "يُرسل لكل عضو تذكيراً **بلغته**، ويُحذف تذكيره السابق تلقائياً "
            "(يبقى الأحدث فقط).\n\n"
            "• **للخاملين:** فقط من لم يحمّل منذ فترة.\n"
            "• **للجميع:** كل الأعضاء.\n"
            "• ⭐ أعضاء قائمة الاستثناء لا يصلهم أي تذكير."
        )
        await callback_query.message.edit_text(
            body, reply_markup=InlineKeyboardMarkup(rows))
        await callback_query.answer()
        return

    if action in ('do_remind', 'do_remind_all'):
        exempt = _exempt_ids()
        if action == 'do_remind_all':
            targets = [x for x in subdb.get_all_users_for_reminder()
                       if x[0] not in exempt]
            scope = "لكل الأعضاء"
        else:
            days = int(os.getenv("REMINDER_INACTIVE_DAYS", "7"))
            targets = [x for x in subdb.get_inactive_users(days)
                       if x[0] not in exempt]
            scope = "للأعضاء غير النشطين"
        progress = await callback_query.message.edit_text(
            f"📤 جاري إرسال التذكير {scope} ({len(targets)})..."
        )
        sent_n, fail_n, removed_n = await _send_reminder_batch(client, progress, targets)
        await progress.edit_text(
            f"✅ **اكتمل إرسال التذكير {scope}**\n\n"
            f"✅ وصلت: {sent_n}\n❌ فشلت: {fail_n}\n🗑️ حُذفوا (غادروا): {removed_n}"
        )
        await callback_query.answer()
        return

    if action == 'backup_channel':
        await callback_query.answer("⏳ جاري النسخ ورفعه للقناة...", show_alert=False)
        ok = await _send_backup_to_channel(client, notify_chat=callback_query.from_user.id)
        if ok:
            await callback_query.message.reply_text(
                "✅ تم رفع نسخة احتياطية كاملة لقناة النسخ الاحتياطي.\n"
                "♻️ للاستعادة لاحقاً: أعد إرسال الملف من القناة إلى البوت."
            )
        return

    if action.startswith('unbanlist_'):
        try:
            uid = int(action.split('_', 1)[1])
        except (ValueError, IndexError):
            uid = None
        if uid and subdb.admin_unban(uid):
            await callback_query.answer(f"✅ رُفع الحظر عن {uid}")
            try:
                await client.send_message(uid, t('pledge_accepted', subdb.get_user_language(uid)))
            except Exception:
                pass
        else:
            await callback_query.answer("ℹ️ غير محظور")
        text, kb = _banned_list_view()
        try:
            await callback_query.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        return

    if action == 'punish_user':
        await callback_query.message.edit_text(
            "🚫 **معاقبة عضو**\n\n"
            "أرسل معرّف العضو (ID رقمي) أو `@username`.\n"
            "ثم اختر: 🔨 حظر دائم / ⚠️ تحذير / ✅ رفع الحظر.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'punish_user_id'}
        await callback_query.answer()
        return

    if action == 'fsub':
        await show_forced_sub_panel(client, callback_query)
        return

    if action == 'fsub_toggle':
        new_state = '0' if forced_sub_enabled() else '1'
        subdb.set_setting('forced_sub_enabled', new_state)
        await callback_query.answer(
            "✅ تم تفعيل الاشتراك الإجباري" if new_state == '1'
            else "❌ تم إيقاف الاشتراك الإجباري",
            show_alert=True
        )
        await show_forced_sub_panel(client, callback_query)
        return

    if action == 'fsub_add':
        await callback_query.message.edit_text(
            "➕ **إضافة قناة/قروب للاشتراك الإجباري**\n\n"
            "أرسل أيّاً مما يلي:\n"
            "• معرّف عام `@username`\n"
            "• رابط القناة/القروب (يشمل روابط الدعوة الخاصة)\n"
            "• أو وجّه لي رسالة من القناة/القروب\n\n"
            "💡 إن كان البوت مشرفاً فسيتحقق فعلياً من الاشتراك، وإلا سيظهر "
            "الزر للإعلان ويُحتسب عند ضغط «تحقق». (يُكتشف تلقائياً)\n\n"
            "🔒 **لقروب/قناة خاصة:** اجعل البوت مشرفاً فيها بصلاحية "
            "«دعوة المستخدمين» ثم **وجّه لي رسالة منها** — أوّلد رابط الدعوة "
            "تلقائياً ويُفرض الاشتراك بتحقق حقيقي.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'add_forced_channel'}
        await callback_query.answer()
        return

    if action.startswith('fsubdel_'):
        try:
            row_id = int(action.replace('fsubdel_', ''))
            subdb.remove_forced_channel(row_id)
            await callback_query.answer("🗑️ تم حذف القناة", show_alert=True)
        except Exception:
            await callback_query.answer("❌ تعذّر الحذف", show_alert=True)
        await show_forced_sub_panel(client, callback_query)
        return

    if action == 'set_duration':
        max_duration = subdb.get_max_duration()
        daily_limit = subdb.get_daily_limit()
        referral_minutes = subdb.get_referral_minutes()

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱️ تغيير الحد الزمني", callback_data="change_time_limit")],
            [InlineKeyboardButton("🔢 تغيير الحد اليومي", callback_data="change_daily_limit")],
            [InlineKeyboardButton("🎁 دقائق مكافأة الدعوة", callback_data="change_referral_minutes")],
            [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]
        ])

        await callback_query.message.edit_text(
            "⚙️ **تحديد المدة القصوى**\n\n"
            f"🕒 **الحد الزمني لغير المشتركين:** {max_duration} دقيقة\n"
            f"🔁 **الحد اليومي المسموح به:** {daily_limit} مرات\n"
            f"🎁 **دقائق تُضاف لكل دعوة ناجحة:** {referral_minutes} دقيقة\n\n"
            "💡 **ملاحظات:**\n"
            "• هذه القيود تطبق فقط على المستخدمين غير المشتركين\n"
            "• المشتركون VIP لديهم حرية كاملة بلا قيود\n"
            "• كل صديق ينضم عبر رابط المستخدم يرفع حدّ مدته دائماً بهذا المقدار\n\n"
            "**اختر الإجراء المطلوب:**",
            reply_markup=keyboard
        )
        
    elif action == 'set_price':
        pm, py = _plan_prices()
        pm_txt = "مجاني" if _price_value(pm) <= 0 else f"${pm}"
        py_txt = "مجاني" if _price_value(py) <= 0 else f"${py}"
        await callback_query.message.edit_text(
            "💰 **أسعار الاشتراك**\n\n"
            f"📅 الشهري (30 يوم): **{pm_txt}**\n"
            f"🗓️ السنوي (365 يوم): **{py_txt}**\n\n"
            "اضغط لتعديل السعر (أرسل 0 لجعله مجانياً):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📅 تعديل الشهري ({pm_txt})", callback_data="sub_setprice_monthly")],
                [InlineKeyboardButton(f"🗓️ تعديل السنوي ({py_txt})", callback_data="sub_setprice_yearly")],
                [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")],
            ])
        )

    elif action == 'setprice_monthly':
        await callback_query.message.edit_text(
            "📅 **سعر الاشتراك الشهري**\n\n"
            "أرسل السعر بالدولار (مثلاً: 10)، أو **0** لجعله مجانياً.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'price_monthly'}

    elif action == 'setprice_yearly':
        await callback_query.message.edit_text(
            "🗓️ **سعر الاشتراك السنوي**\n\n"
            "أرسل السعر بالدولار (مثلاً: 100)، أو **0** لجعله مجانياً.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'price_yearly'}

    elif action == 'view_subscribers':
        subscribers = subdb.get_all_subscribers()
        
        if not subscribers:
            await callback_query.message.edit_text(
                "📝 **لا يوجد مشتركون حالياً**",
                reply_markup=_sub_settings_back_kb()
            )
            return
        
        text = "👥 <b>قائمة المشتركين</b>\n\n"

        for idx, sub in enumerate(subscribers[:20], 1):  # أول 20 مشترك
            user_id, username, first_name, end_date, method = sub
            username_str = f"@{html.escape(username)}" if username else "لا يوجد"

            # حساب الأيام المتبقية
            if end_date:
                # PostgreSQL يُرجع datetime object مباشرة، بينما SQLite يُرجع string
                if isinstance(end_date, str):
                    end_dt = datetime.fromisoformat(end_date)
                else:
                    end_dt = end_date
                days_left = (end_dt - datetime.now()).days
                days_str = f"{days_left} يوم" if days_left > 0 else "منتهي"
            else:
                days_str = "مدى الحياة"

            text += f"{idx}. {_user_link(user_id, first_name)} ({username_str})\n"
            text += f"   🆔 <code>{user_id}</code> | ⏳ {days_str}\n\n"

        text += f"\n📊 <b>إجمالي المشتركين:</b> {len(subscribers)}\n"
        text += "💡 اضغط الاسم (الأزرق) لفتح محادثة المشترك."

        await callback_query.message.edit_text(
            text, reply_markup=_sub_settings_back_kb(), parse_mode=enums.ParseMode.HTML)
        
    elif action == 'pending_payments':
        payments = subdb.get_pending_payments()
        
        if not payments:
            await callback_query.message.edit_text(
                "✅ **لا توجد دفوعات معلقة**",
                reply_markup=_sub_settings_back_kb()
            )
            return
        
        text = "💳 **الدفوعات المعلقة**\n\n"
        
        for payment in payments[:10]:  # أول 10 دفوعات
            payment_id, user_id, username, first_name, method, amount, proof_id, created = payment
            username_str = f"@{username}" if username else "لا يوجد"
            name = first_name or "مستخدم"
            
            text += f"━━━━━━━━━━━━━━\n"
            text += f"🔖 **#{payment_id}**\n"
            text += f"👤 {name} ({username_str})\n"
            text += f"💰 ${amount} | 💳 {method}\n\n"
        
        text += f"\n📊 **إجمالي المعلقة:** {len(payments)}"

        await callback_query.message.edit_text(text, reply_markup=_sub_settings_back_kb())
    
    elif action == 'member_stats':
        stats = subdb.get_user_stats()
        all_users = subdb.get_all_users()
        
        gs = subdb.get_gender_stats()
        lc = subdb.get_language_counts()
        current = _current_member_count()
        free_now = max(0, current - stats['subscribed'])
        db_note = (f"📦 <b>في القاعدة:</b> {stats['total']} (للتنظيف)\n"
                   if current != stats['total'] else "")
        text = "📊 <b>إحصائيات الأعضاء</b>\n\n"
        text += f"👥 <b>الأعضاء:</b> {current}\n"
        text += f"💎 <b>المشتركون:</b> {stats['subscribed']}\n"
        text += f"🆓 <b>العاديون:</b> {free_now}\n"
        text += db_note
        text += f"👤 <b>الجنس:</b> 👨 {gs['male']} | 👩 {gs['female']}\n"
        text += f"🌐 <b>اللغة:</b> 🇸🇦 {lc['ar']} | 🇬🇧 {lc['en']}\n\n"

        # عرض بعض المشتركين مع الأيام المتبقية (الاسم قابل للضغط)
        if stats['subscribed'] > 0:
            text += "━━━━━━━━━━━━━━━━\n"
            text += "<b>المشتركون الحاليون:</b>\n\n"

            count = 0
            for user in all_users:
                user_id, username, first_name, is_subscribed, subscription_end = user
                if is_subscribed:
                    days_left = subdb.get_days_remaining(user_id)
                    text += f"• {_user_link(user_id, first_name)}: {days_left} يوم متبقية\n"
                    count += 1
                    if count >= 10:  # أول 10 مشتركين
                        break
            text += "\n💡 اضغط الاسم (الأزرق) لفتح محادثة المشترك."

        await callback_query.message.edit_text(
            text, reply_markup=_sub_settings_back_kb(), parse_mode=enums.ParseMode.HTML)
    
    elif action == 'recent_users':
        users = subdb.get_recent_users(50)
        
        if not users:
            await callback_query.message.edit_text("📝 **لا يوجد مستخدمون**")
            return
        
        text = "📊 <b>آخر 50 مستخدم</b>\n\n"

        for idx, user in enumerate(users[:50], 1):
            user_id, username, first_name, is_subscribed = user
            username_str = f"@{html.escape(username)}" if username else "لا يوجد"
            status = "💎" if is_subscribed else "🆓"

            text += f"{idx}. {status} {_user_link(user_id, first_name)} ({username_str})\n"
            text += f"   🆔 <code>{user_id}</code>\n\n"

        text += f"\n📊 <b>إجمالي المستخدمين:</b> {len(users)}\n\n"
        text += ("💡 اضغط اسم العضو (الأزرق) لفتح ملفه. وإن لم يفتح (عضو بلا يوزر):\n"
                 "انسخ الـ🆔 (اضغط عليه) ثم استخدم زر «✉️ مراسلة عضو» لمراسلته عبر "
                 "البوت — يعمل مع الجميع.")

        await callback_query.message.edit_text(
            text, reply_markup=_sub_settings_back_kb(), parse_mode=enums.ParseMode.HTML)
    
    elif action == 'promote_user':
        await callback_query.message.edit_text(
            "✏️ **ترقية عضو يدوياً**\n\n"
            "أرسل User ID أو Username للعضو المراد ترقيته\n\n"
            "مثال: `123456789` أو `@username`",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'promote_user_id'}
    
    elif action == 'demote_user':
        await callback_query.message.edit_text(
            "❌ **إلغاء ترقية عضو**\n\n"
            "أرسل User ID أو Username للعضو المراد إلغاء ترقيته\n\n"
            "مثال: `123456789` أو `@username`",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'demote_user_id'}
    
    elif action == 'search_user':
        await callback_query.message.edit_text(
            "🔍 **بحث عن عضو**\n\n"
            "أرسل User ID أو Username للبحث عنه\n\n"
            "مثال: `123456789` أو `@username`",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'search_user_id'}
    
    elif action == 'broadcast':
        # عرض شاشة اختيار نوع الإرسال
        exempt_n = len(_exempt_ids())
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📧 إرسال لجميع المستخدمين", callback_data="msg_broadcast_all")],
            [InlineKeyboardButton("👤 إرسال لمستخدم محدد", callback_data="msg_direct_user")],
            [InlineKeyboardButton(f"⭐ قائمة الاستثناء ({exempt_n})", callback_data="sub_exempt")],
            [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]
        ])

        stats = subdb.get_user_stats()
        exempt_note = (f"\n⭐ **مستثنون من البث:** {exempt_n}" if exempt_n else "")
        await callback_query.message.edit_text(
            "📢 **نظام الإرسال الجماعي**\n\n"
            f"👥 **عدد المستخدمين:** {stats['total']}\n"
            f"💎 **المشتركون:** {stats['subscribed']}\n"
            f"🆓 **العاديون:** {stats['free']}"
            f"{exempt_note}\n\n"
            "**اختر نوع الإرسال:**",
            reply_markup=keyboard
        )
    
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^(change_time_limit|change_daily_limit|change_referral_minutes|back_to_sub_settings)$'))
async def handle_duration_actions(client, callback_query):
    """معالج إعدادات المدة والحد اليومي"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return

    action = callback_query.data
    user_id = callback_query.from_user.id

    if action == 'change_time_limit':
        await callback_query.message.edit_text(
            "⏱️ **تغيير الحد الزمني**\n\n"
            f"القيمة الحالية: {subdb.get_max_duration()} دقيقة\n\n"
            "أرسل الحد الزمني الجديد بالدقائق\n"
            "(مثلاً: 60 لساعة واحدة، 120 لساعتين)"
        )
        pending_downloads[user_id] = {'waiting_for': 'max_duration'}

    elif action == 'change_referral_minutes':
        await callback_query.message.edit_text(
            "🎁 **دقائق مكافأة الدعوة**\n\n"
            f"القيمة الحالية: {subdb.get_referral_minutes()} دقيقة لكل دعوة\n\n"
            "أرسل العدد الجديد من الدقائق التي تُضاف لحدّ مدة الفيديو مقابل كل صديق ينضم عبر رابط المستخدم\n"
            "(مثلاً: 5 → كل دعوة ترفع حدّه +5 دقائق دائماً)\n"
            "أرسل 0 لتعطيل مكافأة المدة."
        )
        pending_downloads[user_id] = {'waiting_for': 'referral_minutes'}
    
    elif action == 'change_daily_limit':
        current_limit = subdb.get_daily_limit()
        
        # عرض الحد الحالي
        if current_limit == -1:
            current_text = "♾️ غير محدود"
        else:
            current_text = f"{current_limit} مرات"
        
        # لوحة أزرار الاختيار السريع
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("3️⃣ 3 تحميلات", callback_data="set_daily_limit_3"),
             InlineKeyboardButton("5️⃣ 5 تحميلات", callback_data="set_daily_limit_5")],
            [InlineKeyboardButton("🔟 10 تحميلات", callback_data="set_daily_limit_10"),
             InlineKeyboardButton("2️⃣0️⃣ 20 تحميلة", callback_data="set_daily_limit_20")],
            [InlineKeyboardButton("♾️ غير محدود", callback_data="set_daily_limit_unlimited")],
            [InlineKeyboardButton("✏️ إدخال يدوي", callback_data="set_daily_limit_manual")],
            [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]
        ])
        
        await callback_query.message.edit_text(
            f"🔢 **تغيير الحد اليومي**\n\n"
            f"القيمة الحالية: {current_text}\n\n"
            "اختر الحد اليومي للتحميلات:",
            reply_markup=keyboard
        )
    
    elif action == 'back_to_sub_settings':
        # إلغاء أي إدخال معلّق ثم العودة لشاشة إعدادات الاشتراك
        pending_downloads.pop(user_id, None)
        await subscription_settings_panel(
            client, callback_query.message,
            user_id=callback_query.from_user.id, edit=True
        )
    
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^msg_'))
async def handle_message_type(client, callback_query):
    """معالج اختيار نوع الرسالة"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    user_id = callback_query.from_user.id
    action = callback_query.data.replace('msg_', '')
    
    if action == 'broadcast_all':
        # الخطوة 1: اختيار الجنس المستهدف
        await callback_query.message.edit_text(
            "📢 **بث جماعي — لأي جنس؟**\n\nاختر فئة الجنس:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 الجميع", callback_data="msg_bcg_all")],
                [InlineKeyboardButton("👨 رجال", callback_data="msg_bcg_male"),
                 InlineKeyboardButton("👩 نساء", callback_data="msg_bcg_female")],
                [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")],
            ])
        )

    elif action.startswith('bcg_'):
        g = action.split('_', 1)[1]  # all/male/female
        if g not in ('all', 'male', 'female'):
            g = 'all'
        # الخطوة 2: اختيار اللغة المستهدفة (مع عدد كل فئة ضمن هذا الجنس،
        # بعد استبعاد قائمة الاستثناء حتى يطابق العدد المرسَل فعلاً)
        all_n = len(_broadcast_targets(g, 'all'))
        ar_n = len(_broadcast_targets(g, 'ar'))
        en_n = len(_broadcast_targets(g, 'en'))
        await callback_query.message.edit_text(
            f"📢 **بث إلى:** {_gender_flag(g)}\n\nاختر اللغة:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🌐 كل اللغات ({all_n})", callback_data=f"msg_bcl_{g}_all")],
                [InlineKeyboardButton(f"🇸🇦 العربية ({ar_n})", callback_data=f"msg_bcl_{g}_ar"),
                 InlineKeyboardButton(f"🇬🇧 الإنجليزية ({en_n})", callback_data=f"msg_bcl_{g}_en")],
                [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")],
            ])
        )

    elif action.startswith('bcl_'):
        parts = action.split('_')  # ['bcl', gender, lang]
        g = parts[1] if len(parts) > 1 and parts[1] in ('all', 'male', 'female') else 'all'
        tlang = parts[2] if len(parts) > 2 and parts[2] in ('all', 'ar', 'en') else 'all'
        count = len(_broadcast_targets(g, tlang))
        # الخطوة 3: شكل الرسالة — نظيفة (بلا أزرار نعم/لا) أو مع أزرار تفاعل
        # تُغذّي الإحصائية الحية. النظيفة أهدأ للعضو، والتفاعلية تقيس التجاوب.
        await callback_query.message.edit_text(
            f"📢 **بث إلى:** {_gender_flag(g)} {_lang_flag(tlang)} ({count} مستخدم)\n\n"
            "**اختر شكل الرسالة:**\n\n"
            "✨ **نظيفة** — نص فقط + زر رد (مرتّبة وهادئة)\n"
            "📊 **تفاعلية** — مع أزرار ✅/❌ وإحصائية حية لمن تفاعل",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ رسالة نظيفة", callback_data=f"msg_bcp_{g}_{tlang}_clean")],
                [InlineKeyboardButton("📊 مع أزرار تفاعل", callback_data=f"msg_bcp_{g}_{tlang}_poll")],
                [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")],
            ])
        )

    elif action.startswith('bcp_'):
        parts = action.split('_')  # ['bcp', gender, lang, mode]
        g = parts[1] if len(parts) > 1 and parts[1] in ('all', 'male', 'female') else 'all'
        tlang = parts[2] if len(parts) > 2 and parts[2] in ('all', 'ar', 'en') else 'all'
        with_poll = len(parts) > 3 and parts[3] == 'poll'
        count = len(_broadcast_targets(g, tlang))
        shape = "📊 تفاعلية (نعم/لا + إحصائية)" if with_poll else "✨ نظيفة"
        await callback_query.message.edit_text(
            f"📢 **بث إلى:** {_gender_flag(g)} {_lang_flag(tlang)} ({count} مستخدم)\n"
            f"**الشكل:** {shape}\n\n"
            "أرسل الآن نص الرسالة التي تريد بثّها.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[user_id] = {
            'waiting_for': 'broadcast_message', 'target_lang': tlang,
            'target_gender': g, 'with_poll': with_poll}

    elif action == 'direct_user':
        await callback_query.message.edit_text(
            "👤 **إرسال رسالة لمستخدم محدد**\n\n"
            "أرسل **User ID** أو **Username** للمستخدم المراد مراسلته\n\n"
            "**أمثلة:**\n"
            "• `123456789` (User ID)\n"
            "• `@username` (Username)",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[user_id] = {'waiting_for': 'direct_msg_user_id'}
    
    elif action == 'cancel':
        await callback_query.message.edit_text("❌ **تم الإلغاء**")
        if user_id in pending_downloads:
            del pending_downloads[user_id]

    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^reply_msg_'))
async def handle_reply_button(client, callback_query):
    """زر الرد: يضع الضاغط في حالة انتظار كتابة رد ليُرسَل للطرف الآخر"""
    clicker_id = callback_query.from_user.id
    try:
        target_id = int(callback_query.data.replace('reply_msg_', ''))
    except (ValueError, TypeError):
        await callback_query.answer()
        return

    # تسجيل أن هذا المستخدم سيكتب رداً موجّهاً إلى target_id
    conversation_state[clicker_id] = target_id

    lang = subdb.get_user_language(clicker_id)
    prompt = t('type_your_reply', lang)
    # نرسل التنبيه في الخاص (يعمل حتى لو ضُغط الزر داخل قناة)
    try:
        await client.send_message(clicker_id, prompt)
    except Exception:
        try:
            await callback_query.message.reply_text(prompt)
        except Exception:
            pass
    await callback_query.answer("✍️ اكتب ردّك في خاص البوت", show_alert=True)


@app.on_message(
    filters.text & ~filters.regex(r'^/') & ~filters.regex(r'https?://'),
    group=-2
)
async def handle_conversation_reply(client, message):
    """معالج عالي الأولوية لتمرير الردود بين الأدمن والأعضاء عبر البوت.

    إذا كان المرسل ضغط زر "رد" مسبقاً، نمرّر رسالته للطرف الآخر مع زر رد جديد،
    ثم نوقف انتشار الرسالة لبقية المعالجات.
    """
    if not message.from_user:
        return

    sender_id = message.from_user.id
    if sender_id not in conversation_state:
        return  # ليس في وضع رد؛ اترك المعالجات الأخرى تعمل

    target_id = conversation_state.pop(sender_id)
    reply_text = message.text.strip()
    admin_id = os.getenv("ADMIN_ID")
    sender_is_admin = (str(sender_id) == admin_id)

    target_lang = subdb.get_user_language(target_id)

    sender_lang = subdb.get_user_language(sender_id)
    # زر "رد على العضو" دائماً يشير للمرسل الحالي (العضو) ليبقى في محادثته
    member_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(t('reply_button', target_lang), callback_data=f"reply_msg_{sender_id}")
    ]])

    if sender_is_admin:
        # الأدمن يرد على عضو → يصل العضو في الخاص، وزر الرد يعيده للقناة
        body = f"{t('direct_message_prefix', target_lang)}\n\n{reply_text}"
        try:
            await client.send_message(chat_id=target_id, text=body, reply_markup=member_kb)
            await message.reply_text(t('reply_sent', sender_lang))
        except Exception as e:
            logger.error(f"❌ فشل إرسال رد الأدمن إلى {target_id}: {e}")
            await message.reply_text(t('reply_failed', sender_lang))
    else:
        # عضو يرد → ننشر رسالته في قناة الأعضاء (تبقى محادثة كل عضو منفصلة هناك)
        sender_name = message.from_user.first_name or "عضو"
        channel_id = get_channel_id('SURVEY_CHANNEL_ID')
        if channel_id:
            ch_body = (
                f"💬 <b>رسالة من عضو</b>\n{_member_header_html(message.from_user)}"
                f"\n\n{html.escape(reply_text)}"
            )
            try:
                await client.send_message(channel_id, ch_body,
                                          parse_mode=enums.ParseMode.HTML, reply_markup=member_kb)
                await message.reply_text(t('reply_sent', sender_lang))
            except Exception as e:
                logger.error(f"❌ فشل نشر رد العضو في القناة: {e}")
                await message.reply_text(t('reply_failed', sender_lang))
        else:
            # لا توجد قناة → السلوك القديم: يصل خاص الأدمن
            body = (f"{t('member_reply_prefix', target_lang, name=sender_name, user_id=sender_id)}"
                    f"\n\n{reply_text}")
            try:
                await client.send_message(chat_id=target_id, text=body, reply_markup=member_kb)
                await message.reply_text(t('reply_sent', sender_lang))
            except Exception as e:
                logger.error(f"❌ فشل تمرير رد العضو إلى {target_id}: {e}")
                await message.reply_text(t('reply_failed', sender_lang))

    raise StopPropagation


def _broadcast_stats_kb(bid):
    """لوحة الإحصائية: زر مراسلة عبر البوت لكل عضو صوّت (يعمل حتى بلا username) + تحديث"""
    rows = []
    p = broadcast_polls.get(bid)
    if p:
        voters = list(p['yes'].items()) + list(p['no'].items())
        for uid, name in voters[:16]:  # حدّ معقول لتفادي ازدحام الأزرار
            rows.append([InlineKeyboardButton(
                f"✉️ {str(name)[:20]}",
                callback_data=f"dm_{uid}"
            )])
    rows.append([InlineKeyboardButton("🔄 تحديث الإحصائية", callback_data=f"bcref_{bid}")])
    return InlineKeyboardMarkup(rows)


@app.on_callback_query(filters.regex(r'^dm_'))
async def handle_dm_button(client, callback_query):
    """مراسلة عضو عبر البوت مباشرة (للأدمن) — يعمل حتى لو لم يكن للعضو username"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    try:
        target = int(callback_query.data[len('dm_'):])
    except ValueError:
        await callback_query.answer()
        return

    # ضع الأدمن في وضع كتابة رسالة موجّهة لهذا العضو عبر البوت
    conversation_state[callback_query.from_user.id] = target
    await callback_query.message.reply_text(
        "✍️ **اكتب رسالتك الآن** وسأرسلها للعضو عبر البوت:"
    )
    await callback_query.answer()


def _html_escape(s):
    """تهريب رموز HTML لتفادي كسر التنسيق"""
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _broadcast_stats_text(bid):
    """نص الإحصائية الحيّة (HTML) مع أسماء قابلة للنقر تفتح محادثة العضو"""
    p = broadcast_polls.get(bid)
    if not p:
        return "⌛ انتهت صلاحية هذه الإحصائية."

    yes, no = p['yes'], p['no']
    total = p.get('total', 0)
    pending = max(total - len(yes) - len(no), 0)

    def name_link(uid, name):
        # اسم أزرق قابل للنقر يفتح ملف/محادثة العضو
        return f'• <a href="tg://user?id={uid}">{_html_escape(name)}</a>'

    lines = [
        "📊 <b>إحصائية البث المباشر</b>\n",
        f"📨 وصلت إلى: <b>{total}</b>",
        f"✅ نعم (متواجد): <b>{len(yes)}</b>",
        f"❌ لا: <b>{len(no)}</b>",
        f"⏳ لم يتفاعلوا بعد: <b>{pending}</b>",
    ]

    if yes:
        lines.append("\n✅ <b>من قال نعم:</b>")
        for uid, name in list(yes.items())[:15]:
            lines.append(name_link(uid, name))
        if len(yes) > 15:
            lines.append(f"… و{len(yes) - 15} غيرهم")

    if no:
        lines.append("\n❌ <b>من قال لا:</b>")
        for uid, name in list(no.items())[:15]:
            lines.append(name_link(uid, name))
        if len(no) > 15:
            lines.append(f"… و{len(no) - 15} غيرهم")

    return "\n".join(lines)


async def _update_broadcast_stats(client, bid, force=False):
    """تحديث رسالة الإحصائية للأدمن مع تقييد بسيط لتفادي flood"""
    p = broadcast_polls.get(bid)
    if not p or not p.get('stats_msg_id'):
        return
    now = time.time()
    if not force and (now - p.get('last_edit', 0) < 1.0):
        return
    p['last_edit'] = now
    try:
        await client.edit_message_text(
            chat_id=p['stats_chat'],
            message_id=p['stats_msg_id'],
            text=_broadcast_stats_text(bid),
            reply_markup=_broadcast_stats_kb(bid),
            parse_mode=enums.ParseMode.HTML
        )
    except Exception:
        pass  # MessageNotModified أو flood مؤقت — يُحدّث في الضغطة التالية


@app.on_callback_query(filters.regex(r'^bc(yes|no|ref)_'))
async def handle_broadcast_vote(client, callback_query):
    """تسجيل تفاعل العضو (نعم/لا) وتحديث الإحصائية الحيّة للأدمن"""
    data = callback_query.data
    if data.startswith('bcyes_'):
        kind, bid_str = 'yes', data[len('bcyes_'):]
    elif data.startswith('bcno_'):
        kind, bid_str = 'no', data[len('bcno_'):]
    elif data.startswith('bcref_'):
        kind, bid_str = 'ref', data[len('bcref_'):]
    else:
        await callback_query.answer()
        return

    try:
        bid = int(bid_str)
    except ValueError:
        await callback_query.answer()
        return

    p = broadcast_polls.get(bid)
    if not p:
        await callback_query.answer("⌛ انتهت صلاحية هذا الاستبيان")
        return

    uid = callback_query.from_user.id
    lang = subdb.get_user_language(uid)

    # زر التحديث اليدوي (للأدمن)
    if kind == 'ref':
        if is_admin(uid):
            await _update_broadcast_stats(client, bid, force=True)
        await callback_query.answer("🔄 تم التحديث")
        return

    name = callback_query.from_user.first_name or "مستخدم"
    if kind == 'yes':
        p['no'].pop(uid, None)
        p['yes'][uid] = name
        await callback_query.answer(t('vote_yes_ack', lang))
    else:
        p['yes'].pop(uid, None)
        p['no'][uid] = name
        await callback_query.answer(t('vote_no_ack', lang))

    # بعد الاختيار: أزِل زرّي نعم/لا وأبقِ زر الرد فقط
    try:
        await callback_query.edit_message_reply_markup(
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    t('reply_button', lang),
                    callback_data=f"reply_msg_{p['admin_id']}"
                )
            ]])
        )
    except Exception:
        pass

    await _update_broadcast_stats(client, bid)


@app.on_callback_query(filters.regex(r'^set_daily_limit_'))
async def handle_set_daily_limit(client, callback_query):
    """معالج اختيار الحد اليومي السريع"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ للمشرفين فقط!", show_alert=True)
        return
    
    user_id = callback_query.from_user.id
    action = callback_query.data.replace('set_daily_limit_', '')
    
    if action == 'manual':
        # الإدخال اليدوي
        await callback_query.message.edit_text(
            "✏️ **إدخال يدوي للحد اليومي**\n\n"
            f"القيمة الحالية: {subdb.get_daily_limit()} مرات\n\n"
            "أرسل الحد اليومي الجديد للتحميلات\n"
            "(مثلاً: 6 لست مرات يومياً، 15 لـ 15 مرة)"
        )
        pending_downloads[user_id] = {'waiting_for': 'daily_limit'}
    
    elif action == 'unlimited':
        # تعيين غير محدود
        subdb.set_daily_limit(-1)
        await callback_query.message.edit_text(
            "✅ **تم تحديث الحد اليومي**\n\n"
            "الحد الجديد: ♾️ غير محدود\n\n"
            "المستخدمون غير المشتركين يمكنهم الآن التحميل بدون قيود يومية."
        )
        logger.info("✅ تم تعيين الحد اليومي إلى: غير محدود")
    
    else:
        # اختيار رقم محدد
        try:
            limit = int(action)
            subdb.set_daily_limit(limit)
            await callback_query.message.edit_text(
                f"✅ **تم تحديث الحد اليومي**\n\n"
                f"الحد الجديد: {limit} مرات في اليوم"
            )
            logger.info(f"✅ تم تعيين الحد اليومي إلى: {limit} مرات")
        except ValueError:
            await callback_query.answer("❌ خطأ في القيمة", show_alert=True)
    
    await callback_query.answer()



@app.on_message(filters.text & ~filters.regex(r'https?://') & ~filters.regex(r'^(🍪|📊|🔔|💎|/)'))
async def handle_admin_input(client, message):
    """معالج إدخالات الأدمن للإعدادات"""
    # رسائل القنوات أو المجهولة ليس لها from_user
    if not message.from_user:
        return
    user_id = message.from_user.id

    if not is_admin(user_id):
        return
    
    if user_id not in pending_downloads:
        return
    
    data = pending_downloads.get(user_id)
    if not isinstance(data, dict) or 'waiting_for' not in data:
        return
    
    waiting_for = data['waiting_for']
    
    try:
        if waiting_for == 'max_duration':
            minutes = int(message.text.strip())
            if minutes < 1:
                await message.reply_text("❌ يجب أن تكون المدة أكبر من 0")
                return
            
            subdb.set_max_duration(minutes)
            await message.reply_text(
                f"✅ **تم تحديث الحد الأقصى**\n\n"
                f"المدة الجديدة: {minutes} دقيقة ({minutes//60} ساعة و {minutes%60} دقيقة)"
            )
            del pending_downloads[user_id]

        elif waiting_for == 'referral_minutes':
            try:
                minutes = int(message.text.strip())
            except ValueError:
                await message.reply_text("❌ أرسل رقماً صحيحاً (مثلاً 5، أو 0 للتعطيل).")
                return
            if minutes < 0:
                await message.reply_text("❌ لا يقبل قيمة سالبة (0 = تعطيل مكافأة المدة).")
                return

            subdb.set_referral_minutes(minutes)
            await message.reply_text(
                f"✅ **تم تحديث دقائق مكافأة الدعوة**\n\n"
                f"القيمة الجديدة: {minutes} دقيقة لكل دعوة ناجحة\n"
                f"(كل صديق ينضم عبر رابط المستخدم يرفع حدّ مدته دائماً +{minutes} دقيقة)"
            )
            del pending_downloads[user_id]

        elif waiting_for == 'daily_limit':
            limit = int(message.text.strip())
            if limit < 1:
                await message.reply_text("❌ يجب أن يكون الحد أكبر من 0")
                return
            
            subdb.set_daily_limit(limit)
            await message.reply_text(
                f"✅ **تم تحديث الحد اليومي**\n\n"
                f"الحد الجديد: {limit} مرات في اليوم"
            )
            del pending_downloads[user_id]
            
        elif waiting_for in ('price_monthly', 'price_yearly', 'subscription_price'):
            try:
                price = float(message.text.strip())
            except ValueError:
                await message.reply_text("❌ أرسل رقماً صحيحاً (مثلاً 10 أو 0 للمجاني).")
                return
            if price < 0:
                await message.reply_text("❌ لا يقبل سعراً سالباً (0 = مجاني).")
                return
            key = 'price_yearly' if waiting_for == 'price_yearly' else 'price_monthly'
            # نظّف الرقم (10.0 -> 10)
            price_str = str(int(price)) if price == int(price) else str(price)
            subdb.set_setting(key, price_str)
            plan_name = 'السنوي' if key == 'price_yearly' else 'الشهري'
            value_txt = "مجاني 🆓" if price <= 0 else f"${price_str}"
            await message.reply_text(
                f"✅ **تم تحديث سعر الاشتراك {plan_name}**\n\nالسعر الجديد: {value_txt}"
            )
            del pending_downloads[user_id]

        elif waiting_for == 'add_adult_domain':
            host = _url_host(message.text.strip()) or message.text.strip()
            added = _add_to_setting_list('adult_custom_domains', host)
            await message.reply_text(
                f"✅ **تم حظر الموقع:** `{host.lower().lstrip('.')}`" if added
                else f"ℹ️ الموقع `{host.lower().lstrip('.')}` محظور مسبقاً أو غير صالح."
            )
            del pending_downloads[user_id]

        elif waiting_for == 'add_adult_keyword':
            words = [w.strip() for w in message.text.split(',') if w.strip()]
            added = [w for w in words if _add_to_setting_list('adult_custom_keywords', w)]
            if added:
                await message.reply_text(
                    "✅ **تمت إضافة الكلمات المحظورة:**\n" + "\n".join(f"• `{w.lower()}`" for w in added)
                )
            else:
                await message.reply_text("ℹ️ لا كلمات جديدة (محظورة مسبقاً أو فارغة).")
            del pending_downloads[user_id]

        elif waiting_for == 'add_question_person':
            raw = (message.text or '').strip().lstrip('@')
            target_uid = None
            if raw.isdigit():
                target_uid = int(raw)
            else:
                u = subdb.find_user_by_username(raw)
                if u:
                    target_uid = u[0]
            if not target_uid:
                await message.reply_text("❌ لم أجد هذا المستخدم. أرسل ID رقمي أو @يوزر صحيح.")
                return
            data['q_target'] = target_uid
            data['q_gender'] = 'all'
            data['q_lang'] = 'all'
            data['waiting_for'] = 'add_question'
            await message.reply_text(
                f"✅ الشخص: `{target_uid}`\n\nالآن أرسل نص السؤال."
            )

        elif waiting_for == 'add_question':
            q = (message.text or '').strip()
            if not q:
                await message.reply_text("❌ السؤال فارغ. أرسل نص السؤال.")
                return
            data['q_text'] = q
            data['waiting_for'] = 'add_question_options'
            await message.reply_text(
                "🔘 **خيارات الإجابة**\n\n"
                "أرسل خيارات الإجابة مفصولة بـ `|`\n"
                "مثال: `موافق | غير موافق | ربما`\n\n"
                "أو أرسل `-` للإبقاء على أزرار «نعم / لا» الافتراضية."
            )

        elif waiting_for == 'add_question_options':
            raw = (message.text or '').strip()
            options = None
            if raw and raw != '-':
                opts = [o.strip() for o in raw.split('|') if o.strip()]
                if opts:
                    options = '|'.join(opts)
            # نحفظ الخيارات ونعرض معاينة الأزرار قبل التأكيد النهائي
            data['q_options'] = options
            data['waiting_for'] = 'confirm_question'
            await message.reply_text(
                _question_preview_text(data),
                reply_markup=_question_preview_kb(options)
            )

        elif waiting_for == 'punish_user_id':
            raw = (message.text or '').strip().lstrip('@')
            del pending_downloads[user_id]
            target_uid = None
            if raw.isdigit():
                target_uid = int(raw)
            else:
                u = subdb.find_user_by_username(raw)
                if u:
                    target_uid = u[0]
            if not target_uid:
                await message.reply_text("❌ لم أجد المستخدم. أرسل ID رقمي أو @username صحيح.")
                return
            info = subdb.get_ban_info(target_uid)
            if info and info.get('banned'):
                status = f"🚫 محظور حالياً (مخالفات: {info.get('strikes')})"
            else:
                status = "✅ غير محظور"
            await message.reply_text(
                f"👤 المستخدم: <code>{target_uid}</code>\nالحالة: {status}\n\nاختر الإجراء:",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_admin_ban_buttons(target_uid)
            )

        elif waiting_for == 'add_forced_channel':
            await add_forced_channel_from_admin(client, message, user_id)

        elif waiting_for == 'promote_user_id':
            user_input = message.text.strip()
            
            # محاولة البحث بواسطة ID أو Username
            target_user = None
            if user_input.isdigit():
                target_user = subdb.find_user_by_id(int(user_input))
            elif user_input.startswith('@') or user_input.isalnum():
                target_user = subdb.find_user_by_username(user_input)
            
            if not target_user:
                await message.reply_text(
                    "❌ **لم يتم العثور على المستخدم**\n\n"
                    "تأكد من أن المستخدم قد استخدم البوت مسبقاً"
                )
                del pending_downloads[user_id]
                return
            
            # حفظ معلومات المستخدم المستهدف
            pending_downloads[user_id] = {
                'waiting_for': 'promote_duration',
                'target_user_id': target_user[0],
                'target_user_name': target_user[2]
            }
            
            # عرض معلومات المستخدم وطلب المدة
            user_status = "💎 مشترك" if target_user[3] else "🆓 عادي"
            await message.reply_text(
                f"👤 **تم العثور على المستخدم:**\n\n"
                f"الاسم: {target_user[2]}\n"
                f"ID: `{target_user[0]}`\n"
                f"الحالة: {user_status}\n\n"
                f"**أرسل مدة الاشتراك بالأيام**\n"
                f"(مثلاً: 30 لشهر واحد، 365 لسنة)"
            )
        
        elif waiting_for == 'promote_duration':
            days = int(message.text.strip())
            if days < 1:
                await message.reply_text("❌ يجب أن تكون المدة أكبر من 0")
                return
            
            target_user_id = data.get('target_user_id')
            target_user_name = data.get('target_user_name')
            
           # ترقية المستخدم
            subdb.activate_subscription(target_user_id, days, 'manual_by_admin')
            
            # إشعار للأدمن
            await message.reply_text(
                f"✅ **تمت الترقية بنجاح!**\n\n"
                f"👤 **المستخدم:** {target_user_name}\n"
                f"🆔 **ID:** `{target_user_id}`\n"
                f"📅 **المدة:** {days} يوم"
            )
            
            # إشعار للمستخدم
            try:
                # Get user's preferred language
                user_lang = subdb.get_user_language(target_user_id)
                
                await client.send_message(
                    chat_id=target_user_id,
                    text=t('subscription_upgraded', user_lang, days=days)
                )
                logger.info(f"✅ تمت ترقية {target_user_id} لمدة {days} يوم")
            except Exception:
                logger.warning(f"لم يتمكن من إرسال إشعار الترقية للمستخدم {target_user_id}")
            
            del pending_downloads[user_id]
        
        elif waiting_for == 'broadcast_message':
            global broadcast_counter
            broadcast_text = message.text.strip()

            # الجمهور المستهدف: بث خاص للمستثنين فقط، أو بث عام حسب الجنس/اللغة
            # مع استبعاد قائمة الاستثناء (لا يعرفون بما يُرسل للأعضاء)
            if data.get('target_exempt'):
                all_users = sorted(_exempt_ids())
            else:
                target_lang = data.get('target_lang', 'all')
                target_gender = data.get('target_gender', 'all')
                all_users = _broadcast_targets(target_gender, target_lang)

            # شكل الرسالة: تفاعلية (نعم/لا + إحصائية حية) أو نظيفة (نص + زر رد
            # فقط). بث المستثنين نظيف دائماً — أشخاص معدودون لا معنى لإحصائيتهم.
            with_poll = bool(data.get('with_poll')) and not data.get('target_exempt')

            bid = None
            if with_poll:
                # إنشاء استبيان بث جديد بإحصائية حيّة
                broadcast_counter += 1
                bid = broadcast_counter
                broadcast_polls[bid] = {
                    'admin_id': user_id,
                    'total': len(all_users),
                    'yes': {},
                    'no': {},
                    'stats_chat': None,
                    'stats_msg_id': None,
                    'last_edit': 0,
                }

            progress = await message.reply_text(
                f"📤 **جاري الإرسال...**\n\n"
                f"سيتم إرسال الرسالة لـ {len(all_users)} مستخدم"
            )

            success_count = 0
            fail_count = 0
            removed_count = 0
            total_targets = len(all_users)

            for idx, uid in enumerate(all_users, 1):
                try:
                    # Get each user's preferred language
                    user_lang = subdb.get_user_language(uid)

                    # أزرار: (نعم / لا في الوضع التفاعلي فقط) + رد للمطور
                    kb_rows = []
                    if with_poll:
                        kb_rows.append(
                            [InlineKeyboardButton(t('btn_yes', user_lang), callback_data=f"bcyes_{bid}"),
                             InlineKeyboardButton(t('btn_no', user_lang), callback_data=f"bcno_{bid}")])
                    kb_rows.append(
                        [InlineKeyboardButton(t('reply_button', user_lang), callback_data=f"reply_msg_{user_id}")])
                    kb = InlineKeyboardMarkup(kb_rows)

                    await client.send_message(
                        chat_id=uid,
                        text=f"{t('broadcast_message_prefix', user_lang)}\n\n{broadcast_text}",
                        reply_markup=kb
                    )
                    success_count += 1
                    await asyncio.sleep(0.05)  # تأخير بسيط لتجنب Flood
                except FloodWait as e:
                    await asyncio.sleep(getattr(e, 'value', 5))
                    fail_count += 1
                except GONE_USER_ERRORS:
                    # العضو غادر/حظر البوت → احذفه من قاعدة البيانات
                    try:
                        subdb.delete_user(uid)
                        removed_count += 1
                    except Exception:
                        pass
                    fail_count += 1
                except Exception:
                    # خطأ مؤقت/غير معروف → نُبقي العضو
                    fail_count += 1
                # عدّاد حيّ يتحدّث كل 15 رسالة
                if idx % 15 == 0:
                    await _edit_send_progress(progress, "📢 جاري البث الجماعي...",
                                              idx, total_targets, success_count,
                                              fail_count, removed_count)

            if with_poll:
                # عدد من وصلتهم الرسالة فعلاً هو الأساس لحساب "لم يتفاعلوا"
                broadcast_polls[bid]['total'] = success_count

                # رسالة الإحصائية الحيّة للأدمن (تتحدث عند كل ضغطة)
                stats_msg = await message.reply_text(
                    _broadcast_stats_text(bid),
                    reply_markup=_broadcast_stats_kb(bid),
                    parse_mode=enums.ParseMode.HTML
                )
                broadcast_polls[bid]['stats_chat'] = stats_msg.chat.id
                broadcast_polls[bid]['stats_msg_id'] = stats_msg.id

            try:
                await progress.edit_text(
                    f"✅ **اكتمل الإرسال!**\n\n"
                    f"✅ وصلت إلى: {success_count}\n"
                    f"❌ فشلت: {fail_count}\n"
                    f"🗑️ حُذف (غادروا البوت): {removed_count}"
                )
            except Exception:
                pass

            del pending_downloads[user_id]
            logger.info(f"📢 Broadcast {'#' + str(bid) if bid else '(نظيف)'}: "
                        f"{success_count} نجح, {fail_count} فشل, {removed_count} محذوف")
        
        elif waiting_for == 'exempt_add':
            uid, name = _resolve_member_ref(message.text)
            del pending_downloads[user_id]
            if not uid:
                await message.reply_text(
                    "❌ **لم يتم العثور على العضو**\n\n"
                    "أرسل ID رقمياً (يُقبل دائماً) أو @username لعضو استخدم البوت مسبقاً."
                )
                return
            if _add_exempt(uid):
                shown = name or "غير معروف بعد (يُفعّل الإعفاء فور دخوله)"
                await message.reply_text(
                    f"⭐ **أُضيف لقائمة الاستثناء**\n\n"
                    f"👤 {shown}\n🆔 `{uid}`\n\n"
                    "🔕 لن يصله بث أو تذكير، و✅ معفى من الاشتراك الإجباري."
                )
            else:
                await message.reply_text(f"ℹ️ العضو `{uid}` موجود في القائمة مسبقاً.")

        elif waiting_for == 'direct_msg_user_id':
            user_input = message.text.strip()

            # محاولة البحث بواسطة ID أو Username
            target_user = None
            if user_input.isdigit():
                target_user = subdb.find_user_by_id(int(user_input))
            elif user_input.startswith('@') or user_input.isalnum():
                target_user = subdb.find_user_by_username(user_input)
            
            if not target_user:
                await message.reply_text(
                    "❌ **لم يتم العثور على المستخدم**\n\n"
                    "تأكد من أن المستخدم قد استخدم البوت مسبقاً"
                )
                del pending_downloads[user_id]
                return
            
            # حفظ معلومات المستخدم المستهدف
            pending_downloads[user_id] = {
                'waiting_for': 'direct_msg_text',
                'target_user_id': target_user[0],
                'target_user_name': target_user[2]
            }
            
            await message.reply_text(
                f"👤 **سيتم الإرسال إلى:**\n\n"
                f"الاسم: {target_user[2]}\n"
                f"ID: `{target_user[0]}`\n\n"
                f"**أرسل الرسالة الآن:**",
                reply_markup=_sub_settings_back_kb()
            )
        
        elif waiting_for == 'direct_msg_text':
            msg_text = message.text.strip()
            target_user_id = data.get('target_user_id')
            target_user_name = data.get('target_user_name')
            
            try:
                # Get user's preferred language
                user_lang = subdb.get_user_language(target_user_id)

                # زر يتيح للعضو الرد على المطور عبر البوت
                reply_kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        t('reply_button', user_lang),
                        callback_data=f"reply_msg_{user_id}"
                    )
                ]])

                await client.send_message(
                    chat_id=target_user_id,
                    text=f"{t('direct_message_prefix', user_lang)}\n\n{msg_text}",
                    reply_markup=reply_kb
                )

                await message.reply_text(
                    f"✅ **تم الإرسال بنجاح!**\n\n"
                    f"👤 إلى: {target_user_name}\n"
                    f"🆔 ID: `{target_user_id}`"
                )
                logger.info(f"✉️ رسالة مباشرة من الأدمن إلى {target_user_id}")
            except Exception as e:
                await message.reply_text(
                    f"❌ **فشل الإرسال**\n\n"
                    f"الخطأ: {str(e)}"
                )
            
            del pending_downloads[user_id]
        
        elif waiting_for == 'search_user_id':
            user_input = message.text.strip()
            
            # محاولة البحث بواسطة ID أو Username
            target_user = None
            if user_input.isdigit():
                target_user = subdb.find_user_by_id(int(user_input))
            elif user_input.startswith('@') or user_input.isalnum():
                target_user = subdb.find_user_by_username(user_input)
            
            if not target_user:
                await message.reply_text(
                    "❌ **لم يتم العثور على المستخدم**\n\n"
                    "تأكد من أن المستخدم قد استخدم البوت مسبقاً"
                )
                del pending_downloads[user_id]
                return
            
            # عرض معلومات المستخدم
            user_id_found, username, first_name, is_subscribed, subscription_end = target_user
            username_str = f"@{username}" if username else "لا يوجد"
            name = first_name or "مستخدم"
            
            # حالة الاشتراك
            if is_subscribed:
                days_left = subdb.get_days_remaining(user_id_found)
                status = f"💎 **مشترك** ({days_left} يوم متبقية)"
            else:
                status = "🆓 **عادي** (غير مشترك)"
            
            # الجنس واللغة
            gender_txt = _gender_label(subdb.get_survey(user_id_found).get('gender'))
            lang_txt = '🇬🇧 الإنجليزية' if subdb.get_user_language(user_id_found) == 'en' else '🇸🇦 العربية'

            text = (
                f"🔍 **معلومات المستخدم**\n\n"
                f"👤 **الاسم:** {name}\n"
                f"🆔 **User ID:** `{user_id_found}`\n"
                f"📱 **Username:** {username_str}\n"
                f"👥 **الجنس:** {gender_txt}\n"
                f"🌐 **اللغة:** {lang_txt}\n"
                f"📊 **الحالة:** {status}\n"
            )

            await message.reply_text(text)
            del pending_downloads[user_id]
        
        elif waiting_for == 'demote_user_id':
            user_input = message.text.strip()
            
            # محاولة البحث بواسطة ID أو Username
            target_user = None
            if user_input.isdigit():
                target_user = subdb.find_user_by_id(int(user_input))
            elif user_input.startswith('@') or user_input.isalnum():
                target_user = subdb.find_user_by_username(user_input)
            
            if not target_user:
                await message.reply_text(
                    "❌ **لم يتم العثور على المستخدم**\n\n"
                    "تأكد من أن المستخدم قد استخدم البوت مسبقاً"
                )
                del pending_downloads[user_id]
                return
            
            # التحقق من أن المستخدم مشترك
            target_user_id, username, first_name, is_subscribed, subscription_end = target_user
            
            if not is_subscribed:
                await message.reply_text(
                    "❌ **المستخدم ليس مشتركاً**\n\n"
                    f"👤 {first_name}\n"
                    f"🆔 `{target_user_id}`\n"
                    f"الحالة: 🆓 عادي"
                )
                del pending_downloads[user_id]
                return
            
            # إلغاء الاشتراك
            subdb.deactivate_subscription(target_user_id)
            
            # إرسال إشعار للمستخدم
            try:
                # Get user's preferred language
                user_lang = subdb.get_user_language(target_user_id)
                
                await client.send_message(
                    chat_id=target_user_id,
                    text=t('subscription_deactivated', user_lang)
                )
            except Exception:
                pass
            
            await message.reply_text(
                f"✅ **تم إلغاء الترقية بنجاح!**\n\n"
                f"👤 **المستخدم:** {first_name}\n"
                f"🆔 **ID:** `{target_user_id}`\n"
                f"📊 **الحالة الجديدة:** 🆓 عادي"
            )
            logger.info(f"❌ تم إلغاء ترقية المستخدم {target_user_id}")
            del pending_downloads[user_id]
    
    except ValueError:
        await message.reply_text("❌ قيمة غير صحيحة! أرسل رقماً فقط.")


# ═══════════════════════════════════════════════════════════════
# معالج اختيار اللغة - Language Selection Handler
# ═══════════════════════════════════════════════════════════════

@app.on_callback_query(filters.regex(r'^lang_'))
async def handle_language_selection(client, callback_query):
    """معالج اختيار اللغة"""
    lang = callback_query.data.replace('lang_', '')
    user_id = callback_query.from_user.id
    
    # حفظ اللغة
    subdb.set_user_language(user_id, lang)
    
    # إضافة المستخدم إلى قاعدة البيانات
    username = callback_query.from_user.username
    first_name = callback_query.from_user.first_name
    subdb.add_or_update_user(user_id, username, first_name)
    
    # رسالة التأكيد
    await callback_query.message.edit_text(
        t('language_set', lang)
    )
    
    # إرسال رسالة الترحيب
    admin_id = os.getenv("ADMIN_ID")
    keyboard = None
    
    if admin_id and str(user_id) == admin_id:
        from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton(t('btn_cookies', lang)), KeyboardButton(t('btn_daily_report', lang))],
            [KeyboardButton(t('btn_health', lang)), KeyboardButton(t('btn_subscription', lang))],
            [KeyboardButton("📁 نسخ احتياطي"), KeyboardButton(t('btn_change_language', lang))],
            [KeyboardButton(t('btn_update_ytdlp', lang))]
        ], resize_keyboard=True)
    else:
        from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton(t('btn_my_downloads', lang)), KeyboardButton(t('btn_invite', lang))],
            [KeyboardButton(t('btn_change_language', lang))]
        ], resize_keyboard=True)

    await client.send_message(
        chat_id=user_id,
        text=t('welcome', lang, name=first_name),
        reply_markup=keyboard
    )

    # 📋 اسأل العضو الجديد الاستبيان (الجنس + الأسئلة) فور اختيار اللغة
    if not is_admin(user_id):
        await _prompt_survey_if_needed(
            lambda text, reply_markup=None: client.send_message(
                user_id, text, reply_markup=reply_markup),
            user_id
        )

    await callback_query.answer()

@app.on_message(filters.text & ~filters.regex(r'^/'), group=10)
async def handle_change_language_button(client, message):
    """معالج زر تغيير اللغة - مع أولوية أعلى"""
    if not message.from_user:
        return
    # Check if message is change language button in any language
    if message.text in ["🌍 تغيير اللغة", "🌍 Change Language"]:
        user_id = message.from_user.id
        # Get user's current language
        current_lang = subdb.get_user_language(user_id)
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🇮🇶 العربية", callback_data="lang_ar"),
                InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")
            ]
        ])
        
        # Use bilingual message (works for both languages)
        await message.reply_text(
            t('choose_language', current_lang),
            reply_markup=keyboard
        )


async def _register_bot_commands(client):
    """يسجّل قائمة أوامر تلجرام (قائمة /) عند الإقلاع فلا حاجة لحفظ الأوامر:
    للأعضاء يظهر /start فقط، وللأدمن (في محادثته وحدها) تظهر كل أوامر الإدارة
    مع وصف عربي لكل أمر. أي فشل هنا لا يمس عمل البوت."""
    from pyrogram.types import (
        BotCommand, BotCommandScopeChat, BotCommandScopeDefault,
    )
    # المهمة تُنشأ قبل app.run() → انتظر اتصال العميل أولاً
    for _ in range(120):
        if getattr(client, 'is_connected', False):
            break
        await asyncio.sleep(1)
    else:
        logger.warning("⚠️ لم يتصل العميل — تخطّي تسجيل قائمة الأوامر")
        return

    try:
        await client.set_bot_commands(
            [BotCommand("start", "بدء البوت / Start the bot")],
            scope=BotCommandScopeDefault()
        )
    except Exception as e:
        logger.warning(f"⚠️ تعذّر تسجيل أوامر الأعضاء: {e}")

    admin_id = os.getenv("ADMIN_ID")
    if not (admin_id and str(admin_id).lstrip('-').isdigit()):
        return
    admin_cmds = [
        BotCommand("start", "🏠 بدء البوت"),
        BotCommand("exempt", "⭐ إضافة عضو لقائمة الاستثناء"),
        BotCommand("unexempt", "⭐ حذف عضو من قائمة الاستثناء"),
        BotCommand("exemptlist", "⭐ عرض قائمة الاستثناء"),
        BotCommand("health", "🩺 فحص صحة البوت"),
        BotCommand("backup", "💾 نسخة احتياطية فورية"),
        BotCommand("history", "📥 سجل التحميلات"),
        BotCommand("dlstats", "📊 إحصائيات التحميل"),
        BotCommand("realusers", "👥 فحص الأعضاء الحقيقيين"),
        BotCommand("cookies", "🍪 إدارة الكوكيز"),
        BotCommand("update", "⬆️ تحديث أدوات التحميل"),
        BotCommand("uncache", "🧹 حذف رابط من الكاش"),
        BotCommand("unban", "✅ رفع الحظر عن عضو"),
        BotCommand("banned", "📛 قائمة المحظورين"),
        BotCommand("blockacc", "🚫 حظر حساب مصدر"),
        BotCommand("unblockacc", "♻️ رفع حظر حساب مصدر"),
        BotCommand("blockedaccs", "📋 الحسابات المصدر المحظورة"),
    ]
    try:
        await client.set_bot_commands(
            admin_cmds, scope=BotCommandScopeChat(chat_id=int(admin_id)))
        logger.info("✅ سُجّلت قائمة أوامر تلجرام (الأعضاء + الأدمن)")
    except Exception as e:
        logger.warning(f"⚠️ تعذّر تسجيل أوامر الأدمن: {e}")


logger.info("🚀 بدء البوت...")
# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🤖 Telegram Video Downloader Bot (Standalone)")
    print("=" * 60)
    print("✅ يرفع حتى 2GB")
    print("✅ نجح مع فيديو 3 ساعات")
    print("=" * 60)
    
    # إنشاء مجلد videos وcookies
    os.makedirs('videos', exist_ok=True)
    os.makedirs('cookies', exist_ok=True)
    
    # إنشاء قاعدة البيانات
    subdb.init_db()
    print("✅ تم إنشاء قاعدة بيانات الاشتراكات")
    
    # بدء مهمة التقرير اليومي والفحص اليومي للأعضاء (3 فجراً)
    loop = asyncio.get_event_loop()
    loop.create_task(daily_report_task())
    loop.create_task(daily_cleanup_task())
    loop.create_task(_auto_backup_loop(app))  # نسخ احتياطي تلقائي لقناة النسخ
    loop.create_task(_register_bot_commands(app))  # قائمة أوامر / في تلجرام
    
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n⏹️ تم الإيقاف")



if __name__ == "__main__":
    main()

