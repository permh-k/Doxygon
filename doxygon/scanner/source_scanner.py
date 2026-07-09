#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file source_scanner.py ソースコード解析処理
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

from doxygon.model import FunctionBlock, GlobalBlock, SourceUnit
from doxygon.common.token_utils import find_unquoted_token
from doxygon.scanner.language_spec import get_language_spec


@dataclass(slots=True)
class SourceBlock:
    kind: Literal["global", "function", "container", "declaration"]
    name: str
    start_line: int
    end_line: int



"""!
@fn scan_sources ソースコード情報生成処理
@brief 入力フォルダから対象言語のソースコードを探索し、ソースコード情報を生成する。
@param [in] input_dir 対象となるソースファイル格納フォルダ
@param [in] languages_conf プログラミング言語パラメータ辞書型データ
@return sources 生成されたソースコード情報
"""
def scan_sources(
    input_dir: Path,
    languages_conf: dict[str, Any],
) -> list[SourceUnit]:

    results: list[SourceUnit] = []

    for path in _iter_files(input_dir):
        info = resolve_language(path, languages_conf)
        if info is None:
            continue

        raw_lines = read_file_auto_encoding(path)

        results.append(
            SourceUnit(
                path=path,
                language=info["language"],
                extension=info["extension"],
                rouge_ext=info["rouge_ext"],
                container_commands=info["container_commands"],
                dox_block_start=info["dox_block_start"],
                 dox_block_end=info["dox_block_end"],
                dox_inline_start=info["dox_inline_start"],
                dox_inline_end=info["dox_inline_end"],
                raw_lines=raw_lines,
            )
        )

    return results

"""!
@fn scan_source_structure ソースコード構造抽出処理
@brief クリーンソースを生成し、関数領域とグローバル領域を抽出する。
@param [in] source 対象ソースコード
@return clean_lines クリーンソース
@return function_blocks 関数ブロック
@return global_blocks グローバルブロック
"""
def scan_source_structure(
        *,
        source: SourceUnit,
        clean_source_rules: dict[str, Any] | None = None,
) -> tuple[list[str], list[FunctionBlock], list[GlobalBlock], list[SourceBlock]]:
    clean_source_rules = clean_source_rules or {}

    clean_lines, original_line_numbers = generate_clean_source_with_mapping(
        lines=source.raw_lines,
        block_pairs=clean_source_rules.get("block_pairs"),
        inline_pairs=clean_source_rules.get("inline_pairs"),
        line_starts=clean_source_rules.get("line_starts"),
        block_starts=source.dox_block_start,
        block_ends=source.dox_block_end,
        inline_starts=source.dox_inline_start,
        inline_ends=source.dox_inline_end,
    )

    # Comment Only 対応:
    # Doxygon コメント除去後に空行だけが残る場合は、
    # 「クリーンソースなし」として扱う。
    #
    # generate_clean_source_with_mapping() 側では通常ソースの空行を
    # 保持する必要があるため、ここで構造解析用に正規化する。
    if not _has_effective_clean_source(clean_lines):
        clean_lines = []
        original_line_numbers = []

    function_blocks = detect_functions(
        clean_lines=clean_lines,
        language=source.language
    )

    _attach_original_function_lines(
        function_blocks=function_blocks,
        original_line_numbers=original_line_numbers,
    )

    if source.language.lower() in {"javascript", "typescript"}:
        _attach_js_ts_original_function_lines_from_raw(
            raw_lines=source.raw_lines,
            function_blocks=function_blocks,
        )

    # ==================================================
    # グローバル領域
    # ==================================================
    global_blocks = build_global_blocks(
        clean_lines=clean_lines,
        function_blocks=function_blocks,
    )

    # ==================================================
    # ソースコード章用ブロック
    # ==================================================
    source_blocks = build_source_blocks(
        clean_lines=clean_lines,
        function_blocks=function_blocks,
        language=source.language,
    )

    return clean_lines, function_blocks, global_blocks, source_blocks


