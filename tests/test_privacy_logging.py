# -*- coding: utf-8 -*-
"""اختبارات تنقيح السجلات ومهلة الاحتفاظ، بلا تشغيل عميل Telegram.

استيراد bot.py كاملاً ينشئ عميل Pyrogram ويتطلب أسرار التشغيل وكل اعتمادات
التنزيل. لذلك نحمّل عقد الخصوصية الصغيرة نفسها من شجرة المصدر وننفذها مع
اعتمادات Python القياسية فقط.
"""

import ast
import logging
import os
import re
from pathlib import Path
from unittest.mock import Mock

import pytest


_BOT_PATH = Path(__file__).resolve().parents[1] / 'bot.py'
_PRIVACY_ASSIGNMENTS = {
    '_LOG_URL_RE',
    '_LOG_BOT_TOKEN_RE',
    '_LOG_TELEGRAM_ID_RE',
    '_LOG_USERNAME_RE',
}
_PRIVACY_DEFINITIONS = {
    '_redact_log_text',
    '_sanitize_legacy_log_files',
    '_PrivacyLogFormatter',
    '_retention_days_from_env',
}


def _load_privacy_namespace():
    """تنفيذ تعريفات الخصوصية الفعلية فقط من bot.py."""
    tree = ast.parse(_BOT_PATH.read_text(encoding='utf-8'), filename=str(_BOT_PATH))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets
                if isinstance(target, ast.Name)
            }
            if names & _PRIVACY_ASSIGNMENTS:
                selected.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if node.name in _PRIVACY_DEFINITIONS:
                selected.append(node)

    found = {
        node.name for node in selected
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    found.update(
        target.id
        for node in selected if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    )
    expected = _PRIVACY_ASSIGNMENTS | _PRIVACY_DEFINITIONS
    assert found == expected, f'تعريفات الخصوصية المفقودة: {expected - found}'

    namespace = {
        'logging': logging,
        'logger': Mock(),
        'os': os,
        're': re,
    }
    privacy_module = ast.Module(body=selected, type_ignores=[])
    exec(compile(privacy_module, str(_BOT_PATH), 'exec'), namespace)
    return namespace


def _fake_bot_token():
    """Token-shaped test data assembled at runtime to avoid secret scanners."""
    return '123456789:' + 'ABCdefGHIjklMNOpqrsTUVwxyz012345'


@pytest.fixture()
def privacy():
    return _load_privacy_namespace()


def test_redacts_links_telegram_ids_and_usernames(privacy):
    fake_token = _fake_bot_token()
    raw = (
        'download https://example.com/watch?v=secret-token '
        'for 123456789 in chat -1009876543210 by @private_user '
        f'using {fake_token}'
    )

    redacted = privacy['_redact_log_text'](raw)

    assert 'secret-token' not in redacted
    assert '123456789' not in redacted
    assert '-1009876543210' not in redacted
    assert '@private_user' not in redacted
    assert fake_token not in redacted
    assert '[private-link]' in redacted
    assert '[private-token]' in redacted
    assert redacted.count('[private-id]') == 2
    assert '[private-username]' in redacted


def test_redaction_preserves_non_sensitive_text(privacy):
    raw = 'retry 404 after 12345 ms; contact person@example.com'

    assert privacy['_redact_log_text'](raw) == raw


def test_privacy_formatter_redacts_message_arguments_and_traceback(privacy):
    try:
        raise RuntimeError(
            'request https://private.example/video failed for @secret_user 7654321'
        )
    except RuntimeError:
        record = logging.LogRecord(
            name='privacy-test',
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg='download %s for chat %s',
            args=('https://example.com/token', -1001234567890),
            exc_info=__import__('sys').exc_info(),
        )

    formatter = privacy['_PrivacyLogFormatter']('%(levelname)s: %(message)s')
    formatted = formatter.format(record)

    for secret in (
        'https://example.com/token',
        'https://private.example/video',
        '@secret_user',
        '7654321',
        '-1001234567890',
    ):
        assert secret not in formatted
    assert formatted.count('[private-link]') >= 2
    assert formatted.count('[private-id]') >= 2
    assert '[private-username]' in formatted


def test_sanitizes_existing_rotated_logs_before_reuse(privacy, tmp_path):
    base_path = tmp_path / 'bot_standalone.log'
    secrets = (
        'https://private.example/video @secret_user -1001234567890\n'
        f'{_fake_bot_token()}\n'
    )
    paths = [base_path, Path(f'{base_path}.1'), Path(f'{base_path}.2')]
    for path in paths:
        path.write_text(secrets, encoding='utf-8')

    count = privacy['_sanitize_legacy_log_files'](str(base_path), 2)

    assert count == 3
    for path in paths:
        contents = path.read_text(encoding='utf-8')
        assert 'private.example' not in contents
        assert '@secret_user' not in contents
        assert '-1001234567890' not in contents
        assert _fake_bot_token() not in contents
        assert '[private-link]' in contents
        assert '[private-token]' in contents


@pytest.mark.parametrize(
    ('raw_value', 'expected'),
    [
        ('45', 45),
        (' 7 ', 7),
        ('0', 1),
        ('-12', 1),
    ],
)
def test_retention_env_accepts_integers_and_clamps_to_one(
        privacy, monkeypatch, raw_value, expected):
    monkeypatch.setenv('PRIVACY_TEST_RETENTION', raw_value)

    assert privacy['_retention_days_from_env'](
        'PRIVACY_TEST_RETENTION', 30
    ) == expected


def test_retention_env_uses_default_when_missing(privacy, monkeypatch):
    monkeypatch.delenv('PRIVACY_TEST_RETENTION', raising=False)

    assert privacy['_retention_days_from_env'](
        'PRIVACY_TEST_RETENTION', 21
    ) == 21
    privacy['logger'].warning.assert_not_called()


@pytest.mark.parametrize('raw_value', ['abc', '', '2.5'])
def test_retention_env_falls_back_and_warns(
        privacy, monkeypatch, raw_value):
    monkeypatch.setenv('PRIVACY_TEST_RETENTION', raw_value)

    assert privacy['_retention_days_from_env'](
        'PRIVACY_TEST_RETENTION', 14
    ) == 14
    privacy['logger'].warning.assert_called_once_with(
        'Invalid privacy retention setting; using %d days', 14
    )
