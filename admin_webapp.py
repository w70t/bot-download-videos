"""Validation helpers for the optional Telegram admin Mini App."""

import os
from urllib.parse import urlsplit


def admin_webapp_url(environ=None):
    """Return a safe HTTPS Web App URL, or ``None`` when disabled/invalid.

    Keeping validation outside ``bot.py`` makes the fail-closed behavior easy
    to test without importing the Telegram client or production dependencies.
    """
    source = os.environ if environ is None else environ
    raw = str(source.get("ADMIN_WEBAPP_URL", "")).strip()
    if not raw or any(char.isspace() for char in raw):
        return None

    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None

    if port is not None and not (1 <= port <= 65535):
        return None

    return raw