"""!
@fn build_global_blocks グローバル領域生成処理
@brief 関数領域以外のソースをグローバル領域として抽出する。
@param [in] clean_lines クリーンソース行リスト
@param [in] function_blocks 関数領域
@return global_blocks グローバル領域
"""
def build_global_blocks(
    *,
    clean_lines: list[str],
    function_blocks: list[FunctionBlock],
) -> list[GlobalBlock]:

    if not clean_lines:
        return []

    global_blocks: list[GlobalBlock] = []
    sorted_functions = sorted(function_blocks, key=lambda b: b.function_start)

    cursor = 1
    index = 1
    global_index = 1

    def append_block(start_line: int, end_line: int) -> None:
        nonlocal index, global_index

        if end_line < start_line:
            return

        # 空行だけの範囲はソースコード章に出さない。
        if not any(line.strip() for line in clean_lines[start_line - 1:end_line]):
            return

        # 関数領域外のソースには見出しをつけない。
        # 表示時に見出しが必要な場合は generator 側で
        # ファイル名などの文脈に応じた名前を付与する。
        name = ""
        global_index += 1

        global_blocks.append(
            GlobalBlock(
                name=name,
                start_line=start_line,
                end_line=end_line,
            )
        )
        index += 1

    for fn in sorted_functions:
        append_block(cursor, fn.function_start - 1)
        cursor = max(cursor, fn.function_end + 1)

    append_block(cursor, len(clean_lines))

    return global_blocks


def _find_brace_block_end(
    clean_lines: list[str],
    start_index: int,
    body_open_token: str = "{",
) -> int:
    """Return the end index for a brace based block."""
    j = start_index
    n = len(clean_lines)

    while j < n:
        if body_open_token in clean_lines[j]:
            break
        j += 1

    if j >= n:
        return start_index

    brace = 0
    k = j

    while k < n:
        line = clean_lines[k]
        brace += line.count("{")
        brace -= line.count("}")

        if brace == 0 and k > j:
            return k

        k += 1

    return j


def _extract_c_typedef_container_name(line: str) -> str:
    """Return typedef container alias from a closing C declaration line.

    Supports common C patterns such as::

        typedef struct { ... } SensorBuffer;
        typedef enum { ... } SensorState;
        typedef union { ... } SensorValue;

    The source block should be named by the public typedef alias, not by the
    anonymous ``struct``/``enum``/``union`` token.
    """
    text = (line or "").strip()

    m = re.search(
        r"}\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;\s*$",
        text,
    )

    if not m:
        return ""

    return m.group("name")


def _detect_c_typedef_container_at(
    *,
    clean_lines: list[str],
    start_index: int,
) -> SourceBlock | None:
    """Detect anonymous typedef struct/enum/union blocks in C/C++."""
    line = clean_lines[start_index]

    m = re.match(
        r"^\s*typedef\s+"
        r"(?P<kind>struct|enum|union)\b"
        r"(?:\s+[A-Za-z_][A-Za-z0-9_]*)?"
        r"\s*{",
        line,
    )

    if not m:
        return None

    end_index = _find_brace_block_end(clean_lines, start_index)
    name = _extract_c_typedef_container_name(clean_lines[end_index])

    if not name:
        # Keep the block together even if the declaration is unusual.
        # A stable synthetic name is better than splitting the container body.
        name = f"{m.group('kind')}_{start_index + 1}"

    return SourceBlock(
        kind="container",
        name=name,
        start_line=start_index + 1,
        end_line=end_index + 1,
    )


def _detect_python_class_header_at(
    *,
    clean_lines: list[str],
    start_index: int,
) -> SourceBlock | None:
    """Detect a Python class header block for the source-code chapter.

    Methods are already emitted as function blocks, so this block contains
    only the class line and class-level declarations before the first method.
    """
    line = clean_lines[start_index]
    m = re.match(
        r"^(?P<indent>\s*)class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b.*:\s*$",
        line,
    )

    if not m:
        return None

    base_indent = len(m.group("indent"))
    end_index = start_index
    k = start_index + 1
    n = len(clean_lines)

    while k < n:
        current = clean_lines[k]

        if not current.strip():
            end_index = k
            k += 1
            continue

        indent = len(current) - len(current.lstrip())

        if indent <= base_indent:
            break

        stripped = current.strip()
        if re.match(r"^(?:async\s+)?def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", stripped):
            break

        end_index = k
        k += 1

    while end_index > start_index and not clean_lines[end_index].strip():
        end_index -= 1

    return SourceBlock(
        kind="container",
        name=m.group("name"),
        start_line=start_index + 1,
        end_line=end_index + 1,
    )


