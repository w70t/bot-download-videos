# -*- coding: utf-8 -*-
"""Privacy-limited outbound telemetry for the admin Mini App.

The Raspberry Pi never opens an inbound port.  When explicitly enabled, this
module sends small JSON snapshots over HTTPS and authenticates the exact body
with a dedicated HMAC secret.  It deliberately excludes source URLs, local
paths, Telegram file identifiers, cookies, tokens, captions and tracebacks.

Telemetry is fail-open for the downloader: a dashboard/network/database error
is logged generically and never interrupts a user's download.
"""

from dataclasses import dataclass
from datetime import date, datetime
import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import shutil
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)
import uuid

import subscription_db as subdb


logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MAX_BODY_BYTES = 256 * 1024
_PROCESS_STARTED_AT_MS = int(time.time() * 1000)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"(?<!\w)\d{6,12}:[A-Za-z0-9_-]{20,}(?!\w)")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


@dataclass(frozen=True)
class TelemetryConfig:
    endpoint: str
    secret: bytes
    interval_seconds: int = 20
    member_sync_seconds: int = 3600
    member_batch_size: int = 40
    timeout_seconds: float = 5.0


def _bounded_int(raw, default, minimum, maximum):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def telemetry_config(environ=None):
    """Return validated config, or ``None`` unless explicitly enabled.

    A dedicated 32-byte hex secret is required.  The Telegram bot token is not
    accepted or derived here, keeping transport authentication independent.
    """
    env = os.environ if environ is None else environ
    if str(env.get('ADMIN_TELEMETRY_ENABLED', '0')).strip().lower() \
            not in {'1', 'true', 'yes', 'on'}:
        return None

    endpoint = str(env.get('ADMIN_TELEMETRY_URL', '')).strip()
    try:
        parsed = urlsplit(endpoint)
        # Accessing .port also validates the numeric port range.
        _ = parsed.port
    except (TypeError, ValueError):
        return None
    if (parsed.scheme.lower() != 'https' or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        return None

    secret_hex = str(env.get('ADMIN_TELEMETRY_SECRET_HEX', '')).strip()
    if not re.fullmatch(r'[0-9a-fA-F]{64}', secret_hex):
        return None
    secret = bytes.fromhex(secret_hex)

    return TelemetryConfig(
        endpoint=endpoint,
        secret=secret,
        interval_seconds=_bounded_int(
            env.get('ADMIN_TELEMETRY_INTERVAL_SECONDS'), 20, 10, 300),
        member_sync_seconds=_bounded_int(
            env.get('ADMIN_TELEMETRY_MEMBER_SYNC_SECONDS'), 3600, 300, 86400),
        member_batch_size=_bounded_int(
            env.get('ADMIN_TELEMETRY_MEMBER_BATCH_SIZE'), 40, 1, 40),
        timeout_seconds=float(_bounded_int(
            env.get('ADMIN_TELEMETRY_TIMEOUT_SECONDS'), 5, 2, 15)),
    )


def is_configured(environ=None):
    return telemetry_config(environ) is not None


def _safe_text(value, limit=160):
    if value is None:
        return None
    text = _CONTROL_RE.sub(' ', str(value))
    text = _URL_RE.sub('[link]', text)
    text = _TOKEN_RE.sub('[token]', text)
    text = ' '.join(text.split()).strip()
    return text[:limit] or None


def _safe_number(value, minimum=0.0, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


class TelemetryRegistry:
    """Thread-safe, process-local active-job registry and runtime counters."""

    _PHASES = {
        'checking_cache', 'downloading', 'processing', 'uploading',
        'finalizing',
    }
    _OUTCOMES = {'success', 'failed', 'blocked', 'cancelled'}

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs = {}
        self._started_at_ms = int(time.time() * 1000)
        self._counters = {
            'attempts': 0,
            'success': 0,
            'failed': 0,
            'blocked': 0,
            'cancelled': 0,
        }

    def begin(self, *, user_id, first_name=None, username=None,
              platform=None, kind=None, quality=None):
        job_id = uuid.uuid4().hex[:16]
        now_ms = int(time.time() * 1000)
        job = {
            'id': job_id,
            'userId': str(user_id),
            'firstName': _safe_text(first_name, 80),
            'username': _safe_text(username, 64),
            'platform': _safe_text(platform, 32),
            'kind': _safe_text(kind, 16),
            'quality': _safe_text(quality, 24),
            'title': None,
            'phase': 'checking_cache',
            'progress': 0.0,
            'etaSeconds': None,
            'speedMbps': None,
            'sizeMb': None,
            'startedAt': now_ms,
            'updatedAt': now_ms,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._counters['attempts'] += 1
        return job_id

    def update(self, job_id, *, phase=None, progress=None, eta_seconds=None,
               speed_mbps=None, size_mb=None, title=None):
        if not job_id:
            return
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if phase in self._PHASES:
                job['phase'] = phase
            if progress is not None:
                safe = _safe_number(progress, 0.0, 100.0)
                if safe is not None:
                    job['progress'] = round(safe, 1)
            if eta_seconds is not None:
                safe = _safe_number(eta_seconds, 0.0, 7 * 24 * 3600)
                job['etaSeconds'] = int(safe) if safe is not None else None
            if speed_mbps is not None:
                safe = _safe_number(speed_mbps, 0.0, 100000.0)
                job['speedMbps'] = round(safe, 2) if safe is not None else None
            if size_mb is not None:
                safe = _safe_number(size_mb, 0.0, 1024 * 1024.0)
                job['sizeMb'] = round(safe, 2) if safe is not None else None
            if title is not None:
                job['title'] = _safe_text(title, 160)
            job['updatedAt'] = int(time.time() * 1000)

    def finish(self, job_id, outcome='cancelled'):
        if not job_id:
            return
        outcome = outcome if outcome in self._OUTCOMES else 'cancelled'
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is not None:
                self._counters[outcome] += 1

    def active(self):
        with self._lock:
            jobs = [dict(job) for job in self._jobs.values()]
        return sorted(jobs, key=lambda job: job['startedAt'])

    def runtime(self):
        with self._lock:
            counters = dict(self._counters)
        completed = counters['success'] + counters['failed']
        counters['completedForRate'] = completed
        counters['successRate'] = (
            round(counters['success'] * 100.0 / completed, 1)
            if completed else None
        )
        counters['sinceStartedAt'] = self._started_at_ms
        return counters


registry = TelemetryRegistry()


def begin_download(**fields):
    try:
        return registry.begin(**fields)
    except Exception as exc:
        logger.warning('Admin telemetry registry begin failed (%s)',
                       type(exc).__name__)
        return None


def update_job(job_id, **fields):
    try:
        registry.update(job_id, **fields)
    except Exception as exc:
        logger.warning('Admin telemetry registry update failed (%s)',
                       type(exc).__name__)


def finish_job(job_id, outcome='cancelled'):
    try:
        registry.finish(job_id, outcome)
    except Exception as exc:
        logger.warning('Admin telemetry registry finish failed (%s)',
                       type(exc).__name__)


_CPU_LOCK = threading.Lock()
_CPU_PREVIOUS = None


def _read_key_value_file(path):
    values = {}
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                if ':' not in line:
                    continue
                key, raw = line.split(':', 1)
                token = raw.strip().split()[0] if raw.strip() else ''
                try:
                    values[key] = float(token)
                except ValueError:
                    continue
    except OSError:
        pass
    return values


def _cpu_percent():
    global _CPU_PREVIOUS
    try:
        with open('/proc/stat', 'r', encoding='ascii') as handle:
            parts = handle.readline().split()
        if not parts or parts[0] != 'cpu':
            return None
        ticks = [int(value) for value in parts[1:]]
        total = sum(ticks)
        idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    except (OSError, ValueError, IndexError):
        return None

    with _CPU_LOCK:
        previous = _CPU_PREVIOUS
        _CPU_PREVIOUS = (total, idle)
    if not previous:
        return None
    total_delta = total - previous[0]
    idle_delta = idle - previous[1]
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0,
                              (total_delta - idle_delta) * 100.0 / total_delta)), 1)


