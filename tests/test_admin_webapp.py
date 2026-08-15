# -*- coding: utf-8 -*-
"""Tests for the optional admin-only Telegram Mini App button."""

import ast
from pathlib import Path

import pytest

from admin_webapp import admin_webapp_url
from translations import t


BOT_PATH = Path(__file__).resolve().parents[1] / "bot.py"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "http://example.com/control",
        "example.com/control",
        "/control",
        "https://user@example.com/control",
        "https://user:pass@example.com/control",
        "https://example.com/control?admin=1",
        "https://example.com/control#panel",
        "https://example.com:99999/control",
        "https://example .com/control",
    ],
)
def test_admin_webapp_url_rejects_missing_or_unsafe_values(raw):
    environ = {} if raw is None else {"ADMIN_WEBAPP_URL": raw}

    assert admin_webapp_url(environ) is None


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com",
        "https://example.com/control",
        " https://example.com/control ",
        "https://example.com:8443/control",
    ],
)
def test_admin_webapp_url_accepts_https(raw):
    assert admin_webapp_url({"ADMIN_WEBAPP_URL": raw}) == raw.strip()


class FakeWebAppInfo:
    def __init__(self, *, url):
        self.url = url


class FakeKeyboardButton:
    def __init__(self, text, *, web_app=None):
        self.text = text
        self.web_app = web_app


def _load_row_helper(*, admin=True, url="https://example.com/control"):
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"), filename=str(BOT_PATH))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_admin_webapp_row"
    )
    namespace = {
        "KeyboardButton": FakeKeyboardButton,
        "WebAppInfo": FakeWebAppInfo,
        "admin_webapp_url": lambda: url,
        "is_admin": lambda _user_id: admin,
        "t": lambda key, lang: t(key, lang),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(BOT_PATH), "exec"), namespace)
    return namespace["_admin_webapp_row"]


def test_admin_webapp_row_builds_translated_button_for_admin_private_chat():
    row = _load_row_helper()(123, "ar", private_chat=True)

    assert len(row) == 1
    assert len(row[0]) == 1
    assert row[0][0].text == "🎛 مركز التحكم"
    assert row[0][0].web_app.url == "https://example.com/control"


@pytest.mark.parametrize(
    ("admin", "private_chat", "url"),
    [
        (False, True, "https://example.com/control"),
        (True, False, "https://example.com/control"),
        (True, True, None),
    ],
)
def test_admin_webapp_row_fails_closed(admin, private_chat, url):
    helper = _load_row_helper(admin=admin, url=url)

    assert helper(123, "ar", private_chat=private_chat) == []


def test_both_admin_menu_paths_include_optional_webapp_row():
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"), filename=str(BOT_PATH))
    functions = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in ("start", "handle_language_selection"):
        calls = [
            node for node in ast.walk(functions[name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_admin_webapp_row"
        ]
        assert len(calls) == 1
        keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        private_chat = keywords["private_chat"]
        assert isinstance(private_chat, ast.Compare)
        assert any(
            isinstance(node, ast.Attribute)
            and node.attr == "PRIVATE"
            for node in ast.walk(private_chat)
        )


def test_admin_webapp_translation_exists_in_both_languages():
    assert t("btn_admin_webapp", "ar") == "🎛 مركز التحكم"
    assert t("btn_admin_webapp", "en") == "🎛 Control Center"