def detect_containers(
    *,
    clean_lines: list[str],
    language: str,
) -> list[SourceBlock]:
    """Detect source-level containers for the source code chapter.

    This is intentionally independent from Doxygon @class/@struct/etc.
    comments.  It only represents actual source ranges that should not be
    split by member functions in the source code chapter.
    """
    if language.lower() not in {"c", "cpp", "java", "javascript", "typescript", "python"}:
        return []

    container_re = re.compile(
        r"^\s*"
        r"(?:(?:public|private|protected|static|final|abstract|sealed|export)\s+)*"
        # C++ scoped enum declarations are written as ``enum class Name``
        # or ``enum struct Name``.  Match them before the generic enum form
        # so the source-code chapter uses the real enum name instead of the
        # keyword ``class``/``struct`` as the block title.
        r"(?P<kind>class|struct|interface|union|enum(?:\s+class|\s+struct)?)\s+"
        r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\b"
    )

    blocks: list[SourceBlock] = []
    i = 0
    n = len(clean_lines)

    while i < n:
        if language.lower() == "python":
            python_class_block = _detect_python_class_header_at(
                clean_lines=clean_lines,
                start_index=i,
            )

            if python_class_block is not None:
                blocks.append(python_class_block)
                i = max(i + 1, python_class_block.end_line)
                continue

        typedef_block: SourceBlock | None = None

        if language.lower() in {"c", "cpp"}:
            typedef_block = _detect_c_typedef_container_at(
                clean_lines=clean_lines,
                start_index=i,
            )

        if typedef_block is not None:
            blocks.append(typedef_block)
            i = max(i + 1, typedef_block.end_line)
            continue

        line = clean_lines[i]

        typedef_m = re.match(r"^\s*typedef\s+(struct|enum|union)\s*\{", line)

        if typedef_m:
            end_index = _find_brace_block_end(clean_lines, i)

            end_line = clean_lines[end_index]
            name_m = re.search(
                r"}\s*([A-Za-z_][A-Za-z0-9_]*)\s*;",
                end_line,
            )

            if name_m:
                blocks.append(
                    SourceBlock(
                        kind="container",
                        name=name_m.group(1),
                        start_line=i + 1,
                        end_line=end_index + 1,
                    )
                )
                i = max(i + 1, end_index + 1)
                continue

        m = container_re.search(line)

        if not m:
            i += 1
            continue

        # Avoid matching text that is clearly not a declaration.
        before_brace = line.split("{", 1)[0]
        if ";" in before_brace:
            i += 1
            continue

        end_index = _find_brace_block_end(clean_lines, i)

        blocks.append(
            SourceBlock(
                kind="container",
                name=m.group("name"),
                start_line=i + 1,
                end_line=end_index + 1,
            )
        )

        i = max(i + 1, end_index + 1)

    return blocks


def _is_range_inside(inner: SourceBlock | FunctionBlock, outer: SourceBlock) -> bool:
    if isinstance(inner, FunctionBlock):
        start_line = inner.function_start
        end_line = inner.function_end
    else:
        start_line = inner.start_line
        end_line = inner.end_line

    return outer.start_line <= start_line and end_line <= outer.end_line


