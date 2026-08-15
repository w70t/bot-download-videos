# -*- coding: utf-8 -*-
"""فحوص توافق اختيارية لميزات yt-dlp الإضافية."""

from functools import lru_cache

import yt_dlp

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
except ImportError:  # إصدارات yt-dlp القديمة لا تدعم المحاكاة
    ImpersonateTarget = None


def _probe_chrome_impersonation(ytdl_class):
    """أعد بصمة Chrome المعروفة فقط عندما يعلن backend أنه يدعمها.

    تحديد الإصدار والنظام مهم: تمرير ``chrome`` وحده يسمح للـbackend باختيار
    بصمة مختلفة بين الإصدارات، بينما صفحات Facebook الحديثة حساسة لتطابق
    بصمة TLS والمتصفح. Chrome 99/Windows 10 متاح في curl_cffi المتوافق الذي
    نثبته مع yt-dlp.
    """
    if ImpersonateTarget is None:
        return None
    try:
        target = ImpersonateTarget('chrome', '99', 'windows', '10')
        with ytdl_class({'quiet': True, 'no_warnings': True}) as ydl:
            is_available = getattr(ydl, '_impersonate_target_available', None)
            if is_available and is_available(target):
                return target
    except Exception:
        pass
    return None


@lru_cache(maxsize=1)
def chrome_impersonation_target():
    """نسخة مخزنة من فحص backend؛ لا تجعل curl_cffi اعتماداً إلزامياً."""
    return _probe_chrome_impersonation(yt_dlp.YoutubeDL)
