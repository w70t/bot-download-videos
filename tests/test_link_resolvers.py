# -*- coding: utf-8 -*-
"""اختبارات محوّلات الروابط (link_resolvers) — بدون أي طلبات شبكية."""

from unittest.mock import patch

import json

import link_resolvers
from link_resolvers import (
    _is_music_link, _music_search_query, resolve_snapchat_spotlight,
    snapchat_clean_rendition, _is_snap_video_url, snapchat_downloadable_url,
    snapchat_probe_renditions, set_snapchat_clean_rendition,
    get_snapchat_clean_rendition,
    resolve_instagram_media, instagram_mirror_lookup, _is_real_instagram_host,
    resolve_tiktok_media, resolve_tiktok_images,
    resolve_twitter_media, _extract_twitter_media, all_mirror_hosts,
    twitter_mirror_lookup, _twitter_payload_sensitive,
    _extract_twitter_media_list, twitter_mirror_media,
    resolve_pinterest_media, resolve_pinterest_images, _pinterest_pin_id,
    _extract_pinterest_video, _extract_pinterest_images, _upscale_pinimg,
    is_substack_note, resolve_substack_note,
)


def test_all_mirror_hosts_lists_configured_mirrors():
    hosts = all_mirror_hosts()
    # قائمة أزواج (منصة، مضيف) تشمل المرايا الافتراضية
    assert all(isinstance(p, tuple) and len(p) == 2 for p in hosts)
    platforms = {p for p, _ in hosts}
    assert {'instagram', 'tiktok', 'twitter', 'pinterest', 'threads'} <= platforms
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


# ── سناب: النسخة بلا لوقو (رندر 1034 بدل 27) ────────────────────

_SNAP_27 = 'https://bolt-gcdn.sc-cdn.net/bp/u7YkX9hEzOyaij7eKhiSd.27.IRZXSOY'
_SNAP_1034 = 'https://bolt-gcdn.sc-cdn.net/bp/u7YkX9hEzOyaij7eKhiSd.1034.IRZXSOY'


class _FakeHead:
    """محاكاة استجابة طلب HEAD بحالة ونوع محتوى وحجم."""
    def __init__(self, status, ctype, length=1234):
        self.status, self._ctype, self._len = status, ctype, length
        self.headers = self

    def get_content_type(self):
        return self._ctype

    def get(self, name, default=None):
        return str(self._len) if name.lower() == 'content-length' else default

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_is_snap_video_url_accepts_video_renditions():
    # رندر المشاركة (27) والرندر النظيف (1034) وملف mp4 صريح
    assert _is_snap_video_url(_SNAP_27)
    assert _is_snap_video_url(_SNAP_1034)
    assert _is_snap_video_url('https://cf-st.sc-cdn.net/d/abc.mp4')


def test_is_snap_video_url_rejects_thumbnails_and_foreign_hosts():
    # المصغّرات (jpeg/webp) مستبعَدة كي لا نرسل صورة غلاف بدل الفيديو
    for rid in ('256', '1306', '1400', '1430'):
        assert not _is_snap_video_url(
            f'https://bolt-gcdn.sc-cdn.net/bp/u7YkX9hEzOyaij7eKhiSd.{rid}.IRZXSOY')
    # مضيف ينتحل الصيغة نفسها لا يُقبل
    assert not _is_snap_video_url('https://evil.com/x/abcdefghijklmno.27.IRZXSOY')
    assert not _is_snap_video_url('https://sc-cdn.net.evil.com/x/abcdefghij.27.IRZX')
    assert not _is_snap_video_url('')