def _range_overlaps(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a <= end_b and start_b <= end_a


def _is_top_level_declaration_line(line: str, *, language: str) -> bool:
    """Return True for a small top-level declaration block.

    Source-block detection is intentionally conservative. Containers and
    functions already have their own blocks. This helper only splits short
    standalone declarations that otherwise get absorbed into a neighboring
    source block in the source-code chapter.
    """
    lang = language.lower()
    s = line.strip()

    if not s:
        return False

    # C/C++ preprocessor macros. Multi-line macros are expanded by
    # _declaration_end_line().
    if lang in {"c", "cpp"} and re.match(r"^#\s*define\b", s):
        return True

    if "{" in s or "}" in s:
        return False

    # C/C++ simple top-level declarations.
    if lang in {"c", "cpp"}:
        if not s.endswith(";"):
            return False

        if s.startswith(("using ", "typedef ")):
            return True

        return re.match(
            r"^(?:extern\s+|static\s+)?"
            r"(?:const\s+|constexpr\s+|inline\s+constexpr\s+)?"
            r"[A-Za-z_:][A-Za-z0-9_:<>\s*&]*\s+"
            r"[A-Za-z_][A-Za-z0-9_]*\s*(?:=.*)?;$",
            s,
        ) is not None

    # TypeScript top-level type alias.
    if lang == "typescript":
        return re.match(r"^type\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=.+;$", s) is not None

    return False


def build_source_blocks(
    *,
    clean_lines: list[str],
    function_blocks: list[FunctionBlock],
    language: str,
) -> list[SourceBlock]:
    """Build source-code chapter blocks without splitting containers.

    Containers such as classes, structs, interfaces, enums, and unions become
    the primary source blocks.  Functions inside those containers are kept
    inside the container block.  Top-level functions remain function blocks.
    Remaining source ranges are emitted as global blocks, with a heading only
    for the first declaration section.
    """
    if not clean_lines:
        return []

    container_blocks = detect_containers(
        clean_lines=clean_lines,
        language=language,
    )

    top_level_functions: list[FunctionBlock] = []
    for fn in function_blocks:
        if any(_is_range_inside(fn, container) for container in container_blocks):
            continue
        top_level_functions.append(fn)

    source_blocks: list[SourceBlock] = list(container_blocks)

    for fn in top_level_functions:
        source_blocks.append(
            SourceBlock(
                kind="function",
                name=fn.name,
                start_line=fn.function_start,
                end_line=fn.function_end,
            )
        )

    occupied = sorted(
        (block.start_line, block.end_line)
        for block in source_blocks
    )

    global_index = 1
    cursor = 1

    def append_global(start_line: int, end_line: int) -> None:
        nonlocal global_index

        if end_line < start_line:
            return

        # Doxygen/Doxygon コメント削除後に残った前後の空行だけで
        # ソースコード章の表示範囲が広がらないようにする。
        # ただしブロック内部の空行は、元ソースの見た目として保持する。
        while start_line <= end_line and not clean_lines[start_line - 1].strip():
            start_line += 1

        while end_line >= start_line and not clean_lines[end_line - 1].strip():
            end_line -= 1

        if end_line < start_line:
            return

        # ソースコード章用の global ブロック自体には見出しを持たせない。
        # generator 側で block.name が空の場合は source_filename を表示する。
        name = ""
        source_blocks.append(
            SourceBlock(
                kind="global",
                name=name,
                start_line=start_line,
                end_line=end_line,
            )
        )
        global_index += 1

    def _declaration_end_line(line_no: int, end_line: int) -> int:
        """Return declaration end line.

        #define may continue onto following lines with a trailing backslash.
        Other declaration kinds handled here are intentionally one-line blocks.
        """
        line = clean_lines[line_no - 1].strip()

        if not re.match(r"^#\s*define\b", line):
            return line_no

        current = line_no
        while current < end_line:
            raw = clean_lines[current - 1].rstrip()
            if not raw.endswith("\\"):
                break
            current += 1

        return current

    def append_declaration(start_line: int, end_line: int) -> None:
        source_blocks.append(
            SourceBlock(
                kind="declaration",
                name="",
                start_line=start_line,
                end_line=end_line,
            )
        )

    def append_gap(start_line: int, end_line: int) -> None:
        current_start = start_line
        line_no = start_line

        while line_no <= end_line:
            line = clean_lines[line_no - 1]

            if _is_top_level_declaration_line(line, language=language):
                decl_end_line = _declaration_end_line(line_no, end_line)
                append_global(current_start, line_no - 1)
                append_declaration(line_no, decl_end_line)
                current_start = decl_end_line + 1
                line_no = decl_end_line + 1
                continue

            line_no += 1

        append_global(current_start, end_line)

    for start_line, end_line in occupied:
        append_gap(cursor, start_line - 1)
        cursor = max(cursor, end_line + 1)

    append_gap(cursor, len(clean_lines))

    source_blocks.sort(key=lambda block: block.start_line)

    # Drop any accidental overlaps by preferring the earlier/larger block.
    result: list[SourceBlock] = []
    for block in source_blocks:
        if any(_range_overlaps(block.start_line, block.end_line, b.start_line, b.end_line) for b in result):
            continue
        result.append(block)

    return result


def _has_effective_clean_source(clean_lines: list[str]) -> bool:
    """Return True if clean source contains at least one non-blank line.

    Doxygon comments may be removed into empty strings while preserving line
    mapping.  For source-structure detection, a file that contains only those
    empty lines should behave the same as a file with no clean source.
    """
    return any(line.strip() for line in clean_lines)


"""!
@fn _iter_files ファイル探索処理
"""
def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file():
            yield p


"""!
@fn resolve_language プログラミング言語判定処理
"""
def resolve_language(
    path: Path,
    languages_conf: dict[str, Any],
) -> Optional[dict[str, Any]]:

    ext = path.suffix.lstrip(".").lower()
    if not ext:
        return None

    for lang, conf in languages_conf.items():
        if ext not in conf.get("extensions", []):
            continue

        return {
            "language": lang,
            "extension": ext,
            "rouge_ext": conf["rouge_ext"],
            "dox_block_start": conf["dox_block_start"],
            "dox_block_end": conf["dox_block_end"],
            "dox_inline_start": conf["dox_inline_start"],
            "dox_inline_end": conf["dox_inline_end"],
            "container_commands": conf.get("container_commands", []),
        }

    return None


"""!
@fn read_file_auto_encoding ファイル読み込み（文字コード判定）
"""
def read_file_auto_encoding(path: Path) -> list[str]:

    encodings = ["utf-8", "cp932", "euc_jp"]

    for enc in encodings:
        try:
            with open(path, mode="r", encoding=enc) as f:
                return f.read().splitlines()
        except Exception:
            continue

    raise UnicodeDecodeError(
        "read_file_auto_encoding",
        str(path),
        0,
        0,
        "Unable to decode file",
    )


def _make_pairs(
    starts: list[str] | None,
    ends: list[str] | None,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for start, end in zip(starts or [], ends or []):
        if not start:
            continue

        pair = (start, end or "")

        if pair in seen:
            continue

        seen.add(pair)
        pairs.append(pair)

    return pairs


"""!
@fn generate_clean_source クリーンソース生成処理
@brief Doxygonコメントを除去したソースコード行リストを生成する。
@param [in] lines 対象ソースコード行リスト
@param [in] block_pairs ブロックコメント削除対象の開始／終端ペア
@param [in] inline_pairs インラインコメント削除対象の開始／終端ペア
@param [in] line_starts 行コメント削除対象の開始記号
@return clean_lines Doxygonコメントを除去したソースコード行リスト
"""
def _is_quote_style_token(token: str) -> bool:
    return token.startswith(('"""', "'''")) or token in {'"""', "'''"}


def _find_clean_token(text: str, token: str, start: int = 0) -> int:
    """Find Doxygon clean-source token.

    Python inline/block markers intentionally use triple quotes, so the
    generic unquoted scanner hides them as string delimiters.  For those
    quote-style markers, use a plain search.  C/VBA-style markers keep the
    unquoted search to avoid accidental matches inside string literals.
    """
    if _is_quote_style_token(token):
        return text.find(token, start)

    return find_unquoted_token(text, token, start)


def _is_inline_pair_end_at(
    text: str,
    *,
    end_pos: int,
    end_token: str,
    inline_pairs: list[tuple[str, str]],
) -> bool:
    """Return True when end_pos closes an inline Doxygon comment.

    This prevents a block Doxygon comment from being closed early when its
    body describes inline syntax such as ``/**!< ... */``.
    """

    if not end_token:
        return False

    for inline_start, inline_end in inline_pairs:
        if inline_end != end_token:
            continue

        start_pos = find_unquoted_token(text, inline_start)

        while start_pos != -1 and start_pos < end_pos:
            candidate_end = find_unquoted_token(
                text,
                inline_end,
                start_pos + len(inline_start),
            )

            if candidate_end == end_pos:
                return True

            start_pos = find_unquoted_token(
                text,
                inline_start,
                start_pos + len(inline_start),
            )

    return False


def _find_real_block_end_token(
    text: str,
    token: str,
    *,
    inline_pairs: list[tuple[str, str]],
) -> int:
    # Python block comments use quote-style terminators.  They must be found
    # with plain search; otherwise the first quote hides the terminator from
    # the unquoted-token scanner.
    if _is_quote_style_token(token):
        return text.find(token)

    pos = find_unquoted_token(text, token)

    while pos != -1:
        if not _is_inline_pair_end_at(
            text,
            end_pos=pos,
            end_token=token,
            inline_pairs=inline_pairs,
        ):
            return pos

        pos = find_unquoted_token(text, token, pos + len(token))

    return -1


def generate_clean_source_with_mapping(
    *,
    lines: list[str],
    block_pairs: list[tuple[str, str]] | None = None,
    inline_pairs: list[tuple[str, str]] | None = None,
    line_starts: list[str] | None = None,
    block_starts: list[str] | None = None,
    block_ends: list[str] | None = None,
    inline_starts: list[str] | None = None,
    inline_ends: list[str] | None = None,
) -> tuple[list[str], list[int]]:

    # Backward compatibility: when global clean-source pairs are not supplied,
    # fall back to the source language's own Doxygon comment settings.
    if block_pairs is None:
        block_pairs = _make_pairs(block_starts, block_ends)

    if inline_pairs is None:
        inline_pairs = _make_pairs(inline_starts, inline_ends)

    line_starts = line_starts or []
    inline_starts = inline_starts or []
    effective_inline_starts = [start for start, _end in inline_pairs if start]
    for start in inline_starts:
        if start and start not in effective_inline_starts:
            effective_inline_starts.append(start)

    clean_lines: list[str] = []
    original_line_numbers: list[int] = []

    n = len(lines)
    i = 0

    def append_clean(line_text: str, original_line_no: int) -> None:
        clean_lines.append(line_text.rstrip("\n"))
        original_line_numbers.append(original_line_no)

    while i < n:

        line = lines[i]
        stripped = line.lstrip()

        # --------------------------------------------------
        # lineコメント除去
        # --------------------------------------------------
        if any(stripped.startswith(start) for start in line_starts):
            i += 1
            continue

        # --------------------------------------------------
        # inline comment only 行除去
        # --------------------------------------------------
        # C 系の ``//!<`` のように、行頭から Doxygon inline comment
        # だけが書かれている行はソース実体ではない。
        #
        # 通常の inline comment は後段で行末コメントとして除去するが、
        # Comment Only 運用ではこの行自体を clean source に残さない。
        if any(stripped.startswith(start) for start in effective_inline_starts):
            i += 1
            continue

        # --------------------------------------------------
        # blockコメント除去
        # --------------------------------------------------
        matched_pair: tuple[str, str] | None = None

        for start, end in block_pairs:
            if stripped.startswith(start):
                matched_pair = (start, end)
                break

        if matched_pair is not None:
            start_token, end_token = matched_pair

            # Remove Doxygon block comments completely from the clean source.
            # One-line blocks such as:
            #     """! @class Sample ... """
            # are consumed on this line only, so the following source line is
            # not swallowed.
            check = stripped[len(start_token):]
            i += 1

            if not end_token:
                continue

            if _find_real_block_end_token(
                check,
                end_token,
                inline_pairs=inline_pairs,
            ) != -1:
                continue

            while i < n:
                check = lines[i].lstrip()

                if _find_real_block_end_token(
                    check,
                    end_token,
                    inline_pairs=inline_pairs,
                ) != -1:
                    i += 1
                    break

                i += 1

            continue

        # --------------------------------------------------
        # inlineコメント除去
        # --------------------------------------------------
        new_line = line

        while True:
            found: tuple[int, str, str] | None = None

            for start, end in inline_pairs:
                pos = _find_clean_token(new_line, start)

                if pos == -1:
                    continue

                if found is None or pos < found[0]:
                    found = (pos, start, end)

            if found is None:
                break

            pos, start, end = found

            if not end:
                new_line = new_line[:pos].rstrip()
                break

            end_pos = _find_clean_token(
                new_line,
                end,
                pos + len(start),
            )

            if end_pos == -1:
                new_line = new_line[:pos].rstrip()
                break

            new_line = (
                new_line[:pos].rstrip()
                + new_line[end_pos + len(end):]
            )

        append_clean(new_line, i + 1)
        i += 1

    return clean_lines, original_line_numbers


def generate_clean_source(
    *,
    lines: list[str],
    block_pairs: list[tuple[str, str]] | None = None,
    inline_pairs: list[tuple[str, str]] | None = None,
    line_starts: list[str] | None = None,
    block_starts: list[str] | None = None,
    block_ends: list[str] | None = None,
    inline_starts: list[str] | None = None,
    inline_ends: list[str] | None = None,
) -> list[str]:
    clean_lines, _original_line_numbers = generate_clean_source_with_mapping(
        lines=lines,
        block_pairs=block_pairs,
        inline_pairs=inline_pairs,
        line_starts=line_starts,
        block_starts=block_starts,
        block_ends=block_ends,
        inline_starts=inline_starts,
        inline_ends=inline_ends,
    )
    return clean_lines


def _attach_original_function_lines(
    *,
    function_blocks: list[FunctionBlock],
    original_line_numbers: list[int],
) -> None:
    """Attach original line ranges to FunctionBlock objects.

    FunctionBlock.start/end line numbers refer to the generated clean source.
    Inline Doxygon comment nodes, however, keep their original source line
    numbers.  Keeping both ranges lets generator produce compact clean source
    while still reporting accurate orphan-owner warnings.
    """
    if not original_line_numbers:
        return

    for fn in function_blocks:
        start_idx = fn.function_start - 1
        sig_idx = fn.signature_end - 1
        end_idx = fn.function_end - 1

        if 0 <= start_idx < len(original_line_numbers):
            fn.original_function_start = original_line_numbers[start_idx]
        if 0 <= sig_idx < len(original_line_numbers):
            fn.original_signature_end = original_line_numbers[sig_idx]
        if 0 <= end_idx < len(original_line_numbers):
            fn.original_function_end = original_line_numbers[end_idx]

def _match_function_name(match: re.Match, name_group) -> str | None:
    """Return the first non-empty function name from a regex match.

    ``name_group`` may be an int for legacy languages, or a list/tuple of
    candidate capture groups for syntaxes such as JavaScript/TypeScript
    where ``function foo`` and ``const foo = (...) =>`` use different groups.
    """
    if isinstance(name_group, int):
        return match.group(name_group)

    for group in name_group:
        value = match.group(group)
        if value:
            return value

    return None


def _find_body_open_index(
    *,
    clean_lines: list[str],
    start_index: int,
    body_open_token: str,
) -> int | None:
    """Return the line index containing the body-open token.

    Brace based languages may also contain function-like declarations such as
    Java interface methods, C prototypes, or TypeScript interface signatures:

        Product findById(int id);

    These have a semicolon before any function body appears and must not be
    treated as functions for V5 source/function summaries.
    """
    j = start_index
    n = len(clean_lines)

    while j < n:
        line = clean_lines[j]

        open_pos = line.find(body_open_token)
        semi_pos = line.find(";")

        if semi_pos != -1 and (open_pos == -1 or semi_pos < open_pos):
            return None

        if open_pos != -1:
            return j

        j += 1

    return None



def _find_js_ts_raw_body_start(
    *,
    raw_lines: list[str],
    start_index: int,
) -> int | None:
    j = start_index
    n = len(raw_lines)

    while j < n:
        line = raw_lines[j]

        # A semicolon before a body means an interface signature or a
        # declaration, not an implementation body.
        open_pos = line.find("{")
        semi_pos = line.find(";")

        if semi_pos != -1 and (open_pos == -1 or semi_pos < open_pos):
            return None

        if open_pos != -1:
            return j

        j += 1

    return None


def _find_js_ts_raw_brace_end(
    *,
    raw_lines: list[str],
    body_start: int,
) -> int:
    brace = 0
    k = body_start
    n = len(raw_lines)

    while k < n:
        line = raw_lines[k]
        brace += line.count("{")
        brace -= line.count("}")

        if brace == 0 and k > body_start:
            return k

        k += 1

    return body_start


def _match_js_ts_raw_function_name(line: str) -> str | None:
    stripped = (line or "").strip()

    if not stripped:
        return None

    if stripped.startswith(("//", "/*", "*", "@")):
        return None

    # Top-level function declaration.
    m = re.match(
        r"^(?:export\s+)?(?:async\s+)?function\s+"
        r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
        stripped,
    )
    if m:
        return m.group("name")

    # Class method / constructor.
    method_m = _match_js_ts_method_declaration(stripped)
    if method_m is not None:
        return method_m.group("name")

    return None


def _attach_js_ts_original_function_lines_from_raw(
    *,
    raw_lines: list[str],
    function_blocks: list[FunctionBlock],
) -> None:
    """Attach original JS/TS method ranges by scanning raw source.

    Clean-source line mapping normally preserves original line numbers, but
    JS/TS class methods are detected after Doxygon comment removal and may be
    separated from the inline comment nodes that still carry raw-source line
    numbers.  Orphan WARNING relies on raw ownership, so keep an explicit raw
    implementation range for every detected JS/TS function/method.
    """
    if not function_blocks:
        return

    raw_ranges: list[tuple[str, int, int, int]] = []
    i = 0
    n = len(raw_lines)

    while i < n:
        name = _match_js_ts_raw_function_name(raw_lines[i])
        if not name:
            i += 1
            continue

        body_start = _find_js_ts_raw_body_start(
            raw_lines=raw_lines,
            start_index=i,
        )

        if body_start is None:
            i += 1
            continue

        body_end = _find_js_ts_raw_brace_end(
            raw_lines=raw_lines,
            body_start=body_start,
        )

        signature_end = body_start
        raw_ranges.append((name, i + 1, signature_end + 1, body_end + 1))
        i = body_end + 1

    used: set[int] = set()

    for fn in function_blocks:
        target = _normalize_source_name(fn.name)

        for idx, (name, start, signature_end, end) in enumerate(raw_ranges):
            if idx in used:
                continue

            if _normalize_source_name(name) != target:
                continue

            fn.original_function_start = start
            fn.original_signature_end = signature_end
            fn.original_function_end = end
            used.add(idx)
            break


def _normalize_source_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "")).lower()

