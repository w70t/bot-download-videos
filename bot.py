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
import json  # قراءة مخرجات ffprobe
import html  # تأمين النصوص داخل رسائل HTML للقناة
import uuid  # مجلد مؤقت فريد لكل عملية تحميل
import shutil  # حذف مجلد التحميل المؤقت بالكامل
import socket  # التحقق من عناوين IP للروابط (حماية SSRF)
import ipaddress  # كشف العناوين الداخلية/الخاصة
import subprocess  # توليد المصغّر وضبط تاريخ الفيديو عبر ffmpeg
import logging
import asyncio
import yt_dlp
import traceback
from datetime import datetime
from urllib.parse import urlparse, parse_qsl, urlencode
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

# ... (rest of imports/logging/config remains same until download_and_upload)

# ... inside download_and_upload ...


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


def _is_private_host(host: str) -> bool:
    """هل المضيف عنوان داخلي/خاص/loopback أو غير قابل للحل؟ (حماية SSRF)
    يرجع True لمنع التحميل (أي العنوان غير آمن)."""
    if not host:
        return True
    host = host.strip().strip('[]').lower()
    # احجب أسماء المضيف المحلية الواضحة
    if host in ('localhost', 'localhost.localdomain') or host.endswith('.local') \
            or host.endswith('.internal'):
        return True
    # حل اسم المضيف إلى عناوين IP وافحص كل عنوان
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        # تعذّر الحل → اعتبره غير آمن
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split('%')[0])
        except ValueError:
            return True
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return True
    return False


def is_safe_url(url: str) -> bool:
    """يتحقق أن الرابط http/https ولا يشير إلى عنوان داخلي (حماية SSRF)."""
    try:
        parsed = urlparse(url if '://' in url else 'http://' + url)
    except Exception:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    if _is_private_host(parsed.hostname or ''):
        return False
    return True


# معاملات تتبّع تُحذف عند توليد مفتاح الكاش (لا تغيّر الفيديو المقصود)
_TRACKING_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'si', 'feature', 'fbclid', 'igshid', 'igsh', 'spm', 'ref', 'ref_src', '_nc',
}


def cache_key_for_url(url: str) -> str:
    """يولّد مفتاحاً موحّداً للرابط لاستخدامه في الكاش: حذف الجزء (#) ومعاملات
    التتبّع، وتوحيد المضيف والمسار. يبقى دقيقاً (لا يدمج فيديوهات مختلفة)."""
    try:
        p = urlparse(url.strip())
        host = (p.hostname or '').lower().lstrip('.')
        if host.startswith('www.'):
            host = host[4:]
        q = sorted((k, v) for k, v in parse_qsl(p.query)
                   if k.lower() not in _TRACKING_PARAMS)
        path = p.path.rstrip('/')
        key = f"{host}{path}"
        if q:
            key += '?' + urlencode(q)
        return key.lower()
    except Exception:
        return url.strip().lower()


def _platform_of(url: str) -> str:
    """يرجع اسم المنصة من الرابط (للإحصائيات والسجل)."""
    low = (url or '').lower()
    for platform, markers in PLATFORM_URL_MARKERS.items():
        if any(m in low for m in markers):
            return platform
    return 'other'


# Initialize Queue Manager
queue_manager = DownloadQueueManager(cooldown_seconds=10)

# تخزين الروابط
pending_downloads = {}

# روابط قوائم التشغيل المنتظِرة تأكيد المستخدم {user_id: [urls]}
pending_playlists = {}

# عدد التحميلات الافتراضي عند الدعوة، وأقصى عدد مقاطع لقائمة التشغيل
REFERRAL_BONUS = int(os.getenv("REFERRAL_BONUS", "3"))
PLAYLIST_MAX = int(os.getenv("PLAYLIST_MAX", "5"))

# حالة المحادثة بين الأدمن والأعضاء عبر زر الرد
# {user_id: target_user_id} أي أن user_id ينتظر كتابة رد ليُرسَل إلى target_user_id
conversation_state = {}

# استبيانات البث الجماعي مع إحصائية حيّة
# {broadcast_id: {'admin_id', 'total', 'yes': {uid:name}, 'no': {uid:name},
#                 'stats_chat', 'stats_msg_id', 'last_edit'}}
broadcast_polls = {}
broadcast_counter = 0

# منصات الـ cookies المدعومة
COOKIES_PLATFORMS = {
    'facebook': {'name': 'Facebook 📘', 'file': 'cookies/facebook.txt'},
    'instagram': {'name': 'Instagram �', 'file': 'cookies/instagram.txt'},
    'youtube': {'name': 'YouTube 📺', 'file': 'cookies/youtube.txt'},
    'twitter': {'name': 'Twitter/X 🐦', 'file': 'cookies/twitter.txt'},
    'reddit': {'name': 'Reddit �', 'file': 'cookies/reddit.txt'},
    'snapchat': {'name': 'Snapchat 👻', 'file': 'cookies/snapchat.txt'},
    'pinterest': {'name': 'Pinterest 📌', 'file': 'cookies/pinterest.txt'},
    'tiktok': {'name': 'TikTok 🎵', 'file': 'cookies/tiktok.txt'},
    'other': {'name': 'أخرى 🌐', 'file': 'cookies/other.txt'},
}

# ربط أجزاء الرابط بالمنصة المناسبة لاختيار ملف الـ cookies الصحيح
PLATFORM_URL_MARKERS = {
    'youtube': ['youtube.', 'youtu.be'],
    'facebook': ['facebook.', 'fb.watch', 'fb.com'],
    'instagram': ['instagram.', 'instagr.am'],
    'threads': ['threads.net', 'threads.com'],
    'twitter': ['twitter.', 'x.com', 't.co'],
    'reddit': ['reddit.', 'redd.it'],
    'snapchat': ['snapchat.'],
    'pinterest': ['pinterest.', 'pin.it'],
    'tiktok': ['tiktok.'],
}

# منصات تشارك ملف cookies منصة أخرى (Threads يستخدم تسجيل دخول Instagram)
COOKIE_SOURCE_MAP = {
    'threads': 'instagram',
}

# ═══════════════════════════════════════════════════════════════
# فلتر المحتوى الإباحي (حظر قبل التحميل) - Adult content filter
# الطريقة: قائمة نطاقات معروفة + كلمات مفتاحية في الرابط والعنوان.
# يوقف المحتوى قبل أي تحميل (بلا تكلفة) ويمكن للأدمن تشغيله/إيقافه.
# ═══════════════════════════════════════════════════════════════
ADULT_DOMAINS = {
    'pornhub.com', 'xvideos.com', 'xvideos2.com', 'xnxx.com', 'xhamster.com',
    'xhamster.desi', 'redtube.com', 'youporn.com', 'tube8.com', 'spankbang.com',
    'youjizz.com', 'beeg.com', 'tnaflix.com', 'drtuber.com', 'sunporno.com',
    'eporner.com', 'txxx.com', 'hclips.com', 'upornia.com', 'hotmovs.com',
    'vjav.com', 'porntrex.com', 'motherless.com', 'porn.com', 'pornhd.com',
    'porntube.com', 'pornone.com', 'porngo.com', 'porntrex.com', 'fapality.com',
    'brazzers.com', 'realitykings.com', 'bangbros.com', 'naughtyamerica.com',
    'onlyfans.com', 'fansly.com', 'manyvids.com', 'clips4sale.com',
    'chaturbate.com', 'cam4.com', 'myfreecams.com', 'stripchat.com',
    'bongacams.com', 'livejasmin.com', 'camsoda.com', 'streamate.com',
    'redgifs.com', 'gifs.com', 'rule34video.com', 'rule34.xxx',
    'hanime.tv', 'hentaihaven.xxx', 'nhentai.net', 'hentai.tv', 'fakings.com',
    'xmoviesforyou.com', 'fux.com', 'keezmovies.com', 'extremetube.com',
    'gotporn.com', 'pornhat.com', 'analdin.com', 'hdzog.com', 'thothub.tv',
}

