#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file preproc.py Doxygonコメント抽出処理
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from doxygon.model.model import (
    CommandBlock,
    DelimSegment,
    Segment,
    TextSegment,
)

def _extract_command_name(command_line: str) -> str:
    m = re.match(r"^\s*@([A-Za-z_][A-Za-z0-9_]*)\b", command_line)

    if not m:
        return ""

    return m.group(1).lower()

def _can_continue_command_header(command_line: str) -> bool:
    command_name = _extract_command_name(command_line)
    return command_name == "author"

def _find_unquoted_token(text: str, token: str, start: int = 0) -> int:
    """Return token position outside double quotes, or -1.

    Doxygon comments may describe comment markers themselves, e.g.
        "/**!< ... */"
    In that case the markers inside quotes must not be treated as real
    comment start/end tokens.
    """
    if not token:
        return -1

    in_double_quote = False
    escaped = False

    i = start
    n = len(text)

    while i < n:
        ch = text[i]

        if escaped:
            escaped = False
            i += 1
            continue

        if ch == "\\":
            escaped = True
            i += 1
            continue

        if ch == '"':
            in_double_quote = not in_double_quote
            i += 1
            continue

        if not in_double_quote and text.startswith(token, i):
            return i

        i += 1

    return -1




def _find_inline_start_token(text: str, token: str) -> int:
    # Python inline Doxygon comments use triple-quote tokens such as
    #     code """!< @var ...
    # These tokens intentionally look like string/comment delimiters, so the
    # generic unquoted-token scanner would hide them after seeing the first
    # quote.  For quote-style inline tokens, use a plain search.
    if token.startswith(('"""', "'''")):
        return text.find(token)

    return _find_unquoted_token(text, token)


def _split_at_inline_end_token(text: str, token: str) -> tuple[str, bool]:
    # Match the start-token behavior: Python triple-quote inline comments end
    # at the next triple-quote token, while C-like inline comments should still
    # ignore terminators inside double quotes.
    if token in {'"""', "'''"}:
        pos = text.find(token)

        if pos == -1:
            return text, False

        return text[:pos], True

    return _split_at_unquoted_token(text, token)


def _is_quote_block_token(token: str) -> bool:
    return token in {'"""', "'''"}


def _find_block_end_token(text: str, token: str) -> int:
    if _is_quote_block_token(token):
        return text.find(token)

    return _find_unquoted_token(text, token)


def _split_at_block_end_token(text: str, token: str) -> tuple[str, bool]:
    pos = _find_block_end_token(text, token)

    if pos == -1:
        return text, False

    return text[:pos], True


def _split_at_unquoted_token(text: str, token: str) -> tuple[str, bool]:
    pos = _find_unquoted_token(text, token)

    if pos == -1:
        return text, False

    return text[:pos], True


# ==========================================================
# 汎用：識別子抽出（言語非依存）
# ==========================================================

def _extract_member_name(line: str, inline_start: str) -> str:
    pos = line.find(inline_start)
    if pos == -1:
        return ""

    left = line[:pos]

    # 文字列リテラル除去
    left = re.sub(r'".*?"', "", left)
    left = re.sub(r"'.*?'", "", left)

    # 配列添字除去
    left = re.sub(r"\[[^\]]*\]", "", left)

    # TypeScript property:
    #   public stock: number; /**!< ... */
    # The old token based extraction returned the type name (number).
    # Prefer the identifier immediately before ':' when a type annotation exists.
    m = re.search(
        r"([A-Za-z_$][A-Za-z0-9_$]*)\s*[?!]?\s*:\s*[^;=,(){}]+;?\s*$",
        left.strip(),
    )
    if m:
        return m.group(1)

    tokens = re.split(r"[^A-Za-z0-9_$]", left)
    tokens = [t for t in tokens if t]

    return tokens[-1] if tokens else ""


def _is_delim_line(line: str, separator: str) -> bool:
    # return separator in line
    return line.strip() == separator


def _is_command_line(line: str) -> bool:
    return re.match(r"^\s*@[A-Za-z_][A-Za-z0-9_]*\b", line) is not None


