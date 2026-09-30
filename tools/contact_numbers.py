"""Canonical validation helpers for user-confirmed Chinese contact numbers."""

from __future__ import annotations

import re


_MOBILE = re.compile(r"1[3-9]\d{9}\Z")
_HOTLINE_DIGITS = re.compile(r"400\d{7}\Z")
_PLACEHOLDER = re.compile(r"8{8}\Z")
_SEPARATORS = re.compile(r"[\s\-‐‑‒–—−]+")
_CONTACT_IN_TEXT = re.compile(
    r"(?<!\d)(?:1[3-9]\d{9}|400[\s\-‐‑‒–—−]*\d{3}[\s\-‐‑‒–—−]*\d{4})(?!\d)"
)


def normalize_contact_number(value: str, *, allow_placeholder: bool = False) -> str:
    """Return the stable display form for a supported contact number.

    Mainland mobile numbers remain eleven digits. National 400 service
    hotlines are stored and rendered as ``400-XXX-XXXX`` so a user-confirmed
    display format survives planning, prompt freezing, overlays, and review.
    """

    compact = _SEPARATORS.sub("", str(value).strip())
    if _MOBILE.fullmatch(compact):
        return compact
    if _HOTLINE_DIGITS.fullmatch(compact):
        return f"{compact[:3]}-{compact[3:6]}-{compact[6:]}"
    if allow_placeholder and _PLACEHOLDER.fullmatch(compact):
        return compact
    raise ValueError("unsupported Chinese mobile or 400 service number")


def is_canonical_contact_number(value: str, *, allow_placeholder: bool = False) -> bool:
    text = str(value).strip()
    try:
        return normalize_contact_number(text, allow_placeholder=allow_placeholder) == text
    except ValueError:
        return False


def is_placeholder_contact_number(value: str) -> bool:
    return _PLACEHOLDER.fullmatch(str(value).strip()) is not None


def extract_contact_numbers(text: str) -> list[str]:
    """Extract supported numbers from text and return canonical unique values."""

    result: list[str] = []
    for match in _CONTACT_IN_TEXT.finditer(str(text)):
        normalized = normalize_contact_number(match.group(0))
        if normalized not in result:
            result.append(normalized)
    return result


def contains_contact_number(text: str) -> bool:
    return _CONTACT_IN_TEXT.search(str(text)) is not None
