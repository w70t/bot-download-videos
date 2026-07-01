# -*- coding: utf-8 -*-
"""
أدوات الروابط - URL Utilities
=============================
دوال نقيّة للتعامل مع الروابط: حماية SSRF، مفاتيح الكاش، استخراج الروابط
من النصوص، وتحديد المنصة. لا تعتمد على قاعدة البيانات أو عميل تيليجرام.
"""

import re
import socket
import ipaddress
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
    'snapchat': ['snapchat.'],
    'pinterest': ['pinterest.', 'pin.it'],
    'tiktok': ['tiktok.'],
}


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
