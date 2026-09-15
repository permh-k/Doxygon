#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file main.py Doxygon メイン処理
"""

import sys
from pathlib import Path
import tomllib
from typing import Any

from doxygon.builder.generated_files import prepare_generated_files
from doxygon.builder.unit_test_builder import build_unit_test_file_spec
from doxygon.generator import generate_adoc
from doxygon.generator.unit_test_csv import write_unit_test_csv
from doxygon.generator.unit_test_json import (
    write_unit_test_json,
)
from doxygon.model import Node, SourceUnit, UtFileSpec
from doxygon.parser import parse_command_blocks
from doxygon.preproc import preprocess
from doxygon.scanner import scan_source_structure, scan_sources

from .config_loader import load_config


"""!
@fn _write_output_file AsciiDocドキュメント出力処理
@brief 生成されたAsciiDocドキュメントを出力先フォルダへ出力する。
@param [in] basename AsciiDocドキュメントファイル名
@param [in] adoc_text 対象となるAsciiDocドキュメント
@param [in] output_path 出力先フォルダ
"""
def _write_output_file(
    relative_path: Path,
    adoc_text: str,
    output_path: Path,
) -> None:
    """Write generated adoc while preserving input directory structure.

    Example:
        input/common/util.js -> output/common/util.js.adoc
    """

    adoc_path = output_path / relative_path.parent / f"{relative_path.name}.adoc"
    adoc_path.parent.mkdir(parents=True, exist_ok=True)

    with open(adoc_path, "w", encoding="utf-8") as f:
        f.write(adoc_text)


def _unique_pairs(starts: list[str], ends: list[str]) -> list[tuple[str, str]]:
    """Return unique non-empty start/end pairs while preserving order."""

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


def _unique_strings(values: list[str]) -> list[str]:
    """Return unique non-empty strings while preserving order."""

    result: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        if not value:
            continue

        if value in seen:
            continue

        seen.add(value)
        result.append(value)

    return result


def _make_clean_source_rules(
    languages_conf: dict[str, Any],
    clean_conf: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build clean-source deletion rules.

    The base rules are generated from every language's Doxygon comment
    extraction settings.  Extra rescue rules can be added under
    [clean_source] in config.toml.

    VBA and Python are intentionally excluded from the cross-language
    generated rules.

    VBA uses quote-prefixed pseudo block syntax.
    Python uses triple-quote based syntax, and its end token can collide with
    normal docstrings.  Both should use their own language-specific clean
    source rules instead of the cross-language merged rules.
    """

    block_pairs: list[tuple[str, str]] = []
    inline_pairs: list[tuple[str, str]] = []
    line_starts: list[str] = []

    for lang, conf in languages_conf.items():
        if lang.lower() in {"vba", "python"}:
            continue

        block_pairs.extend(
            _unique_pairs(
                conf.get("dox_block_start", []),
                conf.get("dox_block_end", []),
            )
        )

        inline_pairs.extend(
            _unique_pairs(
                conf.get("dox_inline_start", []),
                conf.get("dox_inline_end", []),
            )
        )

    clean_conf = clean_conf or {}

    block_pairs.extend(
        _unique_pairs(
            clean_conf.get("extra_block_starts", []),
            clean_conf.get("extra_block_ends", []),
        )
    )

    inline_pairs.extend(
        _unique_pairs(
            clean_conf.get("extra_inline_starts", []),
            clean_conf.get("extra_inline_ends", []),
        )
    )

    line_starts.extend(
        _unique_strings(
            clean_conf.get("extra_line_starts", []),
        )
    )

    # Final de-duplication after merging generated rules and extra rules.
    block_pairs = _unique_pairs(
        [p[0] for p in block_pairs],
        [p[1] for p in block_pairs],
    )
    inline_pairs = _unique_pairs(
        [p[0] for p in inline_pairs],
        [p[1] for p in inline_pairs],
    )
    line_starts = _unique_strings(line_starts)

    return {
        "block_pairs": block_pairs,
        "inline_pairs": inline_pairs,
        "line_starts": line_starts,
    }


def _make_source_clean_source_rules(
    *,
    source_language: str,
    lang_conf: dict[str, Any],
    global_clean_source_rules: dict[str, Any],
) -> dict[str, Any]:
    """Return clean-source rules for a specific source file.

    Most C-like languages can use the cross-language merged Doxygon comment
    rules.  Python and VBA are safer with their own language-specific rules
    because their comment markers are not ordinary C-like comments.
    """

    if source_language.lower() in {"python", "vba"}:
        return {
            "block_pairs": _unique_pairs(
                lang_conf.get("dox_block_start", []),
                lang_conf.get("dox_block_end", []),
            ),
            "inline_pairs": _unique_pairs(
                lang_conf.get("dox_inline_start", []),
                lang_conf.get("dox_inline_end", []),
            ),
            "line_starts": list(global_clean_source_rules.get("line_starts", [])),
        }

    return global_clean_source_rules

"""!
@fn main メイン処理
@brief 指定されたソースファイルのDoxygonコメントを解析し、AsciiDocドキュメントを生成する。
"""

def _load_command_names(command_toml_path: Path) -> set[str]:
    with command_toml_path.open("rb") as f:
        data = tomllib.load(f)

    commands = data.get("commands", {})

    if not isinstance(commands, dict):
        return set()

    return {str(name).lower() for name in commands.keys()}