# كلمات مفتاحية صريحة (عربي + إنجليزي). تُفحص في النطاق ومسار الرابط والعنوان.
ADULT_KEYWORDS = [
    'porn', 'xxx', 'xnxx', 'sexvideo', 'sex-video', 'nsfw', 'hentai',
    'camgirl', 'camslut', 'fuck', 'blowjob', 'creampie', 'cumshot',
    'milf', 'hardcore', 'bigtits', 'pussy', 'anal', 'escort',
    'سكس', 'اباحي', 'إباحي', 'اباحية', 'إباحية', 'نيك', 'خلاعة', 'عاهرة',
    'شرموطة', 'متناكة', 'سحاق', 'لواط',
]


def _url_host(url):
    """يستخرج اسم المضيف (host) من الرابط بصيغة صغيرة."""
    try:
        host = urlparse(url if '://' in url else 'http://' + url).hostname or ''
    except Exception:
        host = ''
    return host.lower().lstrip('.')


def _custom_adult_domains():
    """نطاقات إضافية حظرها الأدمن من لوحة التحكم (مفصولة بفاصلة)."""
    raw = subdb.get_setting('adult_custom_domains', '') or ''
    return [d.strip().lower().lstrip('.') for d in raw.split(',') if d.strip()]


def _custom_adult_keywords():
    """كلمات إضافية حظرها الأدمن من لوحة التحكم (مفصولة بفاصلة)."""
    raw = subdb.get_setting('adult_custom_keywords', '') or ''
    return [k.strip().lower() for k in raw.split(',') if k.strip()]


def _add_to_setting_list(key, value):
    """يضيف قيمة لقائمة إعداد مفصولة بفواصل (يتجاهل التكرار). يرجع True إن أُضيفت."""
    value = value.strip().lower().lstrip('.')
    if not value:
        return False
    raw = subdb.get_setting(key, '') or ''
    items = [x.strip().lower() for x in raw.split(',') if x.strip()]
    if value in items:
        return False
    items.append(value)
    subdb.set_setting(key, ','.join(items))
    return True


def _remove_from_setting_list(key, index):
    """يحذف عنصراً واحداً من قائمة إعداد حسب فهرسه. يرجع القيمة المحذوفة أو None."""
    raw = subdb.get_setting(key, '') or ''
    items = [x.strip() for x in raw.split(',') if x.strip()]
    if 0 <= index < len(items):
        removed = items.pop(index)
        subdb.set_setting(key, ','.join(items))
        return removed
    return None


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


def _host_is_adult(host):
    """هل المضيف ينتمي لنطاق إباحي معروف (يشمل النطاقات الفرعية)؟"""
    if not host:
        return False
    if host.startswith('www.'):
        host = host[4:]
    for domain in set(ADULT_DOMAINS) | set(_custom_adult_domains()):
        if host == domain or host.endswith('.' + domain):
            return True
    return False


def _text_has_adult_keyword(text):
    """هل النص يحتوي على كلمة مفتاحية إباحية صريحة؟"""
    if not text:
        return False
    low = str(text).lower()
    return any(kw in low for kw in (ADULT_KEYWORDS + _custom_adult_keywords()))


def is_adult_url(url):
    """فحص الرابط قبل الاستخراج: النطاق أولاً، ثم كلمات في مسار الرابط."""
    host = _url_host(url)
    if _host_is_adult(host):
        return True
    return _text_has_adult_keyword(url)


def is_adult_info(info):
    """فحص بيانات الفيديو بعد الاستخراج (الحساسية/العنوان/الوصف/الناشر)."""
    if not info:
        return False
    try:
        if int(info.get('age_limit') or 0) >= 18:
            return True
    except (TypeError, ValueError):
        pass
    # علم الحساسية في X/تويتر ومنصات أخرى
    if info.get('possibly_sensitive') or info.get('is_nsfw') or info.get('nsfw'):
        return True
    parts = [info.get('title'), info.get('description'), info.get('uploader'),
             info.get('uploader_id'), info.get('channel'), info.get('uploader_url')]
    parts.extend(info.get('categories') or [])
    parts.extend(info.get('tags') or [])
    return any(_text_has_adult_keyword(p) for p in parts)


def _blocked_accounts():
    """مجموعة الحسابات المحظورة (يديرها الأدمن، مفصولة بفواصل)."""
    raw = subdb.get_setting('blocked_accounts', '') or ''
    return {x.strip().lower().lstrip('@') for x in raw.split(',') if x.strip()}


def _handle_from_url(url):
    """يستخرج اسم الحساب من رابط X/تويتر (x.com/<handle>/status/...)."""
    try:
        p = urlparse(url if '://' in url else 'http://' + url)
        host = (p.hostname or '').lower()
        if not any(h in host for h in ('x.com', 'twitter.com')):
            return None
        parts = [x for x in p.path.split('/') if x]
        if parts and parts[0].lower() not in ('i', 'status', 'home', 'search'):
            return parts[0].lstrip('@').lower()
    except Exception:
        pass
    return None


def is_blocked_url(url):
    """حظر مبكر (قبل الاستخراج) حسب اسم الحساب في رابط X/تويتر."""
    h = _handle_from_url(url)
    return bool(h and h in _blocked_accounts())


def _account_identifiers(info):
    """يجمع معرّفات الناشر الممكنة من معلومات الفيديو (للمطابقة مع قائمة الحظر)."""
    ids = set()
    if not info:
        return ids
    for key in ('uploader_id', 'uploader', 'channel_id', 'channel', 'creator',
                'uploader_url', 'channel_url', 'webpage_url'):
        v = info.get(key)
        if not v:
            continue
        s = str(v).strip().lower().lstrip('@')
        if s:
            ids.add(s)
            if '/' in s:  # استخرج اسم الحساب من نهاية الرابط
                tail = s.rstrip('/').split('/')[-1]
                if tail:
                    ids.add(tail.lstrip('@'))
    return ids


def is_blocked_account(info):
    """هل ناشر هذا المحتوى ضمن قائمة الحسابات المحظورة؟"""
    blocked = _blocked_accounts()
    if not blocked:
        return False
    return bool(_account_identifiers(info) & blocked)


def adult_filter_enabled():
    """هل فلتر المحتوى الإباحي مُفعّل؟ (افتراضياً مُفعّل)."""
    return subdb.get_setting('block_adult_content', '1') == '1'


def downloads_enabled():
    """هل التحميل مُفعّل للأعضاء؟ (افتراضياً مُفعّل). الأدمن لا يتأثر."""
    return subdb.get_setting('downloads_enabled', '1') == '1'


def generate_video_thumbnail(video_path, duration=None):
    """يولّد صورة مصغّرة (JPEG) للفيديو حتى تظهر معاينة ثابتة في تلجرام
    بدل الإطار الأسود/المتجمّد. يرجع مسار المصغّر أو None عند الفشل."""
    try:
        thumb_path = os.path.splitext(video_path)[0] + '.thumb.jpg'
        # نأخذ لقطة بعد ثانية واحدة (أو 10% من المدة للفيديوهات الأطول)
        ss = 1.0
        if duration and duration > 4:
            ss = min(3.0, duration / 10.0)
        cmd = [
            'ffmpeg', '-y', '-ss', str(ss), '-i', video_path,
            '-frames:v', '1', '-vf', 'scale=320:-2',
            '-q:v', '4', thumb_path,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except Exception as e:
        logger.warning(f"⚠️ تعذّر توليد المصغّر: {e}")
    return None


def probe_video(video_path):
    """يفحص الفيديو بـ ffprobe ويرجع (vcodec, acodec, width, height, duration).
    القيم غير المتوفرة تكون None."""
    try:
        out = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-show_entries', 'stream=codec_type,codec_name,width,height:format=duration',
             '-of', 'json', video_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60
        ).stdout.decode('utf-8', 'ignore')
        data = json.loads(out or '{}')
        vcodec = acodec = width = height = None
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video' and vcodec is None:
                vcodec = (s.get('codec_name') or '').lower()
                width = s.get('width')
                height = s.get('height')
            elif s.get('codec_type') == 'audio' and acodec is None:
                acodec = (s.get('codec_name') or '').lower()
        duration = None
        try:
            duration = int(float(data.get('format', {}).get('duration')))
        except (TypeError, ValueError):
            pass
        return vcodec, acodec, width, height, duration
    except Exception as e:
        logger.warning(f"⚠️ تعذّر فحص الفيديو بـ ffprobe: {e}")
        return None, None, None, None, None


