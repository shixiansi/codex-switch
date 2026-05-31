from __future__ import annotations

import re


SENSITIVE_HEADER_NAMES = {
    "authorization",
    "x-api-key",
    "api-key",
    "anthropic-api-key",
    "anthropic_auth_token",
    "anthropic-api-token",
    "project_api_key",
}
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(sk-[a-z0-9_\-]{8,}|anthropic[_-]?auth[_-]?token\s*[:=]\s*[^,\s]+|api[_-]?key\s*[:=]\s*[^,\s]+)"
)


def mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def sanitize_header(name: str, value: str) -> str:
    if name.casefold() in SENSITIVE_HEADER_NAMES:
        return mask_secret(value)
    return sanitize_text(value)


def sanitize_text(value: str) -> str:
    return SENSITIVE_TEXT_RE.sub(lambda match: mask_secret(match.group(0)), str(value or ""))
