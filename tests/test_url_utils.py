# -*- coding: utf-8 -*-
"""اختبارات أدوات الروابط (url_utils)."""

from unittest.mock import patch

import url_utils
from url_utils import (
    is_safe_url, cache_key_for_url, extract_first_url, _platform_of, _url_host,
    clear_host_cache,
)


class TestHostCache:
    """ذاكرة فحص المضيف: getaddrinfo حاجب (قيس ٢٠–٢١٥ م.ث) ويُستدعى داخل
    حلقة الأحداث لكل رسالة — فالذاكرة تُلغي التكرار دون إضعاف الحماية."""

    def setup_method(self):
        clear_host_cache()

    def teardown_method(self):
        clear_host_cache()

    def test_resolution_happens_once_per_host(self):
        calls = []

        def _fake(host, _port):
            calls.append(host)
            return [(2, 1, 6, '', ('93.184.216.34', 0))]

        with patch.object(url_utils.socket, 'getaddrinfo', side_effect=_fake):
            for _ in range(25):
                assert is_safe_url('https://example.com/a')
        assert len(calls) == 1        # ٢٤ رحلة DNS أُلغيت

    def test_private_verdict_also_cached(self):
        calls = []

        def _fake(host, _port):
            calls.append(host)
            return [(2, 1, 6, '', ('10.0.0.5', 0))]

        with patch.object(url_utils.socket, 'getaddrinfo', side_effect=_fake):
            assert not is_safe_url('https://internal.example/a')
            assert not is_safe_url('https://internal.example/b')
        assert len(calls) == 1

    def test_cache_is_per_host(self):
        def _fake(host, _port):
            ip = '10.0.0.5' if host == 'bad.example' else '93.184.216.34'
            return [(2, 1, 6, '', (ip, 0))]

        with patch.object(url_utils.socket, 'getaddrinfo', side_effect=_fake):
            assert is_safe_url('https://good.example/a')
            assert not is_safe_url('https://bad.example/a')
            assert is_safe_url('https://good.example/b')

    def test_local_names_never_reach_dns(self):
        # الأسماء المحلية تُرفض بلا أي طلب — قبل الذاكرة وقبل الشبكة
        def _boom(*a):
            raise AssertionError('ما كان ينبغي حلّ هذا المضيف')

        with patch.object(url_utils.socket, 'getaddrinfo', side_effect=_boom):
            assert not is_safe_url('http://localhost/x')
            assert not is_safe_url('http://db.internal/x')
            assert not is_safe_url('http://x.local/x')

    def test_expired_entry_is_re_resolved(self):
        calls = []

        def _fake(host, _port):
            calls.append(host)
            return [(2, 1, 6, '', ('93.184.216.34', 0))]

        with patch.object(url_utils.socket, 'getaddrinfo', side_effect=_fake):
            is_safe_url('https://example.com/a')
            with patch.object(url_utils, '_HOST_TTL', -1):
                is_safe_url('https://example.com/a')
        assert len(calls) == 2

    def test_cache_is_bounded(self):
        def _fake(host, _port):
            return [(2, 1, 6, '', ('93.184.216.34', 0))]

        with patch.object(url_utils.socket, 'getaddrinfo', side_effect=_fake), \
                patch.object(url_utils, '_HOST_CACHE_MAX', 8):
            for i in range(40):
                is_safe_url(f'https://h{i}.example/a')
        assert len(url_utils._host_cache) <= 8

    def test_unresolvable_host_stays_unsafe(self):
        with patch.object(url_utils.socket, 'getaddrinfo',
                          side_effect=OSError('لا يُحلّ')):
            assert not is_safe_url('https://nope.invalid/a')
            assert not is_safe_url('https://nope.invalid/a')


