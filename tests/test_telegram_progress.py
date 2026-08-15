import asyncio
import threading

from telegram_progress import (
    CoalescingMessageEditor, DownloadProgressState, progress_values,
)
from translations import TRANSLATIONS, t


def test_progress_values_handles_unknown_and_clamps_percentage():
    unknown = progress_values(1024, None, 512)
    assert unknown['percentage'] is None
    assert unknown['eta_seconds'] is None

    estimated = progress_values(120, 100, 10)
    assert estimated['percentage'] == 100.0
    assert estimated['eta_seconds'] == 0

    invalid = progress_values('bad', -1, 'bad')
    assert invalid['current_bytes'] == 0
    assert invalid['total_bytes'] == 0
    assert invalid['speed_bps'] == 0


def test_progress_states_exist_in_both_languages_and_format_safely():
    keys = {
        'start_downloading', 'downloading_unknown', 'retrying_source',
        'download_complete', 'upload_complete', 'retrying_upload',
    }
    for language in ('ar', 'en'):
        assert keys <= TRANSLATIONS[language].keys()
        assert '1.5' in t(
            'downloading_unknown', language,
            current_mb='1.5', speed_mb='0.7')
        assert '100%' in t('download_complete', language)


def test_multistream_download_progress_never_reverses_or_finishes_early():
    state = DownloadProgressState()
    trace = [
        {'filename': 'video.part', 'downloaded_bytes': 50,
         'total_bytes': 100, 'speed': 10},
        {'filename': 'video.part', 'downloaded_bytes': 100,
         'total_bytes': 100, 'speed': 10},
        {'filename': 'audio.part', 'downloaded_bytes': 1,
         'total_bytes': 100, 'speed': 10},
        {'filename': 'audio.part', 'downloaded_bytes': 100,
         'total_bytes': 100, 'speed': 10},
    ]
    percentages = [state.update(item, generation=1)['percentage']
                   for item in trace]

    assert percentages == sorted(percentages)
    assert percentages[-1] == 99.0
    assert all(value < 100 for value in percentages)

    # محاولة مصدر جديدة تبدأ عدادها الخاص؛ callbacks القديمة تُحجب بالناقل.
    restarted = state.update(trace[0], generation=2)['percentage']
    assert restarted == 47.5
    assert state.update(trace[-1], generation=1) is None
    continued = state.update(
        {'filename': 'video.part', 'downloaded_bytes': 60,
         'total_bytes': 100, 'speed': 10},
        generation=2,
    )['percentage']
    assert continued == 57.0


def test_burst_keeps_latest_value_and_never_overlaps_edits():
    async def scenario():
        edits = []
        active = 0
        max_active = 0
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def edit(text):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            edits.append(text)
            if len(edits) == 1:
                first_started.set()
                await release_first.wait()
            active -= 1

        loop = asyncio.get_running_loop()
        reporter = CoalescingMessageEditor(
            edit, loop, min_interval=0.01, finish_timeout=1)
        reporter.publish('1%')
        await asyncio.wait_for(first_started.wait(), 1)

        def burst():
            for value in range(2, 100):
                reporter.publish(f'{value}%')

        thread = threading.Thread(target=burst)
        thread.start()
        thread.join()
        release_first.set()
        await asyncio.sleep(0.08)
        assert await reporter.finish('100%')

        assert max_active == 1
        assert edits[0] == '1%'
        assert '99%' in edits
        assert edits[-1] == '100%'
        assert len(edits) <= 3
        assert reporter.is_idle

    asyncio.run(scenario())


def test_finish_interrupts_throttle_and_forces_final_state():
    async def scenario():
        edits = []

        async def edit(text):
            edits.append(text)

        loop = asyncio.get_running_loop()
        reporter = CoalescingMessageEditor(
            edit, loop, min_interval=30, finish_timeout=1)
        reporter.publish('0.2%')
        await asyncio.sleep(0.01)
        reporter.publish('80%')
        assert await reporter.finish('100%')

        assert edits == ['0.2%', '100%']
        assert reporter.is_idle

    asyncio.run(scenario())


