# -*- coding: utf-8 -*-
"""اختبارات مركزة لتسلسل محاولات YouTube وFacebook."""

import asyncio

import pytest

from download_errors import YOUTUBE_403_FALLBACK_CLIENTS
from download_retries import (
    FACEBOOK_IDENTITY_MISMATCH, ensure_facebook_identity,
    facebook_identity_match_filter, run_facebook_retries,
    run_youtube_retries, run_youtube_retries_with_rescue,
    youtube_extractor_args,
)


def test_youtube_format_error_uses_clean_visionos_once():
    calls = []

    async def fake_download(**options):
        calls.append(options)
        return 'ok'

    result = asyncio.run(run_youtube_retries(
        fake_download,
        RuntimeError('Requested format is not available'),
        'bv*+ba/b/best',
    ))

    assert result == 'ok'
    assert calls == [{
        'use_cookies': False,
        'fmt': 'bv*+ba/b/best',
        'yt_clients': YOUTUBE_403_FALLBACK_CLIENTS,
        'continuedl': False,
    }]


def test_youtube_403_uses_clean_visionos_once():
    calls = []

    async def fake_download(**options):
        calls.append(options)
        return 'ok'

    result = asyncio.run(run_youtube_retries(
        fake_download,
        RuntimeError('Unable to download video data: HTTP Error 403: Forbidden'),
        'bestaudio/best',
    ))

    assert result == 'ok'
    assert calls == [{
        'use_cookies': False,
        'fmt': 'bestaudio/best',
        'yt_clients': YOUTUBE_403_FALLBACK_CLIENTS,
        'continuedl': False,
    }]


def test_youtube_timeout_reextracts_with_clean_visionos_once():
    calls = []

    async def fake_download(**options):
        calls.append(options)
        return 'ok'

    result = asyncio.run(run_youtube_retries(
        fake_download,
        TimeoutError('The read operation timed out'),
        'bestaudio/best',
    ))

    assert result == 'ok'
    assert calls == [{
        'use_cookies': False,
        'fmt': 'bestaudio/best',
        'yt_clients': YOUTUBE_403_FALLBACK_CLIENTS,
        'continuedl': False,
    }]


def test_youtube_repeated_timeout_does_not_loop():
    calls = []

    async def always_timeout(**options):
        calls.append(options)
        raise TimeoutError('The read operation timed out')

    with pytest.raises(TimeoutError, match='timed out'):
        asyncio.run(run_youtube_retries(
            always_timeout,
            TimeoutError('The read operation timed out'),
            'bestaudio/best',
        ))

    assert calls == [{
        'use_cookies': False,
        'fmt': 'bestaudio/best',
        'yt_clients': YOUTUBE_403_FALLBACK_CLIENTS,
        'continuedl': False,
    }]


def test_youtube_visionos_unavailable_uses_one_final_default_rescue():
    calls = []
    rescue = {
        'use_cookies': True,
        'fmt': 'bestaudio/best',
        'yt_clients': ('default',),
        'network_retries': 15,
        'socket_timeout': 20,
        'continuedl': False,
    }

    async def fake_download(**options):
        calls.append(options)
        if len(calls) == 1:
            raise RuntimeError('Video unavailable')
        return 'rescued'

    result = asyncio.run(run_youtube_retries_with_rescue(
        fake_download,
        TimeoutError('The read operation timed out'),
        'bestaudio/best',
        rescue_options=rescue,
    ))

    assert result == 'rescued'
    assert calls == [
        {
            'use_cookies': False,
            'fmt': 'bestaudio/best',
            'yt_clients': YOUTUBE_403_FALLBACK_CLIENTS,
            'continuedl': False,
        },
        rescue,
    ]


def test_youtube_local_fallback_failure_never_retries_or_rescues():
    calls = []

    async def disk_full(**options):
        calls.append(options)
        raise RuntimeError('No space left on device')

    with pytest.raises(RuntimeError, match='No space'):
        asyncio.run(run_youtube_retries_with_rescue(
            disk_full,
            TimeoutError('The read operation timed out'),
            'bestaudio/best',
            rescue_options={'use_cookies': True},
        ))

    assert len(calls) == 1