def finalize_video(video_path):
    """يجهّز الفيديو لتلجرام لكل المنصات (وليس يوتيوب فقط) ويرجع
    (width, height, duration) الحقيقية من الملف:
    - يضمن ترميز H.264/AAC: ينسخ إن كان متوافقاً، وإلا يُعيد الترميز (سبب
      تجمّد الصورة في فيسبوك/منصات أخرى تستخدم VP9/AV1).
    - +faststart: نقل moov atom للبداية ليُعاين ويُشغّل فوراً.
    - creation_time = الآن ليظهر المقطع بترتيب وقت التحميل في المعرض.
    """
    vcodec, acodec, width, height, duration = probe_video(video_path)

    # هل الترميز متوافق مع مشغّل تلجرام؟ (None = غير معروف، نكتفي بالنسخ)
    v_compatible = vcodec in ('h264', 'avc1', None)
    a_compatible = acodec in ('aac', 'mp4a', None)
    v_args = ['-c:v', 'copy'] if v_compatible else \
        ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p']
    a_args = ['-c:a', 'copy'] if a_compatible else ['-c:a', 'aac', '-b:a', '128k']
    if not v_compatible:
        logger.info(f"🎞️ إعادة ترميز الفيديو إلى H.264 (المصدر: {vcodec})")

    tmp = os.path.splitext(video_path)[0] + '.fixed.mp4'
    try:
        now_iso = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        cmd = (
            ['ffmpeg', '-y', '-i', video_path, '-map', '0:v?', '-map', '0:a?']
            + v_args + a_args
            + ['-movflags', '+faststart', '-metadata', f'creation_time={now_iso}', tmp]
        )
        # إعادة الترميز قد تستغرق وقتاً أطول من النسخ
        timeout = 3600 if not v_compatible else 900
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, video_path)
            # أعد الفحص بعد التحويل للحصول على الأبعاد الصحيحة
            nv, na, nw, nh, nd = probe_video(video_path)
            width = nw or width
            height = nh or height
            duration = nd or duration
    except Exception as e:
        logger.warning(f"⚠️ تعذّر تجهيز الفيديو لتلجرام: {e}")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    # تحديث تاريخ الملف نفسه إلى الآن (مهم لمعرض أندرويد)
    try:
        os.utime(video_path, None)
    except Exception:
        pass

    return width, height, duration


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


async def enforce_forced_subscription(client, message, user_id, lang):
    """يفحص الاشتراك الإجباري؛ إن كان ناقصاً يعرض شاشة الاشتراك ويُرجع True
    (أي يجب إيقاف المعالجة). الأدمن مُعفى، ويُحترم زر التفعيل/الإيقاف."""
    if not forced_sub_enabled():
        return False
    if is_admin(user_id):
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

    # 2) نص: رابط دعوة خاص أو @username/رابط عام
    if not chat_id and raw:
        token = raw
        if 't.me/' in token:
            token = token.split('t.me/')[-1].strip('/')
        if token.startswith('+') or token.startswith('joinchat/'):
            # قناة/قروب خاص عبر رابط دعوة — لا يمكن التحقق منه (إعلاني)
            url = raw if raw.startswith('http') else f"https://t.me/{token}"
            chat_id = url  # المعرّف الفريد هو الرابط نفسه
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

    note = ("✅ البوت مشرف هنا → **تحقق حقيقي** من اشتراك الأعضاء."
            if verifiable else
            "⚠️ البوت **ليس مشرفاً** هنا، ولا يمكن التحقق من الاشتراك (قيد تلجرام).\n"
            "هذه القناة **لن تُفرض** حتى تجعل البوت مشرفاً فيها.")

    if subdb.add_forced_channel(chat_id, username, title, url):
        label = title or (f"@{username}" if username else url)
        await message.reply_text(f"✅ **تمت الإضافة:** {label}\n\n{note}")
    else:
        await message.reply_text("ℹ️ هذه القناة/القروب مُضافة مسبقاً.")


def _is_valid_cookie_file(platform_key):
    """يتحقق أن ملف الـ cookies الخاص بالمنصة موجود وليس فارغاً"""
    data = COOKIES_PLATFORMS.get(platform_key)
    if not data:
        return None
    path = data['file']
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return path
    return None


def get_cookie_file_for_url(url):
    """يختار ملف الـ cookies المطابق لمنصة الرابط.

    الستوري في فيسبوك وإنستغرام يتطلب تسجيل دخول، لذا يجب استخدام cookies
    نفس المنصة تحديداً وليس أي ملف cookies متوفر. عند عدم توفر ملف المنصة
    نرجع إلى ملف 'other' إن كان صالحاً.
    """
    url_lower = (url or '').lower()
    for platform_key, markers in PLATFORM_URL_MARKERS.items():
        if any(marker in url_lower for marker in markers):
            # بعض المنصات (مثل Threads) تستخدم cookies منصة أخرى (Instagram)
            cookie_platform = COOKIE_SOURCE_MAP.get(platform_key, platform_key)
            cookie = _is_valid_cookie_file(cookie_platform)
            if cookie:
                logger.info(f"🍪 استخدام cookies المنصة المطابقة: {platform_key} (cookies: {cookie_platform})")
                return cookie
            logger.warning(f"⚠️ لا يوجد ملف cookies صالح للمنصة {cookie_platform}؛ قد يفشل تحميل محتوى {platform_key} الخاص")
            break
    # احتياطي: ملف cookies عام
    return _is_valid_cookie_file('other')


# نطاقات كل منصة وأسماء كوكيز تسجيل الدخول الأساسية للتحقق الحقيقي
PLATFORM_COOKIE_INFO = {
    'facebook':  {'domains': ['facebook.com'],                'auth_cookies': ['c_user', 'xs']},
    'instagram': {'domains': ['instagram.com'],               'auth_cookies': ['sessionid', 'ds_user_id']},
    'youtube':   {'domains': ['youtube.com', 'google.com'],   'auth_cookies': ['SID', 'SAPISID']},
    'twitter':   {'domains': ['twitter.com', 'x.com'],        'auth_cookies': ['auth_token', 'ct0']},
    'reddit':    {'domains': ['reddit.com'],                  'auth_cookies': ['reddit_session']},
    'snapchat':  {'domains': ['snapchat.com'],                'auth_cookies': []},
    'pinterest': {'domains': ['pinterest.com'],               'auth_cookies': ['_pinterest_sess']},
    'tiktok':    {'domains': ['tiktok.com'],                  'auth_cookies': ['sessionid']},
    'other':     {'domains': [],                              'auth_cookies': []},
}


def _parse_netscape_cookies(path):
    """يقرأ ملف cookies بصيغة Netscape ويعيد قائمة بالكوكيز (domain/name/expiry)."""
    cookies = []
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                # أسطر #HttpOnly_ هي كوكيز حقيقية وليست تعليقات
                if line.startswith('#HttpOnly_'):
                    line = line[len('#HttpOnly_'):]
                elif line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) != 7:
                    continue
                domain, _flag, _cpath, _secure, expiry, name, _value = parts
                cookies.append({'domain': domain, 'expiry': expiry, 'name': name})
    except Exception as e:
        logger.error(f"خطأ في قراءة ملف الكوكيز {path}: {e}")
    return cookies


