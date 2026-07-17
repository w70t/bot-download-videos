# -*- coding: utf-8 -*-
"""اختبارات محوّلات الروابط (link_resolvers) — بدون أي طلبات شبكية."""

from unittest.mock import patch

import json

import link_resolvers
from link_resolvers import (
    _is_music_link, _music_search_query, resolve_snapchat_spotlight,
    resolve_instagram_media, instagram_mirror_lookup, _is_real_instagram_host,
    resolve_tiktok_media, resolve_tiktok_images,
    resolve_twitter_media, _extract_twitter_media, all_mirror_hosts,
    twitter_mirror_lookup, _twitter_payload_sensitive,
    resolve_pinterest_media, resolve_pinterest_images, _pinterest_pin_id,
    _extract_pinterest_video, _extract_pinterest_images, _upscale_pinimg,
    is_substack_note, resolve_substack_note,
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


# ── instagram_mirror_lookup (علم المنشور الخاص/المحذوف) ─────────

def test_is_real_instagram_host():
    # صفحة إنستغرام الفعلية (جدار الدخول) تطابق؛ الـCDN والمرايا لا تطابق
    assert _is_real_instagram_host('https://www.instagram.com/reel/X/')
    assert _is_real_instagram_host('https://instagram.com/accounts/login/')
    assert not _is_real_instagram_host('https://scontent.cdninstagram.com/o1/v/x.mp4')
    assert not _is_real_instagram_host('https://kkinstagram.com/reel/X')
    assert not _is_real_instagram_host('')


def test_instagram_lookup_returns_video_not_unavailable():
    # المرآة تُرجع فيديو → (الرابط المباشر، False)
    final = 'https://scontent.cdninstagram.com/o1/v/abc.mp4?oe=1'
    with patch('urllib.request.urlopen', return_value=_FakeResp('video/mp4', final)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        media, unavailable = instagram_mirror_lookup(
            'https://www.instagram.com/reel/ABC123/?igsh=x')
    assert media == final
    assert unavailable is False


def test_instagram_lookup_flags_private_or_removed_post():
    # المرآة أحالت لصفحة إنستغرام نفسها (جدار الدخول) بدل الوسائط → المنشور
    # خاص/محذوف: (None, True) ليعرض البوت رسالة واضحة بدل «رابط غير صحيح»
    wall = 'https://www.instagram.com/reel/ABC123/'
    with patch('urllib.request.urlopen', return_value=_FakeResp('text/html', wall)):
        media, unavailable = instagram_mirror_lookup(
            'https://www.instagram.com/reel/ABC123/?igsh=x')
    assert media is None
    assert unavailable is True


def test_instagram_lookup_image_post_not_flagged():
    # منشور صور عام (المرآة تُرجع صورة) → لا علم؛ يكمل مسار الصور عادياً
    with patch('urllib.request.urlopen',
               return_value=_FakeResp('image/jpeg',
                                      'https://scontent.cdninstagram.com/v/p.jpg')):
        media, unavailable = instagram_mirror_lookup(
            'https://www.instagram.com/p/ABC123/')
    assert media is None
    assert unavailable is False


def test_instagram_lookup_mirror_outage_not_flagged():
    # عطل المرآة (504/انقطاع) → (None, False): لا نتّهم المنشور بالخصوصية
    with patch('urllib.request.urlopen', side_effect=OSError('504')):
        media, unavailable = instagram_mirror_lookup(
            'https://www.instagram.com/reel/ABC123/')
    assert media is None
    assert unavailable is False


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


def test_twitter_payload_sensitive_shapes():
    # vxtwitter: العلم في جذر الرد | fxtwitter: داخل tweet | غيابه = غير حسّاس
    assert _twitter_payload_sensitive({'possibly_sensitive': True})
    assert _twitter_payload_sensitive({'sensitive': True})
    assert _twitter_payload_sensitive({'tweet': {'possibly_sensitive': True}})
    assert not _twitter_payload_sensitive({'possibly_sensitive': False})
    assert not _twitter_payload_sensitive({'tweet': {}})
    assert not _twitter_payload_sensitive({})
    assert not _twitter_payload_sensitive(None)


def test_twitter_mirror_lookup_returns_sensitive_flag():
    # تغريدة حسّاسة (NSFW): المرآة تعيد الفيديو + علم الحساسية → البوت يرفضها
    # حين يكون فلتر المحتوى مفعّلاً
    vid = 'https://video.twimg.com/amplify_video/9/vid/avc1/n.mp4'
    payload = {'possibly_sensitive': True,
               'media_extended': [{'type': 'video', 'url': vid}]}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        media, sensitive = twitter_mirror_lookup('https://x.com/u/status/123')
    assert media == vid
    assert sensitive is True


def test_twitter_mirror_lookup_normal_tweet_not_sensitive():
    vid = 'https://video.twimg.com/amplify_video/9/vid/avc1/ok.mp4'
    payload = {'possibly_sensitive': False,
               'media_extended': [{'type': 'video', 'url': vid}]}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        media, sensitive = twitter_mirror_lookup('https://x.com/u/status/123')
    assert media == vid
    assert sensitive is False


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


# ── resolve_substack_note ───────────────────────────────────────

def test_is_substack_note():
    assert is_substack_note('https://substack.com/@flza7/note/c-292715374?r=x')
    assert is_substack_note('https://open.substack.com/@user.name/note/c-123456')
    assert is_substack_note('https://substack.com/note/c-987654')
    assert not is_substack_note('https://substack.com/@flza7')  # بروفايل
    assert not is_substack_note('https://someblog.substack.com/p/post-title')  # مقال
    assert not is_substack_note('https://youtube.com/watch?v=1')
    assert not is_substack_note('')


def test_substack_note_resolves_video_and_title():
    # ملاحظة بمرفق فيديو → رابط وسيط /src الثابت + العنوان من نص الملاحظة
    payload = {'item': {'comment': {
        'name': 'ARCHI',
        'body': 'أشرس معركة ستخوضها\nسطر ثانٍ',
        'attachments': [{'type': 'video',
                         'media_upload_id': 'afa5cef9-9d23-4860-9649-9a3c15dcbaf7',
                         'mediaUpload': {'explicit': False}}],
    }}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        direct, title, explicit = resolve_substack_note(
            'https://substack.com/@flza7/note/c-292715374')
    assert direct == ('https://substack.com/api/v1/video/upload/'
                      'afa5cef9-9d23-4860-9649-9a3c15dcbaf7/src')
    assert title == 'أشرس معركة ستخوضها'
    assert explicit is False


def test_substack_note_flags_explicit_media():
    # وسائط مصنّفة صريحة لدى Substack → يعود العلم True ليرفضها فلتر المحتوى
    payload = {'item': {'comment': {
        'body': 'x',
        'attachments': [{'type': 'video', 'media_upload_id': 'abc-123',
                         'mediaUpload': {'explicit': True}}],
    }}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        direct, _title, explicit = resolve_substack_note('https://substack.com/note/c-1')
    assert direct and explicit is True


def test_substack_note_title_falls_back_to_author():
    # ملاحظة بلا نص → العنوان اسم صاحبها
    payload = {'item': {'comment': {
        'name': 'ARCHI', 'body': '',
        'attachments': [{'type': 'video', 'media_upload_id': 'abc-123'}],
    }}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        _direct, title, _explicit = resolve_substack_note('https://substack.com/note/c-1')
    assert title == 'ARCHI'


def test_substack_note_without_video():
    # ملاحظة نصية/صور بلا فيديو → (None, None, False)
    payload = {'item': {'comment': {'body': 'نص فقط', 'attachments': [
        {'type': 'image', 'media_upload_id': 'x'}]}}}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)):
        assert resolve_substack_note('https://substack.com/note/c-1') == (None, None, False)


def test_substack_resolver_ignores_non_note_urls():
    # غير الملاحظات → (None, None, False) بلا أي طلب شبكي
    assert resolve_substack_note('https://someblog.substack.com/p/post') == (None, None, False)
    assert resolve_substack_note('') == (None, None, False)


def test_substack_resolver_handles_network_error():
    with patch('urllib.request.urlopen', side_effect=OSError('boom')):
        assert resolve_substack_note('https://substack.com/note/c-1') == (None, None, False)
