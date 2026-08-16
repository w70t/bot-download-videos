# -*- coding: utf-8 -*-
"""Tests for the outbound, privacy-limited admin telemetry publisher."""

import asyncio
from datetime import datetime
import hashlib
import hmac
import json

import pytest

import admin_telemetry as telemetry


SECRET_HEX = 'ab' * 32


def _env(**overrides):
    values = {
        'ADMIN_TELEMETRY_ENABLED': '1',
        'ADMIN_TELEMETRY_URL': 'https://example.com/api/ingest',
        'ADMIN_TELEMETRY_SECRET_HEX': SECRET_HEX,
    }
    values.update(overrides)
    return values


def test_config_is_explicitly_feature_flagged_and_fails_closed():
    assert telemetry.telemetry_config({}) is None
    assert telemetry.telemetry_config(_env(ADMIN_TELEMETRY_ENABLED='0')) is None
    assert telemetry.telemetry_config(_env(ADMIN_TELEMETRY_URL='http://example.com')) is None
    assert telemetry.telemetry_config(_env(ADMIN_TELEMETRY_URL='https://user@example.com/x')) is None
    assert telemetry.telemetry_config(_env(ADMIN_TELEMETRY_URL='https://example.com/x?q=1')) is None
    assert telemetry.telemetry_config(_env(ADMIN_TELEMETRY_SECRET_HEX='bad')) is None


def test_config_accepts_dedicated_32_byte_secret_and_bounds_intervals():
    defaults = telemetry.telemetry_config(_env())
    assert defaults.download_sync_seconds == 21600
    assert defaults.download_batch_size == 40

    config = telemetry.telemetry_config(_env(
        ADMIN_TELEMETRY_INTERVAL_SECONDS='1',
        ADMIN_TELEMETRY_MEMBER_SYNC_SECONDS='999999',
        ADMIN_TELEMETRY_MEMBER_BATCH_SIZE='999',
        ADMIN_TELEMETRY_DOWNLOAD_SYNC_SECONDS='1',
        ADMIN_TELEMETRY_DOWNLOAD_BATCH_SIZE='999',
    ))

    assert config.endpoint == 'https://example.com/api/ingest'
    assert config.secret == bytes.fromhex(SECRET_HEX)
    assert config.interval_seconds == 10
    assert config.member_sync_seconds == 86400
    assert config.member_batch_size == 40
    assert config.download_sync_seconds == 3600
    assert config.download_batch_size == 40


def test_payload_signature_covers_timestamp_dot_exact_raw_body():
    config = telemetry.telemetry_config(_env())
    raw, headers = telemetry.encode_signed_payload(
        {'type': 'snapshot', 'observedAt': 123, 'arabic': 'حقيقي'},
        config,
        timestamp=1700000000,
    )

    expected = hmac.new(
        bytes.fromhex(SECRET_HEX),
        b'1700000000.' + raw,
        hashlib.sha256,
    ).hexdigest()
    assert headers['X-Bot7-Timestamp'] == '1700000000'
    assert headers['X-Bot7-Signature'] == expected
    assert json.loads(raw)['arabic'] == 'حقيقي'


def test_registry_tracks_only_sanitized_operational_fields():
    registry = telemetry.TelemetryRegistry()
    job_id = registry.begin(
        user_id=42,
        first_name='Ali https://private.example/video',
        username='user',
        platform='youtube',
        kind='video',
        quality='1080',
    )
    registry.update(
        job_id,
        phase='downloading',
        progress=150,
        speed_mbps=3.125,
        eta_seconds=9,
        size_mb=18.6,
        title='Title https://private.example/watch',
    )

    active = registry.active()
    encoded = json.dumps(active)
    assert len(active) == 1
    assert active[0]['progress'] == 100.0
    assert active[0]['phase'] == 'downloading'
    assert 'https://' not in encoded
    assert 'url' not in {key.lower() for key in active[0]}

    registry.finish(job_id, 'success')
    assert registry.active() == []
    runtime = registry.runtime()
    assert runtime['attempts'] == 1
    assert runtime['success'] == 1
    assert runtime['successRate'] == 100.0