def validate_platform_cookies(platform_id):
    """تحقق حقيقي من صلاحية كوكيز منصة معينة.

    يفحص: وجود الملف، صيغته، أن الكوكيز تخص نطاق المنصة فعلاً،
    وجود كوكيز تسجيل الدخول الأساسية، وأنها غير منتهية الصلاحية.
    يعيد dict فيه ok وسبب وتفاصيل.
    """
    data = COOKIES_PLATFORMS.get(platform_id)
    if not data:
        return {'ok': False, 'reason': 'unknown_platform'}

    path = data['file']
    if not os.path.exists(path) or os.path.getsize(path) <= 100:
        return {'ok': False, 'reason': 'empty'}

    cookies = _parse_netscape_cookies(path)
    if not cookies:
        return {'ok': False, 'reason': 'unparseable'}

    info = PLATFORM_COOKIE_INFO.get(platform_id, {})
    domains = info.get('domains', [])
    auth_names = info.get('auth_cookies', [])

    # كوكيز تخص نطاق المنصة فقط
    if domains:
        platform_cookies = [c for c in cookies if any(d in c['domain'] for d in domains)]
    else:
        platform_cookies = cookies

    if domains and not platform_cookies:
        found = sorted({c['domain'].lstrip('.') for c in cookies})[:5]
        return {'ok': False, 'reason': 'wrong_platform', 'found_domains': found}

    names = {c['name'] for c in platform_cookies}

    # كوكيز تسجيل الدخول الأساسية
    missing_auth = [a for a in auth_names if a not in names]
    if auth_names and missing_auth:
        return {'ok': False, 'reason': 'not_logged_in', 'missing': missing_auth,
                'cookie_count': len(platform_cookies)}

    # فحص انتهاء الصلاحية لكوكيز تسجيل الدخول (أو كلها إن لم تكن هناك كوكيز محددة)
    now = time.time()
    check_list = ([c for c in platform_cookies if c['name'] in auth_names]
                  if auth_names else platform_cookies)
    expired = []
    for c in check_list:
        try:
            exp = float(c['expiry'])
        except (ValueError, TypeError):
            continue
        if exp != 0 and exp < now:
            expired.append(c['name'])

    if expired and (not auth_names or len(expired) == len(check_list)):
        return {'ok': False, 'reason': 'expired', 'expired': expired,
                'cookie_count': len(platform_cookies)}

    return {'ok': True, 'cookie_count': len(platform_cookies),
            'has_auth': bool(auth_names) and not missing_auth,
            'expired': expired}

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

def get_file_size_mb(file_path):
    """الحصول على حجم الملف بالميغابايت"""
    return os.path.getsize(file_path) / (1024 * 1024)



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


def _is_drm_error(err):
    """هل الفيديو محمي بـ DRM (لا يمكن تحميله إطلاقاً)؟"""
    return 'drm' in str(err).lower()


def _is_youtube_cookie_issue(err):
    """هل خطأ يوتيوب ناتج عن حجب الصيغ بسبب الكوكيز/الحماية؟"""
    msg = str(err).lower()
    signs = [
        'requested format is not available',
        'player response',
        'sign in to confirm',
        'this content isn',
        'po token',
        'no video formats',
    ]
    return any(s in msg for s in signs)


async def get_video_info(url: str):
    """استخراج معلومات الفيديو"""
    try:
        # حماية SSRF: ارفض الروابط غير http/https أو التي تشير لعنوان داخلي
        if not is_safe_url(url):
            logger.warning(f"🚫 رابط غير آمن أو داخلي مرفوض: {url[:100]}")
            return None
        # اختيار ملف cookies المطابق لمنصة الرابط (مهم للستوري الخاص)
        cookie_file = get_cookie_file_for_url(url)
        is_youtube = any(m in url.lower() for m in PLATFORM_URL_MARKERS['youtube'])

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
            return await loop.run_in_executor(None, lambda: extract(True))
        except Exception as e:
            # يوتيوب مع الكوكيز قد يفشل بسبب حجب الصيغ → أعد المحاولة بدون كوكيز
            if cookie_file and is_youtube and _is_youtube_cookie_issue(e):
                logger.warning("⚠️ فشل يوتيوب مع الكوكيز، إعادة المحاولة بدون كوكيز...")
                return await loop.run_in_executor(None, lambda: extract(False))
            raise
    except Exception as e:
        error_msg = str(e)
        # معالجة خاصة لأخطاء Facebook parsing
        if 'Cannot parse data' in error_msg or 'facebook' in error_msg.lower():
            logger.error(f"خطأ Facebook parse: {error_msg[:200]}")
        else:
            logger.error(f"خطأ في استخراج المعلومات: {e}")
        return None


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
            await send_error_to_admin(user_id, user_name, "Failed to extract video info", url)
            await status.edit_text(t('invalid_url', lang))
            return

        # 🔞 محتوى إباحي/حساب محظور بعد الاستخراج → عاقِب المستخدم (حظر + تعهّد)
        if (adult_filter_enabled() and is_adult_info(info)) or is_blocked_account(info):
            logger.info(f"🔞 Adult/blocked content (queue) from user {user_id}: {info.get('uploader')}")
            ban_text, ban_kb = await _apply_adult_ban(app, user_id, lang)
            await status.edit_text(ban_text, reply_markup=ban_kb)
            return

        # 📃 كشف قوائم التشغيل: عرض زر لتحميل أول N مقاطع (للمشتركين/الأدمن)
        entries = [e for e in (info.get('entries') or []) if e]
        if entries:
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
        
        # Check daily limit for non-subscribers
        if not is_subscribed:
            daily_limit = subdb.get_daily_limit()
            
            if daily_limit != -1:
                daily_count = subdb.check_daily_limit(user_id)
                
                if daily_count >= daily_limit:
                    # جرّب استهلاك رصيد إضافي من الدعوات قبل الحظر
                    if subdb.consume_bonus_download(user_id):
                        logger.info(f"🎟️ استُخدم رصيد دعوة إضافي للمستخدم {user_id}")
                    else:
                        await status.edit_text(
                            t('daily_limit_exceeded', lang, limit=daily_limit, count=daily_count),
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton(t('subscribe_now', lang), callback_data="pay_binance")],
                                [_invite_button(lang)],
                                [InlineKeyboardButton(t('contact_developer', lang), url=f"https://t.me/{subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))}")]
                            ])
                        )
                        return
        
        max_duration_minutes = subdb.get_max_duration()
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


def _build_media_caption(title, file_size_mb, duration, user_name):
    """وصف الوسائط الموحّد: العنوان قابل للنسخ (monospace) + الحجم والمدة."""
    safe_title = (title or 'فيديو').replace('`', "'")[:300]
    dur_line = f"⏱️ {int(duration)//60}:{int(duration)%60:02d}\n" if duration else ""
    return (
        f"🎬 `{safe_title}`\n\n"
        f"📊 {file_size_mb:.1f} MB\n"
        f"{dur_line}"
        f"👤 {user_name}"
    )


async def _send_daily_remaining_notice(message, user_id, lang):
    """يزيد عداد الحد اليومي لغير المشتركين ويعرض المتبقي (مشترك بين المسارين)."""
    if subdb.is_user_subscribed(user_id):
        return
    subdb.increment_download_count(user_id)
    daily_limit = subdb.get_daily_limit()
    if daily_limit != -1:
        daily_count = subdb.check_daily_limit(user_id)
        remaining = daily_limit - daily_count
        if remaining > 0:
            await message.reply_text(t('downloads_remaining', lang, remaining=remaining))


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
    caption = _build_media_caption(title, fsize, cdur, user_name)

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


