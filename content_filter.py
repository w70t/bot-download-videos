# -*- coding: utf-8 -*-
"""
فلتر المحتوى - Content Filter
=============================
- فلتر المحتوى الإباحي (حظر قبل التحميل): قائمة نطاقات معروفة + كلمات
  مفتاحية في الرابط والعنوان. يوقف المحتوى قبل أي تحميل (بلا تكلفة)
  ويمكن للأدمن تشغيله/إيقافه وإضافة نطاقات/كلمات مخصصة.
- حظر الحسابات المصدر: منع تحميل أي محتوى من ناشر معيّن.
"""

from urllib.parse import urlparse

import subscription_db as subdb
from url_utils import _url_host

ADULT_DOMAINS = {
    'pornhub.com', 'xvideos.com', 'xvideos2.com', 'xnxx.com', 'xhamster.com',
    'xhamster.desi', 'redtube.com', 'youporn.com', 'tube8.com', 'spankbang.com',
    'youjizz.com', 'beeg.com', 'tnaflix.com', 'drtuber.com', 'sunporno.com',
    'eporner.com', 'txxx.com', 'hclips.com', 'upornia.com', 'hotmovs.com',
    'vjav.com', 'porntrex.com', 'motherless.com', 'porn.com', 'pornhd.com',
    'porntube.com', 'pornone.com', 'porngo.com', 'porntrex.com', 'fapality.com',
    'brazzers.com', 'realitykings.com', 'bangbros.com', 'naughtyamerica.com',
    'onlyfans.com', 'fansly.com', 'manyvids.com', 'clips4sale.com',
    'chaturbate.com', 'cam4.com', 'myfreecams.com', 'stripchat.com',
    'bongacams.com', 'livejasmin.com', 'camsoda.com', 'streamate.com',
    'redgifs.com', 'gifs.com', 'rule34video.com', 'rule34.xxx',
    'hanime.tv', 'hentaihaven.xxx', 'nhentai.net', 'hentai.tv', 'fakings.com',
    'xmoviesforyou.com', 'fux.com', 'keezmovies.com', 'extremetube.com',
    'gotporn.com', 'pornhat.com', 'analdin.com', 'hdzog.com', 'thothub.tv',
}

# كلمات مفتاحية صريحة (عربي + إنجليزي). تُفحص في النطاق ومسار الرابط والعنوان.
ADULT_KEYWORDS = [
    'porn', 'xxx', 'xnxx', 'sexvideo', 'sex-video', 'nsfw', 'hentai',
    'camgirl', 'camslut', 'fuck', 'blowjob', 'creampie', 'cumshot',
    'milf', 'hardcore', 'bigtits', 'pussy', 'anal', 'escort',
    'سكس', 'اباحي', 'إباحي', 'اباحية', 'إباحية', 'نيك', 'خلاعة', 'عاهرة',
    'شرموطة', 'متناكة', 'سحاق', 'لواط',
]


def _custom_adult_domains():
    """نطاقات إضافية حظرها الأدمن من لوحة التحكم (مفصولة بفاصلة)."""
    raw = subdb.get_setting('adult_custom_domains', '') or ''
    return [d.strip().lower().lstrip('.') for d in raw.split(',') if d.strip()]


def _custom_adult_keywords():
    """كلمات إضافية حظرها الأدمن من لوحة التحكم (مفصولة بفاصلة)."""
    raw = subdb.get_setting('adult_custom_keywords', '') or ''
    return [k.strip().lower() for k in raw.split(',') if k.strip()]


def _add_to_setting_list(key, value):
    """يضيف قيمة لقائمة إعداد مفصولة بفواصل (يتجاهل التكرار). يرجع True إن أُضيفت."""
    value = value.strip().lower().lstrip('.')
    if not value:
        return False
    raw = subdb.get_setting(key, '') or ''
    items = [x.strip().lower() for x in raw.split(',') if x.strip()]
    if value in items:
        return False
    items.append(value)
    subdb.set_setting(key, ','.join(items))
    return True


def _remove_from_setting_list(key, index):
    """يحذف عنصراً واحداً من قائمة إعداد حسب فهرسه. يرجع القيمة المحذوفة أو None."""
    raw = subdb.get_setting(key, '') or ''
    items = [x.strip() for x in raw.split(',') if x.strip()]
    if 0 <= index < len(items):
        removed = items.pop(index)
        subdb.set_setting(key, ','.join(items))
        return removed
    return None


