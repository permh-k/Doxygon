#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file diagnostics_scanner.py 未定義コマンド検出処理
"""

from __future__ import annotations

import re

from doxygon.model.model import Diagnostic
from doxygon.parser.command_registry import CommandRegistry


INLINE_CMD_RE = re.compile(
    r"""
    (?<![\w."'<`])
    @([A-Za-z_][A-Za-z0-9_]*)
    (?!["'`])
    """,
    re.VERBOSE,
)

DOXYGON_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_ASCII_WS_RE = re.compile(r"[ \t]+")
_JAPANESE_PARTICLE_TAGS = {
    "が", "を", "に", "は", "へ", "と", "で", "の", "も",
    "や", "か", "ね", "よ", "な", "から", "まで", "より",
}


def _split_ascii_argument(argument: str) -> tuple[str, str]:
    """Split TAG/SENTENCE using only ASCII space and tab.

    Doxygon command syntax uses half-width space/tab as the TAG/SENTENCE
    separator.  Full-width spaces are document text, not syntax separators.
    """
    s = (argument or "").strip(" \t")

    if not s:
        return "", ""

    parts = _ASCII_WS_RE.split(s, maxsplit=1)
    tag = parts[0]
    sentence = parts[1] if len(parts) >= 2 else ""

    return tag, sentence


def _contains_non_ascii(text: str) -> bool:
    return any(ord(ch) >= 128 for ch in text or "")


"""!
@fn scan_unknown_commands 未定義コマンド検出処理
@brief 文字列中のDoxygonコマンドを走査し、未定義コマンドを返す。
@param [in] text 対象となる文字列
@param [in] registry 定義済みコマンドの一覧
@param [in] line 未定義コマンドの行番号
@return diagnostics 検出された未定義コマンド一覧
"""
def scan_unknown_commands(
    *,
    text: str,
    registry: CommandRegistry,
    line: int | None = None,
) -> list[Diagnostic]:

    diagnostics: list[Diagnostic] = []

    for m in INLINE_CMD_RE.finditer(text):
        name = m.group(1)

        if registry.is_known(name):
            continue

        diagnostics.append(
            Diagnostic(
                level="error",
                message=f"unknown command: @{name}",
                line=line,
            )
        )

    return diagnostics


def scan_extra_command_tokens(
    *,
    text: str,
    line: int | None = None,
) -> list[Diagnostic]:
    """Return diagnostics for a second @xxx token in a command line.

    Doxygon command lines are one command per line.  This scanner is intended
    only for the argument part of a command line, after the leading command
    token has already been parsed.  Quoted command names such as ``"@var"``
    are ignored by INLINE_CMD_RE.
    """

    diagnostics: list[Diagnostic] = []

    for m in INLINE_CMD_RE.finditer(text or ""):
        name = m.group(1)
        diagnostics.append(
            Diagnostic(
                level="error",
                message=f"multiple doxygen command in one line: @{name}",
                line=line,
            )
        )

    return diagnostics


def scan_invalid_tag_commands(
    *,
    command: str,
    argument: str,
    line: int | None = None,
) -> list[Diagnostic]:
    """Return diagnostics for command tags that are syntactically invalid.

    TAG-bearing commands are still command lines even when the first payload
    token is not a valid identifier.  For @var, a Japanese particle such as
    ``が`` must not be accepted as a variable name just because it appears
    after ``@var`` at the start of a line.
    """

    command_name = (command or "").lower().lstrip("@")

    if command_name != "var":
        return []

    tag, sentence = _split_ascii_argument(argument)

    if not tag:
        return []

    if DOXYGON_IDENTIFIER_RE.fullmatch(tag):
        return []

    # Japanese TAGs are valid display names in comment-driven documents.
    # SENTENCE is optional by command.toml (TAG SENTENCE?), so do not reject
    # a non-ASCII tag only because it has no following sentence.  Reject only
    # clearly suspicious Japanese particles such as ``が`` / ``を``.
    if _contains_non_ascii(tag) and tag not in _JAPANESE_PARTICLE_TAGS:
        return []

    return [
        Diagnostic(
            level="error",
            message=f"invalid tag for @{command_name}: {tag}",
            line=line,
        )
    ]
