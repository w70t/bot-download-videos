# -*- coding: utf-8 -*-
"""
محوّلات الروابط الخاصة - Link Resolvers
=======================================
- سناب شات سبوت لايت: استخراج رابط الفيديو الخام من الصفحة مباشرة.
- روابط الأغاني (Shazam/Apple Music/Spotify): لا تُحمّل مباشرة (Shazam يتعرّف
  فقط على الأغنية، وApple/Spotify مشفّرة بـ DRM). الحل: استخراج اسم الأغنية
  والفنان ثم البحث عنها وتحميلها من يوتيوب.
"""

import os
import re
import logging
from urllib.parse import urlparse

import yt_dlp

from url_utils import is_safe_url, PLATFORM_URL_MARKERS
from cookies_manager import get_cookie_file_for_url

logger = logging.getLogger(__name__)


def resolve_snapchat_spotlight(url: str, timeout: int = 20) -> str:
    """يجلب صفحة سناب سبوت لايت ويستخرج رابط الفيديو الخام المباشر (أنظف نسخة
    متاحة، غالباً بلا لوقو لأن اللوقو طبقة واجهة لا جزء من الملف) من وسم
    og:video أو من رابط CDN داخل الصفحة، فيُحمّل مباشرة بدل مسار سناب الضعيف
    في yt-dlp. يعمل للسبوت لايت العام فقط؛ عند أي فشل يعيد الرابط الأصلي.
    يقبل روابط المشاركة snapchat.com/t/... (يتبع التوجيه للصفحة الحقيقية)."""
    low = (url or '').lower()
    if 'snapchat.com' not in low:
        return url
    import urllib.request
    from http.cookiejar import MozillaCookieJar
    try:
        cj = MozillaCookieJar()
        cookie_file = get_cookie_file_for_url(url)
        if cookie_file and os.path.exists(cookie_file):
            try:
                cj.load(cookie_file, ignore_discard=True, ignore_expires=True)
            except Exception:
                pass
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [
            ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/120.0.0.0 Safari/537.36'),
            ('Accept-Language', 'en-US,en;q=0.9'),
        ]
        with opener.open(url, timeout=timeout) as resp:
            html_text = resp.read(1500000).decode('utf-8', 'ignore')

        # 1) og:video — الأنسب لأن معاينات الروابط تعتمد عليه فيبقى مستقراً
        for pat in (
            r'property=["\']og:video(?::secure_url)?["\'][^>]*content=["\']([^"\']+\.mp4[^"\']*)["\']',
            r'content=["\']([^"\']+\.mp4[^"\']*)["\'][^>]*property=["\']og:video',
        ):
            m = re.search(pat, html_text)
            if m:
                cand = m.group(1).replace('&amp;', '&')
                if is_safe_url(cand):
                    logger.info(f"🎯 سناب سبوت لايت (og:video): {cand[:90]}")
                    return cand

        # 2) أي رابط فيديو خام من CDN سناب داخل JSON المضمّن (قد تكون الشرطات
        #    مهرّبة \/ لذا نطابق حتى علامة الاقتباس ثم نفكّ التهريب)
        m = re.search(r'"(https:[^"]*sc-cdn\.net[^"]*\.mp4[^"]*)"', html_text)
        if m:
            cand = m.group(1).replace('\\/', '/').replace('&amp;', '&')
            if is_safe_url(cand):
                logger.info(f"🎯 سناب سبوت لايت (cdn): {cand[:90]}")
                return cand
    except Exception as e:
        logger.warning(f"⚠️ تعذّر استخراج سناب سبوت لايت ({url[:60]}): {e}")
    return url


# ═══════════════════════════════════════════════════════════════
# إنستغرام: خطة بديلة عبر مرآة عامة (بدون كوكيز)
# إنستغرام يحجب الوصول المجهول لبيانات الوسائط ويعيد "empty media response"،
# فيفشل yt-dlp في استخراج الريلز/المنشورات للزوّار حتى مع كوكيز منتهية. مرايا
# InstaFix العامة تعيد توجيهاً مباشراً لملف الفيديو على CDN إنستغرام عند الطلب
# بوكيل مستخدم بوت، فنستخدمها للحصول على رابط mp4 مباشر يحمّله yt-dlp عادياً.
# ═══════════════════════════════════════════════════════════════

# مرايا InstaFix العامة، تُجرَّب بالترتيب. يمكن إضافة/تغيير المرايا بمتغيّر
# البيئة INSTAGRAM_PROXY_HOSTS (مفصولة بفواصل) دون تعديل الكود إن تعطّلت مرآة.
_INSTAGRAM_PROXY_HOSTS = [
    h.strip() for h in os.getenv(
        'INSTAGRAM_PROXY_HOSTS', 'kkinstagram.com'
    ).split(',') if h.strip()
]

