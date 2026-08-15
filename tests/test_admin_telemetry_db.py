# -*- coding: utf-8 -*-
"""Prove dashboard database reads are grouped rather than N+1."""

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import subscription_db as subdb


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


def test_summary_uses_grouped_queries_and_never_selects_url():
    now = datetime(2026, 8, 15, 12, 0, 0)
    cursor = FakeCursor([
        (624, 5, 1196, 4, 21, 1164, 34, 1, 13.79, 0, 29),
        [(9, 42, 'Ali', 'ali', 'Title', '1080', 'video',
          'youtube', 12.5, False, now)],
        [(42, 'Ali', 'ali', 26, 24)],
        [(42, 'Ali', 'ali', now, now, 2)],
    ])

    with patch.object(subdb, 'db_cursor', _fake_db(cursor)):
        result = subdb.get_admin_telemetry_summary()

    assert len(cursor.queries) == 4
    assert 'h.url' not in cursor.queries[1][0].lower()
    assert 'GROUP BY' in cursor.queries[2][0]
    # The alert groups by URL inside PostgreSQL but never SELECTs/returns it.
    assert cursor.queries[3][0].split('FROM download_history')[0].lower().find('h.url') == -1
    assert 'GROUP BY h.user_id, h.url' in cursor.queries[3][0]
    assert result['membersTotal'] == 624
    assert result['recentDownloads'][0]['title'] == 'Title'
    assert result['topReferrers'][0]['invitesIncomplete'] == 2
    assert result['reviewItems'][0]['userId'] == 42


def test_member_batch_is_one_query_with_grouped_referrals():
    now = datetime(2026, 8, 15, 12, 0, 0)
    cursor = FakeCursor([[
        (42, 'ali', 'Ali', 'ar', 'male', True, None,
         26, 24, 2, 3, 100, now),
        (43, None, 'Sara', 'en', 'female', False, None,
         0, 0, 0, 1, 5, now),
    ]])

    with patch.object(subdb, 'db_cursor', _fake_db(cursor)):
        result = subdb.get_admin_telemetry_members(limit=100, offset=0)

    assert len(cursor.queries) == 1
    sql = cursor.queries[0][0]
    assert 'WITH referral_stats AS' in sql
    assert 'GROUP BY r.referrer_user_id' in sql
    assert len(result) == 2
    assert result[0]['invitesTotal'] == 26
    assert result[1]['downloadsToday'] == 1
