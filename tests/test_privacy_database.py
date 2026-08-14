# -*- coding: utf-8 -*-
"""اختبارات حذف بيانات الخصوصية في subscription_db بلا PostgreSQL حي."""

from contextlib import contextmanager

import subscription_db as subdb


def _normalized(sql):
    return ' '.join(sql.split())


class _RecordingCursor:
    def __init__(self, rowcounts=None, fetchone_values=None):
        self.executions = []
        self._rowcounts = iter(rowcounts or [])
        self._fetchone_values = iter(fetchone_values or [])
        self.rowcount = -1

    def execute(self, sql, params=()):
        self.executions.append((_normalized(sql), params))
        self.rowcount = next(self._rowcounts, -1)

    def fetchone(self):
        return next(self._fetchone_values, None)


def _fake_db(cursor, commit_calls):
    @contextmanager
    def _cursor(commit=False):
        commit_calls.append(commit)
        yield cursor
    return _cursor


def test_cleanup_expired_privacy_data_deletes_only_expired_history_and_cache(
        monkeypatch):
    cursor = _RecordingCursor(rowcounts=[8, 3])
    commit_calls = []
    monkeypatch.setattr(subdb, 'db_cursor', _fake_db(cursor, commit_calls))

    result = subdb.cleanup_expired_privacy_data(history_days=14, cache_days=7)

    assert result == {'download_history': 8, 'media_cache': 3}
    assert commit_calls == [True]
    assert cursor.executions == [
        (
            "DELETE FROM download_history WHERE created_at < NOW() - "
            "(%s * INTERVAL '1 day')",
            (14,),
        ),
        (
            "DELETE FROM media_cache WHERE created_at < NOW() - "
            "(%s * INTERVAL '1 day')",
            (7,),
        ),
    ]


def test_cleanup_expired_privacy_data_clamps_non_positive_periods(monkeypatch):
    cursor = _RecordingCursor(rowcounts=[0, 0])
    commit_calls = []
    monkeypatch.setattr(subdb, 'db_cursor', _fake_db(cursor, commit_calls))

    result = subdb.cleanup_expired_privacy_data(history_days=0, cache_days=-5)

    assert result == {'download_history': 0, 'media_cache': 0}
    assert [params for _, params in cursor.executions] == [(1,), (1,)]


def test_delete_user_removes_private_rows_but_preserves_audit_and_enforcement(
        monkeypatch):
    user_id = 771234567
    other_user_id = 889876543
    cursor = _RecordingCursor()
    commit_calls = []
    setting_updates = []
    monkeypatch.setattr(subdb, 'db_cursor', _fake_db(cursor, commit_calls))
    monkeypatch.setattr(
        subdb, 'get_setting',
        lambda key, default=None: f'42,{user_id},{other_user_id}',
    )
    monkeypatch.setattr(
        subdb, 'set_setting',
        lambda key, value: setting_updates.append((key, value)),
    )
    monkeypatch.setitem(subdb._lang_cache, user_id, ('en', 1.0))
    monkeypatch.setitem(subdb._lang_cache, other_user_id, ('ar', 2.0))

    subdb.delete_user(user_id)

    assert commit_calls == [True]
    assert cursor.executions == [
        (
            'DELETE FROM member_answers WHERE question_id IN '
            '(SELECT id FROM admin_questions WHERE target_user = %s)',
            (user_id,),
        ),
        ('DELETE FROM member_answers WHERE user_id = %s', (user_id,)),
        ('DELETE FROM admin_questions WHERE target_user = %s', (user_id,)),
        ('DELETE FROM member_survey WHERE user_id = %s', (user_id,)),
        ('DELETE FROM download_history WHERE user_id = %s', (user_id,)),
        ('DELETE FROM daily_downloads WHERE user_id = %s', (user_id,)),
        ('DELETE FROM fsub_user_passed WHERE user_id = %s', (user_id,)),
        ('UPDATE payments SET user_id = NULL WHERE user_id = %s', (user_id,)),
        ('DELETE FROM users WHERE user_id = %s', (user_id,)),
    ]
    executed_sql = ' '.join(sql for sql, _ in cursor.executions)
    assert 'moderation' not in executed_sql
    assert 'DELETE FROM payments' not in executed_sql
    assert 'referrals' not in executed_sql
    assert setting_updates == [
        ('exempt_user_ids', f'42,{other_user_id}'),
    ]
    assert user_id not in subdb._lang_cache
    assert subdb._lang_cache[other_user_id] == ('ar', 2.0)


def test_approve_payment_rejects_detached_audit_row(monkeypatch):
    cursor = _RecordingCursor(
        fetchone_values=[(None, 'binance', 'pending', 30)],
    )
    commit_calls = []
    monkeypatch.setattr(subdb, 'db_cursor', _fake_db(cursor, commit_calls))

    result = subdb.approve_payment(payment_id=17, admin_id=42)

    assert result == (False, "صاحب الدفعة لم يعد موجوداً")
    assert commit_calls == [True]
    assert len(cursor.executions) == 1
    assert cursor.executions[0] == (
        'SELECT user_id, payment_method, status, '
        'COALESCE(duration_days, 30) FROM payments WHERE payment_id = %s '
        'FOR UPDATE',
        (17,),
    )


def test_approve_payment_does_not_approve_when_user_update_misses(monkeypatch):
    cursor = _RecordingCursor(
        rowcounts=[-1, 0],
        fetchone_values=[(771234567, 'binance', 'pending', 30)],
    )
    commit_calls = []
    monkeypatch.setattr(subdb, 'db_cursor', _fake_db(cursor, commit_calls))

    result = subdb.approve_payment(payment_id=18, admin_id=42)

    assert result == (False, "صاحب الدفعة لم يعد موجوداً")
    assert commit_calls == [True]
    assert len(cursor.executions) == 2
    assert cursor.executions[0][0].endswith('FOR UPDATE')
    assert cursor.executions[1][0].startswith('UPDATE users')
    assert all(
        not sql.startswith('UPDATE payments')
        for sql, _ in cursor.executions
    )
