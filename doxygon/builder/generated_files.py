#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file generated_files.py Doxygonコマンド構文定義ファイル生成前処理
"""

from pathlib import Path

from doxygon.builder.command_lark_builder import (
    generate_command_lark,
)


"""!
@fn prepare_generated_files Doxygonコマンド構文定義ファイル生成処理
@brief 指定されたパスからDoxygonコマンド構文定義ファイルを生成する。
@param [in] project_root プロジェクトルートパス
"""
def prepare_generated_files(project_root: Path) -> None:
    generate_command_lark(
        toml_path=project_root / "config" / "command.toml",
        output_path=project_root / "generated" / "command.lark",
    )

