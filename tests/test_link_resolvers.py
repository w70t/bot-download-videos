# -*- coding: utf-8 -*-
"""اختبارات محوّلات الروابط (link_resolvers) — بدون أي طلبات شبكية."""

from unittest.mock import patch

import json

import link_resolvers
from link_resolvers import (
    _is_music_link, _music_search_query, resolve_snapchat_spotlight,
    resolve_instagram_media, resolve_tiktok_media, resolve_tiktok_images,
    resolve_twitter_media, _extract_twitter_media, all_mirror_hosts,
    resolve_pinterest_media, resolve_pinterest_images, _pinterest_pin_id,
    _extract_pinterest_video, _extract_pinterest_images, _upscale_pinimg,
)


def test_all_mirror_hosts_lists_configured_mirrors():
    hosts = all_mirror_hosts()
    # قائمة أزواج (منصة، مضيف) تشمل المرايا الافتراضية
    assert all(isinstance(p, tuple) and len(p) == 2 for p in hosts)
    platforms = {p for p, _ in hosts}
    assert {'instagram', 'tiktok', 'twitter', 'pinterest'} <= platforms
    host_names = {h for _, h in hosts}
    assert 'tikwm.com' in host_names
    assert 'api.vxtwitter.com' in host_names
    assert 'www.pinterest.com' in host_names


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