def _print_unit_test_diagnostics(
    *,
    nodes: list[Node],
    source_filename: str,
) -> None:
    for node in nodes:
        if node.command != "ut":
            continue

        for diagnostic in node.diagnostics:
            if "invalid abnormal marker in @ut heading" not in diagnostic.message:
                continue

            location = f" {source_filename}"
            if diagnostic.line is not None:
                location += f": {diagnostic.line}"

            print(
                f"[SYNTAX_ERROR]{location} "
                "@ut コマンドの見出しに ! を指定することはできません。"
            )

def main() -> None:

    config_path: Path = Path("config.toml")
    config: dict[str, Any] = load_config(path=config_path)

    project_root = Path.cwd()

    # --------------------------------------------------
    # generated files
    # --------------------------------------------------
    prepare_generated_files(project_root)

    command_toml_path = project_root / "config" / "command.toml"
    command_names = _load_command_names(command_toml_path)

    input_path: Path = Path(config["paths"]["input_dir"])
    output_path: Path = Path(config["paths"]["output_dir"])

    languages_conf = config["languages"]

    clean_source_rules = _make_clean_source_rules(
        languages_conf,
        config.get("clean_source", {}),
    )

    sources: list[SourceUnit] = scan_sources(input_path, languages_conf)
    delim_conf = config["delim"]
    unit_test_cfg = config.get("unit_test", {})
    json_output = unit_test_cfg.get("json_output", False)
    csv_output = unit_test_cfg.get("csv_output", False)

    if not isinstance(json_output, bool):
        raise ValueError(
            "[unit_test] json_output は true/false で指定してください。"
        )

    if not isinstance(csv_output, bool):
        raise ValueError(
            "[unit_test] csv_output は true/false で指定してください。"
        )

    unit_test_output = json_output or csv_output

    unit_test_file_specs: list[UtFileSpec] = []

    for src in sources:

        print(f"Searching for files in directory {src.path} ...")

        try:
            relative_path = src.path.relative_to(input_path)
        except ValueError:
            relative_path = src.path.resolve().relative_to(input_path.resolve())

        source_filename = relative_path.as_posix()

        lines: list[str] = src.raw_lines or []

        # --------------------------------------------------
        # preprocess
        # --------------------------------------------------
        print(f"Preprocessing {src.path} ...\n")

        lang_conf = languages_conf[src.language]

        command_blocks = preprocess(
            lines,
            block_starts=lang_conf["dox_block_start"],
            block_ends=lang_conf["dox_block_end"],
            inline_starts=lang_conf["dox_inline_start"],
            inline_ends=lang_conf["dox_inline_end"],
            container_commands=src.container_commands,
            delim_separator=delim_conf["separator"],
            known_commands=command_names,
        )

        # --------------------------------------------------
        # source structure scan
        # --------------------------------------------------
        print("Scanning source structure ...")

        source_clean_source_rules = _make_source_clean_source_rules(
            source_language=src.language,
            lang_conf=lang_conf,
            global_clean_source_rules=clean_source_rules,
        )

        clean_lines, function_blocks, global_blocks, source_blocks = scan_source_structure(
            source=src,
            clean_source_rules=source_clean_source_rules,
        )

        # --------------------------------------------------
        # clean source output
        # --------------------------------------------------
        if clean_lines:
            print("Generating clean sources ...")

            clean_path = output_path / "src" / relative_path
            clean_path.parent.mkdir(parents=True, exist_ok=True)
            clean_path.write_text(
                "\n".join(clean_lines) + "\n",
                encoding="utf-8",
            )

        # --------------------------------------------------
        # parser
        # --------------------------------------------------
        print("Parsing files ...")

        nodes = parse_command_blocks(
            command_blocks,
            command_lark_path=project_root / "generated" / "command.lark",
            command_toml_path=command_toml_path,
            container_commands=lang_conf.get("container_commands", []),
        )

        _print_unit_test_diagnostics(
            nodes=nodes,
            source_filename=source_filename,
        )

        if unit_test_output:
            unit_test_file_specs.append(
                build_unit_test_file_spec(
                    source_filename=source_filename,
                    nodes=nodes,
                )
            )

        # --------------------------------------------------
        # adoc generation
        # --------------------------------------------------
        print("Generating adoc files ...")

        adoc_text = generate_adoc(
            nodes=nodes,
            source_filename=source_filename,
            lang_cfg=lang_conf,
            function_blocks=function_blocks,
            global_blocks=global_blocks,
            source_blocks=source_blocks,
            clean_lines=clean_lines,
            unit_test_cfg=unit_test_cfg,
        )

        _write_output_file(
            relative_path,
            adoc_text,
            output_path,
        )

    for file_spec in unit_test_file_specs:
        if json_output:
            write_unit_test_json(
                output_path=(
                    output_path / f"{file_spec.source_filename}.json"
                ),
                file_specs=[file_spec],
            )

        if csv_output:
            write_unit_test_csv(
                output_path=(
                    output_path / f"{file_spec.source_filename}.csv"
                ),
                file_specs=[file_spec],
            )


if __name__ == "__main__":
    main()
