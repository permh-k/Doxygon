#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file generator.py AsciiDocドキュメント生成処理
"""

from __future__ import annotations
from pathlib import Path
import re

from doxygon.model import TextSegment, DelimSegment, Node, FunctionBlock, GlobalBlock
from doxygon.scanner.source_scanner import SourceBlock

_NUM_LIST_RE = re.compile(r"^\s*\.+\s+")
_UNKNOWN_INLINE_RE = re.compile(r"(?<![\w.\"'<`])@([A-Za-z_][A-Za-z0-9_]*)")
CONTAINER_TITLE_MAP = {
    "struct": "構造体",
    "enum": "列挙体",
    "class": "クラス",
    "interface": "インターフェース",
    "union": "共用体",
    "type": "型定義",
}
CONTAINER_COMMANDS = set(CONTAINER_TITLE_MAP.keys())

def _extract_location(n: Node, *, source_filename) -> str:

    location = ""

    line_no = None
    for d in getattr(n, "diagnostics", []) or []:
        if getattr(d, "line", None) is not None:
            line_no = d.line
            break

    if source_filename and line_no is not None:
        location = f" {source_filename}: {line_no}"
    elif source_filename:
        location = f" {source_filename}"
    elif line_no is not None:
        location = f" line:{line_no}"

    return location


_ASCII_WS_RE = re.compile(r"[ \t]+")


def _split_ascii_ws(text: str, *, maxsplit: int = 0) -> list[str]:
    """Split only on ASCII space/tab.

    Full-width spaces (U+3000) are part of Japanese text and must not
    terminate TAG.  ASCII space separates TAG/SENTENCE fields; full-width
    space remains literal text.
    """
    s = (text or "").strip(" \t")

    if not s:
        return []

    return _ASCII_WS_RE.split(s, maxsplit=maxsplit)


_JAPANESE_SENTENCE_HINTS = (
    "説明",
    "本文",
    "概要",
    "詳細",
    "確認",
    "正常",
    "異常",
    "成功",
    "失敗",
    "グローバル",
    "関数",
    "メンバー説明",
    "member",
    "sentence",
    "with",
    "space",
)


def _contains_non_ascii(text: str) -> bool:
    return any(ord(ch) >= 128 for ch in text or "")


def _looks_like_sentence_fragment(text: str) -> bool:
    t = (text or "").strip()

    if not t:
        return False

    lower = t.lower()
    return any(hint.lower() in lower for hint in _JAPANESE_SENTENCE_HINTS)


def _split_argument(argument: str) -> tuple[str, str]:

    s = (argument or "").strip(" \t")

    if not s:
        return "", ""

    parts = _split_ascii_ws(s, maxsplit=1)

    # Japanese TAGs may contain ASCII spaces in TAG-only forms, e.g.
    #   @define マク ロタグG
    #   @type 型定 義タグG
    # Treat a two-part Japanese argument as a single TAG unless the second
    # part clearly looks like a SENTENCE.  This keeps ordinary English
    # TAG/SENTENCE splitting unchanged while preserving Japanese display
    # names used by the command-tag matrix.
    if (
        len(parts) == 2
        and _contains_non_ascii(parts[0])
        and _contains_non_ascii(parts[1])
        and not _looks_like_sentence_fragment(parts[1])
    ):
        return s, ""

    name = parts[0]
    desc = parts[1] if len(parts) > 1 else ""

    return name, desc


def _split_fn_argument(argument: str) -> tuple[str, str]:
    """Split @fn argument into signature/display text and description.

    Ordinary Doxygon commands use ASCII whitespace to separate TAG and
    SENTENCE.  @fn is special in Comment Only documents because the TAG may
    be an API-style signature such as ``hoge(fuga, foo)``.  In that case,
    consume through the matching closing parenthesis before splitting the
    optional description.
    """
    s = (argument or "").strip(" \t")

    if not s:
        return "", ""

    open_pos = s.find("(")

    # No function-like signature at the start; keep normal TAG/SENTENCE rule.
    if open_pos == -1:
        return _split_argument(s)

    before_open = s[:open_pos]

    # If ASCII whitespace appears before "(", this is not a compact function
    # signature.  Fall back to the normal rule instead of changing the meaning
    # of other @fn notations.
    if _ASCII_WS_RE.search(before_open):
        return _split_argument(s)

    depth = 0

    for i, ch in enumerate(s[open_pos:], start=open_pos):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1

            if depth == 0:
                signature = s[: i + 1].strip()
                desc = s[i + 1 :].strip(" \t")
                return signature, desc

    # Unbalanced parentheses are not repaired here.  Let the normal rule and
    # parser diagnostics decide how to report the malformed @fn.
    return _split_argument(s)



_ALLOWED_PARAM_DIRECTIONS = {"[in]", "[out]", "[in,out]", "[out,in]"}


def _has_invalid_param_direction(argument: str) -> bool:
    """Return True when @param starts with an invalid [in/out] token."""
    parts = _split_ascii_ws(argument or "", maxsplit=2)

    if not parts:
        return False

    first = parts[0]

    if first.startswith("[") and first.endswith("]"):
        return first not in _ALLOWED_PARAM_DIRECTIONS

    return False

def _fn_lookup_name(argument: str) -> str:
    """Return the source-scanner lookup name for an @fn argument."""
    signature, _desc = _split_fn_argument(argument)

    if "(" in signature:
        return signature.split("(", 1)[0].strip()

    return signature


"""!
@fn _split_global_and_sections セクション分割処理
@brief コマンドノードをグローバルノード、関数ノード、コンテナノードに分割する。
@param [in] nodes 対象となるコマンドノード
@return global_nodes グローバルノード
@return fn_nodes 関数ノード
@return conainer_nodes コンテナノード
"""
def _split_global_and_sections(
    nodes: list[Node],
) -> tuple[list[Node], list[Node], list[Node]]:
    global_nodes: list[Node] = []
    fn_nodes: list[Node] = []
    container_nodes: list[Node] = []

    current_parent: Node | None = None

    for n in nodes:
        if n.command == "fn":
            n.children = []
            fn_nodes.append(n)
            current_parent = n
            continue

        if n.is_container or n.command in CONTAINER_COMMANDS:
            n.children = list(n.children or [])
            container_nodes.append(n)
            current_parent = n
            continue

        if current_parent is None:
            global_nodes.append(n)
        else:
            current_parent.children.append(n)

    return global_nodes, fn_nodes, container_nodes


"""!
@fn _normalize_name 文字列正規化処理
@brief 空白を除去し、小文字化した比較用文字列を返す。
@param [in] s 正規化対象文字列
@return s 正規化済み文字列
"""
def _normalize_name(s: str) -> str:

    return re.sub(r"\s+", "", (s or "")).lower()


"""!
@fn _find_function_block 関数ブロック検索処理
@brief 関数名に対応する関数ブロックを検索する。
@param [in] function_blocks 関数ブロック
@param [in] fn_name 対象となる関数名
@return FunctionBlock 関数名が一致した関数ブロック。見つからない場合は"None"を返す。
"""
def _find_function_block(
    function_blocks: list[FunctionBlock],
    fn_name: str,
) -> FunctionBlock | None:
    target = _normalize_name(fn_name)

    for span in function_blocks:
        if _normalize_name(span.name) == target:
            return span

    return None


def _map_fn_nodes_by_name(fn_nodes: list[Node]) -> dict[str, Node]:
    """Return @fn nodes keyed by normalized function name.

    Source scanning and Doxygon comments are intentionally separate.
    The source scanner is the source of truth for the function summary,
    while @fn nodes only provide optional descriptions and function detail.
    """
    result: dict[str, Node] = {}

    for fn in fn_nodes:
        fname = _fn_lookup_name(fn.argument or "")
        key = _normalize_name(fname)
        if key and key not in result:
            result[key] = fn

    return result


def _find_fn_node(
    fn_nodes_by_name: dict[str, Node],
    fn_name: str,
) -> Node | None:
    return fn_nodes_by_name.get(_normalize_name(fn_name))


"""!
@fn _is_promotable_one_liner 1行コメント判定処理
@brief 本文の先頭行を説明文に昇格できるかを判定する。
@param [in] s 判定対象文字列
@return True 説明文に昇格可
@return False 説明文に昇格不可
"""
def _is_promotable_one_liner(s: str) -> bool:
    t = (s or "").strip()

    if not t:
        return False

    if t.startswith(("*", ".", "-", "+")):
        return False

    if t.startswith("[") or t.startswith("----"):
        return False

    return True


"""!
@fn _merge_argument_body ヘッダと本文の結合処理
@brief コマンドノードのヘッダを本文の先頭行として扱うためのリストを生成する。
@param [in] node 対象となるコマンドノード
@return body ヘッダを追加した本文のリスト
"""
def _merge_argument_body(node: Node) -> list[str]:
    body = list(node.body or [])

    if node.argument:
        body.insert(0, node.argument.strip())

    return body


"""!
@fn _emit_segments セグメント出力処理
@brief 本文セグメントと除外ブロックをAsciiDocフォーマットで出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] segments 出力対象セグメント一覧
"""
def _emit_segments(lines: list[str], segments) -> None:
    if not segments:
        return

    for seg in segments:
        if isinstance(seg, TextSegment):
            _emit_body(lines, seg.lines)

        elif isinstance(seg, DelimSegment):
            lines.append("----")
            for line in seg.lines:
                lines.append(line)
            lines.append("----")


def _emit_segments_raw(lines: list[str], segments) -> None:
    """Emit command payload without adding AsciiDoc listing delimiters.

    Text segments and DELIM segments are both user-authored AsciiDoc.
    DELIM is only a Doxygon boundary marker, so its payload is emitted as-is.
    """
    if not segments:
        return

    for seg in segments:
        if isinstance(seg, TextSegment):
            _emit_body(lines, seg.lines)
        elif isinstance(seg, DelimSegment):
            lines.extend(seg.lines)


def _escape_adoc_attr_value(text: str) -> str:
    """Escape text embedded in an AsciiDoc attribute value.

    This is intentionally limited to strings that Doxygon itself places
    inside title="..." and similar attribute values.  Normal body text and
    DELIM payloads are emitted as written.
    """
    return text.replace('"', '&#34;')


def _escape_adoc_identifier(name: str) -> str:
    """Return a display-safe identifier for AsciiDoc text positions.

    Python dunder names such as ``__init__`` collide with AsciiDoc emphasis
    markup.  ``+...+`` keeps the original text visible without affecting
    ordinary identifiers such as ``average_score``.
    """
    if re.fullmatch(r"__.*__", name or ""):
        return f"+{name}+"

    return name


def _node_line_no(n: Node) -> int | None:
    line_no = getattr(n, "line_no", None)

    if line_no is not None:
        return line_no

    for d in getattr(n, "diagnostics", []) or []:
        if getattr(d, "line", None) is not None:
            return d.line

    return None


def _format_location(
    *,
    source_filename: str | None,
    line_no: int | None,
) -> str:
    if source_filename and line_no is not None:
        return f" {source_filename}: {line_no}"
    if source_filename:
        return f" {source_filename}"
    if line_no is not None:
        return f" line:{line_no}"
    return ""


def _find_enclosing_function_block(
    *,
    function_blocks: list[FunctionBlock],
    line_no: int | None,
) -> FunctionBlock | None:
    if line_no is None:
        return None

    for fn in function_blocks:
        original_start = getattr(fn, "original_function_start", None)
        original_end = getattr(fn, "original_function_end", None)

        if original_start is not None and original_end is not None:
            if original_start <= line_no <= original_end:
                return fn
            continue

        if fn.function_start <= line_no <= fn.function_end:
            return fn

    return None


def _has_documented_function(
    *,
    fn_nodes_by_name: dict[str, Node],
    fn_name: str,
) -> bool:
    return _find_fn_node(fn_nodes_by_name, fn_name) is not None


def _warning_subject_name(n: Node) -> str:
    name, _desc = _split_argument(n.argument or "")
    if name:
        return name

    arg = (n.argument or "").strip()
    return arg if arg else f"@{n.command}"


def _present_orphan_warning(
    lines: list[str],
    n: Node,
    *,
    source_filename: str | None = None,
    parent_kind: str = "所属先",
    parent_name: str | None = None,
) -> None:
    subject = _warning_subject_name(n)
    line_no = _node_line_no(n)
    location = _format_location(
        source_filename=source_filename,
        line_no=line_no,
    )

    parent_display = _escape_adoc_identifier(parent_name or "")

    if parent_kind == "function":
        if parent_display:
            message = f'"{subject}" が属する "{parent_display}" 関数に Doxygon コメントの記述がありません。'
        else:
            message = f'"{subject}" が属する関数に Doxygon コメントの記述がありません。'
    elif parent_kind == "class":
        if parent_display:
            message = f'"{subject}" が属する "{parent_display}" クラスに Doxygon コメントの記述がありません。'
        else:
            message = f'"{subject}" が属するクラスに Doxygon コメントの記述がありません。'
    else:
        return

    lines.append(
        f"\n\n====\n[.maroon]##[WARNING]##{location} "
        f"{message}\n===="
    )


OrphanWarning = tuple[Node, str, str | None]





def _split_orphan_nodes_for_function_context(
    nodes: list[Node],
    *,
    function_blocks: list[FunctionBlock],
    fn_nodes_by_name: dict[str, Node],
    expected_fn_name: str | None,
) -> tuple[list[Node], list[OrphanWarning]]:
    """Split nodes into renderable nodes and orphan-warning nodes.

    Inline @var written inside a function whose @fn is missing must not be
    silently promoted to the previous @fn or to a class detail.  Keep it
    visible as a warning instead.
    """
    render_nodes: list[Node] = []
    orphan_nodes: list[OrphanWarning] = []

    for n in nodes:
        if n.command != "var":
            render_nodes.append(n)
            continue

        line_no = _node_line_no(n)
        owner_fn = _find_enclosing_function_block(
            function_blocks=function_blocks,
            line_no=line_no,
        )

        if owner_fn is None:
            render_nodes.append(n)
            continue

        if expected_fn_name is not None and _normalize_name(owner_fn.name) == _normalize_name(expected_fn_name):
            render_nodes.append(n)
            continue

        if not _has_documented_function(
            fn_nodes_by_name=fn_nodes_by_name,
            fn_name=owner_fn.name,
        ):
            orphan_nodes.append((n, "function", owner_fn.name))
            continue

        render_nodes.append(n)

    return render_nodes, orphan_nodes


"""!
@fn _emit_body 本文出力処理
@brief 本文をAsciiDocドキュメント出力リストへ追加する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] body 対象となる本文
"""
def _emit_body(lines: list[str], body: list[str] | None) -> None:
    if not body:
        return

    for raw in body:

        if raw is None:
            continue

        line = raw.lstrip()

        if _NUM_LIST_RE.match(line.rstrip()):
            if not line.rstrip().endswith(" +"):
                line = line.rstrip() + " +"

        lines.append(line)


def _emit_body_keep_breaks(lines: list[str], body: list[str] | None) -> None:
    if not body:
        return

    for raw in body:
        line = (raw or "").rstrip()

        if not line:
            lines.append("")
            continue

        if not line.endswith(" +"):
            line += " +"

        lines.append(line)


"""!
@fn _emit_plain 本文ノード出力処理
@brief 本文ノードを出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] body 本文ノード
"""
def _emit_plain(lines: list[str], body: list[str] | None) -> None:
    if not body:
        lines.append("")
        return

    _emit_body(lines, body)


def _unknown_names_by_line_from_diagnostics(
    n: Node,
) -> list[tuple[int | None, list[str]]]:

    groups: list[tuple[int | None, list[str], set[str]]] = []

    for d in getattr(n, "diagnostics", []) or []:
        line_no = getattr(d, "line", None)

        for m in re.finditer(
            r"unknown command: @([A-Za-z_][A-Za-z0-9_]*)",
            d.message,
        ):
            name = m.group(1)
            key = name.lower()

            for i, (line, names, seen) in enumerate(groups):
                if line == line_no:
                    if key not in seen:
                        names.append(name)
                        seen.add(key)
                    break
            else:
                groups.append((line_no, [name], {key}))

    return [(line, names) for line, names, _seen in groups]


def _emphasize_unknowns(text: str, names: set[str]) -> str:
    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name.lower() in names:
            return f"**@{name}**"
        return m.group(0)

    return _UNKNOWN_INLINE_RE.sub(repl, text)


def _to_posix_path(path: str) -> str:
    """Return a stable POSIX-style path for AsciiDoc include directives."""
    return Path(path).as_posix()


def _make_file_anchor(source_filename: str) -> str:
    """Return an anchor-safe id from a source relative path.

    Example:
        mischief/inline_mischief.js -> mischief_inline_mischief_js
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", _to_posix_path(source_filename))


