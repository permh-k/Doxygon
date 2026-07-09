#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""!
@file command_registry.py Doxygonコマンド定義管理ファイル
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


"""!
@class CommandSpec Doxygonコマンド定義格納クラス
"""
@dataclass(slots=True, frozen=True)
class CommandSpec:
    name: str
    syntax: str
    handler: str
    kind: str | None = None


"""!
@class CommandRegistry Doxygonコマンド定義レジストリ格納クラス
"""
class CommandRegistry:
    def __init__(self, specs: dict[str, CommandSpec]) -> None:
        self._specs = specs

    @classmethod
    def from_toml(cls, path: Path) -> "CommandRegistry":
        with path.open("rb") as f:
            data = tomllib.load(f)

        commands = data.get("commands", {})
        specs: dict[str, CommandSpec] = {}

        for name, raw in commands.items():
            specs[name.lower()] = CommandSpec(
                name=name.lower(),
                syntax=raw["syntax"],
                handler=raw["handler"],
                kind=raw.get("kind"),
            )

        return cls(specs)

    def is_known(self, name: str) -> bool:
        return name.lower().lstrip("@") in self._specs

    def get(self, name: str) -> CommandSpec | None:
        return self._specs.get(name.lower().lstrip("@"))

    @property
    def names(self) -> set[str]:
        return set(self._specs.keys())
