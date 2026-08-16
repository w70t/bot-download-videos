# -*- coding: utf-8 -*-
"""Contract and privacy tests for full download-history telemetry sync."""

import asyncio
from contextlib import contextmanager
from datetime import datetime
import json
from unittest.mock import patch

import pytest

import admin_telemetry as telemetry
import subscription_db as subdb


SECRET = bytes.fromhex('ab' * 32)


class FakeCursor:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []
        self.index = -1

    def execute(self, sql, params=()):
        self.index += 1
        self.queries.append((' '.join(sql.split()), params))

    def fetchone(self):
        return self.responses[self.index]

    def fetchall(self):
        return self.responses[self.index]


def _fake_db(cursor):
    @contextmanager
    def manager(commit=False):
        yield cursor
    return manager


def _config(batch_size=2):
    return telemetry.TelemetryConfig(
        endpoint='https://example.com/api/ingest',
        secret=SECRET,
        download_batch_size=batch_size,
    )


def test_download_wire_record_is_an_exact_privacy_allowlist():
    record = telemetry._normalise_download({
        'id': 91,
        'userId': 42,
        'title': (
            'clip https://private.example/watch '
            '123456789:abcdefghijklmnopqrstuvwxyzABCD '
            '/home/bot/private.mp4'
        ),
        'platform': 'youtube',
        'kind': 'album',
        'quality': '1080p',
        'sizeMb': 12.345,
        'fromCache': True,
        'createdAt': datetime(2026, 8, 16, 10, 0, 0),
        'url': 'https://must-not-leak.example',
        'fileId': 'telegram-secret',
        'path': '/tmp/private.mp4',
        'token': 'secret',
        'firstName': 'Not needed for per-member history',
    })

    assert set(record) == {
        'id', 'userId', 'title', 'platform', 'kind', 'quality', 'sizeMb',
        'fromCache', 'createdAt',
    }
    assert record['kind'] == 'album'
    assert record['sizeMb'] == 12.35
    encoded = json.dumps(record)
    assert 'private.example' not in encoded
    assert 'abcdefghijklmnopqrstuvwxyzABCD' not in encoded
    assert '/home/bot' not in encoded
    assert 'telegram-secret' not in encoded
    assert '/tmp/private' not in encoded


def test_download_database_page_is_one_keyset_query_without_private_columns():
    observed = datetime(2026, 8, 16, 12, 0, 0)
    row = (91, 42, 'Title', 'instagram', 'image', 'original',
           1.25, False, observed)
    cursor = FakeCursor([[(row)]])

    with patch.object(subdb, 'db_cursor', _fake_db(cursor)):
        result = subdb.get_admin_telemetry_downloads(
            limit=999,
            after_id=80,
            upper_id=100,
            observed_at=observed,
        )

    assert len(cursor.queries) == 1
    sql, params = cursor.queries[0]
    projection = sql.split('FROM download_history', 1)[0].lower()
    assert 'url' not in projection
    assert 'file_id' not in sql.lower()
    assert 'path' not in sql.lower()
    assert 'token' not in sql.lower()
    assert 'id > %s' in sql and 'id <= %s' in sql
    assert "INTERVAL '30 days'" in sql
    assert 'ORDER BY id' in sql
    assert params == (80, 100, observed, observed, 40)
    assert result == [{
        'id': 91,
        'userId': 42,
        'title': 'Title',
        'platform': 'instagram',
        'kind': 'image',
        'quality': 'original',
        'sizeMb': 1.25,
        'fromCache': False,
        'createdAt': observed,
    }]


def test_download_upper_bound_is_one_retained_window_query():
    observed = datetime(2026, 8, 16, 12, 0, 0)
    cursor = FakeCursor([(123,)])

    with patch.object(subdb, 'db_cursor', _fake_db(cursor)):
        upper_id = subdb.get_admin_telemetry_download_upper_id(observed)

    assert upper_id == 123
    assert len(cursor.queries) == 1
    sql, params = cursor.queries[0]
    assert 'MAX(id)' in sql
    assert "INTERVAL '30 days'" in sql
    assert params == (observed, observed)