def test_build_snapshot_uses_real_grouped_data_without_source_links(monkeypatch):
    sample = {
        'membersTotal': 624,
        'membersActive24h': 7,
        'membersActive7d': 31,
        'membersActive30d': 100,
        'membersInactive30d': 524,
        'subscribers': 5,
        'downloadsTotal': 1196,
        'downloadsToday': 4,
        'departuresToday': 2,
        'departures7d': 5,
        'departures30d': 8,
        'departureReasons30d': [
            {'reason': 'blocked', 'count': 3},
            {'reason': 'deactivated', 'count': 4},
            {'reason': 'unreachable', 'count': 1},
        ],
        '_databaseSizeBytes': 10 * 1024 * 1024,
        'lastReachabilityCheckAt': datetime(2026, 8, 15, 9, 0, 0),
        'recentDownloads': [{
            'id': 9,
            'userId': 42,
            'firstName': 'Ali',
            'username': 'ali',
            'title': 'A title',
            'quality': '1080',
            'kind': 'video',
            'platform': 'youtube',
            'sizeMb': 12.5,
            'fromCache': False,
            'createdAt': datetime(2026, 8, 15, 12, 0, 0),
            'url': 'https://must-not-leak.example',
        }],
        'topReferrers': [{
            'userId': 42,
            'firstName': 'Ali',
            'username': 'ali',
            'invitesTotal': 26,
            'invitesCurrent': 24,
            'invitesIncomplete': 2,
        }],
        'reviewItems': [{
            'userId': 42,
            'firstName': 'Ali',
            'username': 'ali',
            'audioAt': datetime(2026, 8, 15, 10, 0, 0),
            'videoAt': datetime(2026, 8, 15, 11, 0, 0),
            'occurrences': 2,
        }],
    }
    monkeypatch.setattr(
        telemetry.subdb, 'get_admin_telemetry_summary', lambda: dict(sample))
    monkeypatch.setattr(
        telemetry.subdb, 'get_setting', lambda _key, _default: '1')
    monkeypatch.setattr(
        telemetry, 'collect_system_metrics', lambda: {'temperatureC': 40.0})
    monkeypatch.setattr(telemetry, 'registry', telemetry.TelemetryRegistry())

    class Queue:
        user_queues = {}
        processing_users = set()

    snapshot = telemetry.build_snapshot(Queue())
    encoded = json.dumps(snapshot)

    assert snapshot['summary']['membersTotal'] == 624
    assert snapshot['summary']['membersActive24h'] == 7
    assert snapshot['summary']['lastReachabilityCheckAt'] is not None
    assert snapshot['system']['databaseSizeMb'] == 10.0
    assert snapshot['system']['databaseLatencyMs'] >= 0
    assert '_databaseSizeBytes' not in snapshot['summary']
    assert snapshot['recentDownloads'][0]['title'] == 'A title'
    assert snapshot['topReferrers'][0]['invitesTotal'] == 26
    assert snapshot['reviewItems'][0]['type'] == 'audio_then_video'
    assert 'must-not-leak' not in encoded
    assert 'url' not in snapshot['recentDownloads'][0]


def test_member_normalisation_includes_activity_timestamp_only():
    activity = datetime(2026, 8, 15, 12, 30, 0)
    member = telemetry._normalise_member({
        'userId': 42,
        'firstName': 'Ali',
        'lastActivityAt': activity,
    })

    assert member['lastActivityAt'] == int(activity.timestamp() * 1000)
    assert 'activityState' not in member
    assert 'reachabilityCheckedAt' not in member


def test_member_batches_are_sequential_and_final_only_after_prior_success(monkeypatch):
    config = telemetry.TelemetryConfig(
        endpoint='https://example.com/api/ingest',
        secret=bytes.fromhex(SECRET_HEX),
        member_batch_size=2,
    )
    rows = [
        {'userId': 1, 'firstName': 'One'},
        {'userId': 2, 'firstName': 'Two'},
        {'userId': 3, 'firstName': 'Three'},
    ]
    monkeypatch.setattr(
        telemetry.subdb,
        'get_admin_telemetry_members',
        lambda limit, offset: rows[offset:offset + limit],
    )
    sent = []
    monkeypatch.setattr(
        telemetry, '_post_json', lambda _config, payload: sent.append(payload))

    asyncio.run(telemetry._push_member_sync(config))

    assert [payload['batchIndex'] for payload in sent] == [0, 1]
    assert [payload['final'] for payload in sent] == [False, True]
    assert len({payload['syncId'] for payload in sent}) == 1
    assert len({payload['observedAt'] for payload in sent}) == 1
    assert [len(payload['members']) for payload in sent] == [2, 1]


def test_member_sync_never_sends_final_after_failed_prior_batch(monkeypatch):
    config = telemetry.TelemetryConfig(
        endpoint='https://example.com/api/ingest',
        secret=bytes.fromhex(SECRET_HEX),
        member_batch_size=2,
    )
    rows = [{'userId': number} for number in range(1, 6)]
    monkeypatch.setattr(
        telemetry.subdb,
        'get_admin_telemetry_members',
        lambda limit, offset: rows[offset:offset + limit],
    )
    attempted = []

    def fail_second(_config, payload):
        attempted.append(payload)
        if payload['batchIndex'] == 1:
            raise RuntimeError('network')

    monkeypatch.setattr(telemetry, '_post_json', fail_second)

    with pytest.raises(RuntimeError):
        asyncio.run(telemetry._push_member_sync(config))

    assert [payload['batchIndex'] for payload in attempted] == [0, 1]
    assert all(payload['final'] is False for payload in attempted)


def test_missing_batch_restarts_with_new_sync_id_from_zero(monkeypatch):
    config = telemetry.TelemetryConfig(
        endpoint='https://example.com/api/ingest',
        secret=bytes.fromhex(SECRET_HEX),
        member_batch_size=2,
    )
    rows = [{'userId': 1}]
    monkeypatch.setattr(
        telemetry.subdb,
        'get_admin_telemetry_members',
        lambda limit, offset: rows[offset:offset + limit],
    )
    attempted = []

    def miss_once(_config, payload):
        attempted.append(payload)
        if len(attempted) == 1:
            raise telemetry.MissingBatchError('missing')

    monkeypatch.setattr(telemetry, '_post_json', miss_once)

    asyncio.run(telemetry._push_member_sync(config))

    assert [payload['batchIndex'] for payload in attempted] == [0, 0]
    assert attempted[0]['syncId'] != attempted[1]['syncId']
    assert attempted[1]['final'] is True
