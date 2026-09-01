"""交易策略层。

新增策略：在包内新建一个类继承 `BaseStrategy`，实现 `evaluate(df)`，
再给它装饰 `@STRATEGIES.register("名字")`，并在 config/strategies.yaml 中注册即可。
"""
from __future__ import annotations

from .base import BaseStrategy
from . import ma_cross, rsi_oversold, breakout  # noqa: F401  触发注册

__all__ = ["BaseStrategy"]