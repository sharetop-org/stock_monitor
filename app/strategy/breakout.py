"""N 日高低点突破策略。

params:
    nday: 突破参考窗口（默认 20）
    tolerance: 突破容错比例，如 0.005 表示需超过前高 0.5%（默认 0.005，直接设置 0 若无需）
收盘价上破前 nday 日最高 → buy；下破前 nday 日最低 → sell（可选）。
"""
from __future__ import annotations

from typing import List

from ..core.datatypes import Signal
from ..core.registry import STRATEGIES
from .base import BaseStrategy


@STRATEGIES.register("breakout")
class BreakoutStrategy(BaseStrategy):
    name = "breakout"

    def __init__(self, **params) -> None:
        super().__init__(**params)
        self.nday = int(self.params.get("nday", 20))
        self.tolerance = float(self.params.get("tolerance", 0.005))

    def evaluate(self, df) -> List[Signal]:
        if len(df) < self.nday + 2:
            return []
        window = df.iloc[-(self.nday + 1):-1]  # 不含最新一根
        high_n = float(window["high"].max())
        low_n = float(window["low"].min())
        close = float(df["close"].iloc[-1])

        out: List[Signal] = []
        if close > high_n * (1 + self.tolerance):
            out.append(self._signal(df, "buy", f"收价 {close:.2f} 突破{self.nday}日高 {high_n:.2f}"))
        elif close < low_n * (1 - self.tolerance):
            out.append(self._signal(df, "sell", f"收价 {close:.2f} 跌破{self.nday}日低 {low_n:.2f}"))
        return out