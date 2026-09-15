#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file unit_test_builder.py 単体試験仕様内部モデル構築処理
"""

from __future__ import annotations

import re

from doxygon.model import (
    Node,
    UtFileSpec,
    UtFunctionSpec,
    UtHeading,
    UtTestItem,
)


_ASCII_WS_RE = re.compile(r"[ \t]+")


def _command_identity(argument: str) -> tuple[str, str]:
    text = (argument or "").strip(" \t")

    if not text:
        return "", ""

    parts = _ASCII_WS_RE.split(text, maxsplit=1)
    name = parts[0]
    title = parts[1].strip(" \t") if len(parts) > 1 else ""
    return name, title


"""!
@fn build_unit_test_file_spec 単体試験仕様ファイルモデル構築処理
@brief Doxygonノードを登場順に走査し、階層解決済みの内部モデルを構築する。
@param [in] source_filename 実ソースファイル名
@param [in] nodes Doxygonノード列
@return file_spec 単体試験仕様ファイルモデル
"""
def build_unit_test_file_spec(
    *,
    source_filename: str,
    nodes: list[Node],
) -> UtFileSpec:
    file_spec = UtFileSpec(
        name=source_filename,
        source_filename=source_filename,
    )
    current_function: UtFunctionSpec | None = None
    current_function_added = False
    current_heading_level = 0

    for node in nodes:
        if node.command == "file":
            file_name, file_title = _command_identity(node.argument)
            if file_name:
                file_spec.name = file_name
            file_spec.title = file_title
            current_function = None
            current_function_added = False
            continue

        if node.command == "fn":
            function_name, function_title = _command_identity(node.argument)
            current_function = UtFunctionSpec(
                name=function_name,
                title=function_title,
            )
            current_function_added = False
            current_heading_level = 0
            continue

        if node.command != "ut":
            continue

        if not node.ut_entries:
            continue

        if current_function is not None and not current_function_added:
            file_spec.contents.append(current_function)
            current_function_added = True

        target_contents = (
            current_function.contents
            if current_function is not None
            else file_spec.contents
        )

        for entry in node.ut_entries:
            if entry.kind == "heading" and entry.level is not None:
                current_heading_level = entry.level
                target_contents.append(
                    UtHeading(
                        level=current_heading_level,
                        text=entry.text,
                        line=entry.line,
                    )
                )
                continue

            if entry.kind == "test":
                target_contents.append(
                    UtTestItem(
                        level=current_heading_level,
                        classification=entry.test_type or "normal",
                        text=entry.text,
                        line=entry.line,
                    )
                )

    return file_spec
