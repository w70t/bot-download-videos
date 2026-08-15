# -*- coding: utf-8 -*-
"""فحوص توافق اختيارية لميزات yt-dlp الإضافية."""

from functools import lru_cache
import os
import re
import shutil
import subprocess

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


def _probe_node_runtime(which=shutil.which, run=subprocess.run):
    """فعّل Node ليتولى yt-dlp تحديات JavaScript عندما يكون إصداراً مدعوماً."""
    node = which('node')
    if not node:
        return {}
    try:
        result = run(
            [node, '--version'], capture_output=True, text=True,
            timeout=3, check=True)
        match = re.match(r'^v?(\d+)', (result.stdout or '').strip())
        if not match or int(match.group(1)) < 22:
            return {}
    except Exception:
        return {}
    return {'js_runtimes': {'node': {}}}


@lru_cache(maxsize=1)
def youtube_js_runtime_options():
    """خيارات yt-dlp المخزنة لتفعيل Node 22+ من دون كلفة فحص لكل طلب."""
    return _probe_node_runtime()


def _bounded_env_int(environ, name, default, minimum, maximum):
    """اقرأ عدداً صحيحاً مضبوط الحدود دون جعل خطأ الإعداد يمنع إقلاع البوت."""
    try:
        value = int(str(environ.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def youtube_download_network_options(environ=None):
    """مهلة ومحاولات قصيرة لروابط وسائط YouTube المتعثرة.

    ``yt-dlp`` يعيد رابط CDN نفسه داخلياً قبل أن يعيد الخطأ للكود الخارجي.
    إبقاء القيمة العامة (15) قد يؤخر الانتقال إلى عميل YouTube البديل نحو
    دقيقة رغم أن الجهاز والاتصال سليمان. هذه الخيارات تخص YouTube وحده؛
    محاولات الأجزاء تبقى كما هي لحماية تنزيلات DASH/HLS الطويلة.
    """
    env = os.environ if environ is None else environ
    return {
        # initial request + محاولتان إضافيتان قبل إعادة تصنيف الخطأ
        'retries': _bounded_env_int(
            env, 'YTDLP_YOUTUBE_RETRIES', 2, 0, 15),
        # لا تترك اتصالاً بلا بيانات معلقاً إلى أجل غير محدود
        'socket_timeout': _bounded_env_int(
            env, 'YTDLP_YOUTUBE_SOCKET_TIMEOUT_SECONDS', 10, 5, 60),
    }
