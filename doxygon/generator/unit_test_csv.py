#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file unit_test_csv.py 単体試験仕様CSV出力処理
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from doxygon.model import (
    UtFileSpec,
    UtFunctionSpec,
    UtAsciiDoc,
    UtHeading,
    UtTestItem,
    UtValueBlock,
)


_COMPARISON_TEXT = {
    "!=": "{value} 以外の値",
    "<": "{value} より小さい値",
    "<=": "{value} 以下の値",
    ">": "{value} より大きい値",
    ">=": "{value} 以上の値",
}


def _quoted_value(value: str) -> str:
    text = value.strip()

    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text

    return f'"{text}"'


def _value_subject(content: UtValueBlock) -> str:
    subject = content.owner_title or content.owner_name

    if content.condition.index:
        subject = f"{subject}[{content.condition.index}]"

    return subject


def _value_heading(content: UtValueBlock) -> str:
    subject = _value_subject(content)

    if content.owner_title and content.owner_name:
        name = content.owner_name

        if content.condition.index:
            name = f"{name}[{content.condition.index}]"

        return f"{subject}（{name}）"

    return subject


def _condition_text(content: UtValueBlock) -> str:
    condition = content.condition

    if condition.kind == "range":
        return (
            f"{_quoted_value(condition.lower)} 以上 "
            f"{_quoted_value(condition.upper)} 以下の値"
        )

    if condition.kind == "comparison":
        return _COMPARISON_TEXT[condition.operator].format(
            value=_quoted_value(condition.value),
        )

    return _quoted_value(condition.value)


def _parameter_condition_text(content: UtValueBlock) -> str:
    condition = content.condition

    if condition.kind == "range":
        return (
            f"{_quoted_value(condition.lower)} 以上 "
            f"{_quoted_value(condition.upper)} 以下"
        )

    if condition.kind == "comparison":
        return _COMPARISON_TEXT[condition.operator].format(
            value=_quoted_value(condition.value),
        ).removesuffix("の値")

    return _quoted_value(condition.value)


def _value_section_heading(content: UtValueBlock) -> str:
    if content.owner_command == "return":
        return "戻り値の確認"

    if content.direction == "[out]":
        return "出力値の確認"

    if content.direction in {"[in,out]", "[out,in]"}:
        return "入出力値の確認"

    return "入力値の確認"


"""!
@fn _generated_test_text 値条件試験内容生成処理
@brief "@value"の所有元、方向および条件から試験内容を生成する。
@param [in] content 値条件試験ブロック
@return test_text 生成された試験内容
"""
def _generated_test_text(content: UtValueBlock) -> str:
    condition = content.condition
    condition_text = _condition_text(content)

    if content.owner_command == "return":
        text = f"{condition_text} が返されることを確認する。"

        if condition.kind == "range":
            text += (
                f"あわせて、{_quoted_value(condition.lower)} より小さい値および "
                f"{_quoted_value(condition.upper)} より大きい値が返される場合も確認する。"
            )

        return text

    subject = _value_subject(content)
    parameter_condition_text = _parameter_condition_text(content)

    if content.direction == "[out]":
        if condition.kind == "range":
            return (
                f"「{subject}」が {_quoted_value(condition.lower)} 以上 "
                f"{_quoted_value(condition.upper)} 以下の範囲となることを確認する。"
            )

        separator = " " if condition.kind == "exact" else ""
        return (
            f"「{subject}」が {parameter_condition_text}{separator}"
            "となることを確認する。"
        )

    separator = " " if condition.kind == "exact" else ""
    text = (
        f"「{subject}」が {parameter_condition_text}{separator}のときの処理を確認する。"
    )

    if condition.kind == "range":
        text += (
            f"あわせて、{_quoted_value(condition.lower)} より小さい場合および "
            f"{_quoted_value(condition.upper)} より大きい場合の処理も確認する。"
        )

    return text


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
                if isinstance(item, (UtHeading, UtTestItem, UtAsciiDoc)):
                    max_level = max(max_level, item.level)
                elif isinstance(item, UtValueBlock):
                    max_level = max(max_level, 2)

    return max_level