async def download_and_upload(client, message, url, quality, callback_query=None):
    """تحميل ورفع الفيديو"""
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
    status_msg = await message.reply_text(t('processing', lang))

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
        # نُفضّل ترميز H.264 (avc1) + صوت AAC (m4a) لأنه متوافق 100% مع مشغّل
        # تلجرام؛ ترميز VP9/AV1 داخل MP4 يسبب تجمّد الصورة أثناء التشغيل.
        # سلسلة احتياطية تنازلية لضمان نجاح التحميل دائماً.
        quality_formats = {
            'best': (
                'bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/'
                'best[height<=1080][ext=mp4]/best[height<=1080]/best'
            ),
            'medium': (
                'bestvideo[height<=720][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/'
                'best[height<=720][ext=mp4]/best[height<=720]/best'
            ),
            '480': (
                'bestvideo[height<=480][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/'
                'best[height<=480][ext=mp4]/best[height<=480]/best'
            ),
            '360': (
                'bestvideo[height<=360][vcodec^=avc1]+bestaudio[ext=m4a]/'
                'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/'
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
            'outtmpl': os.path.join(dl_dir, '%(title)s.%(ext)s'),
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

        def download(use_cookies=True, fmt=None):
            o = dict(ydl_opts)
            if fmt:
                o['format'] = fmt
            if not use_cookies:
                o.pop('cookiefile', None)
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=True)
                return info, ydl.prepare_filename(info)

        # صيغة متساهلة احتياطية عند فشل المُحدّد الصارم (بلا فلترة ترميز/امتداد)
        fallback_fmt = 'bestaudio/best' if is_audio else 'bv*+ba/b/best'

        try:
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
        # العنوان كاملاً (مع إزالة ` حتى لا يكسر تنسيق النسخ) بحد آمن للوصف
        title = (info.get('title') or 'فيديو').replace('`', "'")[:300]
        
        logger.info(f"📊 حجم الملف النهائي: {file_size_mb:.2f} MB")

        # التحقق من الحجم
        if file_size_mb > 2000:
            await status_msg.edit_text(
                f"❌ **الملف كبير جداً!**\n\n"
                f"📊 {file_size_mb:.1f} MB\n"
                f"🔒 الحد الأقصى: 2000 MB"
            )
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
        
        # العنوان داخل تنسيق monospace (`...`) = يُنسخ بالضغط عليه في تيليجرام
        caption = (
            f"🎬 `{title}`\n\n"
            f"📊 {file_size_mb:.1f} MB\n"
            f"⏱️ {int(duration)//60}:{int(duration)%60:02d}\n"
            f"👤 {user_name}"
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
            
            # عرض رسالة التحميلات المتبقية
            daily_limit = subdb.get_daily_limit()
            if daily_limit != -1:  # فقط إذا لم يكن غير محدود
                daily_count = subdb.check_daily_limit(user_id)
                remaining = daily_limit - daily_count
                
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
            if _is_drm_error(error_text):
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
    balance = subdb.get_bonus_downloads(referrer_id)
    logger.info(f"🎁 دعوة جديدة: {new_user_id} عبر {referrer_id} (+{REFERRAL_BONUS})")
    try:
        r_lang = subdb.get_user_language(referrer_id)
        await client.send_message(
            referrer_id,
            t('referral_granted', r_lang, bonus=REFERRAL_BONUS, balance=balance)
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
    balance = subdb.get_bonus_downloads(user_id)
    return t('invite_info', lang, link=link, bonus=REFERRAL_BONUS,
             count=count, balance=balance)


def _invite_button(lang):
    """زر الدعوة الذي يظهر عند انتهاء الحد اليومي."""
    return InlineKeyboardButton(t('btn_invite', lang), callback_data="show_invite")


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

def _member_question_text():
    return (subdb.get_setting('member_question', '') or '').strip()


def _member_question_enabled():
    return subdb.get_setting('member_question_enabled', '0') == '1' and bool(_member_question_text())


def _member_question_version():
    try:
        return int(subdb.get_setting('member_question_version', '0'))
    except (ValueError, TypeError):
        return 0


def _survey_next(user_id):
    """يرجع 'gender' أو 'question' أو None حسب ما ينقص المستخدم للسماح بالتحميل."""
    s = subdb.get_survey(user_id)
    if not s.get('gender'):
        return 'gender'
    if _member_question_enabled() and s.get('q_version') != _member_question_version():
        return 'question'
    return None


def _gender_keyboard(lang):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t('gender_male', lang), callback_data='gender_male'),
        InlineKeyboardButton(t('gender_female', lang), callback_data='gender_female'),
    ]])


def _question_keyboard(lang):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t('answer_yes', lang), callback_data='mq_yes'),
        InlineKeyboardButton(t('answer_no', lang), callback_data='mq_no'),
    ]])


async def _ask_survey_step(send_func, user_id, lang, step):
    """يعرض خطوة الاستبيان المطلوبة (send_func = reply_text أو edit_text)."""
    if step == 'gender':
        await send_func(t('ask_gender', lang), reply_markup=_gender_keyboard(lang))
    else:
        await send_func(_member_question_text(), reply_markup=_question_keyboard(lang))


def _gender_label(gender):
    return '👨 رجل' if gender == 'male' else ('👩 امرأة' if gender == 'female' else '— غير محدد')


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
    s = subdb.get_survey(uid)
    lines = ["📋 <b>إجابات عضو على الاستبيان</b>\n", _member_header_html(user)]
    if _member_question_enabled() and s.get('q_answer'):
        ans = '✅ نعم' if s['q_answer'] == 'yes' else '❌ لا'
        lines.append(f"\n❓ {html.escape(_member_question_text())}: {ans}")
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 رد على العضو", callback_data=f"reply_msg_{uid}")
    ]])
    try:
        await client.send_message(channel_id, "\n".join(lines),
                                  parse_mode=enums.ParseMode.HTML, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"❌ تعذّر نشر إجابات الاستبيان للقناة: {e}")


@app.on_callback_query(filters.regex(r'^gender_(male|female)$'))
async def handle_gender(client, callback_query):
    """يحفظ جنس العضو ثم ينتقل للسؤال التالي أو ينهي الاستبيان."""
    await callback_query.answer()
    uid = callback_query.from_user.id
    lang = subdb.get_user_language(uid)
    subdb.set_gender(uid, 'male' if callback_query.data == 'gender_male' else 'female')
    step = _survey_next(uid)
    if step:
        await _ask_survey_step(callback_query.message.edit_text, uid, lang, step)
    else:
        await callback_query.message.edit_text(t('survey_done', lang))
        await _post_survey_result(client, callback_query.from_user)


@app.on_callback_query(filters.regex(r'^mq_(yes|no)$'))
async def handle_member_question_answer(client, callback_query):
    """يحفظ إجابة العضو على سؤال الأدمن ثم ينهي الاستبيان."""
    await callback_query.answer()
    uid = callback_query.from_user.id
    lang = subdb.get_user_language(uid)
    subdb.set_question_answer(uid, 'yes' if callback_query.data == 'mq_yes' else 'no',
                              _member_question_version())
    step = _survey_next(uid)
    if step:
        await _ask_survey_step(callback_query.message.edit_text, uid, lang, step)
    else:
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
    )


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


@app.on_message(filters.text & filters.regex(
    r'^(📥 تحميلاتي|📥 My Downloads|🎁 ادعُ أصدقاءك|🎁 Invite Friends)$'))
async def handle_feature_buttons(client, message):
    """أزرار 'تحميلاتي' و'ادعُ أصدقاءك' (عربي/إنجليزي)."""
    text = (message.text or '').strip()
    if text in ('📥 تحميلاتي', '📥 My Downloads'):
        await _show_history(client, message)
    else:
        lang = subdb.get_user_language(message.from_user.id)
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
            [KeyboardButton(t('btn_errors', lang)), KeyboardButton(t('btn_subscription', lang))],
            [KeyboardButton(t('btn_change_language', lang))]
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

    # 📋 اسأل العضو الاستبيان (الجنس + سؤال الأدمن) إن لم يجب بعد — الأدمن مُعفى
    if not is_admin(user_id):
        survey_step = _survey_next(user_id)
        if survey_step:
            await _ask_survey_step(message.reply_text, user_id, lang, survey_step)


