# -*- coding: utf-8 -*-
"""اختبارات منطق تنبيه المرايا (_mirror_state_changes) المستخرَج من bot.py.

المهمّ هنا ليس الفحص الشبكي بل **متى يصل تنبيه ومتى لا يصل**: عطل معروف يجب
ألا يُرسل رسالة كل ساعة، وإعادة تشغيل البوت يجب ألا تُغرق الأدمن بتنبيهات."""

import ast

import pytest

SRC = open('bot.py', encoding='utf-8').read()
_TREE = ast.parse(SRC)
_WANT = {'_mirror_state_changes'}
_NODES = [n for n in _TREE.body
          if isinstance(n, ast.FunctionDef) and n.name in _WANT]
assert _NODES, 'لم تُستخرج دالة _mirror_state_changes من bot.py'

_NS = {'__builtins__': __builtins__, '_mirror_last_state': {}}
exec(compile(ast.Module(body=_NODES, type_ignores=[]), 'mirror', 'exec'), _NS)

changes = _NS['_mirror_state_changes']


def _snapshot(**hosts):
    """{المضيف: (المنصة، يعمل؟، السبب)} من host=True/False."""
    return {h: ('منصة', ok, 'HTTP 200' if ok else 'URLError')
            for h, ok in hosts.items()}


@pytest.fixture(autouse=True)
def _reset():
    _NS['_mirror_last_state'].clear()
    yield
    _NS['_mirror_last_state'].clear()


def test_first_run_healthy_is_silent():
    # الإقلاع وكل المرايا تعمل → لا تنبيه إطلاقاً
    down, up = changes(_snapshot(a=True, b=True))
    assert (down, up) == ([], [])


def test_first_run_reports_already_down_mirror():
    # مرآة ساقطة منذ الإقلاع تستحق الإبلاغ فوراً (وإلا بقيت مجهولة)
    down, up = changes(_snapshot(a=True, b=False))
    assert [h for h, _ in down] == ['b']
    assert up == []


def test_alerts_once_then_stays_quiet():
    # الأهم: عطل مستمرّ يُنبَّه عنه مرّة واحدة لا كل ساعة
    changes(_snapshot(a=True))
    down, _ = changes(_snapshot(a=False))
    assert [h for h, _ in down] == ['a']
    for _ in range(24):                       # ٢٤ ساعة من الفحوص
        down, up = changes(_snapshot(a=False))
        assert (down, up) == ([], [])


def test_recovery_is_reported_once():
    changes(_snapshot(a=True))
    changes(_snapshot(a=False))
    down, up = changes(_snapshot(a=True))
    assert up and [h for h, _ in up] == ['a']
    assert down == []
    down, up = changes(_snapshot(a=True))
    assert (down, up) == ([], [])


def test_tracks_each_host_independently():
    changes(_snapshot(a=True, b=True, c=True))
    down, up = changes(_snapshot(a=False, b=True, c=True))
    assert [h for h, _ in down] == ['a']
    down, up = changes(_snapshot(a=False, b=False, c=True))
    assert [h for h, _ in down] == ['b']      # a لا يتكرّر


def test_simultaneous_down_and_up_in_one_cycle():
    changes(_snapshot(a=True, b=False))       # b ساقطة منذ البداية
    down, up = changes(_snapshot(a=False, b=True))
    assert [h for h, _ in down] == ['a']
    assert [h for h, _ in up] == ['b']


def test_removed_host_leaves_state():
    # مضيف حُذف من متغيّرات البيئة لا يبقى في الذاكرة
    changes(_snapshot(a=True, b=True))
    changes(_snapshot(a=True))
    assert 'b' not in _NS['_mirror_last_state']


def test_new_host_added_later_is_not_flagged_when_healthy():
    changes(_snapshot(a=True))
    down, up = changes(_snapshot(a=True, b=True))   # مضيف جديد سليم
    assert (down, up) == ([], [])


def test_new_host_added_later_while_down_is_reported():
    # مضيف يُضاف لاحقاً وهو ساقط يجب أن يُبلَّغ عنه، لا أن يبقى مجهولاً للأبد
    changes(_snapshot(a=True))
    down, _ = changes(_snapshot(a=True, b=False))
    assert [h for h, _ in down] == ['b']
    # ثم يصمت كبقيّة الأعطال المعروفة
    down, up = changes(_snapshot(a=True, b=False))
    assert (down, up) == ([], [])