def collect_system_metrics():
    """Collect small Linux/Pi health metrics without third-party packages."""
    mem = _read_key_value_file('/proc/meminfo')
    total_mb = mem.get('MemTotal', 0.0) / 1024.0
    available_mb = mem.get('MemAvailable', mem.get('MemFree', 0.0)) / 1024.0
    used_mb = max(0.0, total_mb - available_mb)

    try:
        disk = shutil.disk_usage('/')
        disk_total = float(disk.total)
        disk_used_percent = (disk.used * 100.0 / disk_total) if disk_total else 0.0
        disk_free_gb = disk.free / (1024.0 ** 3)
    except OSError:
        disk_used_percent = None
        disk_free_gb = None

    temperature = None
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r', encoding='ascii') as handle:
            temperature = float(handle.read().strip()) / 1000.0
    except (OSError, ValueError):
        pass

    uptime = None
    try:
        with open('/proc/uptime', 'r', encoding='ascii') as handle:
            uptime = float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        pass

    process = _read_key_value_file('/proc/self/status')
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = None

    return {
        'cpuPercent': _cpu_percent(),
        'memoryUsedMb': round(used_mb, 1) if total_mb else None,
        'memoryTotalMb': round(total_mb, 1) if total_mb else None,
        'memoryPercent': round(used_mb * 100.0 / total_mb, 1) if total_mb else None,
        'diskUsedPercent': round(disk_used_percent, 1)
        if disk_used_percent is not None else None,
        'diskFreeGb': round(disk_free_gb, 2) if disk_free_gb is not None else None,
        'temperatureC': round(temperature, 1) if temperature is not None else None,
        'uptimeSeconds': int(uptime) if uptime is not None else None,
        'processMemoryMb': round(process.get('VmRSS', 0.0) / 1024.0, 1)
        if process.get('VmRSS') is not None else None,
        'load1': round(load1, 2) if load1 is not None else None,
        'load5': round(load5, 2) if load5 is not None else None,
        'load15': round(load15, 2) if load15 is not None else None,
    }


