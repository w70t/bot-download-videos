# -*- coding: utf-8 -*-
"""اختبارات إدارة الكوكيز (cookies_manager)."""

import time

import cookies_manager
from cookies_manager import _parse_netscape_cookies, validate_platform_cookies


FUTURE = str(int(time.time()) + 10 * 24 * 3600)
PAST = str(int(time.time()) - 10 * 24 * 3600)


def _netscape_line(domain, name, value, expiry=FUTURE):
    return f"{domain}\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}\n"


def _write_cookies(path, lines):
    header = "# Netscape HTTP Cookie File\n# padding to exceed the 100-byte minimum size check\n"
    path.write_text(header + ''.join(lines), encoding='utf-8')
    return str(path)


def test_parse_netscape_cookies(tmp_path):
    f = tmp_path / 'c.txt'
    _write_cookies(f, [
        _netscape_line('.facebook.com', 'c_user', '123'),
        "# comment line ignored\n",
        "#HttpOnly_.facebook.com\tTRUE\t/\tTRUE\t" + FUTURE + "\txs\tsecret\n",
        "broken line without tabs\n",
    ])
    cookies = _parse_netscape_cookies(str(f))
    names = {c['name'] for c in cookies}
    # سطر #HttpOnly_ كوكي حقيقي وليس تعليقاً
    assert names == {'c_user', 'xs'}


def test_validate_ok(tmp_path, monkeypatch):
    f = tmp_path / 'facebook.txt'
    _write_cookies(f, [
        _netscape_line('.facebook.com', 'c_user', '123'),
        _netscape_line('.facebook.com', 'xs', 'secret'),
    ])
    monkeypatch.setitem(cookies_manager.COOKIES_PLATFORMS, 'facebook',
                        {'name': 'Facebook', 'file': str(f)})
    result = validate_platform_cookies('facebook')
    assert result['ok'] is True
    assert result['has_auth'] is True


def test_validate_missing_file(monkeypatch, tmp_path):
    monkeypatch.setitem(cookies_manager.COOKIES_PLATFORMS, 'facebook',
                        {'name': 'Facebook', 'file': str(tmp_path / 'missing.txt')})
    assert validate_platform_cookies('facebook') == {'ok': False, 'reason': 'empty'}


def test_validate_wrong_platform(tmp_path, monkeypatch):
    f = tmp_path / 'facebook.txt'
    _write_cookies(f, [_netscape_line('.tiktok.com', 'sessionid', 'x')])
    monkeypatch.setitem(cookies_manager.COOKIES_PLATFORMS, 'facebook',
                        {'name': 'Facebook', 'file': str(f)})
    result = validate_platform_cookies('facebook')
    assert result['ok'] is False
    assert result['reason'] == 'wrong_platform'


def test_validate_not_logged_in(tmp_path, monkeypatch):
    f = tmp_path / 'facebook.txt'
    _write_cookies(f, [_netscape_line('.facebook.com', 'some_cookie', 'x')])
    monkeypatch.setitem(cookies_manager.COOKIES_PLATFORMS, 'facebook',
                        {'name': 'Facebook', 'file': str(f)})
    result = validate_platform_cookies('facebook')
    assert result['ok'] is False
    assert result['reason'] == 'not_logged_in'
    assert 'c_user' in result['missing']


def test_validate_expired(tmp_path, monkeypatch):
    f = tmp_path / 'facebook.txt'
    _write_cookies(f, [
        _netscape_line('.facebook.com', 'c_user', '123', expiry=PAST),
        _netscape_line('.facebook.com', 'xs', 'secret', expiry=PAST),
    ])
    monkeypatch.setitem(cookies_manager.COOKIES_PLATFORMS, 'facebook',
                        {'name': 'Facebook', 'file': str(f)})
    result = validate_platform_cookies('facebook')
    assert result['ok'] is False
    assert result['reason'] == 'expired'


def test_get_cookie_file_for_url_platform_match(tmp_path, monkeypatch):
    f = tmp_path / 'instagram.txt'
    _write_cookies(f, [_netscape_line('.instagram.com', 'sessionid', 'x')])
    monkeypatch.setitem(cookies_manager.COOKIES_PLATFORMS, 'instagram',
                        {'name': 'Instagram', 'file': str(f)})
    assert cookies_manager.get_cookie_file_for_url(
        'https://www.instagram.com/reel/abc') == str(f)


def test_get_cookie_file_threads_uses_instagram(tmp_path, monkeypatch):
    f = tmp_path / 'instagram.txt'
    _write_cookies(f, [_netscape_line('.instagram.com', 'sessionid', 'x')])
    monkeypatch.setitem(cookies_manager.COOKIES_PLATFORMS, 'instagram',
                        {'name': 'Instagram', 'file': str(f)})
    assert cookies_manager.get_cookie_file_for_url(
        'https://www.threads.net/@user/post/1') == str(f)
