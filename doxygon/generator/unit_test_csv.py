#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file unit_test_csv.py 単体試験仕様CSV出力処理
"""

from __future__ import annotations

import csv
from pathlib import Path

from doxygon.model import (
    UtFileSpec,
    UtFunctionSpec,
    UtHeading,
    UtTestItem,
)


def _max_level(file_specs: list[UtFileSpec]) -> int:
    max_level = 0

    for file_spec in file_specs:
        for content in file_spec.contents:
            contents = (
                content.contents
                if isinstance(content, UtFunctionSpec)
                else [content]
            )

            for item in contents:
                if isinstance(item, (UtHeading, UtTestItem)):
                    max_level = max(max_level, item.level)

    return max_level


def _make_rows(
    *,
    file_name: str,
    file_title: str,
    function_name: str,
    function_title: str,
    contents: list[UtHeading | UtTestItem],
    max_level: int,
) -> list[list[str | int]]:
    rows: list[list[str | int]] = []
    headings: dict[int, str] = {}

    for content in contents:
        if isinstance(content, UtHeading):
            headings[content.level] = content.text

            for level in list(headings):
                if level > content.level:
                    del headings[level]

            continue

        if not isinstance(content, UtTestItem):
            continue

        level_columns = [
            headings.get(level, "")
            for level in range(1, max_level + 1)
        ]

        rows.append(
            [
                file_name,
                file_title,
                function_name,
                function_title,
                *level_columns,
                content.classification,
                content.text,
                content.line if content.line is not None else "",
            ]
        )

    return rows


"""!
@fn write_unit_test_csv 単体試験仕様CSV出力処理
@brief 階層解決済みの内部モデルを試験項目単位のCSVへ出力する。
@param [in] output_path CSV出力先パス
@param [in] file_specs 単体試験仕様ファイルモデル列
"""
def write_unit_test_csv(
    *,
    output_path: Path,
    file_specs: list[UtFileSpec],
) -> None:
    max_level = _max_level(file_specs)
    header = [
        "File",
        "File Title",
        "Function",
        "Function Title",
        *(f"Level {level}" for level in range(1, max_level + 1)),
        "Classification",
        "Test",
        "Source Line",
    ]

    rows: list[list[str | int]] = []

    for file_spec in file_specs:
        file_contents = [
            content
            for content in file_spec.contents
            if isinstance(content, (UtHeading, UtTestItem))
        ]
        rows.extend(
            _make_rows(
                file_name=file_spec.name,
                file_title=file_spec.title,
                function_name="",
                function_title="",
                contents=file_contents,
                max_level=max_level,
            )
        )

        for content in file_spec.contents:
            if not isinstance(content, UtFunctionSpec):
                continue

            rows.extend(
                _make_rows(
                    file_name=file_spec.name,
                    file_title=file_spec.title,
                    function_name=content.name,
                    function_title=content.title,
                    contents=content.contents,
                    max_level=max_level,
                )
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        writer.writerows(rows)
