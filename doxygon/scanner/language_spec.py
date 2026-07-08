#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file language_spec.py プログラミング言語仕様定義ファイル
"""

from __future__ import annotations

# ==========================================================
# プログラミング言語仕様（内部定義）
# ==========================================================
# function_detect:
#   - "brace"  : { } カウント
#   - "indent" : インデント構造（Python）
#   - "regex"  : 開始/終了パターン
#
# name_group:
#   関数名を取得するキャプチャグループ番号
# ==========================================================

LANGUAGE_SPECS: dict[str, dict] = {

    # ======================================================
    # VBA
    # ======================================================
    "vba": {
        "function_detect": "regex",
        "function_start": r"^\s*(Public|Private)?\s*(Sub|Function|Property\s+(Get|Let|Set))\s+([A-Za-z0-9_]+)",
        "function_end":   r"^\s*End\s+(Sub|Function|Property)",
        "name_group": 4,
        "supports_nesting": False,
    },

    # ======================================================
    # Python
    # ======================================================
    "python": {
        "function_detect": "indent",
        "function_start": r"^\s*def\s+(\w+)",
        "function_end": None,
        "name_group": 1,
        "supports_nesting": True,
    },

    # ======================================================
    # C
    # ======================================================
    "c": {
        "function_detect": "brace",
        "function_start": r"^\w[\w\s\*]*\s+(\w+)\s*\(",
        "function_end": None,
        "name_group": 1,
        "supports_nesting": False,
        "body_open_token" : "{",
    },

    # ======================================================
    # C++
    # ======================================================
    "cpp": {
        "function_detect": "brace",
        "function_start": r"^\w[\w\s:<>&\*]*\s+(\w+)\s*\(",
        "function_end": None,
        "name_group": 1,
        "supports_nesting": False,
        "body_open_token" : "{",
    },

    # ======================================================
    # Java
    # ======================================================
    "java": {
        "function_detect": "brace",
        # Java methods may omit public/private/protected and begin with
        # modifiers such as ``static``.  Require a return type before the
        # method name so class declarations and control statements are not
        # treated as methods.
        "function_start": (
            r"^\s*"
            r"(?:(?:public|private|protected|static|final|abstract|"
            r"synchronized|native|strictfp)\s+)*"
            r"[A-Za-z_$][A-Za-z0-9_$<>\[\],.?\s]*\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\("
        ),
        "function_end": None,
        "name_group": 1,
        "supports_nesting": False,
        "body_open_token" : "{",
    },

    # ======================================================
    # JavaScript
    # ======================================================
    "javascript": {
        "function_detect": "brace",
        "function_start": r"(?:function\s+([A-Za-z_$][A-Za-z0-9_$]*)|(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*\(|([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*\()",
        "function_end": None,
        "name_group": [1, 2, 3],
        "supports_nesting": False,
        "body_open_token" : "{",
    },

    # ======================================================
    # TypeScript
    # ======================================================
    "typescript": {
        "function_detect": "brace",
        "function_start": r"(?:function\s+([A-Za-z_$][A-Za-z0-9_$]*)|(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*\(|([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*\()",
        "function_end": None,
        "name_group": [1, 2, 3],
        "supports_nesting": False,
        "body_open_token" : "{",
    },
}


"""!
@fn get_language_spec プログラミング言語仕様取得処理
@brief 指定されたプログラミング言語に対応する関数仕様を取得する。
@attention
対応するプログラミング言語は以下のとおりとする。

* VBA
* Python
* C/C++
* Java
* JavaScript
* TypeScript

@param [in] language 対象となるプログラミング言語
@return spec 当該プログラミング言語仕様を定義した辞書型データ
"""
def get_language_spec(language: str) -> dict:
    try:
        return LANGUAGE_SPECS[language]
    except KeyError:
        raise ValueError(f"Unsupported language: {language}")
