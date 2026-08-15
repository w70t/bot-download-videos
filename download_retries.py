# -*- coding: utf-8 -*-
"""تنفيذ خطط إعادة محاولة التحميل دون الارتباط بواجهة تلجرام."""

from download_errors import (
    _facebook_retry_options, _is_facebook_retryable_error,
    _youtube_retry_options,
)


FACEBOOK_IDENTITY_MISMATCH = 'Facebook media identity mismatch'
FACEBOOK_IDENTITY_UNAVAILABLE = 'Facebook target identity unavailable'


def ensure_facebook_identity(info, expected_id):
    """ارفض نتيجة Facebook التي لا تثبت تطابقها مع معرّف الرابط."""
    if not expected_id:
        return info
    actual_id = info.get('id') if isinstance(info, dict) else None
    if actual_id is None:
        raise RuntimeError(FACEBOOK_IDENTITY_UNAVAILABLE)
    if str(actual_id) != str(expected_id):
        raise RuntimeError(FACEBOOK_IDENTITY_MISMATCH)
    return info


def facebook_identity_match_filter(expected_id):
    """مرشح yt-dlp يوقف الفيديو الخطأ قبل تنزيل أي bytes."""
    if not expected_id:
        return None

    def match_filter(info, *args, **kwargs):
        actual_id = info.get('id') if isinstance(info, dict) else None
        if actual_id is None:
            return FACEBOOK_IDENTITY_UNAVAILABLE
        if str(actual_id) != str(expected_id):
            return FACEBOOK_IDENTITY_MISMATCH
        return None

    return match_filter


def _attempt_key(options):
    """مفتاح ثابت يمنع تكرار محاولة yt-dlp نفسها داخل المهمة."""
    return (
        bool(options.get('use_cookies', True)),
        options.get('fmt'),
        tuple(options.get('yt_clients') or ()),
    )


async def run_youtube_retries(
        run_download, initial_error, fallback_format, on_attempt=None):
    """نفّذ محاولات يوتيوب مع إعادة تصنيف كل خطأ جديد.

    قد يبدأ المسار بخطأ صيغة، ثم يظهر 403 فقط أثناء المحاولة التالية. لذلك
    لا تكفي خطة ثابتة مشتقة من الخطأ الأول: كل فشل يولّد خطته الجديدة، مع
    ``visited`` لمنع الدوران أو تكرار الخيارات نفسها.
    """
    pending = list(_youtube_retry_options(initial_error, fallback_format))
    if not pending:
        raise initial_error

    visited = set()
    last_error = initial_error
    while pending:
        options = pending.pop(0)
        key = _attempt_key(options)
        if key in visited:
            continue
        visited.add(key)
        if on_attempt:
            on_attempt(options)
        try:
            return await run_download(**options)
        except Exception as retry_error:
            last_error = retry_error
            for new_options in _youtube_retry_options(retry_error, fallback_format):
                new_key = _attempt_key(new_options)
                if new_key not in visited and all(
                        _attempt_key(item) != new_key for item in pending):
                    pending.append(new_options)
    raise last_error


async def run_facebook_retries(
        run_download, *, has_cookiefile, impersonation_target=None,
        on_attempt=None):
    """جرّب أوضاع فيسبوك مرة واحدة لكل وضع، والمحاكاة في النهاية فقط."""
    last_error = None
    for options in _facebook_retry_options(
            has_cookiefile, impersonation_target=impersonation_target):
        if on_attempt:
            on_attempt(options)
        try:
            return await run_download(**options)
        except Exception as error:
            last_error = error
            if not _is_facebook_retryable_error(error):
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError('Facebook retry plan is empty')
