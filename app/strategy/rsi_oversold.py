"""RSI 超卖反弹策略。

params:
    period: RSI 周期（默认 14）
    oversold: 超卖阈值（默认 30）
    lookback: 回升判定回看窗口（默认 5）。RSI 须在超卖线(≤oversold)下
              连续待满 lookback 根，今日回升到超卖线上方 → buy。
              用于过滤「单根插针」式的假拐头，确认是自底部磨底后的有效反弹。
"""
from __future__ import annotations

from typing import List

from ..core.datatypes import Signal
from ..core.registry import STRATEGIES
from ..indicators.rsi import rsi
from .base import BaseStrategy


@STRATEGIES.register("rsi_oversold")
class RsiOversoldStrategy(BaseStrategy):
    name = "rsi_oversold"

    def __init__(self, **params) -> None:
        super().__init__(**params)
        self.period = int(self.params.get("period", 14))
        self.oversold = float(self.params.get("oversold", 30))
        self.lookback = int(self.params.get("lookback", 5))

    def evaluate(self, df) -> List[Signal]:
        # 需足够的 K 线：period 期 RSI + lookback 窗口 + 今日
        if len(df) < self.period + self.lookback + 2:
            return []
        r = rsi(df["close"], self.period)
        cur = r.iloc[-1]
        if cur != cur:  # 今日 RSI 为 NaN
            return []
        # 今日必须已回升到超卖线上方
        if not cur > self.oversold:
            return []
        # 今日之前的连续 lookback 根须落在超卖线(≤阈值)内：确认最近有“磨底”
        prior = r.iloc[-(self.lookback + 1):-1]
        if len(prior) < self.lookback or (prior > self.oversold).any():
            return []
        # 首次评估窗口不足也可能让 prior 恰好 ≥ lookback；此处已保证 len(prior)==lookback
        return [self._signal(df, "buy", f"RSI({self.period}) 超卖线(≤{self.oversold})连续{self.lookback}日后回升 {cur:.1f}")]