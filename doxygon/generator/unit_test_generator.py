#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file unit_test_generator.py 単体試験仕様書生成統括処理
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doxygon.builder.unit_test_builder import build_unit_test_file_spec
from doxygon.generator.unit_test_csv import write_unit_test_csv
from doxygon.generator.unit_test_json import write_unit_test_json
from doxygon.model import Node, UtFileSpec


@dataclass(slots=True, frozen=True)
class UnitTestConfig:
    json_output: bool = False
    csv_output: bool = False
    auto_generate: bool = False
    csv_encoding_utf8: bool = False

    @property
    def output_enabled(self) -> bool:
        return self.json_output or self.csv_output

    @property
    def csv_encoding(self) -> str:
        return "utf-8-sig" if self.csv_encoding_utf8 else "cp932"


def _boolean_setting(
    config: dict[str, Any],
    name: str,
) -> bool:
    value = config.get(name, False)

    if not isinstance(value, bool):
        raise ValueError(
            f"[unit_test] {name} は true/false で指定してください。"
        )

    return value


"""!
@fn load_unit_test_config 単体試験仕様書出力設定読込み処理
@brief config.tomlのunit_testセクションを検証して設定モデルへ変換する。
@param [in] config unit_testセクション
@return unit_test_config 単体試験仕様書出力設定
"""
def load_unit_test_config(config: dict[str, Any] | None) -> UnitTestConfig:
    raw = config or {}

    return UnitTestConfig(
        json_output=_boolean_setting(raw, "json_output"),
        csv_output=_boolean_setting(raw, "csv_output"),
        auto_generate=_boolean_setting(raw, "auto_generate"),
        csv_encoding_utf8=_boolean_setting(raw, "csv_encoding_utf8"),
    )


def _diagnostic_message(node: Node, diagnostic_message: str) -> str | None:
    if node.command == "ut":
        if diagnostic_message == "empty @ut heading":
            return "@ut コマンドの見出しが空です。"
        if diagnostic_message == "empty @ut test item":
            return "@ut コマンドの試験項目が空です。"
        return "@ut コマンドの構文に誤りがあります。"

    if node.command == "value":
        if diagnostic_message == "empty @value test item":
            return "@value コマンドの試験項目が空です。"
        return "@value コマンドの構文に誤りがあります。"

    return None


def print_unit_test_diagnostics(
    *,
    nodes: list[Node],
    source_filename: str,
) -> None:
    for node in nodes:
        for diagnostic in node.diagnostics:
            message = _diagnostic_message(node, diagnostic.message)

            if message is None:
                continue

            location = f" {source_filename}"
            if diagnostic.line is not None:
                location += f": {diagnostic.line}"

            print(f"[SYNTAX_ERROR]{location} {message}")


def _write_unit_test_csv_safely(
    *,
    output_path: Path,
    file_spec: UtFileSpec,
    encoding: str,
) -> bool:
    try:
        write_unit_test_csv(
            output_path=output_path,
            file_specs=[file_spec],
            encoding=encoding,
        )
    except PermissionError:
        print(
            f"[OUTPUT_ERROR] {output_path} CSVファイルを更新できません。"
            "ファイルを閉じてから再実行してください。"
        )
        return False

    return True


"""!
@fn generate_unit_test_outputs 単体試験仕様書出力処理
@brief 解析ノードから単体試験仕様モデルを構築しJSONおよびCSVを出力する。
@param [in] source_filename 対象ソースファイル名
@param [in] nodes Doxygonノード列
@param [in] output_path 出力先フォルダ
@param [in] config 単体試験仕様書出力設定
"""
def generate_unit_test_outputs(
    *,
    source_filename: str,
    nodes: list[Node],
    output_path: Path,
    config: UnitTestConfig,
) -> None:
    print_unit_test_diagnostics(
        nodes=nodes,
        source_filename=source_filename,
    )

    if not config.output_enabled:
        return

    file_spec = build_unit_test_file_spec(
        source_filename=source_filename,
        nodes=nodes,
        auto_generate=config.auto_generate,
    )

    if config.json_output:
        write_unit_test_json(
            output_path=output_path / f"{file_spec.source_filename}.json",
            file_specs=[file_spec],
        )

    if config.csv_output:
        _write_unit_test_csv_safely(
            output_path=output_path / f"{file_spec.source_filename}.csv",
            file_spec=file_spec,
            encoding=config.csv_encoding,
        )
