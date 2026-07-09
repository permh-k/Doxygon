#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file model.py Doxygonデータモデル定義ファイル
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field


"""!
@class TextSegment 本文セグメント格納クラス
"""
@dataclass(slots=True)
class TextSegment:
    lines: list[str]

"""!
@class DelimSegment 除外ブロック格納クラス
@attention '........' で囲まれた範囲を解析対象除外ブロックとする。
"""
@dataclass(slots=True)
class DelimSegment:
    lines: list[str]
    is_error: bool = False


Segment = TextSegment | DelimSegment


"""!
@class CommandBlock コマンドブロック格納クラス
"""
@dataclass(slots=True)
class CommandBlock:
    block_id: int

    command_line: str
    body_lines: list[str]

    segments: list[Segment]

    start_line: int
    is_error: bool = False

    inline_children: list[list[str]] = field(default_factory=list)


"""!
@class FunctionBlock 関数ブロック格納クラス
"""
@dataclass(slots=True)
class FunctionBlock:
    name: str

    function_start: int
    signature_end: int
    function_end: int

    # Original source line numbers before Doxygon comments are removed.
    # These are used only when mapping inline comments back to the physical
    # function/class that owns them.  The normal line numbers above refer to
    # the generated clean source.
    original_function_start: int | None = None
    original_signature_end: int | None = None
    original_function_end: int | None = None

"""!
@class GlobalBlock グローバルソースブロック格納クラス
"""
@dataclass(slots=True)
class GlobalBlock:
    name: str

    start_line: int
    end_line: int

"""!
@class Diagnostic 未定義コマンド格納クラス
"""
@dataclass(slots=True)
class Diagnostic:
    level: str
    message: str
    line: int | None = None


"""!
@class Node Doxygon文書構造ノード格納クラス
"""
@dataclass(slots=True)
class Node:
    block_id: int

    command: str
    line_no: int | None = None
    argument: str = ""

    body: list[str] | None = None
    children: list["Node"] | None = None

    is_error: bool = False
    is_container: bool = False

    segments: list[Segment] | None = None

    diagnostics: list[Diagnostic] = field(default_factory=list)

    def __post_init__(self):
        if self.body is None:
            self.body = []
        if self.children is None:
            self.children = []
        if self.segments is None:
            self.segments = []


"""!
@class SourceUnit ソースコード情報格納クラス
"""

@dataclass(slots=True)
class SourceUnit:
    path: Path
    language: str
    extension: str
    rouge_ext: str

    container_commands: list[str]

    dox_block_start: list[str]
    dox_block_end: list[str]
    dox_inline_start: list[str]
    dox_inline_end: list[str]

    raw_lines: list[str]