def _make_source_block_anchor(
    *,
    file_anchor: str,
    block: SourceBlock,
) -> str:
    """Return a unique source-code anchor for a source block."""
    name = block.name or block.kind
    name_safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return f"src.{file_anchor}.L{block.start_line}.{name_safe}"


def _find_source_block_for_function(
    *,
    source_blocks: list[SourceBlock],
    function_block: FunctionBlock,
) -> SourceBlock | None:
    """Return the source block that should be linked from a function detail."""
    best: SourceBlock | None = None

    for block in source_blocks:
        if not (block.start_line <= function_block.function_start <= block.end_line):
            continue

        if best is None:
            best = block
            continue

        best_width = best.end_line - best.start_line
        block_width = block.end_line - block.start_line
        if block_width < best_width:
            best = block

    return best


def _make_source_include_path(source_filename: str) -> str:
    """Return include path from generated .adoc to generated clean source.

    Doxygon mirrors the input directory structure under both output/ and
    output/src/. Therefore, an .adoc generated at:

        output/mischief/inline_mischief.js.adoc

    must include:

        ../src/mischief/inline_mischief.js

    while a root-level .adoc includes:

        src/renderer_check.js
    """
    source_rel = Path(source_filename)
    depth = len(source_rel.parent.parts)
    prefix = "../" * depth
    return f"{prefix}src/{source_rel.as_posix()}"


