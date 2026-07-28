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


# ═══════════════════════════════════════════════════════════════
# سناب شات: النسخة بلا لوقو (رندر 1034 بدل 27)
# وسائط سناب مخزّنة كائناتٍ ثابتة على Google Cloud Storage باسم
# «<معرّف الوسائط>.<رقم الرندر>.<رمز السياق>». لكل مقطع سبوت لايت عدّة رندرات:
#   27   → mp4، وهو الوحيد الذي تشير إليه الصفحة (og:video وcontentUrl)، وفيه
#          سناب يحرق اللوقو واسم الحساب داخل الصورة نفسها — أعلى اليسار في
#          النصف الأول من المقطع ثم أسفل اليمين في النصف الثاني (بروفايل
#          التحويل «SpotlightSharing» المذكور صراحةً داخل بارامتر mo).
#   1034 → mp4 لنفس المقطع بلا أي لوقو، ولا تذكره صفحة سبوت لايت إطلاقاً
#          (ظهر في صفحات حسابات المنشئين، وبارامتر mo الخاص به بلا بروفايل
#          مشاركة). موجود لكل مقطع في عيّنة من 59 مقطعاً — لكن ليس دائماً تحت
#          مضيف/مسار نسخة المشاركة، انظر _SNAP_FALLBACK_BASES.
#   256/1400 (jpeg) و1306/1430 (webp) → صور مصغّرة، وهي بلا لوقو أصلاً وهذا
#          ما يثبت أن اللوقو من بروفايل التحويل لا من المقطع الأصلي.
# فالحل: إعادة كتابة الرندر 27 إلى 1034 بعد التأكّد من وجوده فعلياً. النسخة
# النظيفة أقل دقّةً قليلاً (480×852 مقابل 540×960) وهي المقايضة الوحيدة.
# رقم الرندر قابل للتغيير بمتغيّر البيئة SNAPCHAT_CLEAN_RENDITION إن غيّره سناب.
# ملاحظة: النسخة الخام (المسار بلا لاحقة رندر) مشفّرة بالكامل ومفتاحها لا
# يظهر في الصفحة، فلا فائدة منها.
# ═══════════════════════════════════════════════════════════════
_SNAP_CLEAN_RENDITION = os.getenv('SNAPCHAT_CLEAN_RENDITION', '1034').strip() or '1034'


# مسارات احتياطية للنسخة النظيفة. رندرات المقطع الواحد ليست كلها تحت مضيف/مسار
# واحد: فحص ميداني أظهر مقاطع نسخةُ مشاركتها على bolt-gcdn/bb بينما نسختها
# النظيفة على cf-st/d. تبديل الرقم مع إبقاء المسار كان يفشل معها (≈8% من
# المقاطع) فتعود بنسخة اللوقو رغم أن النسخة النظيفة موجودة فعلاً على مسار آخر.
# فنجرّب المسار الأصلي أولاً ثم هذه المسارات: التغطية صارت 59/59 في عيّنة
# مفحوصة (4 منها احتاجت مساراً احتياطياً) بعد أن كانت 24/26.
_SNAP_FALLBACK_BASES = [b.strip().rstrip('/') for b in os.getenv(
    'SNAPCHAT_FALLBACK_BASES',
    'https://cf-st.sc-cdn.net/d,https://bolt-gcdn.sc-cdn.net/3'
).split(',') if b.strip()]


def _snap_candidate_bases(primary: str):
    """مسارات البحث عن النسخة النظيفة: الأصلي أولاً ثم الاحتياطية، بلا تكرار."""
    bases = [primary.rstrip('/')]
    for b in _SNAP_FALLBACK_BASES:
        if b not in bases:
            bases.append(b)
    return bases


def get_snapchat_clean_rendition() -> str:
    """رقم الرندر النظيف المعمول به الآن."""
    return _SNAP_CLEAN_RENDITION


def set_snapchat_clean_rendition(value) -> str:
    """يضبط رقم الرندر النظيف وقت التشغيل (يستدعيه البوت من إعداد قاعدة
    البيانات كي يغيّره الأدمن بزرّ بلا لمس ملفات ولا إعادة تشغيل).

    مصدر واحد للحقيقة: تغييره هنا يسري على كل المسارات دفعةً واحدة
    (_is_snap_video_url وresolve_snapchat_spotlight وsnapchat_clean_rendition).
    القيمة غير الرقمية تُتجاهَل ويبقى المعمول به كما هو."""
    global _SNAP_CLEAN_RENDITION
    v = str(value or '').strip()
    if v.isdigit():
        _SNAP_CLEAN_RENDITION = v
    return _SNAP_CLEAN_RENDITION

# «/<معرّف الوسائط>.27.<رمز السياق>» في نهاية مسار رابط CDN سناب
_SNAP_SHARING_RENDITION_RE = re.compile(
    r'/([A-Za-z0-9_-]{10,32})\.27\.([A-Za-z0-9]{4,16})\Z')

# صيغة كائن الرندر عامّةً: «/<معرّف>.<رقم الرندر>.<رمز السياق>»
_SNAP_RENDITION_PATH_RE = re.compile(
    r'/([A-Za-z0-9_-]{10,32})\.(\d{1,5})\.([A-Za-z0-9]{4,16})\Z')