def test_download_batches_are_sequential_keyset_and_share_observed_at(monkeypatch):
    rows = [
        {'id': 10, 'userId': 1, 'kind': 'video'},
        {'id': 20, 'userId': 2, 'kind': 'image'},
        {'id': 30, 'userId': 3, 'kind': 'audio'},
    ]
    observed_arguments = []
    page_arguments = []

    def upper(observed):
        observed_arguments.append(observed)
        return 30

    def page(limit, after_id, upper_id, observed):
        page_arguments.append((limit, after_id, upper_id, observed))
        return [row for row in rows if row['id'] > after_id][:limit]

    monkeypatch.setattr(
        telemetry.subdb, 'get_admin_telemetry_download_upper_id', upper)
    monkeypatch.setattr(
        telemetry.subdb, 'get_admin_telemetry_downloads', page)
    sent = []
    monkeypatch.setattr(
        telemetry, '_post_json', lambda _config, payload: sent.append(payload))

    asyncio.run(telemetry._push_download_sync(_config()))

    assert [payload['type'] for payload in sent] == ['downloads', 'downloads']
    assert [payload['batchIndex'] for payload in sent] == [0, 1]
    assert [payload['final'] for payload in sent] == [False, True]
    assert [len(payload['downloads']) for payload in sent] == [2, 1]
    assert len({payload['syncId'] for payload in sent}) == 1
    assert len({payload['observedAt'] for payload in sent}) == 1
    assert [arguments[1] for arguments in page_arguments] == [0, 20]
    assert all(arguments[2] == 30 for arguments in page_arguments)
    assert all(arguments[3] is observed_arguments[0]
               for arguments in page_arguments)


def test_download_sync_stops_before_final_when_a_middle_batch_fails(monkeypatch):
    rows = [{'id': number, 'userId': 1} for number in range(1, 6)]
    monkeypatch.setattr(
        telemetry.subdb,
        'get_admin_telemetry_download_upper_id',
        lambda _observed: 5,
    )
    monkeypatch.setattr(
        telemetry.subdb,
        'get_admin_telemetry_downloads',
        lambda limit, after_id, _upper, _observed: [
            row for row in rows if row['id'] > after_id
        ][:limit],
    )
    attempted = []

    def fail_second(_config_value, payload):
        attempted.append(payload)
        if payload['batchIndex'] == 1:
            raise RuntimeError('network')

    monkeypatch.setattr(telemetry, '_post_json', fail_second)

    with pytest.raises(RuntimeError):
        asyncio.run(telemetry._push_download_sync(_config()))

    assert [payload['batchIndex'] for payload in attempted] == [0, 1]
    assert all(payload['final'] is False for payload in attempted)


def test_download_missing_batch_restarts_once_from_zero(monkeypatch):
    after_ids = []
    monkeypatch.setattr(
        telemetry.subdb,
        'get_admin_telemetry_download_upper_id',
        lambda _observed: 1,
    )

    def page(_limit, after_id, _upper, _observed):
        after_ids.append(after_id)
        return [{'id': 1, 'userId': 42}]

    monkeypatch.setattr(
        telemetry.subdb, 'get_admin_telemetry_downloads', page)
    attempted = []

    def miss_once(_config_value, payload):
        attempted.append(payload)
        if len(attempted) == 1:
            raise telemetry.MissingBatchError('missing')

    monkeypatch.setattr(telemetry, '_post_json', miss_once)

    asyncio.run(telemetry._push_download_sync(_config()))

    assert after_ids == [0, 0]
    assert [payload['batchIndex'] for payload in attempted] == [0, 0]
    assert attempted[0]['syncId'] != attempted[1]['syncId']
    assert attempted[1]['final'] is True


def test_download_sync_with_exact_batch_sends_small_empty_final(monkeypatch):
    rows = [{'id': 1, 'userId': 1}, {'id': 2, 'userId': 2}]
    monkeypatch.setattr(
        telemetry.subdb,
        'get_admin_telemetry_download_upper_id',
        lambda _observed: 2,
    )
    monkeypatch.setattr(
        telemetry.subdb,
        'get_admin_telemetry_downloads',
        lambda limit, after_id, _upper, _observed: [
            row for row in rows if row['id'] > after_id
        ][:limit],
    )
    sent = []
    monkeypatch.setattr(
        telemetry, '_post_json', lambda _config_value, payload: sent.append(payload))

    asyncio.run(telemetry._push_download_sync(_config()))

    assert [len(payload['downloads']) for payload in sent] == [2, 0]
    assert [payload['final'] for payload in sent] == [False, True]