_BRACE_SIGNATURE_LANGS = {"c", "cpp", "java", "javascript", "typescript"}


def _signature_lines_from_clean_source(
    *,
    clean_lines: list[str] | None,
    span: FunctionBlock,
    language: str,
) -> list[str]:
    """Return display lines for a function calling sequence.

    The source-code chapter must include the clean source as-is.  The calling
    sequence, however, is an API-style declaration, so the body-opening ``{``
    in brace languages is removed from the final signature line.  Python's
    trailing ``:`` is kept because it is part of the Python declaration syntax.
    """
    if not clean_lines:
        return []

    start = max(span.function_start - 1, 0)
    end = min(span.signature_end, len(clean_lines))

    if end <= start:
        return []

    result = list(clean_lines[start:end])

    if result and (language or "").lower() in _BRACE_SIGNATURE_LANGS:
        result[-1] = re.sub(r"\s*\{\s*$", "", result[-1]).rstrip()

    return result


def _emit_calling_sequence(
    lines: list[str],
    *,
    span: FunctionBlock,
    clean_lines: list[str] | None,
    lang_cfg: dict,
    include_source_path: str,
) -> None:
    """Emit a calling sequence.

    Prefer inline emission so the final ``{`` can be trimmed for brace based
    languages.  If clean source lines are unavailable, fall back to the old
    include:: form.
    """
    lines.append("\nコーリングシーケンス::")
    lines.append(f"[source,{lang_cfg.get('rouge_ext','text')}]")
    lines.append("----")

    signature_lines = _signature_lines_from_clean_source(
        clean_lines=clean_lines,
        span=span,
        language=lang_cfg.get("rouge_ext", ""),
    )

    if signature_lines:
        lines.extend(signature_lines)
    else:
        lines.append(
            f"include::{include_source_path}[lines={span.function_start}..{span.signature_end}]"
        )

    lines.append("----")


