"""内置价格预警规则。

在 config/alerts.yaml 中通过 rules[].type 引用内置 type：
    price_level   价格触及/跌破某价位（compare + target）
    change_pct    单日涨跌幅超限（max_rise / max_fall）
    ma_deviation  收盘价相对 MA 的偏离（ma + mode: below/above）
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from ..core.datatypes import AlertEvent, Quote
from ..core.registry import ALERT_RULES
from ..indicators.ma import sma
from .base import BaseAlertRule


@ALERT_RULES.register("price_level")
class PriceLevelRule(BaseAlertRule):
    """价格触及/跌破某位点。

    type: { compare: "ge", target: 12.5 }
    """

    type = "price_level"

    def __init__(self, name, **params) -> None:
        super().__init__(name, **params)
        self.compare = self.params.get("compare", "ge")
        self.target = float(self.params.get("target", 0))

    def check(self, quote: Quote) -> Optional[AlertEvent]:
        if self.target <= 0 or quote.last_price <= 0:
            return None
        hit = {
            "ge": quote.last_price >= self.target,
            "le": quote.last_price <= self.target,
            "gt": quote.last_price > self.target,
            "lt": quote.last_price < self.target,
            "eq": quote.last_price == self.target,
        }[self.compare]
        if not hit:
            return None
        return self._event(
            quote,
            f"现价 {quote.last_price:.2f} {self.compare} 目标 {self.target:.2f}",
            quote.last_price, self.target,
        )


@ALERT_RULES.register("change_pct")
class ChangePctRule(BaseAlertRule):
    """单日涨跌幅超过上限/下限（百分比）。"""

    type = "change_pct"

    def __init__(self, name, **params) -> None:
        super().__init__(name, **params)
        self.max_rise = float(self.params.get("max_rise", 5.0))
        self.max_fall = float(self.params.get("max_fall", -5.0))

    def check(self, quote: Quote) -> Optional[AlertEvent]:
        pct = quote.change_pct
        if pct >= self.max_rise:
            return self._event(quote, f"单日涨 {pct:.2f}% ≥ {self.max_rise}%", quote.last_price, self.max_rise)
        if pct <= self.max_fall:
            return self._event(quote, f"单日跌 {pct:.2f}% ≤ {self.max_fall}%", quote.last_price, self.max_fall)
        return None


@ALERT_RULES.register("ma_deviation")
@ALERT_RULES.register("ma_bull")  # 旧名兼容
class MaDeviationRule(BaseAlertRule):
    """收盘价相对 MA 的偏离。mode: below（收盘位于均线下方）/ above（上方）。"""

    type = "ma_deviation"

    def __init__(self, name, **params) -> None:
        super().__init__(name, **params)
        self.ma = int(self.params.get("ma", 20))
        self.mode = self.params.get("mode", "below")
        self._klines: Dict[str, pd.DataFrame] = {}

    def set_klines(self, klines: Dict[str, pd.DataFrame]) -> None:
        self._klines = klines

    def check(self, quote: Quote) -> Optional[AlertEvent]:
        df = self._klines.get(quote.ts_code)
        if df is None or len(df) < self.ma + 2:
            return None
        close = float(df["close"].iloc[-1])
        ma_v = float(sma(df["close"], self.ma).iloc[-1])
        if ma_v != ma_v:
            return None
        if self.mode == "below" and close < ma_v:
            return self._event(quote, f"收盘 {close:.2f} < MA{self.ma} {ma_v:.2f}", quote.last_price, ma_v)
        if self.mode == "above" and close > ma_v:
            return self._event(quote, f"收盘 {close:.2f} > MA{self.ma} {ma_v:.2f}", quote.last_price, ma_v)
        return None