# مسار منشور فيديو/ريلز في إنستغرام (نتجاهل الستوري/البروفايل)
_INSTAGRAM_MEDIA_RE = re.compile(r'/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+', re.I)

# وكيل مستخدم بوت: المرايا تعيد توجيهاً مباشراً للفيديو للبوتات، وصفحة هبوط
# للمتصفحات، لذا ننتحل بوت معاينة روابط للحصول على ملف mp4 مباشرة.
_BOT_UA = 'Mozilla/5.0 (compatible; TelegramBot)'

# وكيل متصفح كامل لاتّباع تحويل الروابط المختصرة (بعض المنصات ترفض وكيل البوت
# على صفحة التحويل).
_BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
               '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def resolve_instagram_media(url: str, timeout: int = 20):
    """يحوّل رابط ريلز/منشور إنستغرام إلى رابط الفيديو المباشر (mp4) عبر مرآة
    عامة لا تتطلّب كوكيز، ليُحمّل حين يعجز yt-dlp عن الوصول المجهول.

    يعيد رابط mp4 مباشراً عند النجاح، أو None لغير روابط إنستغرام أو لمنشورات
    الصور (المرآة تعيد صورة لا فيديو) أو عند أي فشل — فيبقى المسار الأصلي
    (كوكيز إن توفّرت، أو مسار الصور عبر gallery-dl)."""
    import urllib.request
    low = (url or '').lower()
    if not any(h in low for h in ('instagram.com', 'instagr.am')):
        return None
    try:
        path = urlparse(url).path
    except Exception:
        return None
    m = _INSTAGRAM_MEDIA_RE.search(path)
    if not m:
        return None  # ستوري/بروفايل/رابط غير منشور — لا مرآة له
    media_path = m.group(0)
    for proxy_host in _INSTAGRAM_PROXY_HOSTS:
        proxy_url = f"https://{proxy_host}{media_path}"
        try:
            req = urllib.request.Request(proxy_url, headers={
                'User-Agent': _BOT_UA,
                'Accept': '*/*',
            })
            # urlopen يتبع التوجيهات؛ geturl() = الرابط النهائي (mp4 على CDN)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = (resp.headers.get_content_type() or '').lower()
                final = resp.geturl()
            if ctype.startswith('video/') and is_safe_url(final):
                logger.info(f"🎯 إنستغرام عبر {proxy_host}: {final[:90]}")
                return final
            logger.info(f"ℹ️ {proxy_host} لم يُرجع فيديو (نوع={ctype}) لـ {media_path}")
        except Exception as e:
            logger.warning(f"⚠️ تعذّر حل إنستغرام عبر {proxy_host} ({media_path}): {e}")
    return None


# ═══════════════════════════════════════════════════════════════
# مرآة تيك توك العامة (بديل عند حجب IP الخادم)
# تيك توك يحجب عناوين مراكز البيانات فيعيد "Your IP address is blocked"،
# فيفشل yt-dlp حتى مع كوكيز صالحة (الحجب على مستوى الـ IP قبل الكوكيز). مرآة
# عامة (tikwm) تجلب الفيديو من عنوان IP مختلف وتعيد رابط mp4 مباشراً بلا علامة
# مائية وبلا كوكيز، فنحمّله عبر yt-dlp عادياً. يمكن تغيير/إضافة مرايا بمتغيّر
# البيئة TIKTOK_PROXY_HOSTS (مفصولة بفواصل) دون تعديل الكود إن تعطّلت مرآة.
# ═══════════════════════════════════════════════════════════════
_TIKTOK_API_HOSTS = [
    h.strip() for h in os.getenv(
        'TIKTOK_PROXY_HOSTS', 'tikwm.com'
    ).split(',') if h.strip()
]


def _tiktok_candidate_urls(url: str):
    """يبني روابط تيك توك المرشّحة للمرآة بالترتيب: الرابط الكامل الموسّع وبلا
    بارامترات أولاً (المرايا تفشل بـ"Url parsing failed" مع الروابط المختصرة
    vt/vm أو المذيّلة ببارامترات تتبّع مثل ?_t=...)، ثم الرابط الأصلي احتياطاً."""
    import urllib.request
    candidates = []
    low = (url or '').lower()
    # وسّع الروابط المختصرة (vt./vm.tiktok.com أو /t/) لرابط الفيديو الكامل
    if any(s in low for s in ('vt.tiktok.', 'vm.tiktok.', '/t/')):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': _BROWSER_UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                final = (r.geturl() or '').split('?', 1)[0]
            if final:
                candidates.append(final)
        except Exception as e:
            logger.warning(f"⚠️ تعذّر توسيع رابط تيك توك المختصر: {e}")
    # الرابط بلا بارامترات، ثم الأصلي (بلا تكرار)
    for c in ((url or '').split('?', 1)[0], url):
        if c and c not in candidates:
            candidates.append(c)
    return candidates