"""!
@fn _render_file "@file"コマンド描画処理
@brief "@file" はgenerate_adocで処理済みのため、ここでは何もしない。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n ファイルノード
"""
def _render_file(_lines: list[str], _n: Node) -> None:
    return


"""!
@fn _render_brief "@brief"コマンド描画処理
@brief "@brief"を処理概要セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n 処理概要ノード
"""
def _render_brief(lines: list[str], n: Node) -> None:
    body = _merge_argument_body(n)

    # Doxygon policy: if the author wrote @brief, emit the section even
    # when the payload is empty.  {empty} prevents the next block/heading
    # from being absorbed as labeled-list continuation text.
    #
    # Do not join or normalize body lines here.  Command payload is treated
    # as AsciiDoc authored by the user, so line-continuation markers such as
    # `` +`` must be passed through unchanged.
    lines.append("\n処理概要::")

    if any((line or "").strip() for line in body):
        _emit_body(lines, body)
    else:
        lines.append("{empty}")


"""!
@fn _render_details "@details"コマンド描画処理
@brief "@details"を処理詳細セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n 処理詳細ノード
"""
def _render_details(lines: list[str], n: Node) -> None:
    body = _merge_argument_body(n)

    # Doxygon policy: if the author wrote @details, emit the section even
    # when the payload is empty.  {empty} prevents the next block/heading
    # from being absorbed as labeled-list continuation text.
    #
    # Do not join or normalize body lines here.  Command payload is treated
    # as AsciiDoc authored by the user, so line-continuation markers such as
    # `` +`` must be passed through unchanged.
    lines.append("\n処理詳細::")

    if any((line or "").strip() for line in body):
        _emit_body(lines, body)
    else:
        lines.append("{empty}")


"""!
@fn _render_par "@par"コマンド描画処理
@brief "@par"をユーザー定義セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n ユーザー定義ノード
"""
def _render_par(lines: list[str], n: Node) -> None:
    title = (n.argument or "").strip(" \t")
    body = list(n.body or [])

    if not title:
        return

    lines.append(f"\n{title}::")

    if any((line or "").strip() for line in body):
        _emit_body(lines, body)
    else:
        lines.append("{empty}")


"""!
@fn _render_admonition admonition系コマンド描画処理
@brief note/warning/tipをadmonition系セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] kind admonition種別
@param [in] node admonition系ノード
"""
def _render_admonition(lines: list[str], kind: str, node: Node) -> None:
    body = _merge_argument_body(node)

    # Use a longer delimited block marker than section headings.
    # Empty admonition blocks written as [NOTE] / ==== / ==== can be
    # misread by Asciidoctor.  Keep the command visible, but make the
    # block syntactically explicit by emitting {empty} when no body exists.
    lines.append(f"\n[{kind.upper()}]")
    lines.append("========")

    if any((line or "").strip() for line in body):
        _emit_body_keep_breaks(lines, body)
    else:
        lines.append("{empty}")

    lines.append("========")


"""!
@fn _render_attention "@attention"コマンド描画処理
@brief "@attention"を確認ポイントセクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n 確認ポイントノード
"""
def _render_attention(lines: list[str], n: Node) -> None:
    lines.append("\n確認ポイント::")

    # @attention は「確認ポイント::」を固定ラベルとして出力する。
    # そのため、引数側にも同じ語が書かれている場合は、
    # PDF上で「確認ポイント」が二重に見えないように引数を本文へ混ぜない。
    arg = (n.argument or "").strip()
    if arg == "確認ポイント":
        body = list(n.body or [])
    else:
        body = _merge_argument_body(n)

    if any((line or "").strip() for line in body):
        _emit_body(lines, body)
    else:
        lines.append("{empty}")


"""!
@fn _render_deprecated "@deprecated"コマンド描画処理
@brief "@deprecated"を非推奨セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n 非推奨ノード
"""
def _render_deprecated(lines: list[str], n: Node) -> None:
    lines.append("\n非推奨::")
    body = _merge_argument_body(n)

    if any((line or "").strip() for line in body):
        _emit_body(lines, body)
    else:
        lines.append("{empty}")


"""!
@fn _render_todo "@todo"コマンド描画処理
@brief "@todo"をTODOセクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n TODOノード
"""
def _render_todo(lines: list[str], n: Node) -> None:
    lines.append("\nTODO::")

    body = _merge_argument_body(n)
    if any((line or "").strip() for line in body):
        _emit_body_keep_breaks(lines, body)
    else:
        lines.append("{empty}")


"""!
@fn _render_figure "@figure"コマンド描画処理
@brief "@figure"に図キャプションを付加し、画像セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n 画像ノード
"""
def _render_figure(
    lines: list[str],
    n: Node,
    *,
    source_filename: str | None = None,
) -> None:
    title = _escape_adoc_attr_value(n.argument or "")

    lines.append(
        f'\n[caption="{{fig_caption}}.{{counter:figure}}",title=" {title}"]'
    )

    if n.segments:
        _emit_segments_raw(lines, n.segments)
    else:
        _emit_body(lines, n.body)

