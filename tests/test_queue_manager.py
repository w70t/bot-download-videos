# -*- coding: utf-8 -*-
"""اختبارات مدير الطوابير (queue_manager)."""

import asyncio

from queue_manager import DownloadQueueManager, DownloadTask


def _task(url='https://example.com/v', user_id=1):
    return DownloadTask(url=url, message=None, user_id=user_id)


def test_rate_limiting():
    qm = DownloadQueueManager(cooldown_seconds=10)
    limited, remaining = qm.is_rate_limited(1)
    assert not limited

    qm.mark_request(1)
    limited, remaining = qm.is_rate_limited(1)
    assert limited
    assert 0 < remaining <= 10

    # مستخدم آخر غير متأثر
    assert not qm.is_rate_limited(2)[0]


def test_rate_limit_expires():
    qm = DownloadQueueManager(cooldown_seconds=0)
    qm.mark_request(1)
    assert not qm.is_rate_limited(1)[0]


def test_queue_processes_tasks_in_order():
    async def run():
        qm = DownloadQueueManager(cooldown_seconds=0)
        processed = []

        async def process(task):
            processed.append(task.url)

        await qm.add_to_queue(1, _task(url='a'), process)
        await qm.add_to_queue(1, _task(url='b'), process)
        # انتظر انتهاء معالج الطابور (يتوقف بعد ثانية من فراغ الطابور)
        for _ in range(60):
            await asyncio.sleep(0.05)
            if not qm.processor_tasks.get(1) and not qm.get_queue_size(1):
                break
        return processed

    assert asyncio.run(run()) == ['a', 'b']


def test_processing_error_does_not_kill_queue():
    async def run():
        qm = DownloadQueueManager(cooldown_seconds=0)
        processed = []

        async def process(task):
            if task.url == 'bad':
                raise RuntimeError('boom')
            processed.append(task.url)

        await qm.add_to_queue(1, _task(url='bad'), process)
        await qm.add_to_queue(1, _task(url='good'), process)
        for _ in range(60):
            await asyncio.sleep(0.05)
            if not qm.processor_tasks.get(1) and not qm.get_queue_size(1):
                break
        return processed

    assert asyncio.run(run()) == ['good']


def test_clear_user_queue():
    async def run():
        qm = DownloadQueueManager(cooldown_seconds=0)
        started = asyncio.Event()
        release = asyncio.Event()

        async def process(task):
            started.set()
            await release.wait()

        await qm.add_to_queue(1, _task(url='a'), process)
        await asyncio.wait_for(started.wait(), timeout=5)
        # المهمة الأولى قيد المعالجة؛ أضف اثنتين وامسح الطابور
        await qm.add_to_queue(1, _task(url='b'), process)
        await qm.add_to_queue(1, _task(url='c'), process)
        await qm.clear_user_queue(1)
        size = qm.get_queue_size(1)
        release.set()
        await asyncio.sleep(0.1)
        return size

    assert asyncio.run(run()) == 0
