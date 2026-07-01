# -*- coding: utf-8 -*-
"""
تصنيف أخطاء التحميل - Download Error Classification
===================================================
دوال تفحص نص خطأ yt-dlp لتحديد سببه: DRM، حظر جغرافي، مشاكل كوكيز،
أو محتوى مقيّد بالعمر/حسّاس — ليتصرف البوت بالشكل المناسب (إعادة
المحاولة بدون كوكيز، أو رسالة واضحة للمستخدم).
"""

from url_utils import PLATFORM_URL_MARKERS


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