def _epoch_ms(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Database timestamps should not be numeric, but keep already-ms values.
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time()).timestamp() * 1000)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _normalise_recent(row):
    return {
        'id': str(row.get('id')),
        'userId': str(row.get('userId')),
        'firstName': _safe_text(row.get('firstName'), 80),
        'username': _safe_text(row.get('username'), 64),
        'title': _safe_text(row.get('title'), 160),
        'quality': _safe_text(row.get('quality'), 24),
        'kind': _safe_text(row.get('kind'), 16),
        'platform': _safe_text(row.get('platform'), 32),
        'sizeMb': round(float(row['sizeMb']), 2)
        if row.get('sizeMb') is not None else None,
        'fromCache': bool(row.get('fromCache')),
        'createdAt': _epoch_ms(row.get('createdAt')),
    }


def _normalise_referrer(row):
    return {
        'userId': str(row.get('userId')),
        'firstName': _safe_text(row.get('firstName'), 80),
        'username': _safe_text(row.get('username'), 64),
        'invitesTotal': int(row.get('invitesTotal') or 0),
        'invitesCurrent': int(row.get('invitesCurrent') or 0),
        'invitesIncomplete': int(row.get('invitesIncomplete') or 0),
    }


def _normalise_review_item(row):
    audio_at = _epoch_ms(row.get('audioAt'))
    video_at = _epoch_ms(row.get('videoAt'))
    user_id = str(row.get('userId'))
    return {
        # Stable enough for UI keys without deriving or exposing a URL hash.
        'id': f'audio-video-{user_id}-{audio_at or 0}',
        'type': 'audio_then_video',
        'userId': user_id,
        'firstName': _safe_text(row.get('firstName'), 80),
        'username': _safe_text(row.get('username'), 64),
        'audioAt': audio_at,
        'videoAt': video_at,
        'occurrences': int(row.get('occurrences') or 0),
    }


def _queue_metrics(queue_manager):
    try:
        queued = sum(queue.qsize() for queue in queue_manager.user_queues.values())
    except (AttributeError, RuntimeError):
        queued = 0
    try:
        processing_users = {str(user_id) for user_id in queue_manager.processing_users}
    except (AttributeError, RuntimeError):
        processing_users = set()
    return queued, processing_users


def build_snapshot(queue_manager):
    """Build one JSON-ready snapshot from grouped DB and in-memory state."""
    observed_at = int(time.time() * 1000)
    aggregate = subdb.get_admin_telemetry_summary()
    recent = [_normalise_recent(row)
              for row in aggregate.pop('recentDownloads', [])]
    top_referrers = [_normalise_referrer(row)
                     for row in aggregate.pop('topReferrers', [])]
    review_items = [_normalise_review_item(row)
                    for row in aggregate.pop('reviewItems', [])]
    operations = registry.active()
    queued, processing_users = _queue_metrics(queue_manager)
    active_users = processing_users | {
        str(operation['userId']) for operation in operations
        if operation.get('userId') is not None
    }

    return {
        'type': 'snapshot',
        'schemaVersion': SCHEMA_VERSION,
        'observedAt': observed_at,
        'bot': {
            'online': True,
            'startedAt': _PROCESS_STARTED_AT_MS,
            'downloadsEnabled': subdb.get_setting('downloads_enabled', '1') == '1',
            'activeCount': len(active_users),
            'queuedCount': queued,
        },
        'summary': aggregate,
        'system': collect_system_metrics(),
        'operations': operations,
        'recentDownloads': recent,
        'topReferrers': top_referrers,
        'reviewItems': review_items,
        # This rate is explicitly process-local; the historical database stores
        # successful downloads only and cannot truthfully calculate failures.
        'runtime': registry.runtime(),
    }


def _normalise_member(row):
    return {
        'userId': str(row.get('userId')),
        'username': _safe_text(row.get('username'), 64),
        'firstName': _safe_text(row.get('firstName'), 80),
        'language': 'en' if row.get('language') == 'en' else 'ar',
        'gender': row.get('gender') if row.get('gender') in {'male', 'female'} else None,
        'isSubscribed': bool(row.get('isSubscribed')),
        'subscriptionEnd': _epoch_ms(row.get('subscriptionEnd')),
        'invitesTotal': int(row.get('invitesTotal') or 0),
        'invitesCurrent': int(row.get('invitesCurrent') or 0),
        'invitesIncomplete': int(row.get('invitesIncomplete') or 0),
        'downloadsToday': int(row.get('downloadsToday') or 0),
        'totalDownloads': int(row.get('totalDownloads') or 0),
        'joinedAt': _epoch_ms(row.get('joinedAt')),
    }


