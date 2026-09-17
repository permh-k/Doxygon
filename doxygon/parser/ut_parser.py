#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file ut_parser.py "@ut"コマンド本文解析処理
"""

from __future__ import annotations

from doxygon.model.model import Diagnostic, UtEntry


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

    while source_lines and not (source_lines[0][0] or "").strip():
        source_lines.pop(0)

    while source_lines and not (source_lines[-1][0] or "").strip():
        source_lines.pop()

    asciidoc_lines: list[str] = []
    asciidoc_start_line: int | None = None

    def flush_asciidoc() -> None:
        nonlocal asciidoc_lines, asciidoc_start_line

        if not asciidoc_lines:
            return

        entries.append(
            UtEntry(
                kind="asciidoc",
                text="\n".join(asciidoc_lines),
                line=asciidoc_start_line,
            )
        )
        asciidoc_lines = []
        asciidoc_start_line = None

    for raw_line, line_no in source_lines:
        preserved_line = raw_line or ""
        line = preserved_line.lstrip(" \t")

        if line.startswith("."):
            flush_asciidoc()
            level = len(line) - len(line.lstrip("."))
            heading_text = line[level:].strip(" \t")

            if not heading_text:
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message="empty @ut heading",
                        line=line_no,
                    )
                )
                continue

            entries.append(
                UtEntry(
                    kind="heading",
                    level=level,
                    text=heading_text,
                    line=line_no,
                )
            )
            continue

        if line.startswith(("+", "-")):
            flush_asciidoc()
            test_text = line[1:].strip(" \t")

            if not test_text:
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message="empty @ut test item",
                        line=line_no,
                    )
                )
                continue

            entries.append(
                UtEntry(
                    kind="test",
                    test_type="normal" if line[0] == "+" else "abnormal",
                    text=test_text,
                    line=line_no,
                )
            )
            continue

        if not asciidoc_lines:
            asciidoc_start_line = line_no
        asciidoc_lines.append(preserved_line)

    flush_asciidoc()
    return entries, diagnostics