"""!
@fn _render_table "@table"コマンド描画処理
@brief @@tableに表キャプションを付加し、テーブルセクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n テーブルノード
"""
def _render_table(
    lines: list[str],
    n: Node,
    *,
    source_filename: str | None = None,
) -> None:
    title = _escape_adoc_attr_value(n.argument or "")

    lines.append(
        f'\n[caption="{{tbl_caption}}.{{counter:table}}",title=" {title}"]'
    )

    if n.segments:
        _emit_segments_raw(lines, n.segments)
    else:
        _emit_body(lines, n.body)

"""!
@fn _render_authors "@author"コマンド描画処理
@brief "@author"群を担当者セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] authors 担当者ノード
"""
def _render_authors(lines: list[str], authors: list[Node]) -> None:
    if not authors:
        return

    lines.append("\n担当者::")

    seen: set[str] = set()

    def _format_email(text: str) -> str:
        if "<" in text and ">" in text:
            return text

        parts = text.split()
        if len(parts) >= 2 and "@" in parts[-1]:
            name = " ".join(parts[:-1])
            mail = parts[-1]
            return f"{name} <{mail}>"

        return text

    for a in authors:

        arg = (a.argument or "").strip()
        body = [b.strip() for b in (a.body or []) if b.strip()]

        if arg and arg not in seen:
            formatted = _format_email(arg)
            lines.append(f"{formatted} +")
            seen.add(arg)

        for b in body:
            if b not in seen:
                formatted = _format_email(b)
                lines.append(f"{formatted} +")
                seen.add(b)


"""!
@fn _render_params "@param"コマンド描画処理
@brief "@param"群を引数セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] params 引数ノード
"""
def _render_params(lines: list[str], params: list[Node]) -> None:
    if not params:
        return

    lines.append("\n引数::")

    for p in params:
        arg = (p.argument or "").strip()
        body = list(p.body or [])

        while body and not body[0].strip():
            body.pop(0)

        parts = _split_ascii_ws(arg, maxsplit=1)

        direction = ""
        name = ""
        desc = ""

        if parts:
            if parts[0] in _ALLOWED_PARAM_DIRECTIONS:
                direction = parts[0]
                name, desc = _split_argument(parts[1] if len(parts) >= 2 else "")
            else:
                name, desc = _split_argument(arg)

        if not desc and body and _is_promotable_one_liner(body[0]):
            desc = body.pop(0).strip()

        if direction:
            if desc:
                lines.append(f"{direction} [.maroon]##{name}##::: {desc}")
            else:
                lines.append(f"{direction} {name}::: {{empty}}")
        else:
            if desc:
                lines.append(f"[.maroon]##{name}##::: {desc}")
            else:
                lines.append(f"[.maroon]##{name}##::: {{empty}}")

        _emit_body(lines, body)


def _render_returns(lines: list[str], nodes: list[Node]) -> None:
    """Render @return nodes without TAG/SENTENCE splitting.

    @return is not a key-value command in the display sense.  Its argument is
    the return-value text itself, so Japanese text such as ``戻り 値タグG``
    must be preserved as written.
    """
    if not nodes:
        return

    lines.append("\n戻り値::")

    for n in nodes:
        text = (n.argument or "").strip(" \t")
        body = list(n.body or [])

        while body and not body[0].strip():
            body.pop(0)

        if text:
            lines.append(text)
        elif body and _is_promotable_one_liner(body[0]):
            lines.append(body.pop(0).strip())
        elif not any((line or "").strip() for line in body):
            lines.append("{empty}")
            body = []

        _emit_body(lines, body)


"""!
@fn _render_kv_section Key-Value 系コマンド描画処理
@brief 戻り値、変数、マクロなどのKey-Value系セクションを出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] nodes Key-Value系ノードリスト
@param [in] title セクションタイトル
"""
def _render_kv_section(
    lines: list[str],
    nodes: list[Node],
    title: str,
) -> None:
    if not nodes:
        return

    lines.append(f"\n{title}::")

    for n in nodes:

        name, desc = _split_argument(n.argument or "")

        body = list(n.body or [])

        if not desc and body and _is_promotable_one_liner(body[0]):
            desc = body.pop(0).strip()

        if name:
            if desc:
                lines.append(f"{name}::: {desc}")
            else:
                lines.append(f"{name}::: {{empty}}")
        else:
            # @return can be written as:
            #   @return
            #   description
            # In that case there is no key/name.  Do not emit an empty
            # labeled-list key, because Asciidoctor renders it as ':' in PDF.
            #
            # If both description and body are empty, explicitly emit {empty}.
            # Without this placeholder, Asciidoctor may treat the next section
            # title as the continuation text of the labeled list item.
            if desc:
                lines.append(desc)
            elif not any((line or "").strip() for line in body):
                lines.append("{empty}")
                body = []

        _emit_body(lines, body)


def _append_summary_entry(lines: list[str], name: str, desc: str) -> None:
    display_name = _escape_adoc_identifier(name)

    if desc:
        lines.append(f"* {display_name} : {desc}")
    else:
        lines.append(f"* {display_name}")




def _append_summary_title(lines: list[str], title: str) -> None:
    lines.append("")
    lines.append(f"**{title}**::")
    lines.append("")


def _render_function_summary(
    lines: list[str],
    function_blocks: list[FunctionBlock],
    fn_nodes_by_name: dict[str, Node],
) -> None:
    if not function_blocks:
        return

    _append_summary_title(lines, "関数")

    for fn_block in function_blocks:
        fn_node = _find_fn_node(fn_nodes_by_name, fn_block.name)

        if fn_node is not None:
            _fname, desc = _split_argument(fn_node.argument or "")
        else:
            desc = ""

        _append_summary_entry(lines, fn_block.name, desc)


