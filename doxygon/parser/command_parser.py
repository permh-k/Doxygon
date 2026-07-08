#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file command_parser.py Doxygonコマンド解析処理
"""

from __future__ import annotations

from pathlib import Path
import re

from lark import Lark, UnexpectedInput

from doxygon.model.model import CommandBlock, Diagnostic, Node
from doxygon.parser.command_registry import CommandRegistry
from doxygon.parser.command_transformer import CommandTransformer
from doxygon.parser.diagnostics_scanner import (
    scan_invalid_tag_commands,
)
from doxygon.parser.dispatcher import dispatch_command


"""!
@fn parse_command_blocks Doxygonコマンド解析処理
@brief コマンドブロックをLarkで解析し、Doxygonノードへ変換する。
@param [in] command_blocks 解析対象のコマンドブロック
@param [in] command_lark_path Doxygonコマンド構文定義ファイルのパス
@param [in] command_toml_path Doxygonコマンド定義ファイルのパス
@param [in] container_commands コンテナとして扱うコマンド一覧
@return nodes 生成されたDoxygonノード
"""
def parse_command_blocks(
    command_blocks: list[CommandBlock],
    *,
    command_lark_path: Path,
    command_toml_path: Path,
    container_commands: list[str],
) -> list[Node]:

    grammar = command_lark_path.read_text(encoding="utf-8")

    parser = Lark(
        grammar,
        parser="lalr",
        start="start",
        maybe_placeholders=False,
    )

    registry = CommandRegistry.from_toml(command_toml_path)
    container_set = {c.lower().lstrip("@") for c in container_commands}

    nodes: list[Node] = []
    file_seen = False

    for block in command_blocks:
        unknown_node = _make_unknown_command_node(
            block=block,
            registry=registry,
        )

        if unknown_node is not None:
            node = unknown_node
        else:
            try:
                tree = parser.parse(block.command_line)
                parsed = CommandTransformer(
                    block_id=block.block_id,
                    raw_line=block.command_line,
                ).transform(tree)

            except UnexpectedInput as e:
                node = _make_known_command_fallback_node(
                    block=block,
                    registry=registry,
                )

                if node is None:
                    node = Node(
                        block_id=block.block_id,
                        command="__syntax_error__",
                        line_no=block.start_line,
                        argument=block.command_line,
                        body=block.body_lines.copy(),
                        children=_build_inline_children_fallback(block),
                        is_error=True,
                        segments=block.segments.copy(),
                    )
                    node.diagnostics.append(
                        Diagnostic(
                            level="error",
                            message=str(e),
                            line=block.start_line,
                        )
                    )
                    nodes.append(node)
                    continue

            else:
                node = dispatch_command(
                    parsed=parsed,
                    block=block,
                    registry=registry,
                )

        if block.is_error:
            node.is_error = True
            node.diagnostics.append(
                Diagnostic(
                    level="error",
                    message="unterminated DELIM block",
                    line=block.start_line,
                )
            )

        if node.command in container_set:
            node.is_container = True

        diagnostics = _scan_node_text(
            node=node,
            block=block,
            registry=registry,
        )

        node.diagnostics.extend(diagnostics)

        if diagnostics:
            node.is_error = True

        # @file is a file-level command and must appear at most once.
        # Keep the first @file as the file node.  Convert subsequent @file
        # nodes to duplicate diagnostics so generator can display them instead
        # of silently ignoring them via _render_file().
        if node.command == "file":
            if file_seen:
                node.command = "duplicate"
                node.is_error = True
            else:
                file_seen = True

        nodes.append(node)

    return nodes


_KNOWN_COMMAND_LINE_RE = re.compile(r"^\s*@([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?\s*$")


def _make_unknown_command_node(
    *,
    block: CommandBlock,
    registry: CommandRegistry,
) -> Node | None:
    """Return an UNKNOWN node when the command token is not registered.

    Command spelling must be checked before Lark syntax matching.  Otherwise
    typo commands such as ``@pararm`` may be partially matched as ``@par``
    and reported as a misleading syntax error.
    """

    m = _KNOWN_COMMAND_LINE_RE.match(block.command_line or "")
    if not m:
        return None

    command = m.group(1).lower()
    argument = (m.group(2) or "").strip()

    if registry.is_known(command):
        return None

    return Node(
        block_id=block.block_id,
        command=command,
        line_no=block.start_line,
        argument=argument,
        body=block.body_lines.copy(),
        children=_build_inline_children_fallback(block),
        is_error=block.is_error,
        segments=block.segments.copy(),
    )
_BODY_STYLE_FALLBACK_COMMANDS = {
    "brief",
    "details",
    "note",
    "warning",
    "attention",
    "important",
    "tip",
    "todo",
    "deprecated",
}


def _make_known_command_fallback_node(
    *,
    block: CommandBlock,
    registry: CommandRegistry,
) -> Node | None:
    """Return a normal node for a known command when grammar rejects it.

    Lark checks the formal command-line syntax.  Doxygon's rendering policy,
    however, is to preserve registered commands as documents whenever possible.
    Therefore a line whose first token is a known @command is kept as a normal
    node instead of being reported as UNKNOWN only because the grammar did not
    anticipate that position or a body-only form such as '@details'.
    """

    m = _KNOWN_COMMAND_LINE_RE.match(block.command_line or "")
    if not m:
        return None

    command = m.group(1).lower()
    argument = (m.group(2) or "").strip()

    if not registry.is_known(command):
        return None

    # Keep Lark as the syntax checker for commands with strict arguments
    # such as @param or @author.  The fallback is only for body-style
    # commands that may reasonably be written as a command line followed by
    # body text, e.g. @details.
    if command not in _BODY_STYLE_FALLBACK_COMMANDS:
        return None

    return Node(
        block_id=block.block_id,
        command=command,
        argument=argument,
        body=block.body_lines.copy(),
        children=_build_inline_children_fallback(block),
        is_error=block.is_error,
        segments=block.segments.copy(),
    )


def _build_inline_children_fallback(block: CommandBlock) -> list[Node]:
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
                argument=argument,
                body=body,
            )
        )

    return children


"""!
@fn _scan_node_text 未定義コマンド検出処理
@brief Doxygonノードの先頭コマンド自体と、コマンド固有の追加診断を行う。
@param [in] node 対象となるDoxygonノード
@param [in] block 対象となるコマンドブロック
@param [in] registry Doxygonコマンド定義レジストリ
@return diagnostics 検出された診断一覧
"""
def _scan_node_text(
    *,
    node: Node,
    block: CommandBlock,
    registry: CommandRegistry,
) -> list[Diagnostic]:

    diagnostics: list[Diagnostic] = []

    # Doxygon command recognition is line-head only.
    # Once the leading command token has been parsed, @xxx appearing in the
    # argument/body is user-authored text, not another Doxygon command.
    # Therefore do not scan node.argument or node.body for UNKNOWN/extra
    # command tokens here.
    #
    # Example:
    #   @brief 代表的な @command を混在させる試験。
    #
    # The @command in the sentence must remain plain text.

    # unknown_command 自体
    if not registry.is_known(node.command):
        diagnostics.append(
            Diagnostic(
                level="error",
                message=f"unknown command: @{node.command}",
                line=block.start_line,
            )
        )

    diagnostics.extend(
        scan_invalid_tag_commands(
            command=node.command,
            argument=node.argument,
            line=block.start_line,
        )
    )

    return diagnostics
