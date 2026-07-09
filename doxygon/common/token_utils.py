#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Shared token search helpers for Doxygon source/comment scanning."""

from __future__ import annotations


QUOTE_BLOCK_TOKENS = {'"""', "'''"}


def is_quote_block_token(token: str) -> bool:
    """Return True for Python triple-quote Doxygon block markers."""
    return token in QUOTE_BLOCK_TOKENS


def find_unquoted_token(text: str, token: str, start: int = 0) -> int:
    """Return token position outside quoted/literal spans, or -1.

    Doxygon comments may describe comment markers themselves, for example:
        "/**!< ... */"
        `/**!< ... */`

    In those cases the markers inside double quotes or AsciiDoc-style
    backticks must not be treated as real comment start/end tokens.

    Python Doxygon block markers such as triple quotes are real tokens even
    though they contain quote characters, so they are searched literally.
    """
    if not token:
        return -1

    if is_quote_block_token(token):
        return text.find(token, start)

    in_double_quote = False
    in_backtick = False
    escaped = False

    i = start
    n = len(text)

    while i < n:
        ch = text[i]

        if escaped:
            escaped = False
            i += 1
            continue

        if ch == "\\":
            escaped = True
            i += 1
            continue

        if ch == '"' and not in_backtick:
            in_double_quote = not in_double_quote
            i += 1
            continue

        if ch == "`" and not in_double_quote:
            in_backtick = not in_backtick
            i += 1
            continue

        if not in_double_quote and not in_backtick and text.startswith(token, i):
            return i

        i += 1

    return -1


def find_block_end_token(text: str, token: str) -> int:
    """Return block end token position, honoring Python quote block tokens."""
    if is_quote_block_token(token):
        return text.find(token)

    return find_unquoted_token(text, token)


def split_at_block_end_token(text: str, token: str) -> tuple[str, bool]:
    """Split text before a real block end token."""
    pos = find_block_end_token(text, token)

    if pos == -1:
        return text, False

    return text[:pos], True


def split_at_unquoted_token(text: str, token: str) -> tuple[str, bool]:
    """Split text before a token found outside quoted/literal spans."""
    pos = find_unquoted_token(text, token)

    if pos == -1:
        return text, False

    return text[:pos], True
