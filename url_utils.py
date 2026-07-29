# -*- coding: utf-8 -*-
"""
أدوات الروابط - URL Utilities
=============================
دوال نقيّة للتعامل مع الروابط: حماية SSRF، مفاتيح الكاش، استخراج الروابط
من النصوص، وتحديد المنصة. لا تعتمد على قاعدة البيانات أو عميل تيليجرام.
"""

import os
import re
import socket
import ipaddress
import threading
import time
from urllib.parse import urlparse, parse_qsl, urlencode

# ربط أجزاء الرابط بالمنصة المناسبة لاختيار ملف الـ cookies الصحيح
PLATFORM_URL_MARKERS = {
    'youtube': ['youtube.', 'youtu.be'],
    'facebook': ['facebook.', 'fb.watch', 'fb.com'],
    'instagram': ['instagram.', 'instagr.am'],
    'threads': ['threads.net', 'threads.com'],
    # ملاحظة: 't.co/' بشرطة لتفادي مطابقة "snapcha[t.co]m" الخاطئة، و'//x.com'
    # لتفادي مطابقة نطاقات تنتهي بـ x.com (مثل netflix.com).
    'twitter': ['twitter.', '//x.com', 't.co/'],
    'reddit': ['reddit.', 'redd.it'],
    # sc-cdn.net: مضيف وسائط سناب. بعد تحويل الرابط للنسخة النظيفة يصير هذا هو
    # الرابط العامل، فبدونه يُعدّ المقطع «منصة أخرى» فيضيع اسم المنصة في
    # المعاينة ويظهر معرّف الملف عنواناً بدل «Snapchat Video».
    'snapchat': ['snapchat.', 'sc-cdn.net'],
    'pinterest': ['pinterest.', 'pin.it'],
    'tiktok': ['tiktok.'],
}


# ═══════════════════════════════════════════════════════════════
# ذاكرة نتيجة فحص المضيف (حماية SSRF)
# ‏socket.getaddrinfo استدعاء حاجب، وقياسه ميدانياً ٢٠–٢١٥ م.ث للطلب الواحد،
# والمتكرّر يكلّف مثل الأول تماماً (لا تخزين في النظام). وهو يُستدعى داخل حلقة
# الأحداث لكل رسالة، فيُجمّد البوت لكل الأعضاء قبل أن يبدأ أي عمل. المضيفات
# قليلة ومتكرّرة (تيك توك، إنستغرام، المرايا…) فتخزين الحكم يُلغي التكلفة.
#
# المهلة قصيرة عمداً: حكم «آمن» مخزَّن يوسّع نافذة إعادة ربط DNS نظرياً، فنبقيها
# دقائق معدودة. والحكم «غير آمن» يُخزَّن أيضاً (تخزينه لا يضعف الحماية).
# ═══════════════════════════════════════════════════════════════
_HOST_TTL = int(os.getenv('URL_HOST_CACHE_TTL', '300'))
_HOST_CACHE_MAX = int(os.getenv('URL_HOST_CACHE_MAX', '512'))
_host_cache = {}
_host_lock = threading.Lock()


def clear_host_cache():
    """يفرغ ذاكرة فحص المضيفات (للاختبارات أو بعد تغيّر الشبكة)."""
    with _host_lock:
        _host_cache.clear()


def _resolve_is_private(host: str) -> bool:
    """الفحص الفعلي بلا ذاكرة: يحلّ المضيف ويفحص كل عناوينه."""
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


def _is_private_host(host: str) -> bool:
    """هل المضيف عنوان داخلي/خاص/loopback أو غير قابل للحل؟ (حماية SSRF)
    يرجع True لمنع التحميل (أي العنوان غير آمن).

    النتيجة مخزَّنة بمهلة قصيرة — انظر تعليق الذاكرة أعلاه."""
    if not host:
        return True
    host = host.strip().strip('[]').lower()
    # احجب أسماء المضيف المحلية الواضحة (بلا أي طلب شبكي ولا تخزين)
    if host in ('localhost', 'localhost.localdomain') or host.endswith('.local') \
            or host.endswith('.internal'):
        return True

    now = time.monotonic()
    with _host_lock:
        hit = _host_cache.get(host)
        if hit is not None and now - hit[1] < _HOST_TTL:
            return hit[0]

    verdict = _resolve_is_private(host)   # خارج القفل: لا نحجب بقيّة الخيوط

    with _host_lock:
        if len(_host_cache) >= _HOST_CACHE_MAX:
            _host_cache.pop(next(iter(_host_cache)), None)
        _host_cache[host] = (verdict, now)
    return verdict


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


# نمط استخراج الرابط من نص الرسالة: محصور بمحارف الرابط (ASCII) فقط، فيتوقّف
# تلقائياً عند المسافة أو الإيموجي أو الحروف العربية الملاصقة.
_URL_IN_TEXT_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")


def extract_first_url(text: str):
    """يستخرج أول رابط http(s) من نص الرسالة ويزيل اللواصق الشائعة عند النسخ.

    تختلف الأجهزة/التطبيقات في طريقة نسخ/مشاركة الروابط: أحياناً يأتي الرابط
    وحده، وأحياناً مع نص أو إيموجي أو في سطر منفصل، أو تتبعه علامة ترقيم.
    أخذ نص الرسالة كاملاً كرابط كان يكسر الاستخراج (Failed to extract video info).
    هنا نلتقط الرابط فقط وننظّف علامات الترقيم/الأقواس الملاصقة في نهايته."""
    if not text:
        return None
    m = _URL_IN_TEXT_RE.search(text)
    if not m:
        return None
    url = m.group(0).rstrip(".,;:!?)]}>'\"`،؛؟")
    return url or None


def _url_host(url):
    """يستخرج اسم المضيف (host) من الرابط بصيغة صغيرة."""
    try:
        host = urlparse(url if '://' in url else 'http://' + url).hostname or ''
    except Exception:
        host = ''
    return host.lower().lstrip('.')
