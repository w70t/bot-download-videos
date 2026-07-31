# -*- coding: utf-8 -*-
"""اختبارات اختيار جودة التحميل (video_quality).

الهدف الأساسي: التأكد أن «أعلى جودة» (max) بلا سقف دقة فعلاً — فالسقف
height<=1080 في كل الفروع كان يمنع نزول 1440p/4K مهما توفّرت — وأنها محصورة
بالأدمن، وأن رمزها منفصل عن رمز العضو العادي حتى لا يتشاركا مفتاح كاش واحداً.
"""

import pytest

import video_quality as vq
import translations


class TestNormalizeQuality:
    """صلاحية الجودة: «أعلى جودة» للأدمن وحده."""

    def test_admin_keeps_max(self):
        assert vq.normalize_quality('max', admin=True) == 'max'

    def test_non_admin_downgraded_to_default(self):
        assert vq.normalize_quality('max', admin=False) == vq.DEFAULT_QUALITY

    @pytest.mark.parametrize('quality', ['best', 'medium', '480', '360', 'audio'])
    def test_shared_qualities_untouched_for_members(self, quality):
        # الجودات دون السقف تبقى متاحة للجميع (سجلّ الأعضاء القدامى يحوي بعضها)
        assert vq.normalize_quality(quality, admin=False) == quality
        assert vq.normalize_quality(quality, admin=True) == quality

    @pytest.mark.parametrize('bogus', ['4k', '2160', 'unknown', '', None, '  '])
    def test_unknown_falls_back_to_default(self, bogus):
        assert vq.normalize_quality(bogus, admin=True) == vq.DEFAULT_QUALITY
        assert vq.normalize_quality(bogus, admin=False) == vq.DEFAULT_QUALITY


class TestFormatSelector:
    """مُحدِّدات صيغ yt-dlp."""

    def test_max_has_no_height_cap(self):
        # وجود أي height<= يعني سقفاً — وهو سبب توقّف التحميل عند 1080p
        assert 'height<=' not in vq.format_selector('max')

    def test_max_does_not_restrict_codec(self):
        # يوتيوب لا يوفّر فوق 1080p إلا بـ VP9/AV1، فتقييد avc1 يُلغي 4K عملياً
        fmt = vq.format_selector('max')
        assert 'avc1' not in fmt and 'h264' not in fmt

    @pytest.mark.parametrize('quality,cap', [
        ('best', 1080), ('medium', 720), ('480', 480), ('360', 360),
    ])
    def test_capped_qualities_keep_their_cap(self, quality, cap):
        fmt = vq.format_selector(quality)
        assert f'height<={cap}' in fmt
        # لا سقف آخر مختلط في السلسلة
        assert fmt.count('height<=') == fmt.count(f'height<={cap}')

    def test_capped_qualities_prefer_h264(self):
        assert vq.format_selector('best').startswith('bestvideo[height<=1080][vcodec^=avc1]')

    def test_audio_selector(self):
        assert vq.format_selector('audio') == 'bestaudio/best'

    def test_unknown_quality_uses_default_selector(self):
        assert vq.format_selector('nope') == vq.format_selector(vq.DEFAULT_QUALITY)


class TestFormatSort:
    """ترتيب المفاضلة: الدقّة أولاً لأعلى جودة، وبلا ترتيب مخصّص لغيرها."""

    def test_max_sorts_by_resolution_first(self):
        assert vq.format_sort('max')[0] == 'res'

    def test_max_prefers_h264_as_tiebreak_only(self):
        order = vq.format_sort('max')
        assert 'vcodec:h264' in order
        assert order.index('res') < order.index('vcodec:h264')

    @pytest.mark.parametrize('quality', ['best', 'medium', '480', '360', 'audio'])
    def test_other_qualities_have_no_custom_sort(self, quality):
        assert vq.format_sort(quality) is None


class TestCacheIsolation:
    """رمز الأدمن منفصل عن رمز العضو حتى لا يصل ملف 4K لطالب 1080p."""

    def test_max_is_a_distinct_cache_key(self):
        assert vq.MAX_QUALITY != vq.DEFAULT_QUALITY

    def test_all_cache_qualities_cover_every_format(self):
        assert set(vq.all_cache_qualities()) == set(vq.QUALITY_FORMATS)


class TestKeyboardMetadata:
    """كل زرّ جودة يملك صيغة ونصّاً مترجماً في اللغتين."""

    def test_admin_rows_reference_known_qualities(self):
        for row in vq.ADMIN_QUALITY_ROWS:
            for q in row:
                assert q in vq.QUALITY_FORMATS
                assert q in vq.QUALITY_LABEL_KEYS

    def test_admin_rows_include_max_and_audio(self):
        shown = [q for row in vq.ADMIN_QUALITY_ROWS for q in row]
        assert vq.MAX_QUALITY in shown
        assert vq.AUDIO_QUALITY in shown
        assert len(shown) == len(set(shown))  # بلا تكرار

    @pytest.mark.parametrize('lang', ['ar', 'en'])
    def test_labels_translated(self, lang):
        for key in vq.QUALITY_LABEL_KEYS.values():
            label = translations.t(key, lang)
            assert label and label != key


class TestQualityDisplay:
    """وصف الجودة في سجلّ التحميلات."""

    def test_max_display(self):
        assert vq.quality_display('max') == 'MAX'

    def test_audio_kind_wins_over_quality(self):
        assert vq.quality_display('best', kind='audio') == 'MP3'

    def test_unknown_quality_shown_as_is(self):
        assert vq.quality_display('720x') == '720x'

    def test_none_quality_is_blank(self):
        assert vq.quality_display(None) == ''
