#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file parsed_command.py 解析済みDoxygonコマンドモデルファイル
"""

from __future__ import annotations

from dataclasses import dataclass


"""!
@class ParsedCommand 解析済みDoxygonコマンド格納クラス
"""

@dataclass(slots=True)
class ParsedCommand:
    block_id: int
    command: str

    raw_line: str

    name: str = ""
    tag: str = ""
    direction: str = ""
    mail: str = ""
    sentence: str = ""

    is_unknown: bool = False
    is_error: bool = False
    error_message: str = ""
