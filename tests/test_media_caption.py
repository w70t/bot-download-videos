# -*- coding: utf-8 -*-
"""اختبارات بناء وصف الوسائط (media_caption).

هذا المنطق كان داخل bot.py خارج أي تغطية، ووقعت فيه أعطال حقيقية شوهدت
ميدانياً: تاريخ منقلب في العرض العربي، ومعرّف CDN يظهر عنواناً، وسطور مصدر
غائبة. الاختبارات هنا تثبّت تلك الإصلاحات."""

from datetime import datetime, timedelta, timezone

from media_caption import (
    _looks_like_media_id, _clean_media_title, _country_label,
    _build_source_lines, _build_media_caption,
)


# ── تنظيف العنوان ───────────────────────────────────────────────

class TestCleanTitle:
    def test_readable_title_kept_as_is(self):
        assert _clean_media_title('اجمل مقطع اليوم 🌙',
                                  'https://tiktok.com/@a/video/1') \
            == 'اجمل مقطع اليوم 🌙'

    def test_cdn_media_id_replaced_by_platform_name(self):
        # شوهد ميدانياً: إنستغرام عبر المرآة يعطي اسم ملف CDN عنواناً
        ugly = 'AQM4FbWDo4mvcl9xKzQ12345678abcd'
        assert _clean_media_title(ugly, 'https://www.instagram.com/reel/X/') \
            == 'Instagram Video'

    def test_snapchat_dotted_id_replaced(self):
        # شوهد ميدانياً: «RG3vywiIqsKhqon9qFsTQ.1034» ظهر عنواناً للمستخدم.
        # النقطة تُسقَط قبل فحص isalnum وإلا مرّ المعرّف كعنوان مقروء
        assert _clean_media_title('RG3vywiIqsKhqon9qFsTQ.1034.IRZXSOY',
                                  'https://snapchat.com/spotlight/x') \
            == 'Snapchat Video'

    def test_empty_title_uses_platform(self):
        assert _clean_media_title('', 'https://x.com/a/status/1') == 'Twitter/X Video'
        assert _clean_media_title(None, 'https://youtu.be/abc') == 'YouTube Video'

    def test_unknown_platform_falls_back_to_arabic(self):
        assert _clean_media_title('', 'https://example.com/v') == 'فيديو'

    def test_title_with_spaces_is_never_an_id(self):
        # وجود مسافة = كلمات مقروءة، مهما طال
        long_words = 'a' * 30 + ' ' + 'b' * 30
        assert _clean_media_title(long_words, 'https://instagram.com/reel/X') \
            == long_words

    def test_short_alnum_title_is_not_an_id(self):
        assert not _looks_like_media_id('Video123')
        assert not _looks_like_media_id('')
        # ٢٤ محرفاً فأكثر مع حروف وأرقام معاً = معرّف
        assert _looks_like_media_id('a1' * 12)
        # حروف فقط بلا أرقام → ليس معرّفاً
        assert not _looks_like_media_id('a' * 30)


# ── أسماء الدول ─────────────────────────────────────────────────

class TestCountryLabel:
    def test_known_countries(self):
        assert _country_label('EG') == 'مصر 🇪🇬'
        assert _country_label('SA') == 'السعودية 🇸🇦'
        assert _country_label('NL') == 'هولندا 🇳🇱'

    def test_case_and_whitespace_tolerant(self):
        assert _country_label(' eg ') == 'مصر 🇪🇬'

    def test_unknown_code_shown_as_is(self):
        # إظهار الرمز أفضل من إخفاء المعلومة
        assert _country_label('ZZ') == 'ZZ 🌍'

    def test_empty_returns_none(self):
        assert _country_label('') is None
        assert _country_label(None) is None


# ── سطرا تحليل المصدر ───────────────────────────────────────────

def _analysis(**kw):
    return {'_source_analysis': kw}


