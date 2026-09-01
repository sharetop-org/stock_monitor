"""策略抽象基类。

约定：`evaluate(df)` 只负责「判断最新一根 K 线是否应发出信号」，然后返回
0 或更多 `Signal`。这样同一份实现既可用于监控（传入今天为止的 K 线），
也可用于回测（引擎逐日给出一段截至当日的 K 线窗口）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from ..core.datatypes import Signal


class BaseStrategy(ABC):
    name: str = "base"

    def __init__(self, **params) -> None:
        self.params: Dict = dict(params)

    @abstractmethod
    def evaluate(self, df) -> List[Signal]:
        """对传入的 K 线 DataFrame（列含 open/high/low/close/volume/dt），
        判定最新一行是否触发信号，返回信号列表（可能为空列表）。"""

    def _signal(self, df, action: str, reason: str, price: float = None, **extra) -> Signal:
        last = df.iloc[-1]
        ts_code = last.get("ts_code", "") if "ts_code" in df.columns else ""
        return Signal(
            ts_code=str(ts_code),
            strategy=self.name,
            action=action,
            reason=reason,
            price=float(price if price is not None else last["close"]),
            dt=last.get("dt"),
            params=dict(self.params, **extra),
        )