def _is_known_command_line(
    line: str,
    known_commands: set[str],
) -> bool:
    """Return True when the line starts with a registered Doxygon command."""

    command_name = _extract_command_name(line)

    if not command_name:
        return False

    return command_name in known_commands


# ==========================================================
# block 整形
# ==========================================================

def _strip_vba_quote_prefix(
    raw_block: list[str],
    *,
    start_token: str,
    end_token: str,
) -> tuple[list[str], str, str]:
    """Strip VBA comment quote prefix and normalize block tokens.

    VBA Doxygon block comments are written as quoted comment lines, e.g.

        '/**!
        '@file ...
        '*/

    Once the leading quote is removed from the block lines, the corresponding
    start/end tokens must be normalized as well.  Otherwise later block
    normalization still searches for quoted tokens such as ``'/**!`` and
    ``'*/`` against already-unquoted lines.
    """

    if not raw_block:
        return raw_block, start_token, end_token

    first_line = raw_block[0].lstrip()

    if not first_line.startswith("'"):
        return raw_block, start_token, end_token

    new_block: list[str] = []

    for line in raw_block:
        stripped = line.lstrip()

        if stripped.startswith("'"):
            pos = line.find("'")
            line = line[:pos] + line[pos + 1:]

        new_block.append(line)

    if start_token.startswith("'"):
        start_token = start_token[1:]

    if end_token.startswith("'"):
        end_token = end_token[1:]

    return new_block, start_token, end_token


def _normalize_raw_block(
    raw_block: list[str],
    *,
    start_token: str,
    end_token: str,
) -> list[str]:
    block_lines: list[str] = []

    for idx, raw in enumerate(raw_block):
        s = raw.lstrip()

        if idx == 0:
            s = s[len(start_token):]

        s, _found_end = _split_at_block_end_token(s, end_token)

        block_lines.append(s.rstrip())

    return block_lines


# ==========================================================
# segment 操作
# ==========================================================

def _append_text_segment(
    segments: list[Segment],
    text_lines: list[str],
) -> None:
    if not text_lines:
        return

    segments.append(TextSegment(lines=text_lines.copy()))
    text_lines.clear()


def _flatten_text_segments(segments: list[Segment]) -> list[str]:
    lines: list[str] = []

    for seg in segments:
        if isinstance(seg, TextSegment):
            lines.extend(seg.lines)

    return lines


def _make_command_block(
    *,
    block_id: int,
    command_line: str,
    start_line: int,
) -> CommandBlock:
    return CommandBlock(
        block_id=block_id,
        command_line=command_line.strip(),
        body_lines=[],
        segments=[],
        start_line=start_line,
        is_error=False,
        inline_children=[],
    )


def _inline_to_command_line(
    *,
    source_line: str,
    inline_start: str,
    inline_text: str,
) -> str:
    text = (inline_text or "").strip()

    if not text:
        return ""

    if _is_command_line(text):
        return text

    name = _extract_member_name(source_line, inline_start)

    if name:
        return f"@var {name} {text}".strip()

    return text


# ==========================================================
# CommandBlock 分割
# ==========================================================