# معالج الأزرار السريعة
@app.on_message(filters.text & filters.regex(r'^(🍪 Cookies|📊 التقرير اليومي|🔔 الأخطاء|💎 إعدادات الاشتراك|📁 نسخ احتياطي)$'))
async def handle_quick_buttons(client, message):
    """معالج الأزرار السريعة"""
    if not message.from_user:
        return
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    if message.text == "🍪 Cookies":
        await cookies_panel(client, message)
    elif message.text == "📊 التقرير اليومي":
        await send_daily_report(client, message.from_user.id)
    elif message.text == "🔔 الأخطاء":
        await show_errors(client, message)
    elif message.text == "💎 إعدادات الاشتراك":
        await subscription_settings_panel(client, message)
    elif message.text == "📁 نسخ احتياطي":
        await send_database_backup(client, message)


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
async def show_errors(client, message):
    """عرض قائمة الأخطاء للأدمن"""
    pending_errors = {k: v for k, v in user_errors.items() if v['status'] == 'pending'}
    
    if not pending_errors:
        await message.reply_text("✅ **لا توجد أخطاء معلقة!**\n\nجميع المشاكل تم حلها.")
        return
    
    text = "🔔 **قائمة الأخطاء المعلقة**\n\n"
    
    for error_id, error_data in list(pending_errors.items())[:10]:  # آخر 10 أخطاء
        text += f"━━━━━━━━━━━━━━━━\n"
        text += f"🆔 **ID:** `{error_id}`\n"
        text += f"👤 **المستخدم:** {error_data['user_name']} (`{error_data['user_id']}`)\n"
        text += f"🕐 **الوقت:** {error_data['time']}\n"
        text += f"🔗 **الرابط:** `{error_data['url'][:40]}...`\n\n"
    
    text += f"\n📝 **إجمالي الأخطاء المعلقة:** {len(pending_errors)}"
    
    await message.reply_text(text)


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
        await client.send_message(
            chat_id=error_data['user_id'],
            text=f"✅ **تم إصلاح مشكلتك!**\n\n"
                 f"المشكلة التي واجهتها مع الرابط:\n"
                 f"`{error_data['url'][:50]}...`\n\n"
                 f"تم حلها الآن. يمكنك المحاولة مرة أخرى! 🎉"
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


async def probe_and_cleanup_users(client):
    """فحص صامت لكل الأعضاء لمعرفة من بقي ومن غادر، وحذف الغائبين.

    يستخدم send_chat_action (مؤشر "يكتب…") وهو فحص صامت تماماً لا يرى العضو
    أي رسالة. إن نجح فالعضو موجود، وإن فشل بخطأ "غادر" نحذفه من قاعدة البيانات.
    يُعيد (alive, removed, removed_ids).
    """
    users = subdb.get_all_users()
    alive = 0
    removed = 0
    removed_ids = []

    for u in users:
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
            logger.info(f"🧹 بدء الفحص اليومي للأعضاء ({total_before})...")

            alive, removed, removed_ids = await probe_and_cleanup_users(app)

            await app.send_message(
                admin_id,
                "🧹 **الفحص اليومي للأعضاء (3 فجراً)**\n\n"
                f"👥 قبل الفحص: **{total_before}**\n"
                f"✅ موجودون فعلاً: **{alive}**\n"
                f"🗑️ حُذفوا (غادروا/حظروا): **{removed}**\n"
                f"📊 العدد الحقيقي الآن: **{alive}**"
            )
            logger.info(f"🧹 انتهى الفحص: {alive} موجود، {removed} محذوف")
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


@app.on_message(filters.text & filters.regex(r'https?://\S+'))
async def handle_url(client, message):
    if not message.from_user:
        return
    
    url = message.text.strip()
    user_id = message.from_user.id

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

    # 📋 استبيان إجباري قبل التحميل (الجنس + سؤال الأدمن) — الأدمن مُعفى
    if not is_admin(user_id):
        survey_step = _survey_next(user_id)
        if survey_step:
            await _ask_survey_step(message.reply_text, user_id, lang, survey_step)
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
        daily_limit = subdb.get_daily_limit()
        
        # فقط فحص إذا كان الحد ليس "غير محدود" (-1)
        if daily_limit != -1:
            daily_count = subdb.check_daily_limit(user_id)
            
            if daily_count >= daily_limit:
                await status.edit_text(
                    t('daily_limit_exceeded', lang, limit=daily_limit, count=daily_count),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t('subscribe_now', lang), callback_data="pay_binance")],
                        [InlineKeyboardButton(t('contact_developer', lang), url=f"https://t.me/{subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))}")]
                    ])
                )
                return
    
    max_duration_minutes = subdb.get_max_duration()
    max_duration_seconds = max_duration_minutes * 60
    
    # If not subscribed and exceeds max duration
    if not is_subscribed and duration and duration > max_duration_seconds:
        await show_subscription_screen(client, status, user_id, title, duration, max_duration_minutes)
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



@app.on_callback_query(filters.regex(r'^quality_'))
async def handle_quality(client, callback_query):
    await callback_query.answer()
    
    user_id = callback_query.from_user.id
    quality = callback_query.data.replace("quality_", "")
    
    if user_id not in pending_downloads:
        lang = subdb.get_user_language(user_id)
        await callback_query.message.edit_text(t('error_occurred', lang, error="Session expired. Send link again."))
        return
    
    url = pending_downloads[user_id]
    lang = subdb.get_user_language(user_id)
    await callback_query.message.edit_text(t('start_download', lang))
    
    await download_and_upload(client, callback_query.message, url, quality, callback_query)

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

async def show_subscription_screen(client, message, user_id, title, duration, max_minutes):
    """عرض شاشة الاشتراك للمستخدمين غير المشتركين"""
    duration_minutes = int(duration) // 60
    telegram_support = subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))
    binance_id = subdb.get_setting('binance_pay_id', os.getenv('BINANCE_PAY_ID', ''))
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('binance_pay', lang), callback_data=f"pay_binance")],
        [InlineKeyboardButton(t('visa_card', lang), callback_data=f"pay_visa")],
        [InlineKeyboardButton(t('mastercard', lang), callback_data=f"pay_mastercard")],
        [InlineKeyboardButton(t('telegram_contact', lang), url=f"https://t.me/{telegram_support}")]
    ])
    
    text = (
        t('subscription_required', lang, title=title, duration=duration_minutes, max_duration=max_minutes) +
        "\n\n━━━━━━━━━━━━━━━━\n\n" +
        t('subscription_benefits', lang) +
        "\n\n" +
        t('choose_payment_method', lang)
    )
    
    await message.edit_text(text, reply_markup=keyboard)