def _is_snap_video_url(u: str) -> bool:
    """هل الرابط ملف فيديو على CDN سناب؟ يقبل ملف ‎.mp4‎ صريحاً، أو كائن رندر
    فيديو بصيغة «<معرّف>.<رقم الرندر>.<رمز السياق>» — وهي صيغة سبوت لايت
    الحالية التي لا امتداد فيها إطلاقاً. أرقام رندر المصغّرات (256/1306/1400/
    1430 وغيرها) مستبعَدة كي لا نرسل صورة غلاف بدل الفيديو."""
    try:
        p = urlparse(u or '')
    except Exception:
        return False
    host = (p.hostname or '').lower()
    if not (host == 'sc-cdn.net' or host.endswith('.sc-cdn.net')):
        return False
    path = p.path or ''
    if path.lower().endswith('.mp4'):
        return True
    m = _SNAP_RENDITION_PATH_RE.search(path)
    return bool(m and m.group(2) in ('27', _SNAP_CLEAN_RENDITION))


def snapchat_downloadable_url(media_url: str) -> str:
    """يلحق «#.mp4» برابط وسائط سناب كي يقبله yt-dlp.

    روابط سناب تنتهي برمز السياق (‎…‎.1034.IRZXSOY) بلا امتداد، وyt-dlp يأخذ
    ما بعد آخر نقطة امتداداً فيراه غريباً ويرفض التحميل كلّياً:
    «The extracted extension ('IRZXSOY') is unusual and will be skipped».
    يقرأ yt-dlp الامتداد من آخر نقطة قبل «?» فقط، فلا يفيد أي معامل استعلام.

    الجزء بعد «#» لا يُرسل للخادم إطلاقاً، وcache_key_for_url يُسقطه أصلاً
    فيبقى مفتاح الكاش كما هو — بلا أي أثر جانبي. يشمل نسخة اللوقو الاحتياطية
    (الرندر 27) لأن العلّة نفسها فيها."""
    try:
        p = urlparse(media_url or '')
    except Exception:
        return media_url
    host = (p.hostname or '').lower()
    if not (host == 'sc-cdn.net' or host.endswith('.sc-cdn.net')):
        return media_url
    # رابط بامتداد صريح أو بجزء موجود سلفاً لا يحتاج شيئاً
    if p.fragment or not _SNAP_RENDITION_PATH_RE.search(p.path or ''):
        return media_url
    return f"{media_url}#.mp4"


def snapchat_clean_rendition(media_url: str, timeout: int = 10,
                             rendition: str = None) -> str:
    """يحوّل رابط وسائط سناب من رندر المشاركة (27، اللوقو واسم الحساب محروقان
    داخل الصورة) إلى الرندر النظيف (1034، نفس المقطع بلا لوقو).

    rendition: رقم الرندر المطلوب (يمرّره البوت من إعداد قاعدة البيانات ليغيّره
    الأدمن بزرّ بلا لمس ملفات). عند غيابه يُستعمل متغيّر البيئة ثم الافتراضي.

    يتحقّق بطلب HEAD أن النسخة النظيفة منشورة فعلاً قبل اعتمادها، فإن لم تكن
    (بعض المقاطع لا رندر نظيف لها) يعيد الرابط الأصلي دون تغيير في السلوك.
    يُسقط الاستعلام لأنه يصف الرندر القديم، والتخزين يتجاهله أصلاً."""
    want = str(rendition or _SNAP_CLEAN_RENDITION).strip()
    if not want.isdigit():
        want = _SNAP_CLEAN_RENDITION
    try:
        parts = urlparse(media_url or '')
    except Exception:
        return media_url
    m = _SNAP_SHARING_RENDITION_RE.search(parts.path or '')
    if not m:
        return media_url  # ليس رابط رندر مشاركة — لا شيء نعيد كتابته
    mid, ctx = m.group(1), m.group(2)
    for base in _snap_candidate_bases(
            f"{parts.scheme}://{parts.netloc}{parts.path[:m.start()]}"):
        clean = f"{base}/{mid}.{want}.{ctx}"
        if not is_safe_url(clean):
            continue
        # التخزين يردّ 404 بجسم XML؛ الفيديو يأتي video/mp4 وأحياناً
        # application/octet-stream، فنرفض أنواع النصّ/الترميز فقط
        status, ctype, _size = _snap_head(clean, timeout)
        if status == 200 and not ctype.endswith(('xml', 'html')):
            logger.info(f"🎯 سناب بلا لوقو (رندر {want}): {clean[:90]}")
            return clean
    logger.info(f"ℹ️ لا رندر نظيف لـ {mid} — نبقي نسخة المشاركة")
    return media_url


# رندرات المصغّرة، بترتيب الأفضلية. jpeg أولاً لأن تلجرام يرفض webp أحياناً.
# تعيش مع النسخة النظيفة في نفس العائلة (29 من 30 مقطعاً في فحص ميداني).
_SNAP_THUMB_RENDITIONS = ('256', '1400')


