# -*- coding: utf-8 -*-
"""تحديث رسالة تقدم Telegram بأحدث قيمة فقط ومن دون طلبات متداخلة."""

import asyncio
import threading
from dataclasses import dataclass


@dataclass
class _PendingEdit:
    text: str
    force: bool = False
    waiter: object = None
    generation: int = 0


def progress_values(current, total=None, speed=None):
    """قيم تقدم آمنة للعرض، حتى مع total مجهول أو تقدير يتغير."""
    try:
        current = max(0.0, float(current or 0))
    except (TypeError, ValueError):
        current = 0.0
    try:
        total = max(0.0, float(total or 0))
    except (TypeError, ValueError):
        total = 0.0
    try:
        speed = max(0.0, float(speed or 0))
    except (TypeError, ValueError):
        speed = 0.0

    percentage = None
    eta = None
    if total > 0:
        percentage = min(100.0, max(0.0, current * 100.0 / total))
        if speed > 0:
            eta = max(0, int(max(0.0, total - current) / speed))
    return {
        'current_bytes': current,
        'total_bytes': total,
        'speed_bps': speed,
        'percentage': percentage,
        'eta_seconds': eta,
    }


class DownloadProgressState:
    """حوّل تقدم streams المنفصلة إلى نسبة واحدة لا ترجع إلى الخلف.

    yt-dlp قد ينزل الفيديو ثم الصوت في ملفين: كل واحد يبدأ من 0 ويصل 100.
    نخصص 95% للمسار الأول و4% للثاني، ونترك 100% حصراً لـfinish الحقيقي
    بعد رجوع extract_info. النسبة تقريبية للواجهة، أما MB فتبقى للمسار الحالي.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._generation = None
        self._stream_order = []
        self._stream_max = {}
        self._display_max = 0.0

    @staticmethod
    def _stream_key(data):
        info = data.get('info_dict') or {}
        return (
            data.get('filename') or info.get('id') or 'default',
            info.get('format_id') or data.get('format_id') or 'default',
        )

    def update(self, data, generation):
        values = progress_values(
            data.get('downloaded_bytes'),
            data.get('total_bytes') or data.get('total_bytes_estimate'),
            data.get('speed'),
        )
        raw_percentage = values['percentage']
        if raw_percentage is None:
            return values

        key = self._stream_key(data)
        with self._lock:
            if (self._generation is not None
                    and generation < self._generation):
                return None
            if generation != self._generation:
                self._generation = generation
                self._stream_order = []
                self._stream_max = {}
                self._display_max = 0.0
            if key not in self._stream_max:
                self._stream_order.append(key)
                self._stream_max[key] = 0.0
            self._stream_max[key] = max(
                self._stream_max[key], raw_percentage)
            stream_index = self._stream_order.index(key)
            stable_raw = self._stream_max[key]

            if stream_index == 0:
                display = stable_raw * 0.95
            elif stream_index == 1:
                display = 95.0 + stable_raw * 0.04
            else:
                display = 99.0 + min(stream_index - 1, 1) * 0.25
                display += stable_raw * 0.0025
            self._display_max = min(
                99.5, max(self._display_max, display))
            values['percentage'] = self._display_max
        return values


class CoalescingMessageEditor:
    """محرر متسلسل وآمن للاستدعاء من callbacks تعمل في threads مختلفة.

    لا نرسل كل callback إلى Telegram. نحتفظ بأحدث نص فقط، ونضمن وجود طلب
    ``edit`` واحد كحد أقصى. هذا يمنع تراكم نسب قديمة ثم ظهورها متأخرة أو
    بترتيب عكسي عندما يكون التحميل أسرع من Telegram API.
    """

    def __init__(self, edit_message, loop, *, min_interval=1.0,
                 finish_timeout=3.0, close_timeout=0.5, on_error=None):
        self._edit_message = edit_message
        self._loop = loop
        self._min_interval = max(0.0, float(min_interval))
        self._finish_timeout = max(0.1, float(finish_timeout))
        self._close_timeout = max(0.05, float(close_timeout))
        self._on_error = on_error

        # publish() قد يعمل داخل yt-dlp/Pyrogram thread. القفل يحصر كل burst
        # في call_soon_threadsafe واحد بدلاً من ملء event loop بآلاف callbacks.
        self._thread_lock = threading.Lock()
        self._thread_accepting = True
        self._generation = 0
        self._offered_text = None
        self._transfer_scheduled = False

        # الحقول التالية لا تُلمس إلا من event loop.
        self._loop_accepting = True
        self._latest = None
        self._worker_task = None
        self._wake_event = asyncio.Event()
        self._last_edit_at = float('-inf')
        self._blocked_until = float('-inf')
        self._last_text = None

    @property
    def is_idle(self):
        task = self._worker_task
        return task is None or task.done()

    def note_external_edit(self, text=None):
        """سجّل edit مباشرًا سبق إنشاء العامل كي تُحترم فترة الخنق."""
        self._last_edit_at = self._loop.time()
        if text is not None:
            self._last_text = str(text)

    def new_generation(self):
        """ابدأ محاولة مصدر جديدة وأبطل callbacks المتأخرة للمحاولة السابقة."""
        with self._thread_lock:
            if not self._thread_accepting:
                return None
            self._generation += 1
            self._offered_text = None
            return self._generation

    def publish(self, text, *, generation=None):
        """انشر أحدث نص بلا انتظار؛ يعيد False بعد الإغلاق."""
        text = str(text)
        with self._thread_lock:
            if not self._thread_accepting:
                return False
            if generation is None:
                generation = self._generation
            if generation != self._generation:
                return False
            self._offered_text = (text, generation)
            if self._transfer_scheduled:
                return True
            self._transfer_scheduled = True
        try:
            self._loop.call_soon_threadsafe(self._transfer_offer)
            return True
        except RuntimeError:
            # Event loop أُغلق أثناء إيقاف الخدمة؛ لا ننشئ coroutine يتيمة.
            with self._thread_lock:
                self._thread_accepting = False
                self._offered_text = None
                self._transfer_scheduled = False
            return False

    def _transfer_offer(self):
        with self._thread_lock:
            offered = self._offered_text
            self._offered_text = None
            self._transfer_scheduled = False
            accepting = self._thread_accepting
            generation = self._generation
        if not accepting or not self._loop_accepting or offered is None:
            return
        text, offered_generation = offered
        if offered_generation != generation:
            return
        self._latest = _PendingEdit(
            text=text, generation=offered_generation)
        self._wake_event.set()
        self._ensure_worker()

    def _ensure_worker(self):
        if self._worker_task is None or self._worker_task.done():
            task = self._loop.create_task(self._drain())
            self._worker_task = task
            task.add_done_callback(self._worker_done)

    def _worker_done(self, task):
        if self._worker_task is task:
            self._worker_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except BaseException as error:  # استهلاك الخطأ يمنع Task exception...
            self._report_error(error)
        if self._latest is not None:
            self._ensure_worker()

    @staticmethod
    def _error_name(error):
        return error.__class__.__name__

    @classmethod
    def _is_not_modified(cls, error):
        return cls._error_name(error) == 'MessageNotModified'

    @classmethod
    def _flood_wait_seconds(cls, error):
        if cls._error_name(error) != 'FloodWait':
            return 0.0
        value = getattr(error, 'value', None)
        if value is None:
            value = getattr(error, 'x', 0)
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 0.0

    def _report_error(self, error):
        if self._on_error is None:
            return
        try:
            self._on_error(error)
        except Exception:
            pass

    def _is_current_generation(self, item):
        with self._thread_lock:
            return item.generation == self._generation

    @staticmethod
    def _settle(item, result):
        waiter = item.waiter if item is not None else None
        if waiter is not None and not waiter.done():
            waiter.set_result(bool(result))

    async def _drain(self):
        current = None
        try:
            while self._loop_accepting or self._latest is not None:
                current = self._latest
                self._latest = None
                if current is None:
                    return
                if not current.force and not self._is_current_generation(current):
                    current = None
                    continue

                # انتظر فترة الخنق، لكن اسمح لـ finish القسري بإيقاظ العامل
                # فوراً بدلاً من الانتظار ثانية كاملة ثم فقدان 100%.
                if not current.force and self._latest is not None:
                    current = self._latest
                    self._latest = None
                self._wake_event.clear()
                while True:
                    now = self._loop.time()
                    delay = max(0.0, self._blocked_until - now)
                    if not current.force:
                        delay = max(
                            delay,
                            self._last_edit_at + self._min_interval - now,
                        )
                    if delay <= 0:
                        break
                    try:
                        await asyncio.wait_for(
                            self._wake_event.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        break
                    self._wake_event.clear()
                    if not current.force and self._latest is not None:
                        current = self._latest
                        self._latest = None
                    if (not current.force
                            and not self._is_current_generation(current)):
                        current = None
                        break
                if current is None:
                    continue

                if current.text == self._last_text:
                    self._settle(current, True)
                    current = None
                    continue

                try:
                    await self._edit_message(current.text)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if self._is_not_modified(error):
                        succeeded = True
                    else:
                        wait_seconds = self._flood_wait_seconds(error)
                        if wait_seconds > 0:
                            self._blocked_until = max(
                                self._blocked_until,
                                self._loop.time() + wait_seconds,
                            )
                            # أعد آخر نص فقط بعد FloodWait. إن وُجد نص أحدث
                            # فالأحدث أولى، إلا أن finish القسري لا يُستبدل.
                            if current.force or self._latest is None:
                                self._latest = current
                            current = None
                            continue
                        self._report_error(error)
                        succeeded = False
                else:
                    succeeded = True

                self._last_edit_at = self._loop.time()
                if succeeded:
                    self._last_text = current.text
                self._settle(current, succeeded)
                current = None
        finally:
            self._settle(current, False)

    async def finish(self, text):
        """أوقف callbacks الجديدة، أرسل الحالة النهائية، ثم أغلق العامل.

        تحديث الواجهة لا يجوز أن يحجز إرسال الملف؛ لذلك له مهلة قصيرة، وبعدها
        يُلغى العامل كي لا تكتب نسبة قديمة فوق مرحلة الرفع.
        """
        with self._thread_lock:
            self._thread_accepting = False
            self._offered_text = None
        self._loop_accepting = False

        waiter = self._loop.create_future()
        with self._thread_lock:
            generation = self._generation
        self._latest = _PendingEdit(
            text=str(text), force=True, waiter=waiter,
            generation=generation)
        self._wake_event.set()
        self._ensure_worker()
        try:
            return await asyncio.wait_for(
                asyncio.shield(waiter), timeout=self._finish_timeout)
        except asyncio.TimeoutError:
            return False
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._report_error(error)
            return False
        finally:
            await self.close()

    async def close(self):
        """إغلاق idempotent يمحو أي تحديث قديم وينتظر إلغاء العامل."""
        with self._thread_lock:
            self._thread_accepting = False
            self._offered_text = None
        self._loop_accepting = False
        self._wake_event.set()

        pending = self._latest
        self._latest = None
        self._settle(pending, False)

        task = self._worker_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            done, _pending = await asyncio.wait(
                {task}, timeout=self._close_timeout)
            if task not in done:
                # بعض coroutines قد تبتلع أول CancelledError. أرسل إلغاءً
                # ثانياً ضمن مهلة محدودة كي لا ينجو edit قديم بعد close().
                task.cancel()
                done, _pending = await asyncio.wait(
                    {task}, timeout=self._close_timeout)
            if task in done:
                try:
                    task.result()
                except asyncio.CancelledError:
                    pass
                except Exception as error:
                    self._report_error(error)
            else:
                self._report_error(TimeoutError(
                    'Telegram progress editor did not stop in time'))
        if (task is None or task.done()) and self._worker_task is task:
            self._worker_task = None