@app.on_callback_query(filters.regex(r'^pay_'))
async def handle_payment_method(client, callback_query):
    """معالج طرق الدفع"""
    user_id = callback_query.from_user.id
    payment_method = callback_query.data.replace('pay_', '')
    
    # Get user language
    lang = subdb.get_user_language(user_id)
    
    binance_id = subdb.get_setting('binance_pay_id', os.getenv('BINANCE_PAY_ID', ''))
    telegram_support = subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))
    price = subdb.get_setting('subscription_price', '10')
    
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
    
    # حفظ طريقة الدفع المختارة
    pending_downloads[user_id] = {'payment_method': payment_method}
    
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
    
    telegram_support = subdb.get_setting('telegram_support', os.getenv('SUPPORT_USERNAME', ''))
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t('binance_pay', lang), callback_data="pay_binance")],
        [InlineKeyboardButton(t('visa_card', lang), callback_data="pay_visa")],
        [InlineKeyboardButton(t('mastercard', lang), callback_data="pay_mastercard")],
        [InlineKeyboardButton(t('telegram_contact', lang), url=f"https://t.me/{telegram_support}")]
    ])
    
    # Show subscription options
    text = (
        t('subscription_required', lang, title="Video", duration=10, max_duration=5) +
        "\n\n━━━━━━━━━━━━━━━━\n\n" +
        t('subscription_benefits', lang) +
        "\n\n" +
        t('choose_payment_method', lang)
    )
    
    await callback_query.message.edit_text(
        text,
        reply_markup=keyboard
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
    
    # حفظ الدفعة في قاعدة البيانات
    payment_id = subdb.add_payment(
        user_id=user_id,
        payment_method=payment_method,
        proof_file_id=message.photo.file_id,
        proof_message_id=message.id
    )
    
    # حذف من pending
    del pending_downloads[user_id]
    
    # إرسال إشعار للمستخدم
    await message.reply_text(
        "✅ **تم استلام إثبات الدفع!**\n\n"
        "سيتم مراجعة دفعتك من قبل المسؤول.\n"
        "ستصلك رسالة فور تفعيل اشتراكك! 🎉\n\n"
        "⏳ الانتظار المتوقع: أقل من 24 ساعة"
    )
    
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
                text=(
                    "❌ **تم رفض دفعتك**\n\n"
                    "قد يكون هناك مشكلة في إثبات الدفع.\n"
                    f"تواصل مع المطور: @{telegram_support}"
                )
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
    rows.append([InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")])
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
    await callback_query.answer()


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
    price = subdb.get_setting('subscription_price', '10')
    duration_days = subdb.get_setting('subscription_duration_days', '30')
    stats = subdb.get_user_stats()
    adult_on = adult_filter_enabled()
    adult_label = f"🔞 حظر المحتوى الإباحي: {'✅ مُفعّل' if adult_on else '❌ متوقف'}"
    dl_on = downloads_enabled()
    dl_label = "⏸️ إيقاف التحميل للجميع" if dl_on else "▶️ تشغيل التحميل للجميع"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(dl_label, callback_data="sub_toggle_downloads")],
        [InlineKeyboardButton("⏱️ تحديد المدة القصوى", callback_data="sub_set_duration")],
        [InlineKeyboardButton("💰 تحديد السعر", callback_data="sub_set_price")],
        [InlineKeyboardButton(adult_label, callback_data="sub_toggle_adult")],
        [
            InlineKeyboardButton("➕ موقع محظور", callback_data="sub_add_domain"),
            InlineKeyboardButton("➕ كلمة محظورة", callback_data="sub_add_keyword"),
        ],
        [InlineKeyboardButton("📋 القائمة المحظورة المخصصة", callback_data="sub_list_blocked")],
        [InlineKeyboardButton("❓ سؤال للأعضاء", callback_data="sub_member_question")],
        [InlineKeyboardButton("📢 الاشتراك الإجباري", callback_data="sub_fsub")],
        [InlineKeyboardButton("👥 عرض المشتركين", callback_data="sub_view_subscribers")],
        [InlineKeyboardButton("📊 عرض آخر 50 مستخدم", callback_data="sub_recent_users")],
        [InlineKeyboardButton("💳 الدفوعات المعلقة", callback_data="sub_pending_payments")],
        [InlineKeyboardButton("📊 إحصائيات الأعضاء", callback_data="sub_member_stats")],
        [InlineKeyboardButton("🔍 بحث عن عضو", callback_data="sub_search_user")],
        [InlineKeyboardButton("🚫 معاقبة عضو (حظر/رفع)", callback_data="sub_punish_user")],
        [InlineKeyboardButton("📛 المحظورون", callback_data="sub_banned_list")],
        [InlineKeyboardButton("✏️ ترقية عضو", callback_data="sub_promote_user")],
        [InlineKeyboardButton("❌ إلغاء ترقية", callback_data="sub_demote_user")],
        [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="sub_broadcast")]
    ])

    text = (
        f"💎 **إعدادات الاشتراك**\n\n"
        f"⏱️ **الحد الأقصى للمجاني:** {max_duration} دقيقة\n"
        f"💰 **سعر الاشتراك:** ${price}\n"
        f"📅 **مدة الاشتراك:** {duration_days} يوم\n"
        f"🔞 **حظر المحتوى الإباحي:** {'مُفعّل ✅' if adult_on else 'متوقف ❌'}\n"
        f"⏯️ **التحميل للأعضاء:** {'يعمل ▶️' if dl_on else 'متوقف ⏸️'}\n\n"
        f"📊 **الإحصائيات:**\n"
        f"• المجموع: {stats['total']} عضو\n"
        f"• المشتركون: {stats['subscribed']} 💎\n"
        f"• العاديون: {stats['free']} 🆓\n\n"
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
        q = _member_question_text()
        enabled = _member_question_enabled()
        state = '✅ مُفعّل' if enabled else '❌ متوقف'
        qs = subdb.get_question_stats(_member_question_version())
        gs = subdb.get_gender_stats()
        text = (
            "❓ **سؤال إجباري للأعضاء (نعم/لا)**\n\n"
            f"الحالة: {state}\n"
            f"السؤال الحالي: {q or '— لا يوجد —'}\n\n"
            f"📊 إجابات السؤال: ✅ نعم {qs['yes']} | ❌ لا {qs['no']}\n"
            f"👥 الجنس: 👨 {gs['male']} | 👩 {gs['female']}\n\n"
            "ملاحظة: سؤال الجنس يُطرح دائماً قبل التحميل. هنا تضيف سؤالك الخاص."
        )
        rows = [[InlineKeyboardButton("✏️ تعيين/تغيير السؤال", callback_data="sub_setquestion")]]
        if q:
            rows.append([InlineKeyboardButton(
                "🔕 إيقاف السؤال" if enabled else "🔔 تفعيل السؤال",
                callback_data="sub_mqtoggle")])
        rows.append([InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")])
        await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
        await callback_query.answer()
        return

    if action == 'setquestion':
        await callback_query.message.edit_text(
            "✏️ **تعيين سؤال الأعضاء**\n\n"
            "أرسل نص سؤالك (يُجاب عليه بنعم/لا).\n"
            "سيُطلب من كل عضو الإجابة عليه قبل التحميل.",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'set_member_question'}
        await callback_query.answer()
        return

    if action == 'mqtoggle':
        if not _member_question_text():
            await callback_query.answer("لا يوجد سؤال لتفعيله", show_alert=True)
            return
        new_state = '0' if _member_question_enabled() else '1'
        subdb.set_setting('member_question_enabled', new_state)
        await callback_query.answer(
            "🔔 تم تفعيل السؤال" if new_state == '1' else "🔕 تم إيقاف السؤال",
            show_alert=True)
        return

    if action == 'banned_list':
        text, kb = _banned_list_view()
        await callback_query.message.edit_text(text, reply_markup=kb)
        await callback_query.answer()
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
            "الزر للإعلان ويُحتسب عند ضغط «تحقق». (يُكتشف تلقائياً)",
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
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱️ تغيير الحد الزمني", callback_data="change_time_limit")],
            [InlineKeyboardButton("🔢 تغيير الحد اليومي", callback_data="change_daily_limit")],
            [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]
        ])
        
        await callback_query.message.edit_text(
            "⚙️ **تحديد المدة القصوى**\n\n"
            f"🕒 **الحد الزمني لغير المشتركين:** {max_duration} دقيقة\n"
            f"🔁 **الحد اليومي المسموح به:** {daily_limit} مرات\n\n"
            "💡 **ملاحظات:**\n"
            "• هذه القيود تطبق فقط على المستخدمين غير المشتركين\n"
            "• المشتركون VIP لديهم حرية كاملة بلا قيود\n\n"
            "**اختر الإجراء المطلوب:**",
            reply_markup=keyboard
        )
        
    elif action == 'set_price':
        await callback_query.message.edit_text(
            "💰 **تحديد سعر الاشتراك**\n\n"
            "أرسل السعر بالدولار (مثلاً: 10)\n\n"
            "⚠️ القيمة الحالية: $" + subdb.get_setting('subscription_price', '10'),
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[callback_query.from_user.id] = {'waiting_for': 'subscription_price'}
        
    elif action == 'view_subscribers':
        subscribers = subdb.get_all_subscribers()
        
        if not subscribers:
            await callback_query.message.edit_text(
                "📝 **لا يوجد مشتركون حالياً**",
                reply_markup=_sub_settings_back_kb()
            )
            return
        
        text = "👥 **قائمة المشتركين**\n\n"
        
        for idx, sub in enumerate(subscribers[:20], 1):  # أول 20 مشترك
            user_id, username, first_name, end_date, method = sub
            username_str = f"@{username}" if username else "لا يوجد"
            name = first_name or "مستخدم"
            
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
            
            text += f"{idx}. {name} ({username_str})\n"
            text += f"   🆔 `{user_id}` | ⏳ {days_str}\n\n"
        
        text += f"\n📊 **إجمالي المشتركين:** {len(subscribers)}"

        await callback_query.message.edit_text(text, reply_markup=_sub_settings_back_kb())
        
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
        
        text = "📊 **إحصائيات الأعضاء**\n\n"
        text += f"👥 **إجمالي الأعضاء:** {stats['total']}\n"
        text += f"💎 **المشتركون:** {stats['subscribed']}\n"
        text += f"🆓 **العاديون:** {stats['free']}\n\n"
        
        # عرض بعض المشتركين مع الأيام المتبقية
        if stats['subscribed'] > 0:
            text += "━━━━━━━━━━━━━━━━\n"
            text += "**المشتركون الحاليون:**\n\n"
            
            count = 0
            for user in all_users:
                user_id, username, first_name, is_subscribed, subscription_end = user
                if is_subscribed:
                    days_left = subdb.get_days_remaining(user_id)
                    name = first_name or "مستخدم"
                    text += f"• {name}: {days_left} يوم متبقية\n"
                    count += 1
                    if count >= 10:  # أول 10 مشتركين
                        break

        await callback_query.message.edit_text(text, reply_markup=_sub_settings_back_kb())
    
    elif action == 'recent_users':
        users = subdb.get_recent_users(50)
        
        if not users:
            await callback_query.message.edit_text("📝 **لا يوجد مستخدمون**")
            return
        
        text = "📊 **آخر 50 مستخدم**\n\n"
        
        for idx, user in enumerate(users[:50], 1):
            user_id, username, first_name, is_subscribed = user
            username_str = f"@{username}" if username else "لا يوجد"
            name = first_name or "مستخدم"
            status = "💎" if is_subscribed else "🆓"
            
            text += f"{idx}. {status} {name} ({username_str})\n"
            text += f"   🆔 `{user_id}`\n\n"
        
        text += f"\n📊 **إجمالي المستخدمين:** {len(users)}\n\n"
        text += "💡 **لمراسلة أي مستخدم:**\n"
        text += "استخدم زر 'رسالة خاصة' وأرسل ID المستخدم"

        await callback_query.message.edit_text(text, reply_markup=_sub_settings_back_kb())
    
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📧 إرسال لجميع المستخدمين", callback_data="msg_broadcast_all")],
            [InlineKeyboardButton("👤 إرسال لمستخدم محدد", callback_data="msg_direct_user")],
            [InlineKeyboardButton("« رجوع", callback_data="back_to_sub_settings")]
        ])
        
        stats = subdb.get_user_stats()
        await callback_query.message.edit_text(
            "📢 **نظام الإرسال الجماعي**\n\n"
            f"👥 **عدد المستخدمين:** {stats['total']}\n"
            f"💎 **المشتركون:** {stats['subscribed']}\n"
            f"🆓 **العاديون:** {stats['free']}\n\n"
            "**اختر نوع الإرسال:**",
            reply_markup=keyboard
        )
    
    await callback_query.answer()


