# -*- coding: utf-8 -*-
"""Low-overhead, privacy-safe Raspberry system telemetry tests."""

from io import StringIO
from types import SimpleNamespace

import admin_telemetry as telemetry


def _route(interface='eth0'):
    return (
        'Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n'
        f'{interface} 00000000 0101A8C0 0003 0 0 100 00000000 0 0 0\n'
        'docker0 00000000 00000000 0001 0 0 5 00000000 0 0 0\n'
    )


def _devices(eth_rx, eth_tx, docker_rx=999_000_000, docker_tx=888_000_000):
    return (
        'Inter-| Receive | Transmit\n'
        ' face |bytes packets errs drop fifo frame compressed multicast|'
        'bytes packets errs drop fifo colls carrier compressed\n'
        f' eth0: {eth_rx} 0 0 0 0 0 0 0 {eth_tx} 0 0 0 0 0 0 0\n'
        f' docker0: {docker_rx} 0 0 0 0 0 0 0 {docker_tx} 0 0 0 0 0 0 0\n'
    )


def test_network_uses_only_default_route_and_first_sample_has_no_rate(
        monkeypatch):
    device_samples = iter([
        _devices(1_000_000, 2_000_000),
        _devices(2_000_000, 2_500_000),
    ])

    def fake_open(path, *_args, **_kwargs):
        if path == '/proc/net/route':
            return StringIO(_route())
        if path == '/proc/net/dev':
            return StringIO(next(device_samples))
        raise OSError(path)

    ticks = iter([100.0, 110.0])
    monkeypatch.setattr('builtins.open', fake_open)
    monkeypatch.setattr(telemetry.time, 'monotonic', lambda: next(ticks))
    telemetry._NETWORK_PREVIOUS = None

    first = telemetry._network_metrics()
    second = telemetry._network_metrics()

    assert first['networkInterfaceType'] == 'ethernet'
    assert first['networkRxMbps'] is None
    assert first['networkTxMbps'] is None
    assert first['networkRxMb'] == round(1_000_000 / (1024 ** 2), 2)
    assert second['networkRxMbps'] == 0.8
    assert second['networkTxMbps'] == 0.4
    # Huge docker counters were not included.
    assert second['networkRxMb'] < 2


def test_network_interface_change_resets_rate(monkeypatch):
    monkeypatch.setattr(
        'builtins.open',
        lambda path, *_args, **_kwargs: StringIO(
            _route('eth0') if path == '/proc/net/route'
            else _devices(2_000_000, 3_000_000)),
    )
    monkeypatch.setattr(telemetry.time, 'monotonic', lambda: 100.0)
    telemetry._NETWORK_PREVIOUS = ('wlan0', 90.0, 1, 1)

    metrics = telemetry._network_metrics()

    assert metrics['networkRxMbps'] is None
    assert metrics['networkTxMbps'] is None


def test_tool_versions_are_cached_instead_of_spawning_each_snapshot(monkeypatch):
    calls = []
    monkeypatch.setattr(telemetry.time, 'monotonic', lambda: 100.0)
    monkeypatch.setattr(
        telemetry,
        '_binary_version',
        lambda binary: (calls.append(binary) or (True, f'{binary}-1.0')),
    )
    telemetry._TOOL_STATUS_CACHE = None

    first = telemetry._tool_metrics()
    second = telemetry._tool_metrics()

    assert calls == ['ffmpeg', 'ffprobe']
    assert first == second
    assert first['ffmpegAvailable'] is True
    assert first['ffprobeAvailable'] is True
    assert 'ytDlpVersion' in first


class _Entries:
    def __enter__(self):
        return iter((object(), object(), object()))

    def __exit__(self, *_args):
        return False


def test_collect_system_metrics_exposes_details_without_identifiers(monkeypatch):
    def key_values(path):
        if path == '/proc/meminfo':
            return {
                'MemTotal': 8 * 1024 * 1024,
                'MemAvailable': 3 * 1024 * 1024,
                'SwapTotal': 2 * 1024 * 1024,
                'SwapFree': 512 * 1024,
            }
        if path == '/proc/self/status':
            return {'VmRSS': 256 * 1024, 'Threads': 7}
        return {}

    def fake_open(path, *_args, **_kwargs):
        if path == '/proc/uptime':
            return StringIO('12345.0 0.0')
        if path == '/sys/class/thermal/thermal_zone0/temp':
            return StringIO('42000')
        raise OSError(path)

    monkeypatch.setattr(telemetry, '_read_key_value_file', key_values)
    monkeypatch.setattr('builtins.open', fake_open)
    monkeypatch.setattr(
        telemetry.shutil,
        'disk_usage',
        lambda _path: SimpleNamespace(
            total=64 * 1024 ** 3,
            used=16 * 1024 ** 3,
            free=48 * 1024 ** 3,
        ),
    )
    monkeypatch.setattr(
        telemetry.os, 'getloadavg', lambda: (0.5, 0.4, 0.3),
        raising=False,
    )
    monkeypatch.setattr(telemetry.os, 'scandir', lambda _path: _Entries())
    monkeypatch.setattr(telemetry, '_cpu_percent', lambda: 12.5)
    monkeypatch.setattr(telemetry, '_static_system_metrics', lambda: {
        'cpuCores': 4,
        'deviceModel': 'Raspberry Pi 5 Model B',
        'architecture': 'aarch64',
        'kernelVersion': '6.12-test',
        'osLabel': 'Debian GNU/Linux 13',
    })
    monkeypatch.setattr(telemetry, '_network_metrics', lambda: {
        'networkRxMb': 10.0,
        'networkTxMb': 5.0,
        'networkRxMbps': 1.0,
        'networkTxMbps': 0.5,
        'networkInterfaceType': 'ethernet',
    })
    monkeypatch.setattr(telemetry, '_tool_metrics', lambda: {
        'ytDlpVersion': '2026.8.4',
        'ffmpegAvailable': True,
        'ffmpegVersion': '7.1',
        'ffprobeAvailable': True,
        'ffprobeVersion': '7.1',
    })
    monkeypatch.setattr(telemetry, '_temporary_metrics', lambda: {
        'temporaryJobCount': 2,
        'temporaryFileCount': 3,
        'temporaryBytesMb': 12.0,
    })

    metrics = telemetry.collect_system_metrics()

    assert metrics['cpuCores'] == 4
    assert metrics['memoryAvailableMb'] == 3072.0
    assert metrics['swapUsedMb'] == 1536.0
    assert metrics['diskTotalGb'] == 64.0
    assert metrics['diskUsedGb'] == 16.0
    assert metrics['processMemoryMb'] == 256.0
    assert metrics['processThreads'] == 7
    assert metrics['processFds'] == 3
    assert metrics['networkInterfaceType'] == 'ethernet'
    assert metrics['temporaryJobCount'] == 2
    assert metrics['botUptimeSeconds'] >= 0
    assert not ({'hostname', 'ip', 'mac', 'path'} & set(metrics))
