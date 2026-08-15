# -*- coding: utf-8 -*-
"""اختبارات اكتشاف browser impersonation الاختياري."""

from ytdlp_compat import _probe_chrome_impersonation


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
