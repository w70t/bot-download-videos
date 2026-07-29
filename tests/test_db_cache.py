# -*- coding: utf-8 -*-
"""اختبارات ذاكرة الإعدادات واللغات (subscription_db) — بلا قاعدة بيانات.

يُستبدل db_cursor بمؤشّر وهمي يعدّ الاستعلامات، فنقيس أن الذاكرة تُلغي
الرحلات المتكرّرة **دون** أن تُظهر قيمة قديمة بعد أي كتابة."""

from contextlib import contextmanager
from unittest.mock import patch

import subscription_db as subdb


class _FakeCursor:
    """مؤشّر وهمي: يعدّ الاستعلامات ويردّ من قاموس في الذاكرة."""

    def __init__(self, store, counter):
        self.store, self.counter, self._row = store, counter, None

    def execute(self, sql, params=()):
        self.counter.append(sql.strip().split()[0].upper())
        s = ' '.join(sql.split())
        if s.startswith('SELECT value FROM settings'):
            self._row = (self.store['settings'].get(params[0]),) \
                if params[0] in self.store['settings'] else None
        elif s.startswith('SELECT language FROM users'):
            self._row = (self.store['lang'].get(params[0]),) \
                if params[0] in self.store['lang'] else None
        elif 'INSERT INTO settings' in s:
            self.store['settings'][params[0]] = params[1]
        elif 'INSERT INTO users' in s:
            self.store['lang'][params[0]] = params[1]

    def fetchone(self):
        return self._row


def _fake_db(store, counter):
    @contextmanager
    def _cursor(commit=False):
        yield _FakeCursor(store, counter)
    return _cursor


class _Harness:
    def __init__(self):
        self.store = {'settings': {}, 'lang': {}}
        self.queries = []

    def __enter__(self):
        self._p = patch.object(subdb, 'db_cursor',
                               _fake_db(self.store, self.queries))
        self._p.start()
        subdb.clear_caches()
        return self

    def __exit__(self, *a):
        self._p.stop()
        subdb.clear_caches()
        return False


# ── الإعدادات ───────────────────────────────────────────────────

def test_setting_read_hits_db_once():
    with _Harness() as h:
        h.store['settings']['daily_download_limit'] = '6'
        for _ in range(20):
            assert subdb.get_setting('daily_download_limit') == '6'
        assert h.queries.count('SELECT') == 1     # ١٩ رحلة أُلغيت


def test_setting_write_takes_effect_immediately():
    # الأهم: ضغط الأدمن على الزر يجب أن يسري في الحال لا بعد انتهاء المهلة
    with _Harness() as h:
        h.store['settings']['max_duration_minutes'] = '60'
        assert subdb.get_setting('max_duration_minutes') == '60'
        subdb.set_setting('max_duration_minutes', '15')
        assert subdb.get_setting('max_duration_minutes') == '15'
        assert h.store['settings']['max_duration_minutes'] == '15'


def test_missing_setting_uses_default_and_is_cached():
    with _Harness() as h:
        assert subdb.get_setting('not_there', 'افتراضي') == 'افتراضي'
        assert subdb.get_setting('not_there', 'افتراضي') == 'افتراضي'
        assert h.queries.count('SELECT') == 1
        # الافتراضي ليس مخزَّناً كقيمة: افتراضي مختلف يعطي نتيجة مختلفة
        assert subdb.get_setting('not_there', 'آخر') == 'آخر'


def test_setting_cache_expires_by_ttl():
    with _Harness() as h:
        h.store['settings']['k'] = 'قديم'
        assert subdb.get_setting('k') == 'قديم'
        h.store['settings']['k'] = 'جديد'          # كتابة من خارج البوت
        assert subdb.get_setting('k') == 'قديم'    # ما زالت ضمن المهلة
        with patch.object(subdb, '_SETTINGS_TTL', -1):
            assert subdb.get_setting('k') == 'جديد'


# ── اللغة ───────────────────────────────────────────────────────

def test_language_read_hits_db_once_per_user():
    with _Harness() as h:
        h.store['lang'][7] = 'en'
        for _ in range(30):
            assert subdb.get_user_language(7) == 'en'
        assert h.queries.count('SELECT') == 1


def test_language_defaults_to_arabic_and_caches():
    with _Harness() as h:
        assert subdb.get_user_language(99) == 'ar'
        assert subdb.get_user_language(99) == 'ar'
        assert h.queries.count('SELECT') == 1


def test_language_change_takes_effect_immediately():
    with _Harness() as h:
        h.store['lang'][7] = 'ar'
        assert subdb.get_user_language(7) == 'ar'
        subdb.set_user_language(7, 'en')
        assert subdb.get_user_language(7) == 'en'   # بلا انتظار المهلة


def test_language_cache_is_per_user():
    with _Harness() as h:
        h.store['lang'][1], h.store['lang'][2] = 'ar', 'en'
        assert subdb.get_user_language(1) == 'ar'
        assert subdb.get_user_language(2) == 'en'
        assert subdb.get_user_language(1) == 'ar'


def test_language_cache_bounded():
    # لا تتضخّم الذاكرة مع آلاف الأعضاء
    with _Harness():
        with patch.object(subdb, '_LANG_CACHE_MAX', 10):
            for uid in range(50):
                subdb.get_user_language(uid)
        assert len(subdb._lang_cache) <= 10


def test_clear_caches_forces_reload():
    with _Harness() as h:
        h.store['settings']['x'] = '1'
        subdb.get_setting('x')
        subdb.clear_caches()
        subdb.get_setting('x')
        assert h.queries.count('SELECT') == 2
