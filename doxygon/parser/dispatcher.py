#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file dispatcher.py Doxygonノード生成処理
"""

from __future__ import annotations

from doxygon.model.model import (
    CommandBlock,
    Node,
)
from doxygon.parser.command_registry import CommandRegistry
from doxygon.parser.parsed_command import ParsedCommand


"""!
@fn dispatch_command Doxygonノード生成処理
@brief 解析済みのDoxygonコマンドとコマンドブロックを統合し、Doxygonノードを生成する。
@param [in] parsed 解析済みDoxygonコマンド
@param [in] block 対象となるコマンドブロック
@param [in] registry Doxygonコマンド定義レジストリ
@return node 生成されたDoxygonノード
"""
def dispatch_command(
    *,
    parsed: ParsedCommand,
    block: CommandBlock,
    registry: CommandRegistry,
) -> Node:

    return Node(
        block_id=block.block_id,
        command=parsed.command,
        line_no=block.start_line,
        argument=_build_argument(parsed),
        body=block.body_lines.copy(),
        children=_build_inline_children(block),
        is_error=block.is_error,
        segments=block.segments.copy(),
    )


def _build_argument(parsed: ParsedCommand) -> str:
    parts: list[str] = []

    if parsed.direction:
        parts.append(parsed.direction)

    if parsed.name:
        parts.append(parsed.name)
    elif parsed.tag:
        parts.append(parsed.tag)

    if parsed.mail:
        parts.append(parsed.mail)

    if parsed.sentence:
        parts.append(parsed.sentence)

    return " ".join(parts)


def _build_inline_children(block: CommandBlock) -> list[Node]:
    children: list[Node] = []

    for child_lines in block.inline_children:
        if not child_lines:
            continue

        argument = child_lines[0]
        body = child_lines[1:] if len(child_lines) > 1 else []

        children.append(
            Node(
                block_id=block.block_id,
                command="inline",
                line_no=block.start_line,
                argument=argument,
                body=body,
            )
        )

    return children