def test_youtube_visited_options_prevent_403_retry_loop():
    calls = []

    async def always_403(**options):
        calls.append(options)
        raise RuntimeError('HTTP Error 403: Forbidden')

    with pytest.raises(RuntimeError, match='403'):
        asyncio.run(run_youtube_retries(
            always_403,
            RuntimeError('HTTP Error 403: Forbidden'),
            'bestaudio/best',
        ))

    assert calls == [
        {
            'use_cookies': False,
            'fmt': 'bestaudio/best',
            'yt_clients': YOUTUBE_403_FALLBACK_CLIENTS,
            'continuedl': False,
        },
    ]


def test_youtube_extractor_args_never_exposes_missing_pot_formats():
    args = youtube_extractor_args(('visionos',))

    assert args == {'youtube': {'player_client': ['visionos']}}
    assert 'formats' not in args['youtube']


def test_pinned_ytdlp_supports_the_visionos_fallback_client():
    from yt_dlp.extractor.youtube._base import INNERTUBE_CLIENTS

    assert YOUTUBE_403_FALLBACK_CLIENTS == ('visionos',)
    assert 'visionos' in INNERTUBE_CLIENTS


def test_facebook_uses_only_public_modes_even_when_cookiefile_exists():
    calls = []
    chrome = object()

    async def fake_download(**options):
        calls.append(options)
        if len(calls) < 2:
            raise RuntimeError('Cannot parse data')
        return 'facebook-ok'

    result = asyncio.run(run_facebook_retries(
        fake_download,
        has_cookiefile=True,
        impersonation_target=chrome,
    ))

    assert result == 'facebook-ok'
    assert calls == [
        {'use_cookies': False},
        {'use_cookies': False, 'impersonate': chrome},
    ]


def test_facebook_skips_impersonation_when_backend_unavailable():
    calls = []

    async def always_fail(**options):
        calls.append(options)
        raise RuntimeError('Cannot parse data')

    with pytest.raises(RuntimeError, match='Cannot parse data'):
        asyncio.run(run_facebook_retries(
            always_fail,
            has_cookiefile=True,
            impersonation_target=None,
        ))

    assert calls == [
        {'use_cookies': False},
    ]


def test_facebook_public_impersonation_stays_cookie_free_without_cookiefile():
    calls = []
    chrome = object()

    async def fake_download(**options):
        calls.append(options)
        if len(calls) == 1:
            raise RuntimeError('Cannot parse data')
        return 'ok'

    assert asyncio.run(run_facebook_retries(
        fake_download,
        has_cookiefile=False,
        impersonation_target=chrome,
    )) == 'ok'
    assert calls == [
        {'use_cookies': False},
        {'use_cookies': False, 'impersonate': chrome},
    ]


@pytest.mark.parametrize('message', (
    'No space left on device',
    'Postprocessing: ffmpeg exited with code 1',
    'Unable to download video data: HTTP Error 403',
))
def test_facebook_does_not_retry_local_or_media_download_failures(message):
    calls = []

    async def fail_once(**options):
        calls.append(options)
        raise RuntimeError(message)

    with pytest.raises(RuntimeError, match=message.split(':')[0]):
        asyncio.run(run_facebook_retries(
            fail_once,
            has_cookiefile=True,
            impersonation_target=object(),
        ))

    assert calls == [{'use_cookies': False}]


def test_facebook_identity_guard_accepts_only_requested_media_id():
    info = {'id': '123456'}
    assert ensure_facebook_identity(info, '123456') is info
    assert facebook_identity_match_filter('123456')(info) is None

    with pytest.raises(RuntimeError, match=FACEBOOK_IDENTITY_MISMATCH):
        ensure_facebook_identity({'id': '999999'}, '123456')
    assert FACEBOOK_IDENTITY_MISMATCH in facebook_identity_match_filter(
        '123456')({'id': '999999'})


def test_facebook_identity_filter_is_disabled_without_proven_target():
    assert facebook_identity_match_filter(None) is None
    info = {'id': 'anything'}
    assert ensure_facebook_identity(info, None) is info


@pytest.mark.parametrize('message', (
    'Requested format is not available',
    'No video formats found',
))
def test_facebook_retries_format_selection_failures_before_download(message):
    calls = []
    chrome = object()

    async def download(**options):
        calls.append(options)
        if len(calls) == 1:
            raise RuntimeError(message)
        return 'ok'

    result = asyncio.run(run_facebook_retries(
        download,
        has_cookiefile=True,
        impersonation_target=chrome,
    ))

    assert result == 'ok'
    assert calls == [
        {'use_cookies': False},
        {'use_cookies': False, 'impersonate': chrome},
    ]