"""!
@fn _make_rows 単体試験仕様CSV行生成処理
@brief 単体試験仕様要素を見出し階層が展開されたCSV行へ変換する。
@param [in] file_name ファイル名
@param [in] file_title ファイル和名
@param [in] function_name 関数名
@param [in] function_title 関数和名
@param [in] contents 単体試験仕様要素列
@param [in] max_level 最大見出しレベル
@return rows CSV出力行列
"""
def _make_rows(
    *,
    file_name: str,
    file_title: str,
    function_name: str,
    function_title: str,
    contents: list[UtHeading | UtTestItem | UtAsciiDoc | UtValueBlock],
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

        if isinstance(content, UtValueBlock):
            headings[1] = _value_section_heading(content)
            headings[2] = _value_heading(content)

            for level in list(headings):
                if level > 2:
                    del headings[level]

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
                    "test",
                    "normal",
                    _generated_test_text(content),
                    content.line if content.line is not None else "",
                ]
            )

            for item in content.condition.contents:
                item_lines = (
                    item.text.replace("\r\n", "\n")
                    .replace("\r", "\n")
                    .rstrip("\n")
                    .split("\n")
                    if item.kind == "asciidoc"
                    else [item.text]
                )

                for offset, item_line in enumerate(item_lines):
                    if item.kind == "asciidoc" and not item_line.strip():
                        continue

                    source_line = (
                        item.line + offset
                        if item.line is not None
                        else ""
                    )
                    rows.append(
                        [
                            file_name,
                            file_title,
                            function_name,
                            function_title,
                            *level_columns,
                            item.kind,
                            item.classification or "",
                            item_line,
                            source_line,
                        ]
                    )

            continue

        if isinstance(content, UtAsciiDoc):
            level_columns = [
                headings.get(level, "") if level <= content.level else ""
                for level in range(1, max_level + 1)
            ]
            content_lines = (
                content.text.replace("\r\n", "\n")
                .replace("\r", "\n")
                .rstrip("\n")
                .split("\n")
            )

            for offset, content_line in enumerate(content_lines):
                if not content_line.strip():
                    continue

                rows.append(
                    [
                        file_name,
                        file_title,
                        function_name,
                        function_title,
                        *level_columns,
                        "asciidoc",
                        "",
                        content_line,
                        (
                            content.line + offset
                            if content.line is not None
                            else ""
                        ),
                    ]
                )

            continue

        if not isinstance(content, UtTestItem):
            continue

        level_columns = [
            headings.get(level, "") if level <= content.level else ""
            for level in range(1, max_level + 1)
        ]

        rows.append(
            [
                file_name,
                file_title,
                function_name,
                function_title,
                *level_columns,
                "test",
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
@param [in] encoding CSV文字コード
"""
def write_unit_test_csv(
    *,
    output_path: Path,
    file_specs: list[UtFileSpec],
    encoding: str = "cp932",
) -> None:
    max_level = _max_level(file_specs)
    header = [
        "File",
        "File Title",
        "Function",
        "Function Title",
        *(f"Level {level}" for level in range(1, max_level + 1)),
        "Content Type",
        "Classification",
        "Content",
        "Source Line",
    ]

    rows: list[list[str | int]] = []

    for file_spec in file_specs:
        file_contents = [
            content
            for content in file_spec.contents
            if isinstance(content, (UtHeading, UtTestItem, UtAsciiDoc, UtValueBlock))
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

    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(header)
    writer.writerows(rows)

    try:
        csv_bytes = csv_buffer.getvalue().encode(encoding, errors="strict")
    except UnicodeEncodeError as error:
        unsupported = error.object[error.start:error.end]
        raise ValueError(
            f"CSVを{encoding}で出力できません。"
            f"未対応文字: {unsupported!r}"
        ) from error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(csv_bytes)
