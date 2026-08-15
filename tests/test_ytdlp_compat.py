# -*- coding: utf-8 -*-
"""اختبارات اكتشاف ميزات yt-dlp الاختيارية."""

from types import SimpleNamespace

from ytdlp_compat import (
    _probe_chrome_impersonation, _probe_node_runtime,
    youtube_download_network_options,
)


class _FakeYDL:
    available = True

    def __init__(self, options):
        assert options['quiet'] is True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def _impersonate_target_available(self, target):
        assert str(target) == 'chrome-99:windows-10'
        return self.available


def test_chrome_impersonation_probe_returns_supported_target():
    target = _probe_chrome_impersonation(_FakeYDL)
    assert str(target) == 'chrome-99:windows-10'


def test_chrome_impersonation_probe_is_optional_when_unavailable():
    class UnavailableYDL(_FakeYDL):
        available = False

    assert _probe_chrome_impersonation(UnavailableYDL) is None


def test_node_runtime_probe_enables_supported_node():
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout='v22.22.0\n')

    assert _probe_node_runtime(lambda name: '/usr/bin/node', run) == {
        'js_runtimes': {'node': {}},
    }
    assert calls[0][0] == ['/usr/bin/node', '--version']
    assert calls[0][1]['timeout'] == 3


def test_node_runtime_probe_skips_missing_or_old_node():
    assert _probe_node_runtime(lambda name: None, None) == {}

    def old_node(*_args, **_kwargs):
        return SimpleNamespace(stdout='v20.19.0\n')

    assert _probe_node_runtime(lambda name: '/usr/bin/node', old_node) == {}


def test_node_runtime_probe_fails_closed():
    def broken(*_args, **_kwargs):
        raise OSError('probe failed')

    assert _probe_node_runtime(lambda name: '/usr/bin/node', broken) == {}


def test_youtube_download_network_options_fail_fast_by_default():
    assert youtube_download_network_options({}) == {
        'retries': 2,
        'socket_timeout': 10,
    }


def test_youtube_download_network_options_are_tunable_and_bounded():
    assert youtube_download_network_options({
        'YTDLP_YOUTUBE_RETRIES': '99',
        'YTDLP_YOUTUBE_SOCKET_TIMEOUT_SECONDS': '1',
    }) == {
        'retries': 15,
        'socket_timeout': 5,
    }


def test_youtube_download_network_options_ignore_invalid_values():
    assert youtube_download_network_options({
        'YTDLP_YOUTUBE_RETRIES': 'not-a-number',
        'YTDLP_YOUTUBE_SOCKET_TIMEOUT_SECONDS': '',
    }) == {
        'retries': 2,
        'socket_timeout': 10,
    }
