"""均线金叉/死叉策略。

params:
    fast: 快线 SMA 周期（默认 5）
    slow: 慢线 SMA 周期（默认 20）
快线自下而上穿越慢线（金叉）→ buy；自上而下穿越（死叉）→ sell。
"""
from __future__ import annotations

from typing import List

from ..core.datatypes import Signal
from ..core.registry import STRATEGIES
from ..indicators.ma import sma
from .base import BaseStrategy


@STRATEGIES.register("ma_cross")
class MaCrossStrategy(BaseStrategy):
    name = "ma_cross"

    def __init__(self, **params) -> None:
        super().__init__(**params)
        self.fast = int(self.params.get("fast", 5))
        self.slow = int(self.params.get("slow", 20))

    def evaluate(self, df) -> List[Signal]:
        if len(df) < self.slow + 2:
            return []
        fast = sma(df["close"], self.fast)
        slow = sma(df["close"], self.slow)
        src = (fast.iloc[-2], fast.iloc[-1], slow.iloc[-2], slow.iloc[-1])
        if any(v != v for v in src):
            return []  # 最新两根算不出均线（NaN）
        above_prev = fast.iloc[-2] > slow.iloc[-2]
        above_now = fast.iloc[-1] > slow.iloc[-1]

        out: List[Signal] = []
        if above_now and not above_prev:
            out.append(self._signal(df, "buy", f"MA{self.fast} 上穿 MA{self.slow}"))
        elif not above_now and above_prev:
            out.append(self._signal(df, "sell", f"MA{self.fast} 下穿 MA{self.slow}"))
        return out