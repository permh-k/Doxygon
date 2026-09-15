#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file unit_test_json.py 単体試験仕様JSON出力処理
"""

from __future__ import annotations

import json
from pathlib import Path

from doxygon.model import (
    UtFileSpec,
    UtFunctionSpec,
    UtHeading,
    UtTestItem,
)


"""!
@fn _serialize_content 単体試験仕様要素変換処理
@brief 内部モデルの要素をJSON出力用辞書へ変換する。
@param [in] content 単体試験仕様要素
@return item JSON出力用辞書
"""
def _serialize_content(content) -> dict:
    if isinstance(content, UtFunctionSpec):
        return {
            "function": content.name,
            "function_title": content.title,
            "contents": [_serialize_content(item) for item in content.contents],
        }

    if isinstance(content, UtHeading):
        return {
            "level": content.level,
            "heading": content.text,
            "line": content.line,
        }

    if isinstance(content, UtTestItem):
        return {
            "level": content.level,
            "test": content.text,
            "classification": content.classification,
            "line": content.line,
        }

    raise TypeError(f"Unsupported unit test content: {type(content).__name__}")


"""!
@fn write_unit_test_json 単体試験仕様JSON出力処理
@brief 階層解決済みの内部モデルをJSONファイルへ出力する。
@param [in] output_path JSON出力先パス
@param [in] file_specs 単体試験仕様ファイルモデル列
"""
def write_unit_test_json(
    *,
    output_path: Path,
    file_specs: list[UtFileSpec],
) -> None:
    document = [
        {
            "file": file_spec.name,
            "file_title": file_spec.title,
            "contents": [
                _serialize_content(content)
                for content in file_spec.contents
            ],
        }
        for file_spec in file_specs
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
