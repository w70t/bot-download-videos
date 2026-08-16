# -*- coding: utf-8 -*-
"""Referral registration/reward must never create ghost member profiles."""

from contextlib import contextmanager
from pathlib import Path

import pytest

import subscription_db as subdb


BOT_PATH = Path(__file__).resolve().parents[1] / 'bot.py'


class ReferralCursor:
    def __init__(self, rows, fail_on_execute=None):
        self.rows = iter(rows)
        self.executions = []
        self.rowcount = 1
        self.fail_on_execute = fail_on_execute

    def execute(self, sql, params=()):
        self.executions.append((' '.join(sql.split()), params))
        if self.fail_on_execute == len(self.executions):
            raise RuntimeError('simulated database failure')

    def fetchone(self):
        return next(self.rows, None)


def transaction(cursor, state):
    @contextmanager
    def manager(commit=False):
        state['opened'] += 1
        try:
            yield cursor
        except Exception:
            state['rollbacks'] += 1
            raise
        else:
            if commit:
                state['commits'] += 1
    return manager


def _state():
    return {'opened': 0, 'commits': 0, 'rollbacks': 0}


def test_unknown_referrer_creates_nothing(monkeypatch):
    cursor = ReferralCursor([None])
    state = _state()
    monkeypatch.setattr(subdb, 'db_cursor', transaction(cursor, state))

    assert subdb.record_referral_and_reward(200, 999, 1) is False

    assert state == {'opened': 1, 'commits': 1, 'rollbacks': 0}
    assert len(cursor.executions) == 1
    assert cursor.executions[0] == (
        'SELECT user_id FROM users WHERE user_id = %s FOR UPDATE',
        (999,),
    )
    assert all('INSERT INTO users' not in sql for sql, _ in cursor.executions)
    assert all('INSERT INTO referrals' not in sql for sql, _ in cursor.executions)


def test_existing_referrer_is_rewarded_once_in_one_transaction(monkeypatch):
    cursor = ReferralCursor([(100,), (200,), (100,)])
    state = _state()
    monkeypatch.setattr(subdb, 'db_cursor', transaction(cursor, state))

    assert subdb.record_referral_and_reward(200, 100, 2) is True

    assert state == {'opened': 1, 'commits': 1, 'rollbacks': 0}
    assert len(cursor.executions) == 3
    assert cursor.executions[1][0].startswith('INSERT INTO referrals')
    assert 'ON CONFLICT (referred_user_id) DO NOTHING' in cursor.executions[1][0]
    assert cursor.executions[2] == (
        'UPDATE users SET bonus_downloads = COALESCE(bonus_downloads, 0) + %s '
        'WHERE user_id = %s RETURNING user_id',
        (2, 100),
    )
    assert all('INSERT INTO users' not in sql for sql, _ in cursor.executions)


def test_duplicate_referral_never_rewards_twice(monkeypatch):
    cursor = ReferralCursor([(100,), None])
    state = _state()
    monkeypatch.setattr(subdb, 'db_cursor', transaction(cursor, state))

    assert subdb.record_referral_and_reward(200, 100, 2) is False

    assert len(cursor.executions) == 2
    assert all('bonus_downloads' not in sql for sql, _ in cursor.executions)
    assert state['commits'] == 1


def test_self_referral_is_rejected_before_opening_transaction(monkeypatch):
    def forbidden_db(*_args, **_kwargs):
        raise AssertionError('database must not be touched')

    monkeypatch.setattr(subdb, 'db_cursor', forbidden_db)

    assert subdb.record_referral_and_reward(100, 100, 5) is False


def test_reward_failure_rolls_back_the_referral_insert(monkeypatch):
    cursor = ReferralCursor([(100,), (200,)], fail_on_execute=3)
    state = _state()
    monkeypatch.setattr(subdb, 'db_cursor', transaction(cursor, state))

    with pytest.raises(RuntimeError, match='simulated database failure'):
        subdb.record_referral_and_reward(200, 100, 1)

    assert state == {'opened': 1, 'commits': 0, 'rollbacks': 1}
    assert len(cursor.executions) == 3


def test_bot_uses_atomic_referral_path_only():
    source = BOT_PATH.read_text(encoding='utf-8')
    start = source.index('async def _process_referral_start')
    end = source.index('\n\nasync def _show_history', start)
    referral_handler = source[start:end]

    assert 'record_referral_and_reward' in referral_handler
    assert 'add_bonus_downloads' not in referral_handler
    assert 'record_referral(' not in referral_handler