def _match_js_ts_method_declaration(line: str) -> re.Match | None:
    """Return a method declaration match for JS/TS class methods.

    language_spec based detection covers top-level functions/arrow functions,
    but class methods such as::

        readValue(): number {
        orphanValue() {
        constructor(value) {

    also need FunctionBlock entries.  Orphan WARNING uses the physical
    function owner, so missing method blocks allow inline @var to be attached
    to the previous documented @fn by mistake.
    """
    stripped = (line or "").strip()

    if not stripped:
        return None

    if stripped.startswith(("//", "/*", "*")):
        return None

    # Avoid ordinary control statements that look like name(...){.
    control_keywords = {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "with",
        "function",
        "return",
    }

    m = re.match(
        r"^"
        r"(?:(?:public|private|protected|static|async|get|set|readonly|override)\s+)*"
        r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"
        r"\s*\([^;{}]*\)"
        r"\s*(?::\s*[^{};]+)?"
        r"\s*(?:\{|$)",
        stripped,
    )

    if not m:
        return None

    if m.group("name") in control_keywords:
        return None

    return m


"""!
@fn detect_functions 関数領域検出処理
@brief クリーンソースからプログラミング言語仕様に基づいて関数領域を検出する。
@param [in] clean_lines クリーンソース行リスト
@param [in] language プログラミング言語
@return function_blocks 検出された関数領域一覧
"""
def detect_functions(
    *,
    clean_lines: list[str],
    language: str,
) -> list[FunctionBlock]:

    spec = get_language_spec(language)

    function_detect = spec["function_detect"]
    start_re = re.compile(spec["function_start"], re.IGNORECASE)
    name_group = spec["name_group"]

    blocks: list[FunctionBlock] = []

    i = 0
    n = len(clean_lines)

    while i < n:

        line = clean_lines[i]
        m = start_re.search(line)
        name = _match_function_name(m, name_group) if m else None

        if not name and language.lower() in {"javascript", "typescript"}:
            method_m = _match_js_ts_method_declaration(line)
            if method_m is not None:
                name = method_m.group("name")

        if not name:
            i += 1
            continue

        function_start = i

        # brace方式
        if function_detect == "brace":

            body_open_token = spec.get("body_open_token", "{")

            body_start = _find_body_open_index(
                clean_lines=clean_lines,
                start_index=i,
                body_open_token=body_open_token,
            )

            if body_start is None:
                i += 1
                continue

            # コーリングシーケンス終端
            original_body_line = clean_lines[body_start]

            # Allman:
            # int func()
            # {
            if original_body_line.strip() == body_open_token:
                signature_end = max(i, body_start - 1)

            # K&R:
            # int func() {
            else:
                signature_end = body_start

            # brace解析
            brace = 0
            k = body_start

            while k < n:
                line_for_brace = (
                    original_body_line if k == body_start else clean_lines[k]
                )

                brace += line_for_brace.count("{")
                brace -= line_for_brace.count("}")

                if brace == 0 and k > body_start:
                    function_end = k
                    break

                k += 1
            else:
                function_end = signature_end

        # indent方式（Python）
        elif function_detect == "indent":

            base_indent = len(clean_lines[i]) - len(clean_lines[i].lstrip())

            j = i
            while j < n:
                if clean_lines[j].strip().endswith(":"):
                    break
                j += 1

            signature_end = j
            function_end = signature_end

            k = signature_end + 1

            while k < n:
                line = clean_lines[k]

                if not line.strip():
                    k += 1
                    continue

                indent = len(line) - len(line.lstrip())

                if indent <= base_indent:
                    break

                function_end = k
                k += 1

        elif function_detect == "regex":

            end_re = re.compile(spec["function_end"], re.IGNORECASE)

            # VBA対応（継続行 "_"）
            if language == "vba":

                j = i

                # "_" 継続行を追う
                while j + 1 < n and clean_lines[j].rstrip().endswith("_"):
                    j += 1

                signature_end = j
                function_end = signature_end

                k = signature_end + 1

                while k < n:
                    if end_re.search(clean_lines[k]):
                        function_end = k
                        break
                    k += 1

            # 通常 regex（他言語）
            else:

                signature_end = i
                function_end = i

                k = i + 1
                while k < n:
                    if end_re.search(clean_lines[k]):
                        function_end = k
                        break
                    k += 1
        else:
            raise ValueError(f"Unknown function_detect: {function_detect}")

        blocks.append(
            FunctionBlock(
                name=name,
                function_start=function_start + 1,
                signature_end=signature_end + 1,
                function_end=function_end + 1,
            )
        )
        i = function_end + 1

    return blocks