def _tiktok_media_from_mirror(host: str, target_url: str, timeout: int):
    """يستعلم مرآة تيك توك واحدة عن رابط فيديو مباشر، أو None عند غياب الفيديو."""
    import json
    import urllib.parse
    import urllib.request
    api_url = f"https://{host}/api/?url={urllib.parse.quote(target_url, safe='')}"
    req = urllib.request.Request(api_url, headers={
        'User-Agent': _BOT_UA,
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read(2_000_000).decode('utf-8', 'ignore'))
    data = (payload or {}).get('data') or {}
    # hdplay/play بلا علامة مائية، wmplay احتياطي بعلامة مائية
    for key in ('hdplay', 'play', 'wmplay'):
        media = data.get(key)
        if not media or not isinstance(media, str):
            continue
        # المرآة قد تعيد مساراً نسبياً (/video/...) أو رابطاً كاملاً
        if media.startswith('/'):
            media = f"https://{host}{media}"
        if media.lower().startswith(('http://', 'https://')) and is_safe_url(media):
            return media
    return None


def resolve_tiktok_media(url: str, timeout: int = 20):
    """يحوّل رابط تيك توك إلى رابط الفيديو المباشر (mp4) عبر مرآة عامة لا تتطلّب
    كوكيز، ليُحمّل حين يحجب تيك توك عنوان IP الخادم فيعجز yt-dlp عن الوصول.

    يعيد رابط mp4 مباشراً عند النجاح، أو None لغير روابط تيك توك أو عند أي فشل
    (بما فيها منشورات الصور التي لا تُرجع فيديو) — فيبقى المسار الأصلي دون
    تغيير في السلوك."""
    low = (url or '').lower()
    if 'tiktok.' not in low:
        return None
    candidates = _tiktok_candidate_urls(url)
    for host in _TIKTOK_API_HOSTS:
        for target in candidates:
            try:
                media = _tiktok_media_from_mirror(host, target, timeout)
                if media:
                    logger.info(f"🎯 تيك توك عبر {host}: {media[:90]}")
                    return media
            except Exception as e:
                logger.warning(f"⚠️ تعذّر حل تيك توك عبر {host}: {e}")
    logger.info("ℹ️ لم تُرجع أي مرآة رابط فيديو تيك توك")
    return None


def resolve_tiktok_images(url: str, timeout: int = 20):
    """يعيد قائمة روابط صور منشور تيك توك المصوّر (سلايدشو) عبر مرآة عامة بلا
    كوكيز، حين يفشل gallery-dl (حجب IP الخادم). قائمة روابط مباشرة مرتّبة، أو
    قائمة فارغة لغير تيك توك أو لمنشور فيديو (لا صور) أو عند أي فشل."""
    import json
    import urllib.parse
    import urllib.request
    low = (url or '').lower()
    if 'tiktok.' not in low:
        return []
    for host in _TIKTOK_API_HOSTS:
        for target in _tiktok_candidate_urls(url):
            try:
                api_url = f"https://{host}/api/?url={urllib.parse.quote(target, safe='')}"
                req = urllib.request.Request(api_url, headers={
                    'User-Agent': _BOT_UA,
                    'Accept': 'application/json',
                })
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read(4_000_000).decode('utf-8', 'ignore'))
                images = ((payload or {}).get('data') or {}).get('images')
                if not isinstance(images, list) or not images:
                    continue
                out = []
                for img in images:
                    # عنصر الصورة قد يكون رابطاً نصياً أو كائناً فيه url
                    src = img if isinstance(img, str) else (
                        img.get('url') if isinstance(img, dict) else None)
                    if isinstance(src, str) and src.startswith('/'):
                        src = f"https://{host}{src}"
                    if (isinstance(src, str)
                            and src.lower().startswith(('http://', 'https://'))
                            and is_safe_url(src)):
                        out.append(src)
                if out:
                    logger.info(f"🎯 صور تيك توك عبر {host}: {len(out)} صورة")
                    return out
            except Exception as e:
                logger.warning(f"⚠️ تعذّر جلب صور تيك توك عبر {host}: {e}")
    return []


