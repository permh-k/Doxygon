#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file config_loader.py パラメータファイル読込み処理
"""

from pathlib import Path
from typing import Any
import tomllib

"""!
@fn load_config パラメータファイル読込み処理
@brief TOML形式のパラメータファイルを読み込み、辞書型データに変換する。
@param [in] path パラメータファイルパス
@return config パラメータ変換後の辞書型データ
"""
def load_config(path: str | Path = "config.toml") -> dict[str, Any]:
    p: Path = Path(path)
    with p.open("rb") as f:
        return tomllib.load(f)
