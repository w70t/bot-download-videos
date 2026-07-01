# -*- coding: utf-8 -*-
"""
محوّلات الروابط الخاصة - Link Resolvers
=======================================
- سناب شات سبوت لايت: استخراج رابط الفيديو الخام من الصفحة مباشرة.
- روابط الأغاني (Shazam/Apple Music/Spotify): لا تُحمّل مباشرة (Shazam يتعرّف
  فقط على الأغنية، وApple/Spotify مشفّرة بـ DRM). الحل: استخراج اسم الأغنية
  والفنان ثم البحث عنها وتحميلها من يوتيوب.
"""

import os
import re
import logging

import yt_dlp

from url_utils import is_safe_url
from cookies_manager import get_cookie_file_for_url

logger = logging.getLogger(__name__)


def resolve_snapchat_spotlight(url: str, timeout: int = 20) -> str:
    """يجلب صفحة سناب سبوت لايت ويستخرج رابط الفيديو الخام المباشر (أنظف نسخة
    متاحة، غالباً بلا لوقو لأن اللوقو طبقة واجهة لا جزء من الملف) من وسم
    og:video أو من رابط CDN داخل الصفحة، فيُحمّل مباشرة بدل مسار سناب الضعيف
    في yt-dlp. يعمل للسبوت لايت العام فقط؛ عند أي فشل يعيد الرابط الأصلي.
    يقبل روابط المشاركة snapchat.com/t/... (يتبع التوجيه للصفحة الحقيقية)."""
    low = (url or '').lower()
    if 'snapchat.com' not in low:
        return url
    import urllib.request
    from http.cookiejar import MozillaCookieJar
    try:
        cj = MozillaCookieJar()
        cookie_file = get_cookie_file_for_url(url)
        if cookie_file and os.path.exists(cookie_file):
            try:
                cj.load(cookie_file, ignore_discard=True, ignore_expires=True)
            except Exception:
                pass
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [
            ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/120.0.0.0 Safari/537.36'),
            ('Accept-Language', 'en-US,en;q=0.9'),
        ]
        with opener.open(url, timeout=timeout) as resp:
            html_text = resp.read(1500000).decode('utf-8', 'ignore')

        # 1) og:video — الأنسب لأن معاينات الروابط تعتمد عليه فيبقى مستقراً
        for pat in (
            r'property=["\']og:video(?::secure_url)?["\'][^>]*content=["\']([^"\']+\.mp4[^"\']*)["\']',
            r'content=["\']([^"\']+\.mp4[^"\']*)["\'][^>]*property=["\']og:video',
        ):
            m = re.search(pat, html_text)
            if m:
                cand = m.group(1).replace('&amp;', '&')
                if is_safe_url(cand):
                    logger.info(f"🎯 سناب سبوت لايت (og:video): {cand[:90]}")
                    return cand

        # 2) أي رابط فيديو خام من CDN سناب داخل JSON المضمّن (قد تكون الشرطات
        #    مهرّبة \/ لذا نطابق حتى علامة الاقتباس ثم نفكّ التهريب)
        m = re.search(r'"(https:[^"]*sc-cdn\.net[^"]*\.mp4[^"]*)"', html_text)
        if m:
            cand = m.group(1).replace('\\/', '/').replace('&amp;', '&')
            if is_safe_url(cand):
                logger.info(f"🎯 سناب سبوت لايت (cdn): {cand[:90]}")
                return cand
    except Exception as e:
        logger.warning(f"⚠️ تعذّر استخراج سناب سبوت لايت ({url[:60]}): {e}")
    return url


_MUSIC_LINK_MARKERS = ('shazam.com', 'music.apple.com', 'itunes.apple.com',
                       'open.spotify.com/track', 'spotify.link/')


def _is_music_link(url: str) -> bool:
    """هل الرابط من منصة أغاني نحوّلها لبحث يوتيوب؟"""
    low = (url or '').lower()
    return any(m in low for m in _MUSIC_LINK_MARKERS)