def _render_define_summary(lines: list[str], nodes: list[Node]) -> None:
    targets: list[Node] = []

    for n in nodes:
        if n.command != "define":
            continue

        # @define requires a tag.  Empty @define is reported by the normal
        # grouped renderer as SYNTAX_ERROR; do not also emit an empty bullet
        # in the global macro summary.
        name, _desc = _split_argument(n.argument or "")
        if not name:
            continue

        # Diagnostics-bearing nodes should not be promoted to summaries.
        if getattr(n, "diagnostics", None):
            continue

        targets.append(n)

    if not targets:
        return

    _append_summary_title(lines, "マクロ")

    for n in targets:
        name, desc = _split_argument(n.argument or "")
        _append_summary_entry(lines, name, desc)


def _render_container_summary(
    lines: list[str],
    nodes: list[Node],
    command: str,
) -> None:
    targets = [n for n in nodes if n.command == command or (n.is_container and n.command == command)]

    if not targets:
        return

    title = CONTAINER_TITLE_MAP.get(command, "コンテナ")

    _append_summary_title(lines, title)

    for n in targets:
        name, desc = _split_argument(n.argument or "")
        _append_summary_entry(lines, name, desc)


def _split_inline_member_argument(argument: str) -> tuple[str, str]:
    """Return member name/description from an inline child argument.

    Preferred inline syntax is:
        member; /**!< description */

    For JS/TS, preproc may pick the type token as the member name when a
    type annotation exists. Therefore this also accepts the explicit form:
        member: Type; /**!< @var member description */
    and lets the @var payload override the inferred token.
    """
    arg = (argument or "").strip()

    if not arg:
        return "", ""

    parts = _split_ascii_ws(arg)
    if "@var" in parts:
        idx = parts.index("@var")
        rest = parts[idx + 1:]
        if rest:
            name = rest[0]
            desc = " ".join(rest[1:])
            return name, desc

    return _split_argument(arg)


def _render_inline_members(lines: list[str], nodes: list[Node]) -> None:
    if not nodes:
        return

    lines.append("\nメンバ::")

    for n in nodes:
        raw_arg = (n.argument or "").strip()
        body = list(n.body or [])

        # Inline comments are part of the source author's text.
        # Do not reject or silently drop unsupported-looking @commands.
        #
        # Keep @var as the member-friendly shorthand:
        #     member; /**!< @var member description */
        #
        # For any other standalone @command in an inline comment, emit it
        # as-is so it does not disappear into the dark.
        #     /**!< @author name <mail> */
        if raw_arg.startswith("@") and not raw_arg.startswith("@var"):
            lines.append(raw_arg)
            _emit_body(lines, body)
            continue

        name, desc = _split_inline_member_argument(raw_arg)

        if not desc and body and _is_promotable_one_liner(body[0]):
            desc = body.pop(0).strip()

        if desc:
            lines.append(f"{name}::: {desc}")
        else:
            lines.append(f"{name}::: {{empty}}")

        _emit_body(lines, body)


def _container_has_detail(n: Node) -> bool:
    """Return True when a container needs its own detail section.

    The container command's TAG/SENTENCE itself is already shown in the
    container summary list.  Therefore a detail section is emitted only when
    the container has additional content such as body text, child commands,
    inline members, or an actual DelimSegment.

    Note: current V4 Node always has ``segments``.  A command without body may
    still carry an empty TextSegment, so checking ``if n.segments`` makes every
    container look detailed.
    """
    if n.body and any((line or "").strip() for line in n.body):
        return True

    if n.children:
        return True

    for seg in (n.segments or []):
        if isinstance(seg, DelimSegment):
            return True
        if isinstance(seg, TextSegment) and any((line or "").strip() for line in seg.lines):
            return True

    # Older/future models may expose delim_blocks directly.
    if getattr(n, "delim_blocks", None):
        return True

    return False


"""!
@fn _render_container_section コンテナブロック描画処理
@brief コンテナブロックを描画する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] nodes 対象となるコンテナブロック
@param [in] command Doxygonコマンド
"""
def _render_container_section(
    lines: list[str],
    nodes: list[Node],
    command: str,
    *,
    source_filename: str | None = None,
    function_blocks: list[FunctionBlock] | None = None,
    fn_nodes_by_name: dict[str, Node] | None = None,
) -> None:
    targets = [n for n in nodes if n.command == command and _container_has_detail(n)]

    if not targets:
        return

    title = CONTAINER_TITLE_MAP.get(command, "コンテナ")

    lines.append(f"\n==== {title}詳解")

    for n in targets:
        name, desc = _split_argument(n.argument or "")

        lines.append(f"\n===== {_escape_adoc_identifier(name)}")

        if desc:
            lines.append(desc)

        if n.segments:
            _emit_segments(lines, n.segments)
        elif n.body:
            _emit_body(lines, n.body)

        if n.children:
            children = list(n.children)
            orphan_nodes: list[OrphanWarning] = []

            if function_blocks is not None and fn_nodes_by_name is not None:
                children, orphan_nodes = _split_orphan_nodes_for_function_context(
                    children,
                    function_blocks=function_blocks,
                    fn_nodes_by_name=fn_nodes_by_name,
                    expected_fn_name=None,
                )

            _render_grouped(
                lines,
                children,
                var_title="メンバ",
                source_filename=source_filename,
            )

            for orphan, parent_kind, parent_name in orphan_nodes:
                _present_orphan_warning(
                    lines,
                    orphan,
                    source_filename=source_filename,
                    parent_kind=parent_kind,
                    parent_name=parent_name,
                )


"""!
@fn _present_duplicate 重複"@file"コマンド表示処理
@brief 重複した"@file"コマンドを警告セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n 重複コマンドノード
"""
def _present_duplicate(
    lines: list[str],
    n: Node,
    *,
    source_filename: str | None = None,
) -> None:

    location = _extract_location(n, source_filename=source_filename)

    lines.append(
        f"\n\n====\n[.red]##[DUPLICATE]##{location} \
        **@file** コマンドが重複しています。\n====")

    _emit_body(lines, body=None)


"""!
@fn _present_unknown 未定義コマンド表示処理
@brief 未定義コマンドをUNKNOWNセクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] n 未定義コマンドノード
"""
def _present_unknown(
        lines: list[str],
        n: Node,
        *,
        source_filename: str | None = None,
) -> None:

    groups = _unknown_names_by_line_from_diagnostics(n)

    if not groups:
        location = _extract_location(n, source_filename=source_filename)
        lines.append(
            f"\n\n====\n"
            f"[.red]##[UNKNOWN]##{location} "
            f"指定されたコマンドは存在しません。\n"
            f"===="
        )
        return

    for line_no, names in groups:
        if source_filename and line_no is not None:
            location = f" {source_filename}: {line_no}"
        elif source_filename:
            location = f" {source_filename}"
        elif line_no is not None:
            location = f" line:{line_no}"
        else:
            location = ""

        names_text = "、".join(f"**@{name}**" for name in names)

        lines.append(
            f"\n\n====\n"
            f"[.red]##[UNKNOWN]##{location} "
            f"指定された {names_text} コマンドは存在しません。\n"
            f"===="
        )