def _host_is_adult(host):
    """هل المضيف ينتمي لنطاق إباحي معروف (يشمل النطاقات الفرعية)؟"""
    if not host:
        return False
    if host.startswith('www.'):
        host = host[4:]
    for domain in set(ADULT_DOMAINS) | set(_custom_adult_domains()):
        if host == domain or host.endswith('.' + domain):
            return True
    return False


def _text_has_adult_keyword(text):
    """هل النص يحتوي على كلمة مفتاحية إباحية صريحة؟"""
    if not text:
        return False
    low = str(text).lower()
    return any(kw in low for kw in (ADULT_KEYWORDS + _custom_adult_keywords()))


def is_adult_url(url):
    """فحص الرابط قبل الاستخراج: النطاق أولاً، ثم كلمات في مسار الرابط."""
    host = _url_host(url)
    if _host_is_adult(host):
        return True
    return _text_has_adult_keyword(url)


def is_adult_info(info):
    """فحص بيانات الفيديو بعد الاستخراج (الحساسية/العنوان/الوصف/الناشر)."""
    if not info:
        return False
    try:
        if int(info.get('age_limit') or 0) >= 18:
            return True
    except (TypeError, ValueError):
        pass
    # علم الحساسية في X/تويتر ومنصات أخرى
    if info.get('possibly_sensitive') or info.get('is_nsfw') or info.get('nsfw'):
        return True
    parts = [info.get('title'), info.get('description'), info.get('uploader'),
             info.get('uploader_id'), info.get('channel'), info.get('uploader_url')]
    parts.extend(info.get('categories') or [])
    parts.extend(info.get('tags') or [])
    return any(_text_has_adult_keyword(p) for p in parts)


def _blocked_accounts():
    """مجموعة الحسابات المحظورة (يديرها الأدمن، مفصولة بفواصل)."""
    raw = subdb.get_setting('blocked_accounts', '') or ''
    return {x.strip().lower().lstrip('@') for x in raw.split(',') if x.strip()}


def _handle_from_url(url):
    """يستخرج اسم الحساب من رابط X/تويتر (x.com/<handle>/status/...)."""
    try:
        p = urlparse(url if '://' in url else 'http://' + url)
        host = (p.hostname or '').lower()
        if not any(h in host for h in ('x.com', 'twitter.com')):
            return None
        parts = [x for x in p.path.split('/') if x]
        if parts and parts[0].lower() not in ('i', 'status', 'home', 'search'):
            return parts[0].lstrip('@').lower()
    except Exception:
        pass
    return None


def is_blocked_url(url):
    """حظر مبكر (قبل الاستخراج) حسب اسم الحساب في رابط X/تويتر."""
    h = _handle_from_url(url)
    return bool(h and h in _blocked_accounts())


def _account_identifiers(info):
    """يجمع معرّفات الناشر الممكنة من معلومات الفيديو (للمطابقة مع قائمة الحظر)."""
    ids = set()
    if not info:
        return ids
    for key in ('uploader_id', 'uploader', 'channel_id', 'channel', 'creator',
                'uploader_url', 'channel_url', 'webpage_url'):
        v = info.get(key)
        if not v:
            continue
        s = str(v).strip().lower().lstrip('@')
        if s:
            ids.add(s)
            if '/' in s:  # استخرج اسم الحساب من نهاية الرابط
                tail = s.rstrip('/').split('/')[-1]
                if tail:
                    ids.add(tail.lstrip('@'))
    return ids


def is_blocked_account(info):
    """هل ناشر هذا المحتوى ضمن قائمة الحسابات المحظورة؟"""
    blocked = _blocked_accounts()
    if not blocked:
        return False
    return bool(_account_identifiers(info) & blocked)


def adult_filter_enabled():
    """هل فلتر المحتوى الإباحي مُفعّل؟ (افتراضياً مُفعّل)."""
    return subdb.get_setting('block_adult_content', '1') == '1'


def downloads_enabled():
    """هل التحميل مُفعّل للأعضاء؟ (افتراضياً مُفعّل). الأدمن لا يتأثر."""
    return subdb.get_setting('downloads_enabled', '1') == '1'