def _json_ready(value):
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date)):
        return _epoch_ms(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def encode_signed_payload(payload, config, timestamp=None):
    """Return canonical raw JSON and authentication headers (testable/pure)."""
    raw = json.dumps(
        _json_ready(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError('telemetry body exceeds limit')
    timestamp = str(int(time.time()) if timestamp is None else int(timestamp))
    signature = hmac.new(
        config.secret,
        timestamp.encode('ascii') + b'.' + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, {
        'Content-Type': 'application/json; charset=utf-8',
        'X-Bot7-Timestamp': timestamp,
        'X-Bot7-Signature': signature,
        'User-Agent': 'bot7-telemetry/1',
    }


class _NoRedirect(HTTPRedirectHandler):
    """Do not follow redirects, especially not an HTTPS-to-HTTP downgrade."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_HTTP_OPENER = build_opener(_NoRedirect())


class MissingBatchError(RuntimeError):
    """The receiver lost sequence state; restart a full sync from batch zero."""


def _response_json(raw):
    try:
        value = json.loads(raw.decode('utf-8'))
        return value if isinstance(value, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _post_json(config, payload):
    raw, headers = encode_signed_payload(payload, config)
    request = Request(config.endpoint, data=raw, headers=headers, method='POST')
    try:
        with _HTTP_OPENER.open(request, timeout=config.timeout_seconds) as response:
            status = getattr(response, 'status', response.getcode())
            response_data = _response_json(response.read(4096))
    except HTTPError as exc:
        response_data = _response_json(exc.read(4096))
        error_value = response_data.get('error')
        error_code = response_data.get('code') or (
            error_value.get('code') if isinstance(error_value, dict)
            else error_value
        )
        if exc.code == 409 and error_code == 'MISSING_BATCH':
            raise MissingBatchError('missing-batch') from None
        # Keep endpoint and response content out of logs/callers.
        raise RuntimeError(f'http-status-{exc.code}') from None
    if not 200 <= int(status) < 300:
        raise RuntimeError(f'http-status-{status}')
    if (response_data.get('ok') is not True
            or response_data.get('accepted') is not True):
        raise RuntimeError('invalid-telemetry-ack')


async def _push_member_sync_once(config):
    """Push one complete sequential sync, or fail before any later batch."""
    sync_id = uuid.uuid4().hex
    observed_at = int(time.time() * 1000)
    offset = 0
    batch_index = 0
    while True:
        rows = await asyncio.to_thread(
            subdb.get_admin_telemetry_members,
            config.member_batch_size,
            offset,
        )
        members = [_normalise_member(row) for row in rows]
        final = len(rows) < config.member_batch_size
        payload = {
            'type': 'members',
            'schemaVersion': SCHEMA_VERSION,
            'observedAt': observed_at,
            'syncId': sync_id,
            'batchIndex': batch_index,
            'final': final,
            'members': members,
        }
        await asyncio.to_thread(_post_json, config, payload)
        if final:
            return
        offset += len(rows)
        batch_index += 1


async def _push_member_sync(config):
    """Push members and restart once if the receiver reports missing state."""
    for attempt in range(2):
        try:
            return await _push_member_sync_once(config)
        except MissingBatchError:
            if attempt:
                raise


async def telemetry_reporter_loop(queue_manager, config=None):
    """Continuously push live state; failures never escape into the bot."""
    config = config or telemetry_config()
    if config is None:
        return

    logger.info('Admin telemetry publisher enabled (outbound HTTPS only)')
    next_member_sync = 0.0
    while True:
        cycle_started = time.monotonic()
        try:
            snapshot = await asyncio.to_thread(build_snapshot, queue_manager)
            await asyncio.to_thread(_post_json, config, snapshot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Admin telemetry snapshot failed (%s)',
                           type(exc).__name__)

        now = time.monotonic()
        if now >= next_member_sync:
            member_sync_succeeded = False
            try:
                await _push_member_sync(config)
                member_sync_succeeded = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning('Admin telemetry member sync failed (%s)',
                               type(exc).__name__)
            finally:
                retry_seconds = min(60, max(10, config.interval_seconds * 3))
                next_member_sync = time.monotonic() + (
                    config.member_sync_seconds
                    if member_sync_succeeded else retry_seconds
                )

        elapsed = time.monotonic() - cycle_started
        await asyncio.sleep(max(1.0, config.interval_seconds - elapsed))