"""!
@fn _split_block_lines_to_command_blocks Doxygonコマンド分割処理
@brief コメントブロックをDoxygonコマンドごとのコマンドブロックへ分割する。
@param [in] block_id コメントブロックID
@param [in] block_lines 正規化済みコメント行
@param [in] start_line ブロック開始行
@param [in] delim_separator 除外ブロック用セパレータ
@return command_blocks 分割されたコマンドブロック一覧
"""
def _split_block_lines_to_command_blocks(
    block_lines: list[str],
    *,
    start_line: int,
    separator: str,
    block_id_start: int,
    known_commands: set[str] | None = None,
) -> tuple[list[CommandBlock], int]:

    blocks: list[CommandBlock] = []

    block_id = block_id_start
    line_offset = 0

    command_line: str | None = None
    command_start_line: int = start_line

    segments: list[Segment] = []
    text_buffer: list[str] = []

    in_delim = False
    delim_lines: list[str] = []

    current_is_error = False
    known_commands = known_commands or set()

    def flush_current_command() -> None:
        nonlocal block_id
        nonlocal command_line
        nonlocal command_start_line
        nonlocal segments
        nonlocal text_buffer
        nonlocal current_is_error

        if command_line is None:
            text_buffer.clear()
            segments = []
            current_is_error = False
            return

        _append_text_segment(segments, text_buffer)

        body_lines = _flatten_text_segments(segments)

        blocks.append(
            CommandBlock(
                block_id=block_id,
                command_line=command_line,
                body_lines=body_lines,
                segments=segments,
                start_line=command_start_line,
                is_error=current_is_error,
                inline_children=[],
            )
        )

        block_id += 1

        command_line = None
        command_start_line = start_line
        segments = []
        text_buffer = []
        current_is_error = False

    idx = 0
    while idx < len(block_lines):
        line = block_lines[idx]

        # --------------------------------------------------
        # DELIM separator
        # --------------------------------------------------
        if _is_delim_line(line, separator):
            if not in_delim:
                _append_text_segment(segments, text_buffer)

                in_delim = True
                delim_lines = []
            else:
                segments.append(
                    DelimSegment(
                        lines=delim_lines.copy(),
                        is_error=False,
                    )
                )

                delim_lines = []
                in_delim = False

            line_offset += 1
            idx += 1
            continue

        # --------------------------------------------------
        # DELIM 内部
        # --------------------------------------------------
        if in_delim:
            if _is_known_command_line(line, known_commands):
                # A registered Doxygon command inside an open DELIM block is
                # treated as a missing closing delimiter.  UNKNOWN commands,
                # such as @startuml/@enduml, intentionally remain hidden in
                # DELIM payloads.
                segments.append(
                    DelimSegment(
                        lines=delim_lines.copy(),
                        is_error=True,
                    )
                )
                delim_lines = []
                in_delim = False
                current_is_error = True
                continue

            delim_lines.append(line)
            line_offset += 1
            idx += 1
            continue

        # --------------------------------------------------
        # command line
        # --------------------------------------------------
        if _is_command_line(line):
            flush_current_command()

            command_line = line.strip()
            command_start_line = start_line + line_offset

            # ----------------------------------------------
            # header continuation
            # ----------------------------------------------
            if _can_continue_command_header(command_line):
                next_idx = idx + 1

                if next_idx < len(block_lines):
                    next_line = block_lines[next_idx]
                    next_line_stripped = next_line.strip()

                    if (
                        next_line_stripped
                        and not _is_command_line(next_line)
                        and not _is_delim_line(next_line, separator)
                    ):
                        command_line = (
                            command_line.rstrip()
                            + " "
                            + next_line_stripped
                        )

                        line_offset += 1
                        idx += 1

            line_offset += 1
            idx += 1
            continue

        # --------------------------------------------------
        # normal text line
        # --------------------------------------------------
        text_buffer.append(line)
        line_offset += 1
        idx += 1

    # ------------------------------------------------------
    # 除外ブロック終端処理
    # ------------------------------------------------------
    if in_delim:
        segments.append(
            DelimSegment(
                lines=delim_lines.copy(),
                is_error=True,
            )
        )
        current_is_error = True

    flush_current_command()

    return blocks, block_id


