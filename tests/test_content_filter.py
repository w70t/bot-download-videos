# -*- coding: utf-8 -*-
"""اختبارات فلتر المحتوى (content_filter) — قاعدة البيانات مستبدلة بذاكرة مؤقتة."""

import pytest

import content_filter
from content_filter import (
    is_adult_url, is_adult_info, _handle_from_url, is_blocked_url,
    is_blocked_account, _host_is_adult, adult_filter_enabled, downloads_enabled,
)


@pytest.fixture(autouse=True)
def fake_settings(monkeypatch):
    """استبدال إعدادات قاعدة البيانات بقاموس في الذاكرة."""
    settings = {}
    monkeypatch.setattr(content_filter.subdb, 'get_setting',
                        lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(content_filter.subdb, 'set_setting',
                        lambda key, value: settings.__setitem__(key, value))
    return settings


class TestAdultUrl:
    def test_known_domain_blocked(self):
        assert is_adult_url('https://www.pornhub.com/view?v=1')

    def test_subdomain_blocked(self):
        assert _host_is_adult('sub.xvideos.com')

    def test_clean_url_passes(self):
        assert not is_adult_url('https://www.youtube.com/watch?v=abc')

    def test_keyword_in_url(self):
        assert is_adult_url('https://example.com/free-porn-videos')

    def test_arabic_keyword(self):
        assert is_adult_url('https://example.com/سكس')

    def test_custom_domain_from_admin(self, fake_settings):
        fake_settings['adult_custom_domains'] = 'badsite.com'
        assert is_adult_url('https://badsite.com/v/1')
        assert is_adult_url('https://cdn.badsite.com/v/1')


class TestAdultInfo:
    def test_age_limit(self):
        assert is_adult_info({'age_limit': 18, 'title': 'clip'})
        assert not is_adult_info({'age_limit': 0, 'title': 'clip'})

    def test_sensitive_flag(self):
        assert is_adult_info({'possibly_sensitive': True, 'title': 'clip'})

    def test_keyword_in_title(self):
        assert is_adult_info({'title': 'hot xxx video'})

    def test_clean_info(self):
        assert not is_adult_info({'title': 'وصفة كبسة دجاج', 'uploader': 'مطبخنا'})

    def test_none(self):
        assert not is_adult_info(None)


class TestBlockedAccounts:
    def test_handle_from_twitter_url(self):
        assert _handle_from_url('https://x.com/SomeUser/status/1') == 'someuser'
        assert _handle_from_url('https://twitter.com/@other/status/2') == 'other'

    def test_handle_ignores_non_twitter(self):
        assert _handle_from_url('https://youtube.com/watch?v=1') is None

    def test_handle_ignores_reserved_paths(self):
        assert _handle_from_url('https://x.com/i/status/123') is None

    def test_blocked_url(self, fake_settings):
        fake_settings['blocked_accounts'] = 'baduser, @another'
        assert is_blocked_url('https://x.com/BadUser/status/1')
        assert not is_blocked_url('https://x.com/gooduser/status/1')

    def test_blocked_account_info(self, fake_settings):
        fake_settings['blocked_accounts'] = 'spammer'
        assert is_blocked_account({'uploader_id': 'Spammer'})
        assert is_blocked_account({'uploader_url': 'https://tiktok.com/@spammer'})
        assert not is_blocked_account({'uploader_id': 'normal_user'})

    def test_no_blocklist(self):
        assert not is_blocked_account({'uploader_id': 'anyone'})


class TestToggles:
    def test_defaults_enabled(self):
        assert adult_filter_enabled()
        assert downloads_enabled()

    def test_disabled(self, fake_settings):
        fake_settings['block_adult_content'] = '0'
        fake_settings['downloads_enabled'] = '0'
        assert not adult_filter_enabled()
        assert not downloads_enabled()