def test_snapchat_clean_rendition_rewrites_when_available():
    # الرندر النظيف منشور → نستبدل 27 بـ 1034 ونُسقط الاستعلام
    with patch('urllib.request.urlopen',
               return_value=_FakeHead(200, 'video/mp4')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = snapchat_clean_rendition(_SNAP_27 + '?mo=abc&uc=46')
    assert out == _SNAP_1034


def test_snapchat_clean_rendition_accepts_octet_stream():
    # بعض المقاطع تُقدَّم application/octet-stream وهي فيديو صالح
    with patch('urllib.request.urlopen',
               return_value=_FakeHead(200, 'application/octet-stream')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        assert snapchat_clean_rendition(_SNAP_27) == _SNAP_1034


def test_snapchat_clean_rendition_keeps_original_when_missing():
    # لا رندر نظيف على أي مسار (404 في كل مكان) → نبقي نسخة المشاركة كما هي
    with patch('urllib.request.urlopen', side_effect=OSError('404')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        assert snapchat_clean_rendition(_SNAP_27) == _SNAP_27


def test_snapchat_clean_rendition_falls_back_to_other_base():
    """رندرات المقطع الواحد قد تكون على مضيف/مسار غير مسار نسخة المشاركة،
    فحين يفشل المسار الأصلي نجرّب المسارات الاحتياطية بدل التسليم باللوقو."""
    sharing = 'https://bolt-gcdn.sc-cdn.net/bb/hkAuDagsnNZrUsnw1giGG.27.IRZXSOY'

    def fake_urlopen(req, *a, **k):
        url = req if isinstance(req, str) else req.full_url
        # النسخة النظيفة موجودة على cf-st/d فقط، لا على مسار نسخة المشاركة
        if url.startswith('https://cf-st.sc-cdn.net/d/'):
            return _FakeHead(200, 'video/mp4')
        raise OSError('404')

    with patch('urllib.request.urlopen', side_effect=fake_urlopen), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = snapchat_clean_rendition(sharing)
    assert out == ('https://cf-st.sc-cdn.net/d/'
                   'hkAuDagsnNZrUsnw1giGG.1034.IRZXSOY')


def test_snapchat_clean_rendition_prefers_original_base():
    # المسار الأصلي يُجرَّب أولاً ولا نقفز للاحتياطي بلا داعٍ
    with patch('urllib.request.urlopen',
               return_value=_FakeHead(200, 'video/mp4')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = snapchat_clean_rendition(_SNAP_27)
    assert out.startswith('https://bolt-gcdn.sc-cdn.net/bp/')


def test_snapchat_clean_rendition_rejects_error_body():
    # ردّ XML من التخزين ليس فيديو → نبقي الأصلي
    with patch('urllib.request.urlopen',
               return_value=_FakeHead(200, 'application/xml')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        assert snapchat_clean_rendition(_SNAP_27) == _SNAP_27


def test_snapchat_clean_rendition_ignores_non_sharing_urls():
    # روابط ليست رندر مشاركة تعود كما هي بلا أي طلب شبكي
    for u in (_SNAP_1034, 'https://cf-st.sc-cdn.net/d/abc.mp4', 'x', ''):
        assert snapchat_clean_rendition(u) == u


def test_snapchat_thumbnail_prefers_jpeg_rendition():
    """yt-dlp لا يعطي مصغّرة لرابط ملف مباشر، فنشتقّها من الرابط نفسه.
    نفضّل 256 (jpeg) لأن تلجرام يرفض webp أحياناً."""
    with patch('urllib.request.urlopen',
               return_value=_FakeHead(200, 'image/jpeg')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = link_resolvers.snapchat_thumbnail_url(_SNAP_1034)
    assert out == _SNAP_1034.replace('.1034.', '.256.')


def test_snapchat_thumbnail_falls_back_to_next_rendition():
    # 256 غير موجودة لهذا المقطع → نجرّب 1400 قبل الاستسلام
    def fake(req, *a, **k):
        url = req if isinstance(req, str) else req.full_url
        if '.1400.' in url:
            return _FakeHead(200, 'image/jpeg')
        raise OSError('404')

    with patch('urllib.request.urlopen', side_effect=fake), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = link_resolvers.snapchat_thumbnail_url(_SNAP_1034)
    assert out.endswith('.1400.IRZXSOY')


def test_snapchat_thumbnail_none_for_video_or_foreign_url():
    # نوع فيديو (ليس صورة) أو مضيف غير سناب → None فتبقى المعاينة نصية
    with patch('urllib.request.urlopen',
               return_value=_FakeHead(200, 'video/mp4')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        assert link_resolvers.snapchat_thumbnail_url(_SNAP_1034) is None
    assert link_resolvers.snapchat_thumbnail_url('https://youtube.com/x') is None
    assert link_resolvers.snapchat_thumbnail_url('') is None


def test_snapchat_downloadable_url_appends_mp4_hint():
    """yt-dlp يقرأ رمز السياق امتداداً غريباً ويرفض التحميل، فنلحق «#.mp4».
    يشمل نسخة اللوقو الاحتياطية (27) لأن العلّة نفسها فيها."""
    assert snapchat_downloadable_url(_SNAP_1034) == _SNAP_1034 + '#.mp4'
    assert snapchat_downloadable_url(_SNAP_27) == _SNAP_27 + '#.mp4'
    # مع استعلام: الجزء يلحق في النهاية بعد الاستعلام
    assert snapchat_downloadable_url(_SNAP_1034 + '?uc=46') == \
        _SNAP_1034 + '?uc=46#.mp4'


def test_snapchat_downloadable_url_leaves_others_untouched():
    # امتداد صريح، أو جزء موجود سلفاً، أو مضيف غير سناب → بلا تغيير
    for u in (_SNAP_1034 + '#.mp4',
              'https://cf-st.sc-cdn.net/d/abc.mp4',
              'https://evil.com/x/abcdefghijklmno.27.IRZXSOY',
              'https://youtube.com/watch?v=1', ''):
        assert snapchat_downloadable_url(u) == u


def test_snapchat_downloadable_url_keeps_cache_key_stable():
    # مفتاح الكاش يُسقط الجزء، فلا يتكرّر الملف في الكاش بسبب «#.mp4»
    from url_utils import cache_key_for_url
    assert cache_key_for_url(snapchat_downloadable_url(_SNAP_1034)) == \
        cache_key_for_url(_SNAP_1034)


def test_snapchat_rendition_setter_validates_and_restores():
    """الأدمن يغيّر الرقم بزرّ، فالضابط مصدر الحقيقة الوحيد — ويرفض ما ليس رقماً."""
    original = get_snapchat_clean_rendition()
    try:
        assert set_snapchat_clean_rendition('2048') == '2048'
        assert get_snapchat_clean_rendition() == '2048'
        # قيمة فارغة/غير رقمية لا تُفسد المعمول به
        assert set_snapchat_clean_rendition('') == '2048'
        assert set_snapchat_clean_rendition('abc') == '2048'
        assert set_snapchat_clean_rendition(None) == '2048'
    finally:
        set_snapchat_clean_rendition(original)
    assert get_snapchat_clean_rendition() == original


def test_snapchat_clean_rendition_honours_explicit_number():
    # الرقم المُمرَّر يتقدّم على الافتراضي (يمرّره البوت من قاعدة البيانات)
    with patch('urllib.request.urlopen',
               return_value=_FakeHead(200, 'video/mp4')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = snapchat_clean_rendition(_SNAP_27, rendition='2048')
    assert out.endswith('.2048.IRZXSOY')


def test_snapchat_probe_rejects_non_snapchat():
    # بلا أي طلب شبكي
    res = snapchat_probe_renditions('https://youtube.com/watch?v=1')
    assert res['error'] and not res['found']


class _FakePage:
    """صفحة سناب وهمية لطلب GET."""
    def __init__(self, body):
        self._b = body.encode('utf-8')

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_snapchat_probe_finds_clean_rendition():
    """النسخ التي تذكرها الصفحة هي نسخة اللوقو، وأي رندر فيديو لا تذكره هو
    المرشّح النظيف. المصغّرات لا تُحسب فيديو."""
    page = ('<meta property="og:video" content="https://bolt-gcdn.sc-cdn.net/'
            'bp/u7YkX9hEzOyaij7eKhiSd.27.IRZXSOY?mo=x"/>'
            '"https://bolt-gcdn.sc-cdn.net/bp/u7YkX9hEzOyaij7eKhiSd.256.IRZXSOY"')
    # ما هو منشور فعلاً على التخزين لهذا المقطع
    available = {27: 'video/mp4', 256: 'image/jpeg', 1034: 'video/mp4',
                 1306: 'image/webp'}

    def fake_urlopen(req, *a, **k):
        url = req if isinstance(req, str) else req.full_url
        if 'snapchat.com' in url:
            return _FakePage(page)
        num = int(url.rsplit('/', 1)[1].split('.')[1])
        if num in available:
            return _FakeHead(200, available[num])
        raise OSError('404')

    with patch('urllib.request.urlopen', side_effect=fake_urlopen), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        res = snapchat_probe_renditions(
            'https://www.snapchat.com/spotlight/ABC')
    assert res['error'] is None
    assert res['media_id'] == 'u7YkX9hEzOyaij7eKhiSd'
    assert res['context'] == 'IRZXSOY'
    assert res['videos'] == [27, 1034]
    # 27 تذكره الصفحة (نسخة اللوقو) فيُستبعد؛ يبقى 1034 وحده
    assert res['clean'] == [1034]


def test_snapchat_probe_reports_page_structure_change():
    # صفحة بلا أي رابط وسائط → رسالة تقول إن العلّة تحتاج كوداً لا رقماً
    with patch('urllib.request.urlopen',
               side_effect=lambda *a, **k: _FakePage('<html>no media</html>')), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        res = snapchat_probe_renditions('https://www.snapchat.com/spotlight/ABC')
    assert 'تعديل كود' in res['error']
    assert not res['clean']


def test_snapchat_resolver_extracts_extensionless_og_video():
    """روابط سبوت لايت اليوم بلا امتداد .mp4، والمعالج يلتقطها ثم يحوّلها
    للرندر النظيف. وسوم og:video:type/width تشارك النمط فلا تُلتقط خطأً."""
    page = (
        '<meta property="og:video" content="' + _SNAP_27 + '?mo=x&amp;uc=46"/>'
        '<meta property="og:video:type" content="video/mp4"/>'
        '<meta property="og:video:width" content="540"/>'
    )

    class _Page:
        def read(self, *a):
            return page.encode('utf-8')

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Opener:
        addheaders = []

        def open(self, *a, **k):
            return _Page()

    with patch('urllib.request.build_opener', return_value=_Opener()), \
            patch('urllib.request.urlopen',
                  return_value=_FakeHead(200, 'video/mp4')), \
            patch.object(link_resolvers, 'get_cookie_file_for_url',
                         return_value=None), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = resolve_snapchat_spotlight('https://www.snapchat.com/spotlight/ABC')
    assert out == _SNAP_1034


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


# ── resolve_threads_media (ثريدز عبر مرآة عامة) ─────────────────

class _FakeHtml:
    """محاكاة استجابة urlopen تُرجع صفحة HTML عبر read()."""
    def __init__(self, body):
        self._b = body.encode('utf-8')

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_THREADS_MP4 = 'https://scontent-iad3-2.cdninstagram.com/o1/v/t2/f2/m86/AQP36.mp4'


def test_threads_resolver_ignores_non_posts():
    # بلا أي طلب شبكي: غير ثريدز، أو بروفايل بلا منشور
    assert link_resolvers.resolve_threads_media('https://youtube.com/watch?v=1') is None
    assert link_resolvers.resolve_threads_media('https://www.threads.com/@zuck') is None
    assert link_resolvers.resolve_threads_media('') is None


def test_threads_resolver_reads_og_video():
    """yt-dlp لا يدعم ثريدز، والمرآة تعطي og:video برابط mp4 مباشر."""
    page = (f'<meta property="og:image" content="https://x/cover.jpg"/>'
            f'<meta property="og:video" content="{_THREADS_MP4}"/>')
    for url in ('https://www.threads.com/@user/post/DauKPbYnR6q',
                'https://www.threads.net/@user/video/DauKPbYnR6q',
                'https://www.threads.com/@user/post/DauKPbYnR6q/video-slug'):
        with patch('urllib.request.urlopen', return_value=_FakeHtml(page)), \
                patch.object(link_resolvers, 'is_safe_url', return_value=True):
            assert link_resolvers.resolve_threads_media(url) == _THREADS_MP4


def test_threads_lookup_returns_duration_and_size():
    """بلا مدّة يتخطّى المقطع حدّ المدة المجاني (yt-dlp لا يعرف مدّة mp4 بعيد)،
    فنقرأها من معامل efg داخل الرابط ونقرأ الأبعاد من وسوم المرآة."""
    import base64, json
    efg = base64.urlsafe_b64encode(
        json.dumps({'duration_s': 45}).encode()).decode().rstrip('=')
    media = f'https://scontent.cdninstagram.com/o1/v/x.mp4?efg={efg}'
    page = (f'<meta property="og:video" content="{media}"/>'
            '<meta property="og:video:width" content="1080"/>'
            '<meta property="og:video:height" content="1920"/>')
    with patch('urllib.request.urlopen', return_value=_FakeHtml(page)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out, meta = link_resolvers.threads_mirror_lookup(
            'https://www.threads.com/@user/post/DauKPbYnR6q')
    assert out == media
    assert meta == {'width': 1080, 'height': 1920, 'duration': 45}


def test_threads_lookup_splits_text_from_engagement_stats():
    """og:description = نصّ المنشور ثم سطر التفاعلات. نفصلهما: النصّ عنواناً
    مفهوماً بدل «Threads Video»، والتفاعلات سطراً في وصف الرفع."""
    page = ('<meta property="og:title" content="زينب علاء (@en0la_19)"/>'
            '<meta property="og:description" content="المقاومه ح تلطم\n\n'
            '❤️ 425  💬 113  🔁 1  📤 33"/>'
            '<meta property="og:video" content="https://x.cdninstagram.com/v.mp4"/>')
    with patch('urllib.request.urlopen', return_value=_FakeHtml(page)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        _out, meta = link_resolvers.threads_mirror_lookup(
            'https://www.threads.com/@en0la_19/post/DbT2rAFEYfA')
    assert meta['title'] == 'المقاومه ح تلطم'
    assert meta['stats'] == '❤️ 425  💬 113  🔁 1  📤 33'
    assert meta['uploader'] == '@en0la_19'


def test_threads_lookup_returns_cover_thumbnail():
    """بلا مصغّرة تظهر المعاينة بلا صورة (yt-dlp لا يعرف مصغّرة mp4 بعيد)."""
    page = ('<meta property="og:image" content="https://x.cdninstagram.com/cover.jpg"/>'
            '<meta property="og:video" content="https://x.cdninstagram.com/v.mp4"/>')
    with patch('urllib.request.urlopen', return_value=_FakeHtml(page)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        _out, meta = link_resolvers.threads_mirror_lookup(
            'https://www.threads.com/@u/post/DbT2rAFEYfA')
    assert meta['thumbnail'] == 'https://x.cdninstagram.com/cover.jpg'


def test_threads_lookup_skips_webp_thumbnail():
    # تلجرام يرفض webp أحياناً → نتركها فتسقط المعاينة لنصّية بدل أن تفشل
    page = ('<meta property="og:image" content="https://x.cdninstagram.com/c.webp"/>'
            '<meta property="og:video" content="https://x.cdninstagram.com/v.mp4"/>')
    with patch('urllib.request.urlopen', return_value=_FakeHtml(page)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        _out, meta = link_resolvers.threads_mirror_lookup(
            'https://www.threads.com/@u/post/DbT2rAFEYfA')
    assert 'thumbnail' not in meta


def test_threads_lookup_without_stats_line():
    # منشور بلا تفاعلات معروضة → عنوان فقط، وبلا مفتاح stats
    page = ('<meta property="og:description" content="نصّ فقط"/>'
            '<meta property="og:video" content="https://x.cdninstagram.com/v.mp4"/>')
    with patch('urllib.request.urlopen', return_value=_FakeHtml(page)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        _out, meta = link_resolvers.threads_mirror_lookup(
            'https://www.threads.com/@u/post/DbT2rAFEYfA')
    assert meta['title'] == 'نصّ فقط' and 'stats' not in meta


def test_threads_duration_missing_is_not_fatal():
    # رابط بلا efg → لا مدّة، لكن الفيديو يبقى صالحاً
    media = 'https://scontent.cdninstagram.com/o1/v/x.mp4'
    page = f'<meta property="og:video" content="{media}"/>'
    with patch('urllib.request.urlopen', return_value=_FakeHtml(page)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out, meta = link_resolvers.threads_mirror_lookup(
            'https://www.threads.com/@user/post/DauKPbYnR6q')
    assert out == media and 'duration' not in meta


def test_threads_resolver_none_for_photo_post():
    # منشور صور/نصّ: المرآة تعطي og:image بلا og:video → None فيبقى المسار الأصلي
    page = '<meta property="og:image" content="https://x/pic.jpg"/>'
    with patch('urllib.request.urlopen', return_value=_FakeHtml(page)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        assert link_resolvers.resolve_threads_media(
            'https://www.threads.com/@user/post/DauKPbYnR6q') is None


def test_threads_resolver_tries_next_mirror_on_failure():
    """أول مرآة معطّلة (503 وقت الكتابة) → نجرّب التالية بدل الاستسلام."""
    page = f'<meta property="og:video" content="{_THREADS_MP4}"/>'
    calls = []

    def fake(req, *a, **k):
        url = req if isinstance(req, str) else req.full_url
        calls.append(url)
        if len(calls) == 1:
            raise OSError('503')
        return _FakeHtml(page)

    with patch.object(link_resolvers, '_THREADS_PROXY_HOSTS',
                      ['down.example', 'up.example']), \
            patch('urllib.request.urlopen', side_effect=fake), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        out = link_resolvers.resolve_threads_media(
            'https://www.threads.com/@user/post/DauKPbYnR6q')
    assert out == _THREADS_MP4
    assert len(calls) == 2 and 'up.example' in calls[1]


def test_threads_resolver_handles_all_mirrors_down():
    with patch('urllib.request.urlopen', side_effect=OSError('503')):
        assert link_resolvers.resolve_threads_media(
            'https://www.threads.com/@user/post/DauKPbYnR6q') is None


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


# ── twitter_mirror_media (كل وسائط التغريدة: صور + فيديو) ───────

def test_twitter_media_list_vxtwitter_mixed_keeps_order():
    # تغريدة مختلطة (صورة، فيديو، صورة): يُحافَظ على الترتيب والأنواع
    img1 = 'https://pbs.twimg.com/media/a.jpg'
    vid = 'https://video.twimg.com/amplify_video/1/vid/avc1/x.mp4'
    img2 = 'https://pbs.twimg.com/media/b.jpg'
    payload = {'media_extended': [
        {'type': 'image', 'url': img1},
        {'type': 'video', 'url': vid},
        {'type': 'image', 'url': img2},
    ]}
    assert _extract_twitter_media_list(payload) == [
        {'type': 'photo', 'url': img1},
        {'type': 'video', 'url': vid},
        {'type': 'photo', 'url': img2},
    ]


def test_twitter_media_list_gif_treated_as_video():
    gif = 'https://video.twimg.com/tweet_video/g.mp4'
    payload = {'media_extended': [{'type': 'gif', 'url': gif}]}
    assert _extract_twitter_media_list(payload) == [{'type': 'video', 'url': gif}]


def test_twitter_media_list_fxtwitter_shapes():
    # fxtwitter: tweet.media.all المرتّبة أولاً، وphotos/videos احتياطاً
    img = 'https://pbs.twimg.com/media/c.jpg'
    vid = 'https://video.twimg.com/amplify_video/2/vid/avc1/y.mp4'
    with_all = {'tweet': {'media': {'all': [
        {'type': 'photo', 'url': img}, {'type': 'video', 'url': vid},
    ]}}}
    assert _extract_twitter_media_list(with_all) == [
        {'type': 'photo', 'url': img},
        {'type': 'video', 'url': vid},
    ]
    without_all = {'tweet': {'media': {
        'photos': [{'type': 'photo', 'url': img}],
        'videos': [{'type': 'video', 'url': vid}],
    }}}
    assert _extract_twitter_media_list(without_all) == [
        {'type': 'photo', 'url': img},
        {'type': 'video', 'url': vid},
    ]


def test_twitter_media_list_empty_shapes():
    assert _extract_twitter_media_list(None) == []
    assert _extract_twitter_media_list({}) == []
    assert _extract_twitter_media_list({'tweet': {'media': {}}}) == []
    # روابط غير http وعناصر مشوّهة تُتجاهل
    assert _extract_twitter_media_list(
        {'media_extended': [{'type': 'image', 'url': 'ftp://x'}, 'junk', {}]}) == []


def test_twitter_mirror_media_returns_items_and_flag():
    img = 'https://pbs.twimg.com/media/a.jpg'
    vid = 'https://video.twimg.com/amplify_video/1/vid/avc1/x.mp4'
    payload = {'possibly_sensitive': False,
               'media_extended': [{'type': 'image', 'url': img},
                                  {'type': 'video', 'url': vid}]}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        items, sensitive = twitter_mirror_media('https://x.com/u/status/123')
    assert items == [{'type': 'photo', 'url': img}, {'type': 'video', 'url': vid}]
    assert sensitive is False


def test_twitter_mirror_media_sensitive_flag_passthrough():
    payload = {'possibly_sensitive': True,
               'media_extended': [{'type': 'image',
                                   'url': 'https://pbs.twimg.com/media/n.jpg'}]}
    with patch('urllib.request.urlopen', return_value=_FakeJsonResp(payload)), \
            patch.object(link_resolvers, 'is_safe_url', return_value=True):
        items, sensitive = twitter_mirror_media('https://x.com/u/status/123')
    assert len(items) == 1
    assert sensitive is True


def test_twitter_mirror_media_ignores_non_status():
    # روابط غير تويتر أو بلا معرّف منشور → قائمة فارغة بلا أي طلب شبكي
    assert twitter_mirror_media('https://youtube.com/watch?v=1') == ([], False)
    assert twitter_mirror_media('https://x.com/someuser') == ([], False)
    assert twitter_mirror_media('') == ([], False)


def test_twitter_mirror_media_handles_network_error():
    with patch('urllib.request.urlopen', side_effect=OSError('boom')):
        assert twitter_mirror_media('https://twitter.com/u/status/123') == ([], False)


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
