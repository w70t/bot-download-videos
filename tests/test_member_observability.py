# -*- coding: utf-8 -*-
"""Member activity/departure semantics without a live PostgreSQL server."""

import ast
from contextlib import contextmanager
from pathlib import Path

import subscription_db as subdb


BOT_PATH = Path(__file__).resolve().parents[1] / 'bot.py'
SETUP_PATH = Path(__file__).resolve().parents[1] / 'setup_postgres.py'


class RecordingCursor:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount
        self.executions = []

    def execute(self, sql, params=()):
        self.executions.append((' '.join(sql.split()), params))


def fake_db(cursor, commits):
    @contextmanager
    def manager(commit=False):
        commits.append(commit)
        yield cursor
    return manager


def test_activity_touch_updates_existing_member_once_per_debounce(monkeypatch):
    cursor = RecordingCursor(rowcount=1)
    commits = []
    monkeypatch.setattr(subdb, 'db_cursor', fake_db(cursor, commits))
    monkeypatch.setattr(subdb.time, 'monotonic', lambda: 1000.0)
    subdb._activity_touch_cache.clear()

    assert subdb.touch_user_activity(42, minimum_interval=300) is True
    assert subdb.touch_user_activity(42, minimum_interval=300) is False

    assert commits == [True]
    assert cursor.executions == [(
        'UPDATE users SET last_activity_at = NOW() WHERE user_id = %s',
        (42,),
    )]


def test_activity_touch_never_creates_unknown_member_or_caches_miss(monkeypatch):
    cursor = RecordingCursor(rowcount=0)
    commits = []
    monkeypatch.setattr(subdb, 'db_cursor', fake_db(cursor, commits))
    monkeypatch.setattr(subdb.time, 'monotonic', lambda: 1000.0)
    subdb._activity_touch_cache.clear()

    assert subdb.touch_user_activity(99) is False
    assert subdb.touch_user_activity(99) is False

    assert len(cursor.executions) == 2
    assert all(sql.startswith('UPDATE users') for sql, _ in cursor.executions)
    assert all('INSERT' not in sql for sql, _ in cursor.executions)


def test_profile_upsert_marks_activity_without_resetting_commercial_fields(
        monkeypatch):
    cursor = RecordingCursor()
    monkeypatch.setattr(subdb, 'db_cursor', fake_db(cursor, []))

    subdb.add_or_update_user(42, 'ali', 'Ali')

    sql, params = cursor.executions[0]
    assert 'last_activity_at' in sql
    assert 'last_activity_at = excluded.last_activity_at' in sql
    assert 'is_subscribed' not in sql
    assert 'bonus_downloads' not in sql
    assert 'total_downloads' not in sql
    assert params == (42, 'ali', 'Ali')


def test_member_activity_migration_is_idempotent_indexed_and_anonymous(
        monkeypatch):
    cursor = RecordingCursor()
    monkeypatch.setattr(subdb, 'db_cursor', fake_db(cursor, []))

    subdb._ensure_member_activity_schema()

    statements = [sql for sql, _params in cursor.executions]
    joined = '\n'.join(statements)
    assert 'ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ' in joined
    assert 'CREATE INDEX IF NOT EXISTS idx_users_last_activity_at' in joined
    assert 'CREATE TABLE IF NOT EXISTS member_departures' in joined
    assert 'CREATE INDEX IF NOT EXISTS idx_member_departures_occurred_at' in joined
    departure_table = next(
        sql for sql in statements
        if 'CREATE TABLE IF NOT EXISTS member_departures' in sql
    )
    assert 'user_id' not in departure_table.lower()
    assert 'username' not in departure_table.lower()
    assert 'url' not in departure_table.lower()
    assert "INTERVAL '90 days'" in joined


def test_fresh_postgres_setup_contains_the_same_columns_and_real_indexes():
    source = SETUP_PATH.read_text(encoding='utf-8')

    assert 'last_activity_at TIMESTAMPTZ' in source
    assert 'ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity_at' in source
    assert 'idx_users_last_activity_at' in source
    assert 'CREATE TABLE IF NOT EXISTS member_departures' in source
    assert 'idx_member_departures_occurred_at' in source


def test_bot_tracks_inbound_updates_early_and_only_deletes_conclusive_errors():
    tree = ast.parse(BOT_PATH.read_text(encoding='utf-8'))
    gone_assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name)
                and target.id == 'GONE_USER_ERRORS'
                for target in node.targets)
    )
    error_names = {
        element.id for element in gone_assignment.value.elts
        if isinstance(element, ast.Name)
    }
    assert error_names == {
        'UserIsBlocked', 'InputUserDeactivated',
        'UserDeactivated', 'UserDeactivatedBan',
    }
    assert 'PeerIdInvalid' not in error_names

    functions = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in ('_track_member_message_activity',
                 '_track_member_callback_activity'):
        handler = functions[name]
        decorator = handler.decorator_list[0]
        group = next(keyword.value for keyword in decorator.keywords
                     if keyword.arg == 'group')
        assert isinstance(group, ast.UnaryOp)
        assert isinstance(group.op, ast.USub)
        assert group.operand.value == 100
        calls = [node for node in ast.walk(handler) if isinstance(node, ast.Call)]
        assert any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == 'to_thread'
            and len(call.args) >= 1
            and isinstance(call.args[0], ast.Attribute)
            and call.args[0].attr == 'touch_user_activity'
            for call in calls
        )

    source = BOT_PATH.read_text(encoding='utf-8')
    assert "set_setting('last_reachability_check_at'" in source
    assert 'حذف المحادثة وحده لا يُعد مغادرة' in source