COMMAND_RENDERERS = {
    "file": _render_file,
    "brief": _render_brief,
    "details": _render_details,
    "par": _render_par,
    "warning": lambda l, n: _render_admonition(l, "warning", n),
    "caution": lambda l, n: _render_admonition(l, "caution", n),
    "important": lambda l, n: _render_admonition(l, "important", n),
    "note": lambda l, n: _render_admonition(l, "note", n),
    "tip": lambda l, n: _render_admonition(l, "tip", n),
    "attention": _render_attention,
    "deprecated": _render_deprecated,
    "todo": _render_todo,
    "figure": _render_figure,
    "table": _render_table,
    "duplicate": _present_duplicate,
}


"""!
@fn _present_syntax_error 構文エラー表示処理
@brief 構文エラーが発生した場合 [SYNTAX_ERROR] として出力する。
@param [in] lines AsciiDocドキュメント出力行リスト
@param [in] n 構文エラーノード
"""
def _present_syntax_error(
    lines: list[str],
    n: Node,
    *,
    source_filename: str | None = None,
) -> None:
    """Emit a syntax error with compact source location information."""

    location = _extract_location(n, source_filename=source_filename)

    message = "Doxygon コマンドの構文に誤りがあります。"

    arg = (n.argument or "").strip()
    command_text = arg
    if not command_text and getattr(n, "command", None):
        command_text = f"@{n.command}"

    tag_required_commands = {
        "par",
        "author",
        "var",
        "define",
        "fn",
        "class",
        "struct",
        "enum",
        "interface",
        "union",
        "type",
        "figure",
        "table",
    }

    for d in getattr(n, "diagnostics", []) or []:
        if "multiple doxygen command in one line" in d.message:
            message = "1行に複数の Doxygon コマンドを記述することはできません。"
            break
        if "invalid tag for @var" in d.message:
            message = "@var コマンドの構文に誤りがあります。"
            break
    else:
        if getattr(n, "command", None) == "param" or command_text.startswith("@param"):
            message = "@param コマンドの [in/out] の指定に誤りがあります。"
        else:
            for command_name in sorted(tag_required_commands, key=len, reverse=True):
                if command_text.startswith(f"@{command_name}"):
                    message = f"@{command_name} コマンドの構文に誤りがあります。"
                    break

    for d in getattr(n, "diagnostics", []) or []:
        if "unterminated DELIM block" in d.message:
            message = "除外ブロックの終端デリミタが存在しません。"
            break

    lines.append(
        f"\n\n====\n[.red]##[SYNTAX_ERROR]##{location} "
        f"{message}\n===="
    )

    _emit_body(lines, body=None)


"""!
@fn _render_grouped コマンドグループまとめ処理
@brief param/return/varなど同種コマンドを出現順を保ちながらまとめて描画する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] nodes 描画対象コマンドノード
"""
def _render_grouped(
    lines: list[str],
    nodes: list[Node],
    *,
    var_title: str = "変数",
    source_filename: str | None = None,
) -> None:
    buffer: list[Node] = []
    current_type: str | None = None

    def flush():
        nonlocal buffer, current_type

        if not buffer:
            return

        match current_type:
            case "param":
                _render_params(lines, buffer)
            case "return":
                _render_returns(lines, buffer)
            case "author":
                _render_authors(lines, buffer)
            case "var":
                _render_kv_section(lines, buffer, var_title)
            case "define":
                _render_kv_section(lines, buffer, "マクロ")
            case "inline":
                _render_inline_members(lines, buffer)
            case _:
                _render_nodes(lines, buffer, source_filename=source_filename)

        buffer = []
        current_type = None

    for n in nodes:

        # @define requires a tag.  The parser currently accepts an empty
        # @define node, so reject it here to avoid emitting an empty
        # "マクロ::" section with no actual item.
        if n.command == "define" and not (n.argument or "").strip() and not any(
            (line or "").strip() for line in (n.body or [])
        ):
            flush()
            _present_syntax_error(lines, n, source_filename=source_filename)
            continue

        if n.command == "param" and _has_invalid_param_direction(n.argument or ""):
            flush()
            _present_syntax_error(lines, n, source_filename=source_filename)
            continue

        if n.command in {"param", "return", "author", "var", "define"} and getattr(n, "is_error", False):
            flush()
            _present_syntax_error(lines, n, source_filename=source_filename)
            continue

        if n.command in {"param", "return", "author", "var", "define", "inline"}:

            if current_type == n.command:
                buffer.append(n)
            else:
                flush()
                buffer = [n]
                current_type = n.command

        else:
            flush()
            _render_nodes(lines, [n], source_filename=source_filename)

    flush()


"""!
@fn _render_nodes 単独コマンド描画処理
@brief 単独コマンドを単独セクションとして出力する。
@param [in,out] lines AsciiDocドキュメント出力行リスト
@param [in] nodes 単独コマンドノード
"""
def _render_nodes(
    lines: list[str],
    nodes: list[Node],
    *,
    source_filename: str | None = None,
) -> None:

    for n in nodes:
        # plain
        if n.command == "plain":
            _emit_plain(lines, n.body)
            continue

        # inline children
        if n.command == "inline":
            _render_inline_members(lines, [n])
            continue

        # syntax error
        if n.command == "__syntax_error__":
            _present_syntax_error(lines, n, source_filename=source_filename)

            # DELIM_BLOCK is user-authored AsciiDoc payload.  Once it has
            # been extracted by preproc, keep it visible even when the
            # preceding Doxygon command line has a syntax error.
            if getattr(n, "segments", None):
                _emit_segments_raw(lines, n.segments)

            continue

        if n.diagnostics and any("unterminated DELIM block" in d.message for d in n.diagnostics):
            _present_syntax_error(lines, n, source_filename=source_filename)
            # Error recovery: keep rendering the rescued payload.  This is
            # especially important for @figure/@table whose DELIM payload can
            # still be valid AsciiDoc/PlantUML even when the closing delimiter
            # was omitted.

        if n.diagnostics and any("unknown command:" in d.message for d in n.diagnostics):
            _present_unknown(lines, n, source_filename=source_filename)
            continue

        # dispatch
        if n.command == "figure":
            _render_figure(lines, n, source_filename=source_filename)
            continue

        if n.command == "table":
            _render_table(lines, n, source_filename=source_filename)
            continue

        renderer = COMMAND_RENDERERS.get(n.command)

        if renderer:
            renderer(lines, n)
            continue

        raise RuntimeError(
            f"Renderer not found for Doxygon command: @{n.command}"
        )


