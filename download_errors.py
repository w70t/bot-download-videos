# -*- coding: utf-8 -*-
"""
تصنيف أخطاء التحميل - Download Error Classification
===================================================
دوال تفحص نص خطأ yt-dlp لتحديد سببه: DRM، حظر جغرافي، مشاكل كوكيز،
أو محتوى مقيّد بالعمر/حسّاس — ليتصرف البوت بالشكل المناسب (إعادة
المحاولة بدون كوكيز، أو رسالة واضحة للمستخدم).
"""

from url_utils import PLATFORM_URL_MARKERS


# عملاء يوتيوب البدلاء عند انتهاء/حجب رابط الصيغة بخطأ 403. نبقي القائمة
# هنا مع خطة إعادة المحاولة حتى تستخدمها كل نقاط الفشل (بما فيها المحاولة
# الثانية بلا كوكيز) بنفس الترتيب.
YOUTUBE_403_FALLBACK_CLIENTS = ('tv', 'ios', 'web_safari', 'mweb', 'android')


def _is_drm_error(err):
    """هل الفيديو محمي بـ DRM (لا يمكن تحميله إطلاقاً)؟"""
    return 'drm' in str(err).lower()


def _is_geo_restricted_error(err, url=''):
    """هل الفشل بسبب حظر جغرافي/حقوق بث للمحتوى (لا يمكن تحميله من منطقة الخادم)؟"""
    msg = str(err).lower()
    # عبارات yt-dlp الصريحة عن الحظر الجغرافي
    geo_signs = [
        'geo restrict', 'geo-restrict', 'geo restricted', 'geo blocked',
        'not available from your location', 'not available in your country',
        'not available in your region', 'blocked it in your country',
        'blocked in your country',
    ]
    if any(s in msg for s in geo_signs):
        return True
    # X/تويتر: فشل تنزيل بيانات الفيديو بـ403 = غالباً حظر جغرافي/حقوق بث للمقطع
    is_twitter = any(m in url.lower() for m in PLATFORM_URL_MARKERS['twitter'])
    if is_twitter and '403' in msg and (
        'download video data' in msg or 'm3u8' in msg or 'forbidden' in msg
    ):
        return True
    return False


def _is_http_403_error(err):
    """هل الفشل بسبب HTTP 403 Forbidden أثناء تنزيل بيانات الفيديو؟

    شائع في يوتيوب: روابط الصيغ التي يعطيها عميل مشغّل معيّن قد تنتهي صلاحيتها
    أو تُحظر (throttling) فيظهر 'unable to download video data: HTTP Error 403:
    Forbidden'. إعادة الاستخراج بعميل مشغّل آخر تُنتج روابط جديدة غير محظورة.
    """
    msg = str(err).lower()
    return '403' in msg and ('forbidden' in msg or 'download video data' in msg)


def _is_format_unavailable_error(err):
    """هل أخفق محدد الصيغة الصارم لأن الصيغة المطلوبة غير متاحة؟"""
    msg = str(err).lower()
    return 'requested format is not available' in msg or 'no video formats' in msg


def _youtube_retry_options(err, fallback_format):
    """يعيد محاولات يوتيوب التالية كخيارات ``download`` مرتبة.

    خطأ 403 يحتاج أولاً إعادة استخراج بعملاء مشغّل آخرين للحصول على روابط
    جديدة، ثم نفس العملاء مع صيغة متساهلة. أما غياب الصيغة وحده فيحتاج
    المحاولة المتساهلة بلا كوكيز. إرجاع الخطة كبيانات نقية يجعل المسار قابلاً
    للاختبار ويمنع اختلاف معالجة الخطأ بين المحاولة الأولى والثانية.
    """
    if _is_http_403_error(err):
        return (
            {
                'use_cookies': False,
                'yt_clients': YOUTUBE_403_FALLBACK_CLIENTS,
            },
            {
                'use_cookies': False,
                'fmt': fallback_format,
                'yt_clients': YOUTUBE_403_FALLBACK_CLIENTS,
            },
        )
    if _is_format_unavailable_error(err):
        return ({'use_cookies': False, 'fmt': fallback_format},)
    return ()


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


def _is_facebook_cookie_issue(err):
    """هل خطأ فيسبوك ناتج عن كوكيز فاسدة/منتهية تكسر استخراج المحتوى العام؟

    فيسبوك بكوكيز منتهية يقدّم صفحة تسجيل دخول/تحقّق لا يستطيع yt-dlp قراءتها
    فيظهر 'Cannot parse data'. المحتوى العام (الريلز) يُستخرج بدون كوكيز، لذا
    نعيد المحاولة بدونها.
    """
    msg = str(err).lower()
    return 'cannot parse data' in msg


def _is_facebook_retryable_error(err):
    """هل الفشل حدث أثناء استخراج Facebook قبل بدء تنزيل الوسائط؟

    لا نبدّل الجلسة بعد أخطاء القرص/FFmpeg/الكتابة أو تنزيل بيانات الفيديو؛
    إعادة تلك الحالات بأربع بصمات قد تكرر ملفًا كبيرًا ولا تعالج السبب المحلي.
    """
    msg = str(err).lower()
    local_or_media_failures = (
        'no space left', 'disk full', 'permission denied', 'read-only file',
        'ffmpeg', 'ffprobe', 'postprocessing', 'post-processing',
        'unable to download video data', 'unable to download audio data',
        'broken pipe',
    )
    if any(marker in msg for marker in local_or_media_failures):
        return False
    extraction_failures = (
        'cannot parse data',
        'facebook media identity mismatch',
        'facebook target identity unavailable',
        'login required',
        'log in to',
        'sign in to',
        'cookies are needed',
        'only available for registered users',
        'unable to extract',
        'unable to download webpage',
        'requested format is not available',
        'no video formats',
    )
    return any(marker in msg for marker in extraction_failures)


def _facebook_retry_options(has_cookiefile, impersonation_target=None):
    """يعيد أوضاع فيسبوك الفريدة بالترتيب من الأقل تدخلاً للأخير.

    نعطّل جلسة Facebook عمدًا: extractor القديم قد يربط معرّف URL ببيانات
    فيديو feed/إعلان محقونة داخل الصفحة المسجّلة، فلا تكفي مطابقة ``info.id``
    لإثبات الهوية. البوت يرفض الستوري قبل هذا المسار أصلًا، لذا تبقى محاولتا
    المحتوى العام فقط: عادية ثم ببصمة Chrome.
    """
    del has_cookiefile  # محفوظ في التوقيع للتوافق، لكنه غير مستخدم أمنيًا.
    attempts = [{'use_cookies': False}]
    if impersonation_target is not None:
        attempts.append({
            'use_cookies': False,
            'impersonate': impersonation_target,
        })
    return tuple(attempts)


def _is_cookie_file_issue(err):
    """هل الخطأ بسبب ملف كوكيز تالف/غير صالح (ليس بصيغة Netscape)؟

    ملف كوكيز معطوب يجعل yt-dlp يفشل قبل بدء الاستخراج لأي منصة، فنتجاوزه
    ونعيد المحاولة بدون كوكيز (يكفي للمحتوى العام).
    """
    msg = str(err).lower()
    return 'netscape' in msg and 'cookies' in msg


def _is_restricted_content_error(err_msg: str) -> bool:
    """يكتشف رسائل إنستغرام/غيره للمحتوى المقيّد بالعمر أو الحسّاس."""
    m = (err_msg or '').lower()
    return any(s in m for s in (
        'may be inappropriate',
        'certain audiences',
        'sensitive content',
        'age-restricted',
        'age restricted',
        'restricted video',
    ))
