# -*- coding: utf-8 -*-
"""اختبارات محوّلات الروابط (link_resolvers) — بدون أي طلبات شبكية."""

from unittest.mock import patch

import json

import link_resolvers
from link_resolvers import (
    _is_music_link, _music_search_query, resolve_snapchat_spotlight,
    resolve_instagram_media, resolve_tiktok_media,
)


def test_is_music_link():
    assert _is_music_link('https://www.shazam.com/track/123/song-name')
    assert _is_music_link('https://music.apple.com/us/album/x/1?i=2')
    assert _is_music_link('https://open.spotify.com/track/abc')
    assert not _is_music_link('https://open.spotify.com/playlist/abc')
    assert not _is_music_link('https://youtube.com/watch?v=1')


def test_shazam_query_from_fragment():
    url = ('https://www.shazam.com/track/123/x#'
           '%7B%22title%22%3A%22Kifak%20Inta%22%2C%22artist%22%3A%22Fairuz%22%7D')
    assert _music_search_query(url) == 'Fairuz Kifak Inta'


def test_shazam_query_from_slug():
    # بدون fragment: يستخرج الاسم من مسار الرابط /track/<id>/<slug>
    assert _music_search_query('https://www.shazam.com/track/123/kifak-inta') == 'kifak inta'


def test_snapchat_resolver_ignores_other_urls():
    # روابط غير سناب شات تعود كما هي دون أي طلب شبكي
    url = 'https://youtube.com/watch?v=1'
    assert resolve_snapchat_spotlight(url) == url


# ── resolve_instagram_media ─────────────────────────────────────

def test_instagram_resolver_ignores_non_instagram():
    # روابط غير إنستغرام تعود None بلا أي طلب شبكي
    assert resolve_instagram_media('https://youtube.com/watch?v=1') is None
    assert resolve_instagram_media('') is None


def test_instagram_resolver_ignores_story_and_profile():
    # الستوري/البروفايل ليست منشور فيديو → None بلا طلب شبكي
    assert resolve_instagram_media('https://www.instagram.com/someuser/') is None
    assert resolve_instagram_media('https://www.instagram.com/stories/u/123/') is None


class _FakeResp:
    """محاكاة استجابة urlopen مع نوع محتوى ورابط نهائي."""
    def __init__(self, ctype, final):
        self._ctype, self._final = ctype, final
        self.headers = self

    def get_content_type(self):
        return self._ctype

    def geturl(self):
        return self._final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_instagram_resolver_returns_direct_video(monkeypatch):
    # مرآة تُرجع فيديو mp4 → نعيد الرابط النهائي المباشر
    final = 'https://scontent.cdninstagram.com/o1/v/abc.mp4?oe=1'
    with patch('urllib.request.urlopen', return_value=_FakeResp('video/mp4', final)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_instagram_media('https://www.instagram.com/reel/ABC123/?igsh=x')
    assert out == final


def test_instagram_resolver_skips_non_video(monkeypatch):
    # منشور صور (المرآة تُرجع صورة لا فيديو) → None ليكمل مسار الصور
    with patch('urllib.request.urlopen',
               return_value=_FakeResp('image/jpeg', 'https://x/pic.jpg')):
        out = resolve_instagram_media('https://www.instagram.com/p/ABC123/')
    assert out is None


def test_instagram_resolver_handles_network_error():
    # فشل الطلب الشبكي → None بلا استثناء
    with patch('urllib.request.urlopen', side_effect=OSError('boom')):
        out = resolve_instagram_media('https://www.instagram.com/reel/ABC123/')
    assert out is None


# ── resolve_tiktok_media ────────────────────────────────────────

class _FakeJsonResp:
    """محاكاة استجابة urlopen تُرجع جسم JSON عبر read()."""
    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self, *a):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_tiktok_resolver_ignores_non_tiktok():
    # روابط غير تيك توك تعود None بلا أي طلب شبكي
    assert resolve_tiktok_media('https://youtube.com/watch?v=1') is None
    assert resolve_tiktok_media('') is None


def test_tiktok_resolver_returns_direct_video():
    # المرآة تُرجع رابط hdplay مباشر → نعيده
    play = 'https://tikwm.com/video/media/hdplay/abc.mp4'
    payload = {'code': 0, 'data': {'hdplay': play, 'play': 'https://x/p.mp4'}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_tiktok_media('https://vt.tiktok.com/ZSCV5WkL7')
    assert out == play


def test_tiktok_resolver_prepends_host_for_relative_path():
    # مسار نسبي من المرآة → يُكمَّل برابط كامل على مضيف المرآة
    payload = {'code': 0, 'data': {'play': '/video/media/play/abc.mp4'}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_tiktok_media('https://www.tiktok.com/@u/video/123')
    assert out == 'https://tikwm.com/video/media/play/abc.mp4'


def test_tiktok_resolver_none_when_no_media():
    # المرآة لا تُرجع أي رابط فيديو (منشور صور/فشل) → None
    payload = {'code': -1, 'data': {}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)):
        out = resolve_tiktok_media('https://vt.tiktok.com/ZSCV5WkL7')
    assert out is None


def test_tiktok_resolver_handles_network_error():
    # فشل الطلب الشبكي → None بلا استثناء
    with patch('urllib.request.urlopen', side_effect=OSError('boom')):
        out = resolve_tiktok_media('https://vt.tiktok.com/ZSCV5WkL7')
    assert out is None
