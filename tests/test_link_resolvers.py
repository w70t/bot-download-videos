# -*- coding: utf-8 -*-
"""اختبارات محوّلات الروابط (link_resolvers) — بدون أي طلبات شبكية."""

from link_resolvers import _is_music_link, _music_search_query, resolve_snapchat_spotlight


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