"""!
@fn preprocess Doxygonコメント抽出前処理
@brief コメントブロック、除外ブロックからコマンドブロックを生成する。
@param [in] lines ソースコード行リスト
@param [in] block_starts ブロックコメント開始トークン
@param [in] block_ends ブロックコメント終了トークン
@param [in] inline_starts インラインコメント開始トークン
@param [in] inline_ends インラインコメント終了トークン
@param [in] container_commands コンテナコマンド一覧
@param [in] delim_separator 除外ブロック用セパレータ
@return command_blocks 抽出されたコマンドブロック一覧
"""
def preprocess(
    lines: list[str],
    *,
    block_starts: list[str],
    block_ends: list[str],
    inline_starts: list[str],
    inline_ends: list[str],
    container_commands: list[str],
    delim_separator: str,
    known_commands: Iterable[str] | None = None,
) -> list[CommandBlock]:

    if len(block_starts) != len(block_ends):
        raise ValueError("block_starts and block_ends must match")

    if len(inline_starts) != len(inline_ends):
        raise ValueError("inline_starts and inline_ends must match")

    result: list[CommandBlock] = []

    n = len(lines)
    i = 0
    block_id = 0

    current_container: CommandBlock | None = None
    container_set = {c.lower().lstrip("@") for c in container_commands}
    known_command_set = {c.lower().lstrip("@") for c in (known_commands or [])}

    while i < n:
        line = lines[i]
        stripped = line.lstrip()

        # ==================================================
        # inline処理
        # --------------------------------------------------
        # /**!< は block_start(/**!) にも前方一致するため、
        # block 開始判定より先に処理する。
        #
        # V4 方針:
        #   - inline 内の @command は通常の CommandBlock として扱う。
        #   - @var も特別に捨てず、通常の @var CommandBlock とする。
        #   - @command でない inline member 説明は @var に正規化する。
        #
        # これにより、inline 内の @author / @note なども parser/generator
        # の通常経路に乗り、人知れず消えない。
        # ==================================================
        handled_inline = False

        for start, end in zip(inline_starts, inline_ends):
            pos = _find_inline_start_token(line, start)

            if pos == -1:
                continue

            content = line[pos + len(start):]

            content, _found_inline_end = _split_at_inline_end_token(content, end)

            inline = content.strip()
            command_line = _inline_to_command_line(
                source_line=line,
                inline_start=start,
                inline_text=inline,
            )

            if command_line:
                result.append(
                    _make_command_block(
                        block_id=block_id,
                        command_line=command_line,
                        start_line=i + 1,
                    )
                )
                block_id += 1

            handled_inline = True
            break

        if handled_inline:
            i += 1
            continue

        # ==================================================
        # block開始判定
        # ==================================================
        matched = None

        for idx, start_token in enumerate(block_starts):
            if stripped.startswith(start_token):
                matched = idx
                break

        if matched is not None:
            start_token = block_starts[matched]
            end_token = block_ends[matched]

            raw_block: list[str] = []
            j = i
            stopped_at_next_block = False

            # ------------------------------------------
            # block抽出
            # ------------------------------------------
            while j < n:
                raw = lines[j]
                s = raw.lstrip()

                # block 内で次の block 開始が出たら、現在ブロックは
                # 終端未検出として打ち切る。ただし次ブロック開始行は
                # 消費せず、次のループで改めて処理する。
                if j != i and any(s.startswith(x) for x in block_starts):
                    stopped_at_next_block = True
                    break

                check = s
                if j == i:
                    check = s[len(start_token):]

                raw_block.append(raw)

                if _find_block_end_token(check, end_token) != -1:
                    break

                j += 1

            # ------------------------------------------
            # VBA コメント prefix 除去
            # ------------------------------------------
            raw_block, start_token, end_token = _strip_vba_quote_prefix(
                raw_block,
                start_token=start_token,
                end_token=end_token,
            )

            # ------------------------------------------
            # block 整形
            # ------------------------------------------
            block_lines = _normalize_raw_block(
                raw_block,
                start_token=start_token,
                end_token=end_token,
            )

            # ------------------------------------------
            # @command 単位に分割
            # ------------------------------------------
            command_blocks, block_id = _split_block_lines_to_command_blocks(
                block_lines,
                start_line=i + 1,
                separator=delim_separator,
                block_id_start=block_id,
                known_commands=known_command_set,
            )

            result.extend(command_blocks)

            # ------------------------------------------
            # container 再設定
            # ------------------------------------------
            for block in command_blocks:
                command_name = _extract_command_name(block.command_line)

                if command_name in container_set:
                    current_container = block
                    break

            if stopped_at_next_block:
                i = j
            else:
                i = j + 1
            continue

        i += 1

    return result