class TestIsSafeUrl:
    def test_rejects_localhost(self):
        assert not is_safe_url('http://localhost/video')
        assert not is_safe_url('http://127.0.0.1/video')

    def test_rejects_private_ranges(self):
        assert not is_safe_url('http://192.168.1.1/x')
        assert not is_safe_url('http://10.0.0.5/x')
        assert not is_safe_url('http://169.254.1.1/x')

    def test_rejects_non_http_schemes(self):
        assert not is_safe_url('ftp://example.com/file')
        assert not is_safe_url('file:///etc/passwd')

    def test_accepts_public_ip(self):
        # عنوان IP عام لا يحتاج DNS (يعمل بدون شبكة)
        assert is_safe_url('http://8.8.8.8/video')

    def test_rejects_internal_suffixes(self):
        assert not is_safe_url('http://myserver.local/x')
        assert not is_safe_url('http://db.internal/x')


class TestCacheKeyForUrl:
    def test_strips_tracking_params(self):
        assert (cache_key_for_url('https://www.youtube.com/watch?v=abc&si=xyz')
                == 'youtube.com/watch?v=abc')

    def test_strips_fragment_and_www(self):
        assert (cache_key_for_url('https://WWW.TikTok.com/@user/video/123#comment')
                == 'tiktok.com/@user/video/123')

    def test_same_video_different_tracking_same_key(self):
        a = cache_key_for_url('https://youtu.be/abc?si=AAA&utm_source=share')
        b = cache_key_for_url('https://youtu.be/abc?si=BBB')
        assert a == b

    def test_different_videos_different_keys(self):
        a = cache_key_for_url('https://youtu.be/abc')
        b = cache_key_for_url('https://youtu.be/def')
        assert a != b

    def test_meaningful_params_kept(self):
        key = cache_key_for_url('https://www.youtube.com/watch?v=abc')
        assert 'v=abc' in key


class TestExtractFirstUrl:
    def test_plain_url(self):
        assert extract_first_url('https://tiktok.com/@a/video/1') == 'https://tiktok.com/@a/video/1'

    def test_url_inside_arabic_text(self):
        assert (extract_first_url('شوف هذا المقطع https://youtu.be/abc رهيب!')
                == 'https://youtu.be/abc')

    def test_trailing_punctuation_stripped(self):
        assert extract_first_url('https://x.com/a/status/1!') == 'https://x.com/a/status/1'
        assert extract_first_url('(https://x.com/a/status/1)') == 'https://x.com/a/status/1'

    def test_no_url_returns_none(self):
        assert extract_first_url('مرحبا كيف الحال') is None
        assert extract_first_url('') is None
        assert extract_first_url(None) is None


class TestPlatformOf:
    def test_known_platforms(self):
        assert _platform_of('https://www.youtube.com/watch?v=1') == 'youtube'
        assert _platform_of('https://youtu.be/1') == 'youtube'
        assert _platform_of('https://vm.tiktok.com/x') == 'tiktok'
        assert _platform_of('https://x.com/user/status/1') == 'twitter'
        assert _platform_of('https://www.instagram.com/reel/x') == 'instagram'

    def test_netflix_not_matched_as_twitter(self):
        # '//x.com' بدل 'x.com' حتى لا تتطابق نطاقات تنتهي بـ x.com
        assert _platform_of('https://netflix.com/watch/1') == 'other'

    def test_snapchat_not_matched_as_twitter(self):
        # 't.co/' بالشرطة حتى لا يطابق snapcha[t.co]m
        assert _platform_of('https://snapchat.com/t/abc') == 'snapchat'

    def test_snapchat_cdn_host_is_snapchat(self):
        # بعد التحويل للنسخة النظيفة يصير رابط CDN هو العامل، فلا بد أن يبقى
        # معروفاً كسناب وإلا ضاع اسم المنصة وظهر معرّف الملف عنواناً
        assert _platform_of(
            'https://bolt-gcdn.sc-cdn.net/bp/abcDEF123456789x.1034.IRZXSOY'
        ) == 'snapchat'
        assert _platform_of(
            'https://cf-st.sc-cdn.net/d/abcDEF123456789x.27.IRZXSOY'
        ) == 'snapchat'

    def test_unknown(self):
        assert _platform_of('https://example.com/v') == 'other'


class TestUrlHost:
    def test_basic(self):
        assert _url_host('https://www.Example.COM/path') == 'www.example.com'

    def test_schemeless(self):
        assert _url_host('example.com/path') == 'example.com'

    def test_invalid(self):
        assert _url_host('') == ''