def test_external_edit_seeds_throttle_before_first_progress_update():
    async def scenario():
        edits = []

        async def edit(text):
            edits.append(text)

        loop = asyncio.get_running_loop()
        reporter = CoalescingMessageEditor(
            edit, loop, min_interval=0.05, finish_timeout=1)
        reporter.note_external_edit('connecting')
        reporter.publish('1%')
        await asyncio.sleep(0.01)
        assert edits == []
        await asyncio.sleep(0.06)
        assert edits == ['1%']
        await reporter.close()

    asyncio.run(scenario())


def test_old_attempt_callbacks_are_rejected():
    async def scenario():
        edits = []

        async def edit(text):
            edits.append(text)

        loop = asyncio.get_running_loop()
        reporter = CoalescingMessageEditor(
            edit, loop, min_interval=0, finish_timeout=1)
        first = reporter.new_generation()
        assert reporter.publish('old 50%', generation=first)
        second = reporter.new_generation()
        assert not reporter.publish('old 90%', generation=first)
        assert reporter.publish('retrying', generation=second)
        await asyncio.sleep(0.02)
        assert await reporter.finish('100%')

        assert 'old 90%' not in edits
        assert edits[-2:] == ['retrying', '100%']

    asyncio.run(scenario())


def test_edit_errors_are_consumed_and_do_not_escape_finish():
    async def scenario():
        reported = []
        loop_errors = []

        async def edit(_text):
            raise RuntimeError('network edit failed')

        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(
            lambda _loop, context: loop_errors.append(context))
        try:
            reporter = CoalescingMessageEditor(
                edit, loop, min_interval=0, finish_timeout=1,
                on_error=lambda error: reported.append(type(error).__name__),
            )
            reporter.publish('10%')
            await asyncio.sleep(0.02)
            assert not await reporter.finish('100%')
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(old_handler)

        assert reported == ['RuntimeError', 'RuntimeError']
        assert loop_errors == []

    asyncio.run(scenario())


def test_message_not_modified_is_a_successful_finish():
    class MessageNotModified(Exception):
        pass

    async def scenario():
        async def edit(_text):
            raise MessageNotModified()

        loop = asyncio.get_running_loop()
        reporter = CoalescingMessageEditor(
            edit, loop, min_interval=0, finish_timeout=1)
        assert await reporter.finish('100%')

    asyncio.run(scenario())


def test_flood_wait_retries_latest_text_once_allowed():
    class FloodWait(Exception):
        def __init__(self, value):
            self.value = value

    async def scenario():
        edits = []
        attempts = 0

        async def edit(text):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise FloodWait(0.02)
            edits.append(text)

        loop = asyncio.get_running_loop()
        reporter = CoalescingMessageEditor(
            edit, loop, min_interval=0, finish_timeout=1)
        reporter.publish('10%')
        await asyncio.sleep(0.005)
        reporter.publish('80%')
        await asyncio.sleep(0.05)
        assert await reporter.finish('100%')

        assert edits == ['80%', '100%']
        assert attempts == 3

    asyncio.run(scenario())


def test_close_is_idempotent_and_rejects_late_thread_callback():
    async def scenario():
        edits = []

        async def edit(text):
            edits.append(text)

        loop = asyncio.get_running_loop()
        reporter = CoalescingMessageEditor(edit, loop, min_interval=0)
        await reporter.close()
        await reporter.close()

        result = []
        thread = threading.Thread(
            target=lambda: result.append(reporter.publish('late')))
        thread.start()
        thread.join()
        await asyncio.sleep(0)

        assert result == [False]
        assert edits == []
        assert reporter.is_idle

    asyncio.run(scenario())


def test_close_is_bounded_even_if_edit_suppresses_cancellation():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        reported = []

        async def stubborn_edit(_text):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()

        loop = asyncio.get_running_loop()
        reporter = CoalescingMessageEditor(
            stubborn_edit, loop, min_interval=0, close_timeout=0.03,
            on_error=lambda error: reported.append(type(error).__name__))
        reporter.publish('10%')
        await asyncio.wait_for(started.wait(), 1)

        before = loop.time()
        await reporter.close()
        elapsed = loop.time() - before
        assert elapsed < 0.2
        assert reported == []
        assert reporter.is_idle

        release.set()
        await asyncio.sleep(0.02)
        assert reporter.is_idle

    asyncio.run(scenario())