def snapchat_thumbnail_url(media_url: str, timeout: int = 8):
    """رابط مصغّرة مقطع سناب (بلا لوقو مثل بقية المصغّرات)، أو None.

    yt-dlp لا يعطي مصغّرة لرابط ملف مباشر، فتظهر المعاينة بلا صورة. المصغّرة
    كائن مجاور للنسخة النظيفة يُشتقّ من نفس الرابط بتبديل رقم الرندر.
    يتحقّق بطلب HEAD أنها صورة فعلاً قبل إعادتها كي لا تفشل المعاينة."""
    try:
        p = urlparse(media_url or '')
    except Exception:
        return None
    host = (p.hostname or '').lower()
    if not (host == 'sc-cdn.net' or host.endswith('.sc-cdn.net')):
        return None
    m = _SNAP_RENDITION_PATH_RE.search(p.path or '')
    if not m:
        return None
    mid, ctx = m.group(1), m.group(3)
    primary = f"{p.scheme}://{p.netloc}{p.path[:m.start()]}"
    for base in _snap_candidate_bases(primary):
        for rid in _SNAP_THUMB_RENDITIONS:
            thumb = f"{base}/{mid}.{rid}.{ctx}"
            if not is_safe_url(thumb):
                continue
            status, ctype, _size = _snap_head(thumb, timeout)
            if status == 200 and ctype.startswith('image/'):
                logger.info(f"🖼️ مصغّرة سناب (رندر {rid}): {thumb[:90]}")
                return thumb
    logger.info("ℹ️ لا مصغّرة سناب متاحة — معاينة نصية")
    return None


# أرقام الرندر التي نمسحها بحثاً عن نسخة نظيفة إن غيّر سناب الترقيم. النطاق
# يغطّي الأرقام المعروفة وجوارها (27 فيديو، 256/1306/1400/1430 صور، 1034 نظيف).
_SNAP_SCAN_RANGE = sorted(set(
    list(range(0, 64)) + list(range(250, 262)) + list(range(1000, 1100))
    + list(range(1300, 1312)) + list(range(1395, 1440))))

# رابط رندر داخل نصّ الصفحة (غير مثبّت بالنهاية، بعكس نظيره أعلاه)
_SNAP_RENDITION_IN_TEXT_RE = re.compile(
    r'https://[^"\'\\\s]*sc-cdn\.net[^"\'\\\s]*?'
    r'/([A-Za-z0-9_-]{10,32})\.(\d{1,5})\.([A-Za-z0-9]{4,16})')


