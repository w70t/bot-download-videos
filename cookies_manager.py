# -*- coding: utf-8 -*-
"""
إدارة ملفات الكوكيز - Cookies Manager
=====================================
اختيار ملف الكوكيز المطابق لمنصة الرابط، وقراءة ملفات Netscape،
والتحقق الحقيقي من صلاحية كوكيز كل منصة.
"""

import os
import time
import logging

from url_utils import PLATFORM_URL_MARKERS

logger = logging.getLogger(__name__)

# منصات الـ cookies المدعومة
COOKIES_PLATFORMS = {
    'facebook': {'name': 'Facebook 📘', 'file': 'cookies/facebook.txt'},
    'instagram': {'name': 'Instagram 📷', 'file': 'cookies/instagram.txt'},
    'youtube': {'name': 'YouTube 📺', 'file': 'cookies/youtube.txt'},
    'twitter': {'name': 'Twitter/X 🐦', 'file': 'cookies/twitter.txt'},
    'reddit': {'name': 'Reddit 👽', 'file': 'cookies/reddit.txt'},
    'snapchat': {'name': 'Snapchat 👻', 'file': 'cookies/snapchat.txt'},
    'pinterest': {'name': 'Pinterest 📌', 'file': 'cookies/pinterest.txt'},
    'tiktok': {'name': 'TikTok 🎵', 'file': 'cookies/tiktok.txt'},
    'other': {'name': 'أخرى 🌐', 'file': 'cookies/other.txt'},
}

# منصات تشارك ملف cookies منصة أخرى (Threads يستخدم تسجيل دخول Instagram)
COOKIE_SOURCE_MAP = {
    'threads': 'instagram',
}

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