# ═══════════════════════════════════════════════════════════════
# مرآة تويتر/إكس العامة (بديل عند فشل yt-dlp)
# تويتر/X قد يحجب/يقيّد الوصول (403، حظر جغرافي/حقوق بث، محتوى حسّاس) فيفشل
# yt-dlp. مرايا fx/vxtwitter العامة تعيد بيانات المنشور مع رابط mp4 مباشر على
# video.twimg.com بلا كوكيز. غيّر/أضف مرايا بمتغيّر البيئة TWITTER_PROXY_HOSTS.
# ═══════════════════════════════════════════════════════════════
_TWITTER_API_HOSTS = [
    h.strip() for h in os.getenv(
        'TWITTER_PROXY_HOSTS', 'api.vxtwitter.com,api.fxtwitter.com'
    ).split(',') if h.strip()
]

_TWITTER_STATUS_RE = re.compile(r'/status(?:es)?/(\d+)')


def _twitter_api_url(host: str, status_id: str) -> str:
    """مسار API المرآة حسب نوعها (fxtwitter يختلف عن vxtwitter)."""
    if 'fxtwitter' in host or 'fixupx' in host:
        return f"https://{host}/x/status/{status_id}"
    return f"https://{host}/Twitter/status/{status_id}"


def _extract_twitter_media(payload):
    """يستخرج رابط فيديو mp4 مباشر من رد مرآة تويتر (يدعم شكلي vx/fxtwitter)."""
    if not isinstance(payload, dict):
        return None
    # vxtwitter: media_extended فيها نوع صريح
    for it in (payload.get('media_extended') or []):
        if isinstance(it, dict) and it.get('type') in ('video', 'gif') and it.get('url'):
            return it['url']
    # vxtwitter: mediaURLs قائمة روابط مباشرة — اختر mp4
    for u in (payload.get('mediaURLs') or []):
        if isinstance(u, str) and '.mp4' in u.lower():
            return u
    # fxtwitter: الوسائط متداخلة تحت tweet.media
    media = (payload.get('tweet') or {}).get('media') or {}
    for key in ('videos', 'all'):
        for it in (media.get(key) or []):
            if isinstance(it, dict) and it.get('type') in ('video', 'gif') and it.get('url'):
                return it['url']
    return None


def _twitter_payload_sensitive(payload):
    """هل تغريدة رد المرآة مُعلَّمة كمحتوى حسّاس (NSFW) في X؟
    يدعم شكلي vxtwitter (علم في الجذر) وfxtwitter (داخل tweet)."""
    if not isinstance(payload, dict):
        return False
    if payload.get('possibly_sensitive') or payload.get('sensitive'):
        return True
    tweet = payload.get('tweet')
    return bool(isinstance(tweet, dict) and
                (tweet.get('possibly_sensitive') or tweet.get('sensitive')))


