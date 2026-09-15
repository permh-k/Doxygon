#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file ut_parser.py "@ut"コマンド本文解析処理
"""

from __future__ import annotations

import re

from doxygon.model.model import Diagnostic, UtEntry


_HEADING_RE = re.compile(r"^(\.+)[ \t]+(.+?)\s*$")
_INVALID_HEADING_TYPE_RE = re.compile(r"^(\.+)[ \t]+![ \t]*(.*?)\s*$")
_ABNORMAL_RE = re.compile(r"^![ \t]+(.+?)\s*$")


"""!
@fn parse_ut_entries "@ut"コマンド本文解析処理
@brief "@ut"の引数と本文を、見出しまたは試験項目に変換する。
@param [in] argument "@ut"コマンド行の引数
@param [in] body_lines "@ut"コマンドの本文
@param [in] start_line "@ut"コマンドのソース行番号
@return result 単体試験仕様要素と診断情報
"""
def parse_ut_entries(
    *,
    argument: str,
    body_lines: list[str] | None,
    start_line: int | None = None,
) -> tuple[list[UtEntry], list[Diagnostic]]:
    entries: list[UtEntry] = []
    diagnostics: list[Diagnostic] = []
    source_lines: list[tuple[str, int | None]] = []

    if (argument or "").strip():
        source_lines.append((argument, start_line))

    for offset, body_line in enumerate(body_lines or [], start=1):
        line_no = start_line + offset if start_line is not None else None
        source_lines.append((body_line, line_no))

    for raw_line, line_no in source_lines:
        line = (raw_line or "").strip()

        if not line:
            continue

        invalid_heading_type = _INVALID_HEADING_TYPE_RE.fullmatch(line)

        if invalid_heading_type:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    message="invalid abnormal marker in @ut heading",
                    line=line_no,
                )
            )

            heading_text = invalid_heading_type.group(2).strip()

            if heading_text:
                entries.append(
                    UtEntry(
                        kind="heading",
                        level=len(invalid_heading_type.group(1)),
                        text=heading_text,
                        line=line_no,
                    )
                )
            continue

        heading = _HEADING_RE.fullmatch(line)

        if heading:
            entries.append(
                UtEntry(
                    kind="heading",
                    level=len(heading.group(1)),
                    text=heading.group(2),
                    line=line_no,
                )
            )
            continue

        abnormal = _ABNORMAL_RE.fullmatch(line)

        if abnormal:
            entries.append(
                UtEntry(
                    kind="test",
                    test_type="abnormal",
                    text=abnormal.group(1),
                    line=line_no,
                )
            )
            continue

        entries.append(
            UtEntry(
                kind="test",
                test_type="normal",
                text=line,
                line=line_no,
            )
        )

    return entries, diagnostics
