#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file command_transformer.py Doxygonコマンド構文解析処理
"""

from __future__ import annotations

from lark import Token, Transformer, Tree

from doxygon.parser.parsed_command import ParsedCommand


"""!
@class CommandTransformer 定義済みDoxygonコマンド格納クラス
"""
class CommandTransformer(Transformer):
    def __init__(self, *, block_id: int, raw_line: str) -> None:
        super().__init__()
        self.block_id = block_id
        self.raw_line = raw_line

    # ======================================================
    # start
    # ======================================================

    def start(self, items):
        return items[0]

    def command_header(self, items):
        return items[0]

    def known_command(self, items):
        return items[0]

    # common parts
    def tag(self, items):
        return ("tag", str(items[0]))

    def name(self, items):
        return ("name", str(items[0]))

    def mail(self, items):
        return ("mail", str(items[0]))

    def author(self, items):
        return ("sentence", str(items[0]).strip())

    def direction(self, items):
        return ("direction", str(items[0]))

    def sentence(self, items):
        return ("sentence", str(items[0]))

    def title(self, items):
        return ("tag", str(items[0]).strip(" \t"))

    # unknown command
    def unknown_command(self, items):
        command = ""

        values: dict[str, str] = {
            "tag": "",
            "name": "",
            "mail": "",
            "direction": "",
            "sentence": "",
        }

        for item in items:
            if isinstance(item, Token):
                if item.type == "AT_COMMAND":
                    command = str(item).lstrip("@")
                continue

            if isinstance(item, tuple):
                key, value = item
                values[key] = value

        return ParsedCommand(
            block_id=self.block_id,
            command=command,
            raw_line=self.raw_line,
            tag=values["tag"],
            name=values["name"],
            mail=values["mail"],
            direction=values["direction"],
            sentence=values["sentence"],
            is_unknown=True,
        )

    # fallback for generated command rules
    def __default__(self, data, children, meta):
        rule_name = str(data)

        if rule_name.endswith("_command"):
            command = rule_name.removesuffix("_command")

            values: dict[str, str] = {
                "tag": "",
                "name": "",
                "mail": "",
                "direction": "",
                "sentence": "",
            }

            for child in children:
                if isinstance(child, tuple):
                    key, value = child
                    values[key] = value

            return ParsedCommand(
                block_id=self.block_id,
                command=command,
                raw_line=self.raw_line,
                tag=values["tag"],
                name=values["name"],
                mail=values["mail"],
                direction=values["direction"],
                sentence=values["sentence"],
                is_unknown=False,
            )

        return Tree(data, children)