def twitter_mirror_lookup(url: str, timeout: int = 20):
    """يستعلم مرايا تويتر ويعيد (رابط الفيديو المباشر أو None، هل التغريدة
    حسّاسة/NSFW؟). علم الحساسية يتيح للبوت رفض المحتوى الإباحي عبر المرآة —
    نفس تصنيف age_limit الذي يعطيه yt-dlp حين ينجح الاستخراج المباشر."""
    import json
    import urllib.request
    low = (url or '').lower()
    if not any(m in low for m in PLATFORM_URL_MARKERS['twitter']):
        return None, False
    m = _TWITTER_STATUS_RE.search(url or '')
    if not m:
        return None, False  # ليس رابط منشور (بروفايل/بحث) — لا مرآة له
    status_id = m.group(1)
    for host in _TWITTER_API_HOSTS:
        api_url = _twitter_api_url(host, status_id)
        try:
            req = urllib.request.Request(api_url, headers={
                'User-Agent': _BOT_UA,
                'Accept': 'application/json',
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read(2_000_000).decode('utf-8', 'ignore'))
            media = _extract_twitter_media(payload)
            if media and media.lower().startswith(('http://', 'https://')) and is_safe_url(media):
                sensitive = _twitter_payload_sensitive(payload)
                logger.info(f"🎯 تويتر عبر {host}: {media[:90]}"
                            + (" (⚠️ حسّاس)" if sensitive else ""))
                return media, sensitive
            logger.info(f"ℹ️ {host} لم يُرجع فيديو تويتر")
        except Exception as e:
            logger.warning(f"⚠️ تعذّر حل تويتر عبر {host}: {e}")
    return None, False


def resolve_twitter_media(url: str, timeout: int = 20):
    """يحوّل رابط تويتر/X إلى رابط الفيديو المباشر (mp4) عبر مرآة عامة بلا كوكيز،
    ليُحمّل حين يفشل yt-dlp (حجب/تقييد). يعيد رابط mp4 أو None لغير روابط تويتر
    أو للمنشورات بلا فيديو أو عند أي فشل — فيبقى المسار الأصلي دون تغيير.
    (لا يفحص الحساسية — استخدم twitter_mirror_lookup للفحص مع فلتر المحتوى)."""
    media, _sensitive = twitter_mirror_lookup(url, timeout)
    return media


# ═══════════════════════════════════════════════════════════════
# بينتريست: فيديو وصور متعددة (كاروسيل/Idea Pins) عبر واجهات بينتريست العامة
# yt-dlp قد يفشل مع بينتريست (تغييرات الموقع/حجب)، وgallery-dl قد يتعطّل للصور.
# واجهتا بينتريست العامتان — PinResource على الموقع نفسه وpidgets على
# api.pinterest.com — تعيدان بيانات الـPin كاملة بلا كوكيز ولا تسجيل دخول:
# روابط mp4 المباشرة وكل صور الكاروسيل بدقّتها الأصلية. تُجرَّب المضيفات
# بالترتيب؛ غيّر/أضف مضيفات بمتغيّر البيئة PINTEREST_PROXY_HOSTS (مفصولة
# بفواصل) دون تعديل الكود إن تعطّل مضيف.
# ═══════════════════════════════════════════════════════════════
_PINTEREST_API_HOSTS = [
    h.strip() for h in os.getenv(
        'PINTEREST_PROXY_HOSTS', 'www.pinterest.com,api.pinterest.com'
    ).split(',') if h.strip()
]

_PINTEREST_PIN_RE = re.compile(r'/pin/(\d{5,30})')


def _pinterest_pin_id(url: str, timeout: int = 15):
    """يستخرج معرّف الـPin الرقمي من الرابط، ويوسّع روابط pin.it المختصرة
    باتّباع التحويل أولاً. يعيد None لغير روابط الـPin (بروفايل/لوحة/بحث)."""
    import urllib.request
    low = (url or '').lower()
    if 'pin.it/' in low:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': _BROWSER_UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                url = r.geturl() or url
        except Exception as e:
            logger.warning(f"⚠️ تعذّر توسيع رابط بينتريست المختصر: {e}")
            return None
    m = _PINTEREST_PIN_RE.search(url or '')
    return m.group(1) if m else None


def _pinterest_api_url(host: str, pin_id: str) -> str:
    """رابط الاستعلام عن الـPin حسب نوع المضيف: pidgets لمضيفات api.*،
    وPinResource (واجهة الويب الداخلية غير المسجّلة) لمضيف الموقع نفسه."""
    import json
    import urllib.parse
    if host.startswith('api.'):
        return f"https://{host}/v3/pidgets/pins/info/?pin_ids={pin_id}"
    data = json.dumps({'options': {'id': pin_id,
                                   'field_set_key': 'unauth_react_main_pin'},
                       'context': {}}, separators=(',', ':'))
    q = urllib.parse.urlencode({'source_url': f'/pin/{pin_id}/', 'data': data})
    return f"https://{host}/resource/PinResource/get/?{q}"


def _pinterest_fetch_pin(pin_id: str, timeout: int):
    """يجلب بيانات الـPin من أول مضيف يستجيب ويعيد dict الـPin أو None.
    يطبّع شكلي الرد: PinResource (resource_response.data كائن) وpidgets
    (data قائمة أول عنصر فيها هو الـPin)."""
    import json
    import urllib.request
    for host in _PINTEREST_API_HOSTS:
        api_url = _pinterest_api_url(host, pin_id)
        try:
            req = urllib.request.Request(api_url, headers={
                'User-Agent': _BROWSER_UA,
                'Accept': 'application/json',
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read(4_000_000).decode('utf-8', 'ignore'))
        except Exception as e:
            logger.warning(f"⚠️ تعذّر جلب بيانات بينتريست عبر {host}: {e}")
            continue
        pin = None
        if isinstance(payload, dict):
            rr = payload.get('resource_response')
            if isinstance(rr, dict) and isinstance(rr.get('data'), dict):
                pin = rr['data']
            elif isinstance(payload.get('data'), list) and payload['data'] \
                    and isinstance(payload['data'][0], dict):
                pin = payload['data'][0]
        if pin:
            logger.info(f"🎯 بيانات Pin بينتريست {pin_id} عبر {host}")
            return pin
        logger.info(f"ℹ️ {host} لم يُرجع بيانات Pin لـ {pin_id}")
    return None


def _best_pinterest_video(video_list):
    """يختار أفضل رابط فيديو من video_list (تفضيل mp4 على HLS ثم أعلى عرض)."""
    if not isinstance(video_list, dict):
        return None
    best_url, best_score = None, (-1, -1)
    for v in video_list.values():
        if not isinstance(v, dict):
            continue
        u = v.get('url')
        if not isinstance(u, str) or not u.lower().startswith(('http://', 'https://')):
            continue
        is_mp4 = 0 if '.m3u8' in u.lower() else 1
        score = (is_mp4, int(v.get('width') or 0))
        if score > best_score:
            best_url, best_score = u, score
    return best_url


def _pinterest_story_pages(pin):
    """صفحات الـIdea Pin (story) إن وُجدت، وإلا قائمة فارغة."""
    story = pin.get('story_pin_data')
    if isinstance(story, dict) and isinstance(story.get('pages'), list):
        return story['pages']
    return []


def _extract_pinterest_video(pin):
    """يستخرج رابط الفيديو المباشر من بيانات الـPin (فيديو عادي أو أول فيديو
    في صفحات Idea Pin)، أو None لمنشور صور."""
    if not isinstance(pin, dict):
        return None
    vids = pin.get('videos')
    if isinstance(vids, dict):
        u = _best_pinterest_video(vids.get('video_list'))
        if u:
            return u
    for page in _pinterest_story_pages(pin):
        blocks = page.get('blocks') if isinstance(page, dict) else None
        for b in (blocks or []):
            v = b.get('video') if isinstance(b, dict) else None
            if isinstance(v, dict):
                u = _best_pinterest_video(v.get('video_list'))
                if u:
                    return u
    return None


def _best_pinterest_image(images):
    """أفضل رابط صورة من dict الأحجام (orig/originals أولاً ثم الأعرض)."""
    if not isinstance(images, dict):
        return None
    for key in ('orig', 'originals'):
        d = images.get(key)
        if isinstance(d, dict) and isinstance(d.get('url'), str):
            return d['url']
    best_url, best_w = None, -1
    for d in images.values():
        if isinstance(d, dict) and isinstance(d.get('url'), str):
            w = int(d.get('width') or 0)
            if w > best_w:
                best_url, best_w = d['url'], w
    return best_url


# رابط i.pinimg.com بحجم مصغّر (مثل /236x/ أو /564x1128/) → الدقّة الأصلية
_PINIMG_SIZE_RE = re.compile(r'(pinimg\.com)/\d+x\d*/')


def _upscale_pinimg(u):
    """يرفع رابط صورة pinimg المصغّر إلى /originals/ (الدقّة الكاملة)."""
    return _PINIMG_SIZE_RE.sub(r'\1/originals/', u) if isinstance(u, str) else u


def _extract_pinterest_images(pin):
    """يستخرج روابط كل صور الـPin مرتّبة: كاروسيل متعدد الصور، أو صفحات
    Idea Pin، أو الصورة المفردة. يعيد [] لمنشور فيديو — صورته مجرّد غلاف
    فلا نعيدها كي لا يستقبل المستخدم صورة بدل الفيديو."""
    if not isinstance(pin, dict):
        return []
    out = []

    def _add(u):
        u = _upscale_pinimg(u)
        if (isinstance(u, str) and u.lower().startswith(('http://', 'https://'))
                and u not in out):
            out.append(u)

    carousel = pin.get('carousel_data')
    slots = carousel.get('carousel_slots') if isinstance(carousel, dict) else None
    for slot in (slots or []):
        if isinstance(slot, dict):
            _add(_best_pinterest_image(slot.get('images')))
    if out:
        return out

    for page in _pinterest_story_pages(pin):
        blocks = page.get('blocks') if isinstance(page, dict) else None
        for b in (blocks or []):
            if not isinstance(b, dict) or isinstance(b.get('video'), dict):
                continue  # صفحات الفيديو لمسار الفيديو، لا كصور غلاف
            img = b.get('image')
            if isinstance(img, dict):
                _add(_best_pinterest_image(img.get('images')) or img.get('url'))
    if out:
        return out

    if _extract_pinterest_video(pin):
        return []
    _add(_best_pinterest_image(pin.get('images')))
    return out


def resolve_pinterest_media(url: str, timeout: int = 20):
    """يحوّل رابط Pin بينتريست إلى رابط الفيديو المباشر (mp4/HLS) عبر واجهات
    بينتريست العامة بلا كوكيز، ليُحمّل حين يفشل yt-dlp. يعيد None لغير روابط
    بينتريست أو لمنشورات الصور أو عند أي فشل — فيبقى المسار الأصلي دون تغيير."""
    low = (url or '').lower()
    if not any(m in low for m in PLATFORM_URL_MARKERS['pinterest']):
        return None
    pin_id = _pinterest_pin_id(url, timeout=min(timeout, 15))
    if not pin_id:
        return None
    pin = _pinterest_fetch_pin(pin_id, timeout)
    media = _extract_pinterest_video(pin) if pin else None
    if media and is_safe_url(media):
        logger.info(f"🎯 فيديو بينتريست {pin_id}: {media[:90]}")
        return media
    return None


def resolve_pinterest_images(url: str, timeout: int = 20):
    """يعيد قائمة روابط صور الـPin (كاروسيل/Idea Pin/صورة مفردة) بدقّتها
    الأصلية عبر واجهات بينتريست العامة بلا كوكيز، حين يفشل gallery-dl.
    قائمة فارغة لغير بينتريست أو لمنشور فيديو أو عند أي فشل."""
    low = (url or '').lower()
    if not any(m in low for m in PLATFORM_URL_MARKERS['pinterest']):
        return []
    pin_id = _pinterest_pin_id(url, timeout=min(timeout, 15))
    if not pin_id:
        return []
    pin = _pinterest_fetch_pin(pin_id, timeout)
    if not pin:
        return []
    images = [u for u in _extract_pinterest_images(pin) if is_safe_url(u)]
    if images:
        logger.info(f"🎯 صور بينتريست {pin_id}: {len(images)} صورة (بلا كوكيز)")
    return images


# ═══════════════════════════════════════════════════════════════
# ملاحظات Substack (فيديو Notes) عبر واجهة Substack العامة
# روابط substack.com/@user/note/c-<id> صفحات جافاسكربت: لا og:video فيها ولا
# يدعمها yt-dlp، والفيديو على Mux بتشغيل موقّع (روابط stream.mux.com المباشرة
# ترفض بـ403). الحل: واجهة Substack العامة (بلا كوكيز):
#   1) /api/v1/reader/comment/<id> → بيانات الملاحظة ومرفق الفيديو
#   2) /api/v1/video/upload/<media_id>/src → تحويل 307 لرابط mp4 موقّع
# نعيد رابط /src الثابت (لا التوقيع المؤقت) فيتجدد التوقيع عند كل تحميل
# ويبقى مفتاح الكاش ثابتاً.
# ═══════════════════════════════════════════════════════════════
_SUBSTACK_NOTE_RE = re.compile(r'substack\.com/(?:@[\w.-]+/)?note/c-(\d+)', re.I)


def is_substack_note(url: str) -> bool:
    """هل الرابط ملاحظة Substack (Notes)؟"""
    return bool(_SUBSTACK_NOTE_RE.search(url or ''))


def resolve_substack_note(url: str, timeout: int = 20):
    """يحوّل رابط ملاحظة Substack إلى (رابط الفيديو المباشر، العنوان) عبر واجهة
    Substack العامة بلا كوكيز. الرابط المعاد هو وسيط /src الثابت الذي يحوّل
    لملف mp4 موقّعاً حديثاً عند كل طلب (yt-dlp يتبع التحويل عادياً).

    يعيد (None, None) لغير روابط الملاحظات أو لملاحظة بلا فيديو أو عند أي فشل
    — فيبقى المسار الأصلي (رسالة الفشل المعتادة) دون تغيير."""
    import json
    import urllib.request
    m = _SUBSTACK_NOTE_RE.search(url or '')
    if not m:
        return None, None
    comment_id = m.group(1)
    api_url = f"https://substack.com/api/v1/reader/comment/{comment_id}"
    try:
        req = urllib.request.Request(api_url, headers={
            'User-Agent': _BROWSER_UA,
            'Accept': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read(4_000_000).decode('utf-8', 'ignore'))
    except Exception as e:
        logger.warning(f"⚠️ تعذّر جلب ملاحظة Substack {comment_id}: {e}")
        return None, None
    comment = ((payload or {}).get('item') or {}).get('comment') or {}
    for att in comment.get('attachments') or []:
        if not isinstance(att, dict):
            continue
        media_id = att.get('media_upload_id')
        if att.get('type') == 'video' and media_id and re.fullmatch(r'[\w-]+', str(media_id)):
            direct = f"https://substack.com/api/v1/video/upload/{media_id}/src"
            # عنوان ودود: أول سطر من نص الملاحظة، وإلا اسم صاحبها، وإلا عام
            body = (comment.get('body') or '').strip()
            title = body.split('\n')[0][:80] if body else ''
            if not title:
                title = (comment.get('name') or '').strip() or 'Substack Video'
            if is_safe_url(direct):
                logger.info(f"🎯 فيديو ملاحظة Substack {comment_id}: {direct}")
                return direct, title
    logger.info(f"ℹ️ ملاحظة Substack {comment_id} بلا مرفق فيديو")
    return None, None


def all_mirror_hosts():
    """يعيد قائمة (المنصة، المضيف) لكل مرايا البدائل المُهيّأة — لفحص الصحّة."""
    hosts = []
    for h in _INSTAGRAM_PROXY_HOSTS:
        hosts.append(('instagram', h))
    for h in _TIKTOK_API_HOSTS:
        hosts.append(('tiktok', h))
    for h in _TWITTER_API_HOSTS:
        hosts.append(('twitter', h))
    for h in _PINTEREST_API_HOSTS:
        hosts.append(('pinterest', h))
    hosts.append(('substack', 'substack.com'))
    return hosts


_MUSIC_LINK_MARKERS = ('shazam.com', 'music.apple.com', 'itunes.apple.com',
                       'open.spotify.com/track', 'spotify.link/')


def _is_music_link(url: str) -> bool:
    """هل الرابط من منصة أغاني نحوّلها لبحث يوتيوب؟"""
    low = (url or '').lower()
    return any(m in low for m in _MUSIC_LINK_MARKERS)


def _fetch_music_meta(url: str, timeout: int = 10):
    """يجلب (العنوان، الفنان) من صفحة Apple Music/Spotify عبر وسوم og/title."""
    import urllib.request
    from html import unescape
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            page = resp.read(600000).decode('utf-8', 'ignore')
    except Exception as e:
        logger.warning(f"⚠️ تعذّر جلب بيانات الأغنية ({url[:60]}): {e}")
        return None, None

    def meta(prop):
        for pat in (rf'{prop}["\'][^>]*content=["\']([^"\']+)["\']',
                    rf'content=["\']([^"\']+)["\'][^>]*{prop}'):
            m = re.search(pat, page, re.I)
            if m:
                return unescape(m.group(1)).strip()
        return None

    og_title = meta('og:title')
    desc = meta('og:description') or ''
    raw_title = None
    m = re.search(r'<title[^>]*>([^<]+)</title>', page, re.I)
    if m:
        raw_title = unescape(m.group(1)).strip()

    title = og_title or raw_title
    artist = None
    # نمط "العنوان by الفنان" (شائع في Apple Music) من og:title أو <title>
    for src in (og_title, raw_title):
        if src and not artist:
            mm = re.search(r'^(.*?)\s+by\s+(.+?)(?:\s+on\s+Apple Music.*)?(?:\s*[|].*)?$',
                           src, re.I)
            if mm:
                title = mm.group(1).strip()
                artist = mm.group(2).strip()
    # Spotify: og:description مثل "Elissa · Song · 2004" → الفنان أول جزء
    if not artist and '·' in desc:
        first = desc.split('·')[0].strip()
        if first and first.lower() not in ('song', 'album', 'single', 'listen'):
            artist = first
    # نظّف اللواحق الشائعة من العنوان
    if title:
        title = re.sub(r'\s*[|].*$', '', title).strip()
        title = re.sub(r'\s+on Apple Music.*$', '', title, flags=re.I).strip()
    return (title or None), (artist or None)


def _music_search_query(url: str):
    """يبني نص بحث 'الفنان العنوان' من رابط أغنية، أو None عند التعذّر."""
    import urllib.parse
    from html import unescape
    low = (url or '').lower()
    title = artist = None

    if 'shazam.com' in low:
        # الاسم والفنان في نهاية رابط شزام: #{"title":"...","artist":"..."}
        if '#' in url:
            frag = urllib.parse.unquote(url.split('#', 1)[1])
            mt = re.search(r'"title"\s*:\s*"([^"]+)"', frag)
            ma = re.search(r'"artist"\s*:\s*"([^"]+)"', frag)
            title = mt.group(1) if mt else None
            artist = ma.group(1) if ma else None
        # احتياطي: اسم المقطع من مسار الرابط /track/<id>/<slug>
        if not title:
            ms = re.search(r'/track/\d+/([^/?#]+)', url)
            if ms:
                title = urllib.parse.unquote(ms.group(1)).replace('-', ' ')
    else:
        # Apple Music / Spotify: اجلب الصفحة واقرأ الوسوم
        title, artist = _fetch_music_meta(url)

    if not title:
        return None
    q = f"{artist} {title}" if artist else title
    return re.sub(r'\s+', ' ', unescape(q)).strip()


def resolve_music_link(url: str):
    """يحوّل رابط أغنية إلى رابط يوتيوب لأول نتيجة بحث، أو None عند الفشل.
    (طلب شبكي متزامن — يُنفَّذ خارج حلقة الأحداث)."""
    query = _music_search_query(url)
    if not query:
        return None
    try:
        opts = {'quiet': True, 'no_warnings': True, 'skip_download': True,
                'extract_flat': True, 'default_search': 'ytsearch1'}
        with yt_dlp.YoutubeDL(opts) as ydl:
            r = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = (r or {}).get('entries') or []
        if not entries:
            return None
        vid = entries[0].get('id')
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
        return entries[0].get('url') or entries[0].get('webpage_url')
    except Exception as ex:
        logger.warning(f"⚠️ فشل بحث يوتيوب للأغنية '{query}': {ex}")
        return None
