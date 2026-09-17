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
    UtAsciiDoc,
    UtHeading,
    UtTestItem,
    UtValueBlock,
)


_ASCII_WS_RE = re.compile(r"[ \t]+")
_PARAM_RE = re.compile(
    r"^(?P<direction>\[(?:in|out|in,out)\])[ \t]+"
    r"(?P<name>\S+)(?:[ \t]+(?P<description>.*))?$"
)


def _command_identity(argument: str) -> tuple[str, str]:
    text = (argument or "").strip(" \t")

    if not text:
        return "", ""

    parts = _ASCII_WS_RE.split(text, maxsplit=1)
    name = parts[0]
    title = parts[1].strip(" \t") if len(parts) > 1 else ""
    return name, title


def _param_identity(argument: str) -> tuple[str, str, str] | None:
    """Return a parameter direction, name, and description."""

    match = _PARAM_RE.fullmatch((argument or "").strip(" \t"))

    if match is None:
        return None

    return (
        match.group("direction"),
        match.group("name"),
        (match.group("description") or "").strip(" \t"),
    )


"""!
@fn build_unit_test_file_spec 単体試験仕様ファイルモデル構築処理
@brief Doxygonノードを登場順に走査し、階層解決済みの内部モデルを構築する。
@param [in] source_filename 実ソースファイル名
@param [in] nodes Doxygonノード列
@param [in] auto_generate 引数の値定義から試験項目を自動生成する場合は"True"
@return file_spec 単体試験仕様ファイルモデル
"""
def build_unit_test_file_spec(
    *,
    source_filename: str,
    nodes: list[Node],
    auto_generate: bool = False,
) -> UtFileSpec:
    file_spec = UtFileSpec(
        name=source_filename,
        source_filename=source_filename,
    )
    current_function: UtFunctionSpec | None = None
    current_function_added = False
    current_heading_level = 0
    current_owner: tuple[str, str, str, str] | None = None
    auto_contents: list[UtValueBlock] = []

    def flush_auto_contents() -> None:
        nonlocal current_function_added

        if not auto_contents:
            return

        if current_function is not None:
            if not current_function_added:
                file_spec.contents.append(current_function)
                current_function_added = True
            current_function.contents.extend(auto_contents)
        else:
            file_spec.contents.extend(auto_contents)

        auto_contents.clear()

    for node in nodes:
        if node.command in {"file", "fn"}:
            flush_auto_contents()

        if node.command == "file":
            file_name, file_title = _command_identity(node.argument)
            if file_name:
                file_spec.name = file_name
            file_spec.title = file_title
            current_function = None
            current_function_added = False
            current_owner = None
            continue

        if node.command == "fn":
            function_name, function_title = _command_identity(node.argument)
            current_function = UtFunctionSpec(
                name=function_name,
                title=function_title,
            )
            current_function_added = False
            current_heading_level = 0
            current_owner = None
            continue

        if auto_generate and node.command == "param":
            identity = _param_identity(node.argument)
            current_owner = (
                ("param", identity[1], identity[2], identity[0])
                if identity is not None
                else None
            )
            continue

        if auto_generate and node.command == "return":
            name, title = _command_identity(node.argument)
            current_owner = ("return", name, title, "") if name else None
            continue

        if auto_generate and node.command == "value":
            if (
                current_owner is None
                or node.is_error
                or node.value_entry is None
            ):
                continue

            owner_command, owner_name, owner_title, direction = current_owner
            auto_contents.append(
                UtValueBlock(
                    owner_command=owner_command,
                    owner_name=owner_name,
                    owner_title=owner_title,
                    direction=direction,
                    condition=node.value_entry,
                    line=node.line_no,
                )
            )
            continue

        current_owner = None

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
                continue

            if entry.kind == "asciidoc":
                target_contents.append(
                    UtAsciiDoc(
                        level=current_heading_level,
                        text=entry.text,
                        line=entry.line,
                    )
                )

    flush_auto_contents()
    return file_spec
