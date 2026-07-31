# -*- coding: utf-8 -*-
"""اختبارات حدود رفع الملفات (upload_limits).

الهدف: تثبيت أن السقف لا يتجاوز سقف بايروجرام الصلب (2000 MiB لحساب غير
بريميوب — والبوت ليس بريميوم) مهما كان الإعداد، وأن محاولة التصغير قبل
الرفض حكرٌ على الأدمن فلا يتغيّر شيء للعضو العادي.
"""

import pytest

import upload_limits as ul
import translations

LIMIT = ul.TELEGRAM_BOT_UPLOAD_LIMIT_MB


class TestUploadLimitMb:
    """السقف الفعّال مقصوص دائماً على سقف تلجرام."""

    def test_default_is_telegram_ceiling(self):
        assert ul.upload_limit_mb() == LIMIT

    def test_higher_setting_is_clamped(self):
        # وعدٌ بما لا يُرفع = انهيار ValueError من بايروجرام بدل رسالة واضحة
        assert ul.upload_limit_mb(4000) == LIMIT
        assert ul.upload_limit_mb(10 ** 9) == LIMIT

    def test_lower_setting_is_honoured(self):
        assert ul.upload_limit_mb(500) == 500

    @pytest.mark.parametrize('bogus', [0, -1, 'abc', '', None, float('nan')])
    def test_invalid_setting_falls_back_to_ceiling(self, bogus):
        assert ul.upload_limit_mb(bogus) == LIMIT


class TestFitsUploadLimit:
    """حدّ القبول: المساواة تمرّ، وما فوقها يُرفض."""

    def test_exactly_at_limit_passes(self):
        assert ul.fits_upload_limit(LIMIT)

    def test_above_limit_rejected(self):
        assert not ul.fits_upload_limit(LIMIT + 0.1)

    def test_small_file_passes(self):
        assert ul.fits_upload_limit(12.5)


class TestShouldShrinkBeforeReject:
    """التصغير قبل الرفض: للأدمن، وللفيديو، وعند تجاوز السقف فقط."""

    def test_admin_oversized_video_shrinks(self):
        assert ul.should_shrink_before_reject(3200, admin=True, is_audio=False)

    def test_member_oversized_video_is_rejected_as_before(self):
        # سلوك العضو العادي لم يتغيّر: رفض فوري بلا إعادة ترميز تُثقل الجهاز
        assert not ul.should_shrink_before_reject(3200, admin=False, is_audio=False)

    def test_admin_audio_never_shrinks(self):
        # finalize_video لا يُجهّز الصوت أصلاً
        assert not ul.should_shrink_before_reject(3200, admin=True, is_audio=True)

    def test_fitting_file_is_left_alone(self):
        assert not ul.should_shrink_before_reject(900, admin=True, is_audio=False)

    def test_exactly_at_limit_is_left_alone(self):
        assert not ul.should_shrink_before_reject(LIMIT, admin=True, is_audio=False)


class TestMessages:
    """رسالتا الحجم الكبير والتصغير تعرضان قيمهما في اللغتين."""

    @pytest.mark.parametrize('lang', ['ar', 'en'])
    def test_too_large_shows_actual_limit(self, lang):
        msg = translations.t('file_too_large', lang, size='3200.0',
                             max=ul.upload_limit_mb())
        assert '3200.0' in msg and str(LIMIT) in msg
        assert '{' not in msg  # لا وسيط متروك بلا تعبئة

    @pytest.mark.parametrize('lang', ['ar', 'en'])
    def test_shrinking_message_formats(self, lang):
        msg = translations.t('shrinking', lang, size='3200.0')
        assert '3200.0' in msg
        assert '{' not in msg