class TestSourceLines:
    def test_no_analysis_gives_no_lines(self):
        assert _build_source_lines({}) == []
        assert _build_source_lines(None) == []
        assert _build_source_lines(_analysis()) == []

    def test_country_line(self):
        lines = _build_source_lines(_analysis(created_in='EG'))
        assert lines == ['🌍 نُشر من: مصر 🇪🇬']

    def test_created_in_preferred_over_region(self):
        # created_in حقل تيك توك الصريح — أدقّ من region الذي تعطيه المرآة
        lines = _build_source_lines(_analysis(created_in='EG', video_region='US'))
        assert 'مصر' in lines[0]

    def test_region_used_when_created_in_missing(self):
        lines = _build_source_lines(_analysis(video_region='US'))
        assert lines == ['🌍 نُشر من: أمريكا 🇺🇸']

    def test_missing_country_still_shows_account_date(self):
        # حالة حقيقية: تيك توك لا ينشر locationCreated لبعض المقاطع
        d = datetime(2019, 4, 27, tzinfo=timezone.utc)
        lines = _build_source_lines(_analysis(account_created=d))
        assert len(lines) == 1
        assert '2019-04-27' in lines[0]

    def test_date_wrapped_in_ltr_marks(self):
        # العطل المُصلَح: «2023-03-29» كان يُقرأ «29-03-2023» في السياق العربي
        d = datetime(2023, 3, 29, tzinfo=timezone.utc)
        line = _build_source_lines(_analysis(account_created=d))[0]
        assert '‎2023-03-29‎' in line

    def test_age_in_years_for_old_account(self):
        d = datetime.now(timezone.utc) - timedelta(days=730)
        line = _build_source_lines(_analysis(account_created=d))[0]
        assert 'سنة' in line and '2.0' in line

    def test_age_in_days_for_new_account(self):
        d = datetime.now(timezone.utc) - timedelta(days=40)
        line = _build_source_lines(_analysis(account_created=d))[0]
        assert 'يوماً' in line and '40' in line

    def test_both_lines_order(self):
        d = datetime(2022, 7, 11, tzinfo=timezone.utc)
        lines = _build_source_lines(_analysis(created_in='NL', account_created=d))
        assert lines[0].startswith('🌍') and lines[1].startswith('📅')

    def test_account_country_never_shown(self):
        # قرار مقصود: تيك توك لا ينشر بلد الحساب، فلا نخمّنه من منطقة التخزين
        lines = _build_source_lines(_analysis(storage_region='EU', language='ar'))
        assert lines == []


# ── الوصف الموحّد ───────────────────────────────────────────────

class TestMediaCaption:
    def test_basic_shape(self):
        cap = _build_media_caption('مقطع', 2.9, 65, 'عبدالوهاب')
        assert '🎬 `مقطع`' in cap
        assert '📊 2.9 MB' in cap
        assert '⏱️ 1:05' in cap        # ٦٥ث = 1:05
        assert '👤 عبدالوهاب' in cap

    def test_backtick_in_title_escaped(self):
        # ` يكسر تنسيق النسخ (monospace) في تلجرام
        cap = _build_media_caption('a`b', 1.0, 10, 'u')
        assert '`' in cap and 'a`b' not in cap
        assert "a'b" in cap

    def test_no_duration_line_when_unknown(self):
        cap = _build_media_caption('م', 1.0, None, 'u')
        assert '⏱️' not in cap

    def test_source_lines_included(self):
        cap = _build_media_caption('م', 1.0, 10, 'u',
                                   source_lines=['🌍 نُشر من: مصر 🇪🇬',
                                                 '📅 الحساب أُنشئ: x'])
        assert 'نُشر من' in cap and 'الحساب أُنشئ' in cap

    def test_bot_username_optional(self):
        assert '📥 @bot' in _build_media_caption('م', 1.0, 10, 'u',
                                                 bot_username='bot')
        assert '📥' not in _build_media_caption('م', 1.0, 10, 'u')

    def test_stats_line(self):
        cap = _build_media_caption('م', 1.0, 10, 'u', stats='❤️ 425  💬 113')
        assert '❤️ 425' in cap

    def test_long_title_truncated(self):
        cap = _build_media_caption('ط' * 500, 1.0, 10, 'u')
        assert 'ط' * 300 in cap and 'ط' * 301 not in cap

    def test_empty_title_has_fallback(self):
        assert '`فيديو`' in _build_media_caption('', 1.0, 10, 'u')
