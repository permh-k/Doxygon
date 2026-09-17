#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file value_parser.py "@value"コマンド解析処理
"""

from __future__ import annotations

import re

from doxygon.model.model import Diagnostic, ValueContent, ValueEntry


_VALUE_PREFIX_RE = re.compile(
    r"^(?:\[(?P<index>[^\]\r\n]*)\][ \t]*)?"
    r"(?P<operator>!=|<=|>=|=|<|>)[ \t]*"
    r"(?P<payload>.*)$"
)


def _quotes_are_balanced(text: str) -> bool:
    quoted = False
    escaped = False

    for char in text:
        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            quoted = not quoted

    return not quoted


def _split_unquoted(text: str, separator: str) -> tuple[str, str] | None:
    """Split once on a separator that is outside double quotes."""

    quoted = False
    escaped = False
    index = 0

    while index <= len(text) - len(separator):
        char = text[index]

        if escaped:
            escaped = False
            index += 1
            continue

        if char == "\\":
            escaped = True
            index += 1
            continue

        if char == '"':
            quoted = not quoted
            index += 1
            continue

        if not quoted and text.startswith(separator, index):
            return text[:index], text[index + len(separator):]

        index += 1

    return None


def _split_description(payload: str) -> tuple[str, str, bool]:
    """Split an optional `` : description`` suffix."""

    quoted = False
    escaped = False

    for index, char in enumerate(payload):
        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            quoted = not quoted
            continue

        if quoted or char != ":" or index == 0:
            continue

        before_is_space = payload[index - 1] in " \t"
        if before_is_space:
            return (
                payload[:index].strip(" \t"),
                payload[index + 1:].strip(" \t"),
                True,
            )

    return payload.strip(" \t"), "", False


def _parse_value_contents(
    *,
    body_lines: list[str],
    start_line: int | None,
) -> tuple[tuple[ValueContent, ...], list[Diagnostic]]:
    """Parse test markers and preserve other lines as AsciiDoc blocks."""

    contents: list[ValueContent] = []
    diagnostics: list[Diagnostic] = []
    asciidoc_lines: list[str] = []
    asciidoc_start_line: int | None = None

    first_content = 0
    last_content = len(body_lines)

    while (
        first_content < last_content
        and not body_lines[first_content].strip()
    ):
        first_content += 1

    while (
        last_content > first_content
        and not body_lines[last_content - 1].strip()
    ):
        last_content -= 1

    def flush_asciidoc() -> None:
        nonlocal asciidoc_lines, asciidoc_start_line

        if not asciidoc_lines:
            return

        contents.append(
            ValueContent(
                kind="asciidoc",
                text="\n".join(asciidoc_lines),
                line=asciidoc_start_line,
            )
        )
        asciidoc_lines = []
        asciidoc_start_line = None

    for index in range(first_content, last_content):
        raw_line = body_lines[index]
        offset = index + 1
        source_line = start_line + offset if start_line is not None else None
        classification = None
        marker_line = raw_line.lstrip(" \t")

        if marker_line.startswith("+"):
            classification = "normal"
        elif marker_line.startswith("-"):
            classification = "abnormal"

        if classification is None:
            if not asciidoc_lines:
                asciidoc_start_line = source_line
            asciidoc_lines.append(raw_line)
            continue

        flush_asciidoc()
        test_text = marker_line[1:].strip(" \t")

        if not test_text.strip(" \t"):
            diagnostics.append(
                Diagnostic(
                    level="error",
                    message="empty @value test item",
                    line=source_line,
                )
            )
            continue

        contents.append(
            ValueContent(
                kind="test",
                classification=classification,
                text=test_text,
                line=source_line,
            )
        )

    flush_asciidoc()
    return tuple(contents), diagnostics


"""!
@fn parse_value_entry "@value"コマンド解析処理
@brief "@value [添字]? 条件 [ : 説明]"とブロック本文を解析する。
@param [in] argument "@value"コマンドの引数
@param [in] body_lines "@value"ブロック本文
@param [in] line ソース行番号
@return result 値定義と診断情報
"""
def parse_value_entry(
    *,
    argument: str,
    body_lines: list[str] | None = None,
    line: int | None = None,
) -> tuple[ValueEntry | None, list[Diagnostic]]:
    text = (argument or "").strip(" \t")
    match = _VALUE_PREFIX_RE.fullmatch(text)

    if match is None:
        return None, [
            Diagnostic(
                level="error",
                message="invalid @value syntax",
                line=line,
            )
        ]

    index = (match.group("index") or "").strip(" \t")
    operator = match.group("operator")
    payload = match.group("payload")

    if match.group("index") is not None and not index:
        return None, [
            Diagnostic(
                level="error",
                message="empty @value index",
                line=line,
            )
        ]

    if not _quotes_are_balanced(payload):
        return None, [
            Diagnostic(
                level="error",
                message="unterminated quote in @value",
                line=line,
            )
        ]

    condition_text, description, has_description = _split_description(payload)

    if not condition_text or (has_description and not description):
        return None, [
            Diagnostic(
                level="error",
                message="empty @value value or description",
                line=line,
            )
        ]

    if condition_text[0] in "=<>!":
        return None, [
            Diagnostic(
                level="error",
                message="invalid @value operator",
                line=line,
            )
        ]

    if operator == "=" and condition_text.endswith(" -"):
        return None, [
            Diagnostic(
                level="error",
                message="invalid @value range",
                line=line,
            )
        ]

    kind = "exact" if operator == "=" else "comparison"
    value = condition_text
    lower = ""
    upper = ""

    if operator == "=":
        range_parts = _split_unquoted(condition_text, " - ")

        if range_parts is not None:
            lower = range_parts[0].strip(" \t")
            upper = range_parts[1].strip(" \t")

            if not lower or not upper or _split_unquoted(upper, " - ") is not None:
                return None, [
                    Diagnostic(
                        level="error",
                        message="invalid @value range",
                        line=line,
                    )
                ]

            kind = "range"
            value = ""

    contents, content_diagnostics = _parse_value_contents(
        body_lines=body_lines or [],
        start_line=line,
    )

    return (
        ValueEntry(
            kind=kind,
            operator=operator,
            value=value,
            index=index,
            description=description,
            lower=lower,
            upper=upper,
            contents=contents,
        ),
        content_diagnostics,
    )