@app.on_callback_query(filters.regex(r'^(change_time_limit|change_daily_limit|back_to_sub_settings)$'))
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
        await callback_query.message.edit_text(
            "📢 **إرسال رسالة لجميع المستخدمين**\n\n"
            "أرسل الرسالة التي تريد إرسالها لجميع مستخدمي البوت\n\n"
            f"⚠️ سيتم إرسالها لـ **{subdb.get_user_stats()['total']}** مستخدم",
            reply_markup=_sub_settings_back_kb()
        )
        pending_downloads[user_id] = {'waiting_for': 'broadcast_message'}

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
            
        elif waiting_for == 'subscription_price':
            price = float(message.text.strip())
            if price < 0:
                await message.reply_text("❌ يجب أن يكون السعر أكبر من 0")
                return
            
            subdb.set_setting('subscription_price', str(price))
            await message.reply_text(
                f"✅ **تم تحديث السعر**\n\n"
                f"السعر الجديد: ${price}"
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

        elif waiting_for == 'set_member_question':
            q = (message.text or '').strip()
            if not q:
                await message.reply_text("❌ السؤال فارغ. أرسل نص السؤال.")
                return
            subdb.set_setting('member_question', q)
            subdb.set_setting('member_question_enabled', '1')
            new_version = int(subdb.get_setting('member_question_version', '0')) + 1
            subdb.set_setting('member_question_version', str(new_version))
            await message.reply_text(
                f"✅ **تم تعيين سؤال الأعضاء وتفعيله:**\n\n{q}\n\n"
                "سيُطلب من كل عضو الإجابة عليه (نعم/لا) قبل التحميل."
            )
            del pending_downloads[user_id]

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

            # الحصول على جميع المستخدمين
            all_users = subdb.get_all_users()

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

            for user in all_users:
                try:
                    # Get each user's preferred language
                    user_lang = subdb.get_user_language(user[0])

                    # أزرار: نعم / لا + رد للمطور
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(t('btn_yes', user_lang), callback_data=f"bcyes_{bid}"),
                         InlineKeyboardButton(t('btn_no', user_lang), callback_data=f"bcno_{bid}")],
                        [InlineKeyboardButton(t('reply_button', user_lang), callback_data=f"reply_msg_{user_id}")],
                    ])

                    await client.send_message(
                        chat_id=user[0],  # user_id
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
                        subdb.delete_user(user[0])
                        removed_count += 1
                    except Exception:
                        pass
                    fail_count += 1
                except Exception:
                    # خطأ مؤقت/غير معروف → نُبقي العضو
                    fail_count += 1

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
            logger.info(f"📢 Broadcast #{bid}: {success_count} نجح, {fail_count} فشل, {removed_count} محذوف")
        
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
            
            text = (
                f"🔍 **معلومات المستخدم**\n\n"
                f"👤 **الاسم:** {name}\n"
                f"🆔 **User ID:** `{user_id_found}`\n"
                f"📱 **Username:** {username_str}\n"
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
            [KeyboardButton(t('btn_errors', lang)), KeyboardButton(t('btn_subscription', lang))],
            [KeyboardButton("📁 نسخ احتياطي"), KeyboardButton(t('btn_change_language', lang))]
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

    # 📋 اسأل العضو الجديد الاستبيان (الجنس + سؤال الأدمن) فور اختيار اللغة
    if not is_admin(user_id):
        survey_step = _survey_next(user_id)
        if survey_step:
            await _ask_survey_step(
                lambda text, reply_markup=None: client.send_message(
                    user_id, text, reply_markup=reply_markup),
                user_id, lang, survey_step
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
    
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n⏹️ تم الإيقاف")



if __name__ == "__main__":
    main()