class _FakeRedirect:
    """محاكاة استجابة urlopen لاتّباع تحويل رابط مختصر (geturl فقط)."""
    def __init__(self, final):
        self._final = final

    def geturl(self):
        return self._final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_tiktok_resolver_returns_direct_video():
    # المرآة تُرجع رابط hdplay مباشر (رابط كامل بلا توسيع) → نعيده
    play = 'https://tikwm.com/video/media/hdplay/abc.mp4'
    payload = {'code': 0, 'data': {'hdplay': play, 'play': 'https://x/p.mp4'}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_tiktok_media('https://www.tiktok.com/@u/video/123')
    assert out == play


def test_tiktok_resolver_prepends_host_for_relative_path():
    # مسار نسبي من المرآة → يُكمَّل برابط كامل على مضيف المرآة
    payload = {'code': 0, 'data': {'play': '/video/media/play/abc.mp4'}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_tiktok_media('https://www.tiktok.com/@u/video/123')
    assert out == 'https://tikwm.com/video/media/play/abc.mp4'


def test_tiktok_resolver_expands_short_link():
    # رابط مختصر (vt.tiktok) → يُوسَّع أولاً ثم يُستعلم المرآة بالرابط الكامل
    play = 'https://tikwm.com/video/media/play/abc.mp4'
    full = 'https://www.tiktok.com/@u/video/123'
    payload = {'code': 0, 'data': {'play': play}}
    # أول urlopen = اتّباع التحويل، الثاني = استعلام المرآة
    with patch('urllib.request.urlopen',
               side_effect=[_FakeRedirect(full), _FakeJsonResp(payload)]), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_tiktok_media('https://vt.tiktok.com/ZSCV5WkL7')
    assert out == play


def test_tiktok_resolver_none_when_no_media():
    # المرآة لا تُرجع أي رابط فيديو (منشور صور/فشل) → None
    payload = {'code': -1, 'data': {}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)):
        out = resolve_tiktok_media('https://www.tiktok.com/@u/video/123')
    assert out is None


def test_tiktok_resolver_handles_network_error():
    # فشل الطلب الشبكي → None بلا استثناء
    with patch('urllib.request.urlopen', side_effect=OSError('boom')):
        out = resolve_tiktok_media('https://www.tiktok.com/@u/video/123')
    assert out is None


# ── resolve_tiktok_images ───────────────────────────────────────

def test_tiktok_images_ignores_non_tiktok():
    assert resolve_tiktok_images('https://youtube.com/watch?v=1') == []
    assert resolve_tiktok_images('') == []


def test_tiktok_images_returns_urls():
    imgs = ['https://tikwm.com/img/1.jpg', 'https://tikwm.com/img/2.jpg']
    payload = {'code': 0, 'data': {'images': imgs}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_tiktok_images('https://www.tiktok.com/@u/photo/123')
    assert out == imgs


def test_tiktok_images_empty_for_video_post():
    # منشور فيديو (لا صور) → قائمة فارغة
    payload = {'code': 0, 'data': {'play': 'https://x/v.mp4'}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)):
        out = resolve_tiktok_images('https://www.tiktok.com/@u/video/123')
    assert out == []


def test_tiktok_images_handles_network_error():
    with patch('urllib.request.urlopen', side_effect=OSError('boom')):
        out = resolve_tiktok_images('https://www.tiktok.com/@u/photo/123')
    assert out == []


# ── resolve_twitter_media ───────────────────────────────────────

def test_twitter_resolver_ignores_non_twitter():
    # روابط غير تويتر (وروابط تويتر بلا معرّف منشور) → None بلا طلب شبكي
    assert resolve_twitter_media('https://youtube.com/watch?v=1') is None
    assert resolve_twitter_media('https://x.com/someuser') is None
    assert resolve_twitter_media('') is None


def test_twitter_extract_from_vxtwitter_shape():
    # شكل vxtwitter: media_extended بنوع فيديو صريح
    vid = 'https://video.twimg.com/amplify_video/1/vid/avc1/x.mp4'
    payload = {'hasMedia': True,
               'mediaURLs': [vid],
               'media_extended': [{'type': 'video', 'url': vid}]}
    assert _extract_twitter_media(payload) == vid


def test_twitter_extract_from_fxtwitter_shape():
    # شكل fxtwitter: الوسائط متداخلة تحت tweet.media.videos
    vid = 'https://video.twimg.com/amplify_video/2/vid/avc1/y.mp4'
    payload = {'code': 200, 'tweet': {'media': {'videos': [{'type': 'video', 'url': vid}]}}}
    assert _extract_twitter_media(payload) == vid


def test_twitter_extract_none_for_photo_only():
    # منشور صور فقط → لا فيديو
    payload = {'mediaURLs': ['https://pbs.twimg.com/media/x.jpg'],
               'media_extended': [{'type': 'image', 'url': 'https://pbs.twimg.com/media/x.jpg'}]}
    assert _extract_twitter_media(payload) is None


def test_twitter_resolver_returns_direct_video():
    vid = 'https://video.twimg.com/amplify_video/9/vid/avc1/z.mp4'
    payload = {'media_extended': [{'type': 'video', 'url': vid}]}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_twitter_media('https://x.com/user/status/2072917832770228479?s=46')
    assert out == vid


def test_twitter_resolver_handles_network_error():
    with patch('urllib.request.urlopen', side_effect=OSError('boom')):
        out = resolve_twitter_media('https://twitter.com/user/status/123')
    assert out is None


# ── resolve_pinterest_media / resolve_pinterest_images ─────────

def test_pinterest_pin_id_from_full_url():
    # معرّف رقمي من رابط Pin كامل بلا أي طلب شبكي
    assert _pinterest_pin_id('https://www.pinterest.com/pin/1234567890123/') == '1234567890123'
    assert _pinterest_pin_id('https://pinterest.co.uk/pin/9876543210/?mt=login') == '9876543210'
    # بروفايل/لوحة → None
    assert _pinterest_pin_id('https://www.pinterest.com/someuser/board/') is None


def test_pinterest_pin_id_expands_short_link():
    # رابط pin.it مختصر → يُوسَّع باتّباع التحويل ثم يُستخرج المعرّف
    full = 'https://www.pinterest.com/pin/1234567890123/sent/?invite_code=x'
    with patch('urllib.request.urlopen', return_value=_FakeRedirect(full)):
        assert _pinterest_pin_id('https://pin.it/AbCdEf123') == '1234567890123'


def test_pinterest_resolvers_ignore_non_pinterest():
    # روابط غير بينتريست → None/[] بلا أي طلب شبكي
    assert resolve_pinterest_media('https://youtube.com/watch?v=1') is None
    assert resolve_pinterest_media('') is None
    assert resolve_pinterest_images('https://youtube.com/watch?v=1') == []
    assert resolve_pinterest_images('') == []


def test_pinterest_video_prefers_mp4_over_hls():
    # video_list فيها HLS أعرض وmp4 أضيق → نفضّل mp4
    pin = {'videos': {'video_list': {
        'HLS': {'url': 'https://v.pinimg.com/x.m3u8', 'width': 1080},
        'V_720P': {'url': 'https://v.pinimg.com/720p/x.mp4', 'width': 720},
    }}}
    assert _extract_pinterest_video(pin) == 'https://v.pinimg.com/720p/x.mp4'


def test_pinterest_video_from_story_pages():
    # Idea Pin: الفيديو داخل صفحات story_pin_data
    vid = 'https://v.pinimg.com/videos/mc/720p/a.mp4'
    pin = {'story_pin_data': {'pages': [
        {'blocks': [{'video': {'video_list': {'V_720P': {'url': vid, 'width': 720}}}}]},
    ]}}
    assert _extract_pinterest_video(pin) == vid


def test_pinterest_images_from_carousel():
    # كاروسيل متعدد الصور → كل الصور بدقّة orig مرتّبة بلا تكرار
    pin = {'carousel_data': {'carousel_slots': [
        {'images': {'orig': {'url': 'https://i.pinimg.com/originals/a.jpg'}}},
        {'images': {'orig': {'url': 'https://i.pinimg.com/originals/b.jpg'}}},
    ]}}
    assert _extract_pinterest_images(pin) == [
        'https://i.pinimg.com/originals/a.jpg',
        'https://i.pinimg.com/originals/b.jpg',
    ]


def test_pinterest_images_upscaled_to_originals():
    # روابط مصغّرة (شكل pidgets مثل /236x/) → تُرفع للدقّة الأصلية /originals/
    assert _upscale_pinimg('https://i.pinimg.com/236x/ab/cd/x.jpg') == \
        'https://i.pinimg.com/originals/ab/cd/x.jpg'
    pin = {'images': {'237x': {'url': 'https://i.pinimg.com/237x/ab/x.jpg', 'width': 237}}}
    assert _extract_pinterest_images(pin) == ['https://i.pinimg.com/originals/ab/x.jpg']


def test_pinterest_images_empty_for_video_pin():
    # Pin فيديو: صورته غلاف فقط → [] كي لا يستقبل المستخدم صورة بدل الفيديو
    pin = {'videos': {'video_list': {'V_720P': {'url': 'https://v.pinimg.com/x.mp4'}}},
           'images': {'orig': {'url': 'https://i.pinimg.com/originals/cover.jpg'}}}
    assert _extract_pinterest_images(pin) == []


def test_pinterest_resolver_returns_video_from_pinresource_shape():
    # رد PinResource (resource_response.data) → رابط الفيديو المباشر
    vid = 'https://v.pinimg.com/videos/mc/720p/z.mp4'
    payload = {'resource_response': {'data': {
        'videos': {'video_list': {'V_720P': {'url': vid, 'width': 720}}}}}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_pinterest_media('https://www.pinterest.com/pin/1234567890123/')
    assert out == vid


def test_pinterest_images_from_pidgets_shape():
    # رد pidgets (data قائمة) لصورة مفردة → قائمة برابط الدقّة الأصلية
    payload = {'status': 'success', 'data': [
        {'images': {'237x': {'url': 'https://i.pinimg.com/237x/ab/cd/x.jpg', 'width': 237}}},
    ]}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_pinterest_images('https://www.pinterest.com/pin/1234567890123/')
    assert out == ['https://i.pinimg.com/originals/ab/cd/x.jpg']


def test_pinterest_resolver_handles_network_error():
    # فشل الطلب الشبكي → None/[] بلا استثناء
    with patch('urllib.request.urlopen', side_effect=OSError('boom')):
        assert resolve_pinterest_media('https://www.pinterest.com/pin/1234567890123/') is None
        assert resolve_pinterest_images('https://www.pinterest.com/pin/1234567890123/') == []