def _snap_head(url: str, timeout: int = 15):
    """(الحالة، نوع المحتوى، الحجم) لطلب HEAD، أو (0, '', 0) عند أي فشل."""
    import urllib.request
    try:
        req = urllib.request.Request(url, method='HEAD',
                                     headers={'User-Agent': _BROWSER_UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (r.status, (r.headers.get_content_type() or '').lower(),
                    int(r.headers.get('Content-Length') or 0))
    except Exception:
        return 0, '', 0


def snapchat_probe_renditions(page_url: str, timeout: int = 20) -> dict:
    """يمسح أرقام رندر مقطع سناب حقيقي ويعيد ما هو منشور فعلاً — أداة صيانة
    تُجيب: أي رقم يعطي فيديو نظيفاً إن غيّر سناب الترقيم.

    يعيد dict فيه: error (نصّ عند التعذّر)، media_id، context، page_rendition
    (رقم نسخة اللوقو كما في الصفحة)، found (قائمة (رقم، نوع، حجم))، videos،
    و clean (أرقام الفيديو عدا نسخة الصفحة — أي المرشّحة لتكون بلا لوقو).
    طلب شبكي متزامن: يُنفَّذ خارج حلقة الأحداث."""
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    out = {'error': None, 'media_id': None, 'context': None,
           'page_rendition': None, 'found': [], 'videos': [], 'clean': []}
    if 'snapchat.com' not in (page_url or '').lower() or not is_safe_url(page_url):
        out['error'] = 'ليس رابط سناب صالحاً'
        return out
    try:
        req = urllib.request.Request(page_url,
                                     headers={'User-Agent': _BROWSER_UA,
                                              'Accept-Language': 'en-US,en;q=0.9'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html_text = r.read(3_000_000).decode('utf-8', 'ignore')
    except Exception as e:
        out['error'] = f'تعذّر جلب الصفحة: {type(e).__name__}'
        return out
    flat = html_text.replace('\\/', '/')
    hits = list(_SNAP_RENDITION_IN_TEXT_RE.finditer(flat))
    if not hits:
        out['error'] = ('لم أجد رابط وسائط في الصفحة — غالباً سناب غيّر بنيتها، '
                        'وهذا يحتاج تعديل كود لا مجرّد تغيير رقم')
        return out
    # المقطع المطلوب: معرّف og:video إن وُجد، وإلا الأكثر تكراراً في الصفحة
    og = re.search(r'og:video[^>]*content=["\']([^"\']+)["\']', flat)
    media_id = None
    if og:
        om = _SNAP_RENDITION_IN_TEXT_RE.search(og.group(1))
        if om:
            media_id = om.group(1)
    if not media_id:
        counts = {}
        for h in hits:
            counts[h.group(1)] = counts.get(h.group(1), 0) + 1
        media_id = max(counts, key=counts.get)
    mine = [h for h in hits if h.group(1) == media_id]
    first = mine[0]
    ctx = first.group(3)
    # رندرات المقطع الواحد قد تكون موزّعة على مضيفات/مسارات مختلفة، فنمسح كل
    # مسار تذكره الصفحة لهذا المقطع بالإضافة للمسارات الاحتياطية
    bases = []
    for h in mine:
        b = h.group(0)[:h.group(0).rindex('/')]
        if b not in bases:
            bases.append(b)
    for b in _SNAP_FALLBACK_BASES:
        if b not in bases:
            bases.append(b)
    # كل الأرقام التي تذكرها الصفحة لهذا المقطع — نسخة اللوقو من بينها، فأي
    # رقم فيديو لا تذكره الصفحة هو المرشّح للنسخة النظيفة
    page_nums = {h.group(2) for h in mine}
    out.update(media_id=media_id, context=ctx,
               page_rendition=','.join(sorted(page_nums, key=int)))

    def probe(job):
        b, n = job
        st, ct, cl = _snap_head(f"{b}/{media_id}.{n}.{ctx}", 15)
        return n, st, ct, cl

    seen = set()

    def scan(base_list):
        jobs = [(b, n) for n in _SNAP_SCAN_RANGE for b in base_list]
        with ThreadPoolExecutor(24) as ex:
            for n, st, ct, cl in ex.map(probe, jobs):
                if st == 200 and not ct.endswith(('xml', 'html')) and n not in seen:
                    seen.add(n)
                    out['found'].append((n, ct, cl))

    def summarize():
        out['found'].sort()
        out['videos'] = [n for n, ct, _c in out['found']
                         if 'video' in ct or 'octet-stream' in ct]
        out['clean'] = [n for n in out['videos'] if str(n) not in page_nums]

    # مسح على مرحلتين: المسار الأول يكفي لأغلب المقاطع، فلا ندفع كلفة بقية
    # المسارات إلا حين لا نجد نسخة نظيفة (كل مسار إضافي يضاعف عدد الطلبات)
    scan(bases[:1])
    summarize()
    if not out['clean'] and len(bases) > 1:
        logger.info(f"ℹ️ لا نسخة نظيفة على المسار الأول لـ {media_id} — "
                    f"نجرّب {len(bases) - 1} مساراً آخر")
        scan(bases[1:])
        summarize()
    logger.info(f"👻 فحص رندرات سناب {out['media_id']}: "
                f"فيديو={out['videos']} نظيف={out['clean']}")
    return out


def resolve_snapchat_spotlight(url: str, timeout: int = 20) -> str:
    """يجلب صفحة سناب سبوت لايت ويستخرج رابط الفيديو المباشر من وسم og:video أو
    من رابط CDN داخل الصفحة، فيُحمّل مباشرة بدل مسار سناب الضعيف في yt-dlp، ثم
    يحوّله إلى الرندر النظيف بلا لوقو (انظر snapchat_clean_rendition — الصفحة
    لا تعطي إلا رندر المشاركة الذي يحرق اللوقو داخل الصورة).
    يعمل للسبوت لايت العام فقط؛ عند أي فشل يعيد الرابط الأصلي.
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

        from html import unescape

        # 1) og:video — الأنسب لأن معاينات الروابط تعتمد عليه فيبقى مستقراً.
        #    نلتقط كل قيم content ثم نصفّيها بـ _is_snap_video_url لأن وسوم
        #    og:video:type/width/height تشارك النمط نفسه بقيم ليست روابط.
        for pat in (
            r'property=["\']og:video(?::secure_url)?["\'][^>]*?content=["\']([^"\']+)["\']',
            r'content=["\']([^"\']+)["\'][^>]*?property=["\']og:video',
        ):
            for m in re.finditer(pat, html_text):
                cand = unescape(m.group(1))
                if _is_snap_video_url(cand) and is_safe_url(cand):
                    logger.info(f"🎯 سناب سبوت لايت (og:video): {cand[:90]}")
                    return snapchat_clean_rendition(cand)

        # 2) رابط الفيديو من JSON المضمّن في الصفحة (contentUrl/mediaUrl)؛ قد
        #    تكون الشرطات مهرّبة \/ والمحارف بصيغة & فنفكّها قبل الفحص
        for m in re.finditer(r'"(https:[^"\s]*sc-cdn\.net[^"\s]*)"', html_text):
            cand = unescape(m.group(1).replace('\\/', '/')
                            .replace('\\u0026', '&').replace('\\u003d', '='))
            if _is_snap_video_url(cand) and is_safe_url(cand):
                logger.info(f"🎯 سناب سبوت لايت (cdn): {cand[:90]}")
                return snapchat_clean_rendition(cand)
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


def _is_real_instagram_host(u: str) -> bool:
    """هل مضيف الرابط هو instagram.com نفسه (لا مرآة ولا CDN)؟
    scontent.cdninstagram.com (وسائط ناجحة) لا يطابق — فقط الموقع الفعلي."""
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        return False
    return host == 'instagram.com' or host.endswith('.instagram.com')


def instagram_mirror_lookup(url: str, timeout: int = 20):
    """يستعلم مرايا إنستغرام ويعيد (رابط الفيديو المباشر أو None، هل المنشور
    غير متاح — خاص/محذوف؟).

    علم عدم الإتاحة: حين تصل المرآة لإنستغرام ويرفض تسليم المنشور، تعيد
    توجيهاً لصفحة instagram.com نفسها (جدار تسجيل الدخول) بدل ملف الوسائط —
    إشارة موثوقة أن المنشور من حساب خاص أو محذوف، فيعرض البوت رسالة واضحة
    بدل «رابط غير صحيح» المضلّلة. أعطال المرآة (504/انقطاع) لا ترفع العلم."""
    import urllib.request
    low = (url or '').lower()
    if not any(h in low for h in ('instagram.com', 'instagr.am')):
        return None, False
    try:
        path = urlparse(url).path
    except Exception:
        return None, False
    m = _INSTAGRAM_MEDIA_RE.search(path)
    if not m:
        return None, False  # ستوري/بروفايل/رابط غير منشور — لا مرآة له
    media_path = m.group(0)
    unavailable = False
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
                return final, False
            if not ctype.startswith('image/') and _is_real_instagram_host(final):
                # المرآة أحالتنا لصفحة إنستغرام الفعلية (جدار الدخول) — المنشور
                # خاص/محذوف. (الصور تبقى لمسار الصور: منشور مصوّر عام سليم)
                unavailable = True
                logger.info(f"🔒 {proxy_host} أحال لصفحة إنستغرام (منشور خاص/"
                            f"محذوف؟) لـ {media_path}")
                continue
            logger.info(f"ℹ️ {proxy_host} لم يُرجع فيديو (نوع={ctype}) لـ {media_path}")
        except Exception as e:
            logger.warning(f"⚠️ تعذّر حل إنستغرام عبر {proxy_host} ({media_path}): {e}")
    return None, unavailable


def resolve_instagram_media(url: str, timeout: int = 20):
    """يحوّل رابط ريلز/منشور إنستغرام إلى رابط الفيديو المباشر (mp4) عبر مرآة
    عامة لا تتطلّب كوكيز، ليُحمّل حين يعجز yt-dlp عن الوصول المجهول.

    يعيد رابط mp4 مباشراً عند النجاح، أو None لغير روابط إنستغرام أو لمنشورات
    الصور (المرآة تعيد صورة لا فيديو) أو عند أي فشل — فيبقى المسار الأصلي
    (كوكيز إن توفّرت، أو مسار الصور عبر gallery-dl).
    (لا يميّز المنشور الخاص/المحذوف — استخدم instagram_mirror_lookup لذلك)."""
    media, _unavailable = instagram_mirror_lookup(url, timeout)
    return media


# ═══════════════════════════════════════════════════════════════
# فيسبوك: توسيع روابط المشاركة وفكّ غلاف صفحة الدخول
# زرّ المشاركة في فيسبوك اليوم يعطي «facebook.com/share/<code>/»، ولا مستخرِج
# في yt-dlp يطابق هذه الصيغة إطلاقاً (ولا /share/v/ ولا /stories/) — الصيغ
# المدعومة هي /watch/?v= و/<user>/videos/ و/reel/ فقط. فيسبوك يحوّل رابط
# المشاركة للرابط الأساسي، لكنه كثيراً ما يلفّه بصفحة الدخول:
#   login.php?next=<الرابط الحقيقي مرمّزاً>
# فيصل yt-dlp إلى login.php ويردّ «Unsupported URL» — خطأ مضلّل لأن المشكلة
# ليست في الرابط. فنوسّع الرابط أولاً ونفكّ غلاف الدخول ونسلّم الرابط الأساسي.
# ملاحظة محقَّقة: ستوري فيسبوك يحتاج تسجيل دخول فعلاً — النسخة العادية تحوّل
# لصفحة الدخول، وm.facebook.com يردّ صفحة بلا أي وسائط. فالتوسيع لا يجعل
# الستوري قابلاً للتحميل بلا كوكيز، لكنه يجعل الخطأ مفهوماً.
# ═══════════════════════════════════════════════════════════════
_FB_SHARE_RE = re.compile(r'/share(?:/[a-z])?/[A-Za-z0-9_-]+', re.I)
_FB_STORY_RE = re.compile(r'/stories/\d+', re.I)


def _fb_unwrap_login(url: str) -> str:
    """يعيد الوجهة الحقيقية من غلاف صفحة دخول فيسبوك (login.php?next=…)."""
    import urllib.parse
    try:
        p = urllib.parse.urlparse(url or '')
    except Exception:
        return url
    if 'login' not in (p.path or '').lower():
        return url
    nxt = urllib.parse.parse_qs(p.query or '').get('next')
    if nxt and nxt[0].lower().startswith(('http://', 'https://')):
        return nxt[0]
    return url


def is_facebook_story(url: str) -> bool:
    """هل الرابط ستوري فيسبوك؟ (يتطلّب تسجيل دخول — لا يعمل بلا كوكيز)."""
    low = (url or '').lower()
    if not any(m in low for m in PLATFORM_URL_MARKERS['facebook']):
        return False
    return bool(_FB_STORY_RE.search(_fb_unwrap_login(url)))


def resolve_facebook_share(url: str, timeout: int = 20) -> str:
    """يوسّع رابط مشاركة فيسبوك إلى الرابط الأساسي الذي يفهمه yt-dlp.

    يتبع التحويل ثم يفكّ غلاف صفحة الدخول إن وُجد. يعيد الرابط الأصلي كما هو
    لغير روابط فيسبوك أو للروابط الأساسية أصلاً أو عند أي فشل."""
    import urllib.request
    low = (url or '').lower()
    if not any(m in low for m in PLATFORM_URL_MARKERS['facebook']):
        return url
    # الروابط الأساسية لا تحتاج توسيعاً (نتفادى طلباً شبكياً بلا فائدة)
    if not (_FB_SHARE_RE.search(url or '') or 'fb.watch' in low):
        return url
    # وكيل البوت أولاً: فيسبوك يردّ 400 لوكيل المتصفح على روابط المشاركة،
    # بينما يعطي التحويل الصحيح لوكلاء معاينة الروابط (محقَّق ميدانياً)
    final = None
    for ua in (_BOT_UA, _BROWSER_UA):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': ua})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                final = r.geturl() or url
            break
        except Exception as e:
            logger.info(f"ℹ️ توسيع رابط فيسبوك تعذّر بـ{ua[:24]}: {e}")
    if not final:
        return url
    final = _fb_unwrap_login(final)
    if final and final != url and is_safe_url(final):
        logger.info(f"🎯 فيسبوك: رابط المشاركة وُسّع إلى {final[:100]}")
        return final
    return url


# ═══════════════════════════════════════════════════════════════
# ثريدز: مرآة عامة (بدون كوكيز)
# yt-dlp لا يملك مستخرِجاً لثريدز إطلاقاً فيردّ "Unsupported URL"، وصفحة
# المنشور واجهة جافاسكربت لا وسائط فيها للزوّار: لا og:video ولا JSON مضمّن،
# وفحص 261 حزمة جافاسكربت (162 استعلام GraphQL) لم يُظهر استعلام وسائط المنشور
# — أي أن ثريدز لا يسلّم الفيديو لغير المسجّلين أصلاً، ووسوم المعاينة تعطي
# صورة الغلاف فقط حتى لوكلاء فيسبوك/تويتر الرسميين.
# مرايا vxthreads العامة تجلب المنشور وتعيد وسم og:video فيه رابط mp4 مباشر
# على cdninstagram — فنقرأه ونحمّله عادياً. تُجرَّب المضيفات بالترتيب؛ غيّرها
# بمتغيّر البيئة THREADS_PROXY_HOSTS إن تعطّلت مرآة (بعضها يتوقّف فعلاً: عند
# الكتابة كانت vxthreads.net وfixthreads.net تردّان 503 وvxthreads.com تعمل).
# ═══════════════════════════════════════════════════════════════
_THREADS_PROXY_HOSTS = [
    h.strip() for h in os.getenv(
        'THREADS_PROXY_HOSTS', 'vxthreads.com,vxthreads.net,fixthreads.net'
    ).split(',') if h.strip()
]

# مسار منشور ثريدز: /@user/post/<code> أو /@user/video/<code>
_THREADS_POST_RE = re.compile(
    r'/(@[A-Za-z0-9_.]{1,40})/(?:post|video)/([A-Za-z0-9_-]{5,24})')


def _threads_post_path(url: str, timeout: int = 15):
    """«/@user/post/<code>» من رابط ثريدز، بعد توسيع الروابط المختصرة
    (threads.net/t/<code>) لأن المعرّف لا يظهر فيها. None لغير المنشورات."""
    import urllib.request
    low = (url or '').lower()
    if not any(m in low for m in PLATFORM_URL_MARKERS['threads']):
        return None
    if '/t/' in low:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': _BROWSER_UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                url = r.geturl() or url
        except Exception as e:
            logger.warning(f"⚠️ تعذّر توسيع رابط ثريدز المختصر: {e}")
    m = _THREADS_POST_RE.search(url or '')
    return f"/{m.group(1)}/post/{m.group(2)}" if m else None


def _threads_duration(media_url: str):
    """مدّة الفيديو بالثواني من معامل efg داخل رابط cdninstagram (JSON مرمّز
    base64 فيه duration_s)، أو None.

    مهمّة لا تجميلية: بلا مدّة يتخطّى المقطع حدّ المدة المجاني في البوت،
    لأن yt-dlp لا يعرف مدّة ملف mp4 بعيد قبل تحميله."""
    import base64
    import json
    import urllib.parse
    try:
        efg = urllib.parse.parse_qs(urllib.parse.urlparse(media_url).query).get('efg')
        if not efg:
            return None
        raw = base64.urlsafe_b64decode(efg[0] + '=' * (-len(efg[0]) % 4))
        val = json.loads(raw).get('duration_s')
        return int(val) if isinstance(val, (int, float)) and val > 0 else None
    except Exception:
        return None


# سطر التفاعلات في وصف المرآة: «❤️ 425  💬 113  🔁 1  📤 33»
_THREADS_STATS_RE = re.compile(r'^[\s‏‎]*(?:[❤️💬🔁📤]️?\s*[\d.,KkMm]+\s*){2,}$')

# اسم الحساب داخل og:title: «الاسم المعروض (@user)»
_THREADS_HANDLE_RE = re.compile(r'\(@([A-Za-z0-9_.]{1,40})\)\s*$')


def _threads_description_meta(page: str) -> dict:
    """يستخرج نصّ المنشور وسطر التفاعلات واسم الحساب من وسوم المرآة.

    og:description = نصّ المنشور ثم سطر التفاعلات (❤️/💬/🔁/📤). نفصلهما كي
    يصير نصّ المنشور عنواناً مفهوماً بدل «Threads Video»، ويظهر سطر التفاعلات
    في وصف الرفع. أي جزء غائب يُترك ببساطة."""
    import re as _re
    from html import unescape
    out = {}
    m = _re.search(r'property=["\']og:description["\'][^>]*?content=["\']([^"\']*)["\']',
                   page, _re.S)
    if m:
        desc = unescape(m.group(1)).replace('\r', '')
        lines = [ln.strip() for ln in desc.split('\n') if ln.strip()]
        body = [ln for ln in lines if not _THREADS_STATS_RE.match(ln)]
        stats = [ln for ln in lines if _THREADS_STATS_RE.match(ln)]
        if stats:
            out['stats'] = stats[-1]
        if body:
            # أول سطر مفيد عنواناً (الوصف كاملاً قد يكون طويلاً جداً)
            out['title'] = ' '.join(body)[:200]
    m = _re.search(r'property=["\']og:title["\'][^>]*?content=["\']([^"\']*)["\']', page)
    if m:
        h = _THREADS_HANDLE_RE.search(unescape(m.group(1)).strip())
        if h:
            out['uploader'] = '@' + h.group(1)
    # صورة الغلاف: yt-dlp لا يعرف مصغّرة ملف mp4 بعيد، فبدونها تظهر المعاينة
    # بلا صورة. نتخطّى webp لأن تلجرام يرفضه أحياناً.
    m = _re.search(r'property=["\']og:image["\'][^>]*?content=["\']([^"\']+)["\']', page)
    if m:
        img = unescape(m.group(1))
        if (img.lower().startswith(('http://', 'https://'))
                and '.webp' not in img.lower() and is_safe_url(img)):
            out['thumbnail'] = img
    return out


def threads_mirror_lookup(url: str, timeout: int = 20):
    """يستعلم مرايا ثريدز ويعيد (رابط الفيديو المباشر أو None، بيانات المقطع).

    البيانات dict فيه width/height (من وسوم المرآة) وduration (من الرابط) —
    يستعملها البوت للمعاينة ولتطبيق حدّ المدة المجاني."""
    import re as _re
    import urllib.request
    from html import unescape
    meta = {}
    path = _threads_post_path(url, timeout=min(timeout, 15))
    if not path:
        return None, meta
    for host in _THREADS_PROXY_HOSTS:
        proxy_url = f"https://{host}{path}"
        try:
            req = urllib.request.Request(proxy_url, headers={
                'User-Agent': _BOT_UA,   # المرايا تعطي وسوم المعاينة للبوتات
                'Accept': 'text/html,*/*',
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                page = resp.read(2_000_000).decode('utf-8', 'ignore')
        except Exception as e:
            logger.warning(f"⚠️ تعذّر حل ثريدز عبر {host} ({path}): {e}")
            continue
        for pat in (r'property=["\']og:video(?::secure_url)?["\'][^>]*?content=["\']([^"\']+)["\']',
                    r'content=["\']([^"\']+)["\'][^>]*?property=["\']og:video'):
            m = _re.search(pat, page)
            if m:
                media = unescape(m.group(1))
                if media.lower().startswith(('http://', 'https://')) and is_safe_url(media):
                    for key, tag in (('width', 'og:video:width'),
                                     ('height', 'og:video:height')):
                        mm = _re.search(
                            rf'{tag}["\'][^>]*?content=["\'](\d+)["\']', page)
                        if mm:
                            meta[key] = int(mm.group(1))
                    dur = _threads_duration(media)
                    if dur:
                        meta['duration'] = dur
                    meta.update(_threads_description_meta(page))
                    logger.info(f"🎯 ثريدز عبر {host}: {media[:90]}"
                                + (f" ({dur}ث)" if dur else ""))
                    return media, meta
        logger.info(f"ℹ️ {host} لم يُرجع فيديو ثريدز لـ {path} (منشور صور/نصّ؟)")
    return None, meta


def resolve_threads_media(url: str, timeout: int = 20):
    """يحوّل رابط منشور ثريدز إلى رابط الفيديو المباشر (mp4) عبر مرآة عامة بلا
    كوكيز، لأن yt-dlp لا يدعم ثريدز أصلاً.

    يعيد رابط mp4 عند النجاح، أو None لغير روابط المنشورات أو لمنشور بلا فيديو
    (صور/نصّ) أو عند أي فشل — فيبقى المسار الأصلي دون تغيير في السلوك.
    (بلا بيانات المقطع — استخدم threads_mirror_lookup لها.)"""
    media, _meta = threads_mirror_lookup(url, timeout)
    return media


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


def _extract_twitter_media_list(payload):
    """يستخرج كل وسائط التغريدة مرتّبة كما وردت فيها: قائمة عناصر
    {'type': 'photo'|'video', 'url': ...} (يدعم شكلي vx/fxtwitter).
    الـGIF يُعامل كفيديو (المرآة تعيده ملف mp4). قائمة فارغة لغياب الوسائط."""
    if not isinstance(payload, dict):
        return []
    out, seen = [], set()

    def _add(kind, u):
        if (isinstance(u, str)
                and u.lower().startswith(('http://', 'https://'))
                and u not in seen):
            seen.add(u)
            out.append({'type': kind, 'url': u})

    # vxtwitter: media_extended قائمة مرتّبة بأنواع صريحة (image/video/gif)
    for it in (payload.get('media_extended') or []):
        if not isinstance(it, dict):
            continue
        if it.get('type') == 'image':
            _add('photo', it.get('url'))
        elif it.get('type') in ('video', 'gif'):
            _add('video', it.get('url'))
    if out:
        return out

    # fxtwitter: tweet.media.all قائمة مرتّبة (photo/video/gif)،
    # وphotos/videos منفصلتان احتياطاً للردود التي بلا all
    media = (payload.get('tweet') or {}).get('media') or {}
    for it in (media.get('all') or []):
        if not isinstance(it, dict):
            continue
        if it.get('type') in ('photo', 'image'):
            _add('photo', it.get('url'))
        elif it.get('type') in ('video', 'gif'):
            _add('video', it.get('url'))
    if out:
        return out
    for it in (media.get('photos') or []):
        if isinstance(it, dict):
            _add('photo', it.get('url'))
    for it in (media.get('videos') or []):
        if isinstance(it, dict):
            _add('video', it.get('url'))
    return out


def twitter_mirror_media(url: str, timeout: int = 20):
    """يستعلم مرايا تويتر ويعيد (قائمة كل وسائط التغريدة مرتّبة، هل التغريدة
    حسّاسة/NSFW؟). كل عنصر {'type': 'photo'|'video', 'url': ...}.

    يغطي ما يعجز عنه yt-dlp: تغريدات الصور (يفشل بـ"No video could be found
    in this tweet") والتغريدات المختلطة/متعددة الفيديو (يستخرج الفيديو فقط
    ويُسقط الصور). قائمة فارغة لغير روابط المنشورات أو عند أي فشل."""
    import json
    import urllib.request
    low = (url or '').lower()
    if not any(m in low for m in PLATFORM_URL_MARKERS['twitter']):
        return [], False
    m = _TWITTER_STATUS_RE.search(url or '')
    if not m:
        return [], False  # ليس رابط منشور (بروفايل/بحث) — لا مرآة له
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
            items = [it for it in _extract_twitter_media_list(payload)
                     if is_safe_url(it['url'])]
            if items:
                sensitive = _twitter_payload_sensitive(payload)
                photos = sum(1 for it in items if it['type'] == 'photo')
                logger.info(
                    f"🎯 وسائط تويتر عبر {host}: {photos} صورة + "
                    f"{len(items) - photos} فيديو"
                    + (" (⚠️ حسّاس)" if sensitive else ""))
                return items, sensitive
            logger.info(f"ℹ️ {host} لم يُرجع وسائط تويتر")
        except Exception as e:
            logger.warning(f"⚠️ تعذّر جلب وسائط تويتر عبر {host}: {e}")
    return [], False


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
    """يحوّل رابط ملاحظة Substack إلى (رابط الفيديو المباشر، العنوان، هل هو
    محتوى صريح؟) عبر واجهة Substack العامة بلا كوكيز. الرابط المعاد هو وسيط
    /src الثابت الذي يحوّل لملف mp4 موقّعاً حديثاً عند كل طلب.

    علم explicit يأتي من تصنيف Substack نفسه للوسائط — يتيح للبوت رفض
    المحتوى الإباحي حين يكون فلتر المحتوى مفعّلاً. يعيد (None, None, False)
    لغير روابط الملاحظات أو لملاحظة بلا فيديو أو عند أي فشل."""
    import json
    import urllib.request
    m = _SUBSTACK_NOTE_RE.search(url or '')
    if not m:
        return None, None, False
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
        return None, None, False
    comment = ((payload or {}).get('item') or {}).get('comment') or {}
    for att in comment.get('attachments') or []:
        if not isinstance(att, dict):
            continue
        media_id = att.get('media_upload_id')
        if att.get('type') == 'video' and media_id and re.fullmatch(r'[\w-]+', str(media_id)):
            direct = f"https://substack.com/api/v1/video/upload/{media_id}/src"
            media = att.get('mediaUpload') if isinstance(att.get('mediaUpload'), dict) else {}
            explicit = bool(media.get('explicit'))
            # عنوان ودود: أول سطر من نص الملاحظة، وإلا اسم صاحبها، وإلا عام
            body = (comment.get('body') or '').strip()
            title = body.split('\n')[0][:80] if body else ''
            if not title:
                title = (comment.get('name') or '').strip() or 'Substack Video'
            if is_safe_url(direct):
                logger.info(f"🎯 فيديو ملاحظة Substack {comment_id}: {direct}"
                            + (" (⚠️ صريح)" if explicit else ""))
                return direct, title, explicit
    logger.info(f"ℹ️ ملاحظة Substack {comment_id} بلا مرفق فيديو")
    return None, None, False


def all_mirror_hosts():
    """يعيد قائمة (المنصة، المضيف) لكل مرايا البدائل المُهيّأة — لفحص الصحّة."""
    hosts = []
    for h in _INSTAGRAM_PROXY_HOSTS:
        hosts.append(('instagram', h))
    for h in _THREADS_PROXY_HOSTS:
        hosts.append(('threads', h))
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
