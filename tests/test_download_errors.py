# -*- coding: utf-8 -*-
"""اختبارات تصنيف أخطاء التحميل (download_errors)."""

from download_errors import (
    _is_drm_error, _is_geo_restricted_error, _is_youtube_cookie_issue,
    _is_facebook_cookie_issue, _is_cookie_file_issue, _is_restricted_content_error,
    _is_http_403_error, _is_youtube_transport_error,
    _is_youtube_rescueable_error,
)


def test_drm_error():
    assert _is_drm_error('This video is DRM protected')
    assert not _is_drm_error('Video unavailable')


def test_geo_restricted_explicit():
    assert _is_geo_restricted_error('This video is not available in your country')
    assert _is_geo_restricted_error('This video is geo restricted')
    assert not _is_geo_restricted_error('Network timeout')


def test_geo_restricted_twitter_403():
    err = 'Unable to download video data: HTTP Error 403: Forbidden'
    assert _is_geo_restricted_error(err, url='https://x.com/user/status/1')
    # نفس الخطأ من منصة أخرى ليس حظراً جغرافياً
    assert not _is_geo_restricted_error(err, url='https://youtube.com/watch?v=1')


def test_youtube_cookie_issue():
    assert _is_youtube_cookie_issue('Requested format is not available')
    assert _is_youtube_cookie_issue('Sign in to confirm you are not a bot')
    assert not _is_youtube_cookie_issue('Video unavailable')


def test_facebook_cookie_issue():
    assert _is_facebook_cookie_issue('Cannot parse data')
    assert not _is_facebook_cookie_issue('HTTP Error 404')


def test_cookie_file_issue():
    assert _is_cookie_file_issue("cookies file is not in Netscape format")
    assert not _is_cookie_file_issue('netscape browser detected')


def test_http_403_error():
    assert _is_http_403_error('ERROR: unable to download video data: HTTP Error 403: Forbidden')
    assert _is_http_403_error('HTTP Error 403: Forbidden')
    assert not _is_http_403_error('HTTP Error 404: Not Found')
    assert not _is_http_403_error('Network timeout')


def test_youtube_transport_error_only_matches_network_failures():
    assert _is_youtube_transport_error('The read operation timed out')
    assert _is_youtube_transport_error(
        'Remote end closed connection without response')
    assert _is_youtube_transport_error('Incomplete Read (42 bytes read)')
    assert _is_youtube_transport_error(
        'IncompleteRead(42 bytes read, 100 more expected)')
    assert not _is_youtube_transport_error('FFmpeg postprocessing failed')
    assert not _is_youtube_transport_error('No space left on device')
    assert not _is_youtube_transport_error('HTTP Error 404: Not Found')
    assert not _is_youtube_transport_error('Video unavailable')


def test_youtube_rescueable_error_covers_client_limitations_not_local_errors():
    assert _is_youtube_rescueable_error('Video unavailable')
    assert _is_youtube_rescueable_error('Not available on this app')
    assert _is_youtube_rescueable_error('Sign in to confirm your age')
    assert not _is_youtube_rescueable_error('FFmpeg postprocessing failed')
    assert not _is_youtube_rescueable_error('No space left on device')
    assert not _is_youtube_rescueable_error('Permission denied')


def test_restricted_content():
    assert _is_restricted_content_error('This video may be inappropriate for some users')
    assert _is_restricted_content_error('Age-restricted video')
    assert not _is_restricted_content_error('Private video')
    assert not _is_restricted_content_error(None)