"""!
@fn generate_adoc AsciiDocドキュメント生成処理
@brief Doxygonノード列とソース構造情報からAsciiDocドキュメントを生成する。
@param [in] nodes Doxygonノード列
@param [in] source_filename 対象となるソースファイル名
@param [in] lang_cfg プログラミング言語情報
@param [in] function_blocks 関数領域一覧
@param [in] global_blocks グローバル領域一覧
@return adoc_text 生成されたAsciiDocドキュメント
"""
def generate_adoc(
    *,
    nodes: list[Node],
    source_filename: str,
    lang_cfg: dict,
    function_blocks: list[FunctionBlock],
    global_blocks: list[GlobalBlock],
    source_blocks: list[SourceBlock],
    clean_lines: list[str] | None = None,
) -> str:
    lines: list[str] = []
    file_anchor = _make_file_anchor(source_filename)
    include_source_path = _make_source_include_path(source_filename)

    # file
    file_node = next((n for n in nodes if n.command == "file"), None)

    if file_node:
        name, desc = _split_argument(file_node.argument or "")
        # Empty @file is equivalent to an omitted @file: use the source
        # filename as the file tag.  This keeps @file faithful to the
        # auto-completion rule while still allowing duplicate @file tests.
        if not name:
            name = source_filename
    else:
        name = source_filename
        desc = ""

    lines.append(f"\n=== {name} ファイル")

    if desc:
        lines.append("")

        if source_blocks:
            first_source_anchor = _make_source_block_anchor(
                file_anchor=file_anchor,
                block=source_blocks[0],
            )
            lines.append(f"<<{first_source_anchor},{desc}>>")
        else:
            lines.append(desc)

    global_nodes, fn_nodes, container_nodes = _split_global_and_sections(nodes)

    fn_nodes_by_name = _map_fn_nodes_by_name(fn_nodes)

    # @file に続く @command はここに表示
    global_nodes_without_define = [
        n for n in global_nodes
        if n.command not in {"file"}
    ]

    _render_grouped(lines, global_nodes_without_define, source_filename=source_filename)

    # コンテナ索引
    for command in ("class", "struct", "enum", "interface", "union", "type"):
        _render_container_summary(lines, container_nodes, command)

    # マクロ索引
    _render_define_summary(lines, global_nodes)

    # 関数一覧
    _render_function_summary(lines, function_blocks, fn_nodes_by_name)

    # 関数詳解
    if fn_nodes:
        lines.append("\n==== 関数詳解")

    for fn in fn_nodes:

        fname, fdesc = _split_fn_argument(fn.argument or "")
        lookup_name = _fn_lookup_name(fn.argument or "")

        lines.append(f"\n===== {_escape_adoc_identifier(fname)}")

        if fdesc:
            lines.append(fdesc)

        span = _find_function_block(function_blocks, lookup_name)

        if span:
            _emit_calling_sequence(
                lines,
                span=span,
                clean_lines=clean_lines,
                lang_cfg=lang_cfg,
                include_source_path=include_source_path,
            )

            source_block = _find_source_block_for_function(
                source_blocks=source_blocks,
                function_block=span,
            )

            if source_block is not None:
                anchor = _make_source_block_anchor(
                    file_anchor=file_anchor,
                    block=source_block,
                )
                lines.append(f"<<{anchor},ソースコードを見る>> （{span.function_start} 行目）")

        # 本文
        fn_children = list(fn.children or [])
        fn_orphans: list[OrphanWarning] = []

        if span is not None:
            fn_children, fn_orphans = _split_orphan_nodes_for_function_context(
                fn_children,
                function_blocks=function_blocks,
                fn_nodes_by_name=fn_nodes_by_name,
                expected_fn_name=lookup_name,
            )

        _render_grouped(lines, fn_children, source_filename=source_filename)

        for orphan, parent_kind, parent_name in fn_orphans:
            _present_orphan_warning(
                lines,
                orphan,
                source_filename=source_filename,
                parent_kind=parent_kind,
                parent_name=parent_name,
            )

    # コンテナ
    for command in ("class", "struct", "enum", "interface", "union", "type"):
        _render_container_section(
            lines,
            container_nodes,
            command,
            source_filename=source_filename,
            function_blocks=function_blocks,
            fn_nodes_by_name=fn_nodes_by_name,
        )

    if source_blocks:
        lines.append("\n==== ソースコード")

    file_source_anchor_written = False

    for block_index, block in enumerate(source_blocks):

        if not file_source_anchor_written:
            lines.append(f"\n[[src.{file_anchor}]]")
            file_source_anchor_written = True

        anchor = _make_source_block_anchor(
            file_anchor=file_anchor,
            block=block,
        )

        lines.append(f"\n[[{anchor}]]")

        # V5 source-code chapter rule:
        #   - container/function blocks use their own name as the heading.
        #   - an unnamed block at the very top of the source-code chapter
        #     uses the file name, so top-level file code does not float.
        #   - later unnamed declaration/global blocks keep no heading, because
        #     repeating the file name for every declaration is noisy.
        if block.name:
            lines.append(f"===== {_escape_adoc_identifier(block.name)}")
        elif block_index == 0:
            lines.append(f"===== {source_filename}")

        lines.append(
            f"[source,{lang_cfg.get('rouge_ext','text')},linenums,start={block.start_line}]"
        )
        lines.append("----")
        lines.append(
            f"include::{include_source_path}[lines={block.start_line}..{block.end_line}]"
        )
        lines.append("----")

    return "\n".join(lines)