def _fetch_music_meta(url: str, timeout: int = 10):
    """يجلب (العنوان، الفنان) من صفحة Apple Music/Spotify عبر وسوم og/title."""
    import urllib.request
    from html import unescape
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            page = resp.read(600000).decode('utf-8', 'ignore')
    except Exception as e:
        logger.warning(f"⚠️ تعذّر جلب بيانات الأغنية ({url[:60]}): {e}")
        return None, None

    def meta(prop):
        for pat in (rf'{prop}["\'][^>]*content=["\']([^"\']+)["\']',
                    rf'content=["\']([^"\']+)["\'][^>]*{prop}'):
            m = re.search(pat, page, re.I)
            if m:
                return unescape(m.group(1)).strip()
        return None

    og_title = meta('og:title')
    desc = meta('og:description') or ''
    raw_title = None
    m = re.search(r'<title[^>]*>([^<]+)</title>', page, re.I)
    if m:
        raw_title = unescape(m.group(1)).strip()

    title = og_title or raw_title
    artist = None
    # نمط "العنوان by الفنان" (شائع في Apple Music) من og:title أو <title>
    for src in (og_title, raw_title):
        if src and not artist:
            mm = re.search(r'^(.*?)\s+by\s+(.+?)(?:\s+on\s+Apple Music.*)?(?:\s*[|].*)?$',
                           src, re.I)
            if mm:
                title = mm.group(1).strip()
                artist = mm.group(2).strip()
    # Spotify: og:description مثل "Elissa · Song · 2004" → الفنان أول جزء
    if not artist and '·' in desc:
        first = desc.split('·')[0].strip()
        if first and first.lower() not in ('song', 'album', 'single', 'listen'):
            artist = first
    # نظّف اللواحق الشائعة من العنوان
    if title:
        title = re.sub(r'\s*[|].*$', '', title).strip()
        title = re.sub(r'\s+on Apple Music.*$', '', title, flags=re.I).strip()
    return (title or None), (artist or None)


def _music_search_query(url: str):
    """يبني نص بحث 'الفنان العنوان' من رابط أغنية، أو None عند التعذّر."""
    import urllib.parse
    from html import unescape
    low = (url or '').lower()
    title = artist = None

    if 'shazam.com' in low:
        # الاسم والفنان في نهاية رابط شزام: #{"title":"...","artist":"..."}
        if '#' in url:
            frag = urllib.parse.unquote(url.split('#', 1)[1])
            mt = re.search(r'"title"\s*:\s*"([^"]+)"', frag)
            ma = re.search(r'"artist"\s*:\s*"([^"]+)"', frag)
            title = mt.group(1) if mt else None
            artist = ma.group(1) if ma else None
        # احتياطي: اسم المقطع من مسار الرابط /track/<id>/<slug>
        if not title:
            ms = re.search(r'/track/\d+/([^/?#]+)', url)
            if ms:
                title = urllib.parse.unquote(ms.group(1)).replace('-', ' ')
    else:
        # Apple Music / Spotify: اجلب الصفحة واقرأ الوسوم
        title, artist = _fetch_music_meta(url)

    if not title:
        return None
    q = f"{artist} {title}" if artist else title
    return re.sub(r'\s+', ' ', unescape(q)).strip()


def resolve_music_link(url: str):
    """يحوّل رابط أغنية إلى رابط يوتيوب لأول نتيجة بحث، أو None عند الفشل.
    (طلب شبكي متزامن — يُنفَّذ خارج حلقة الأحداث)."""
    query = _music_search_query(url)
    if not query:
        return None
    try:
        opts = {'quiet': True, 'no_warnings': True, 'skip_download': True,
                'extract_flat': True, 'default_search': 'ytsearch1'}
        with yt_dlp.YoutubeDL(opts) as ydl:
            r = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = (r or {}).get('entries') or []
        if not entries:
            return None
        vid = entries[0].get('id')
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
        return entries[0].get('url') or entries[0].get('webpage_url')
    except Exception as ex:
        logger.warning(f"⚠️ فشل بحث يوتيوب للأغنية '{query}': {ex}")
        return None
