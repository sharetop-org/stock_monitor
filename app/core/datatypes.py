"""跨模块共享的数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- 行情
@dataclass
class Quote:
    """实时快照（来自数据源 `get_realtime_quotes`）。"""

    ts_code: str
    name: str = ""
    last_price: float = 0.0
    prev_close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    timestamp: Optional[datetime] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def change_pct(self) -> float:
        """较昨收的涨跌幅（百分比，%，如 3.5 表示 +3.5%）。"""
        if not self.prev_close:
            return 0.0
        return (self.last_price - self.prev_close) / self.prev_close * 100.0


@dataclass
class KlineBar:
    """单根 K 线。"""

    ts_code: str
    period: str
    dt: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0


@dataclass
class KlineSeries:
    """一组按时间升序排列的 K 线。`to_frame` 给出 DataFrame 供指标/策略逻辑使用。"""

    ts_code: str
    period: str
    bars: List[KlineBar] = field(default_factory=list)

    def to_frame(self):  # -> pd.DataFrame
        """转为 pandas DataFrame，列为 dt,open,high,low,close,volume,amount。"""
        import pandas as pd

        if not self.bars:
            return pd.DataFrame(columns=["ts_code", "dt", "open", "high", "low", "close", "volume", "amount"])
        rows = [
            {
                "ts_code": b.ts_code,
                "dt": b.dt,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "amount": b.amount,
            }
            for b in self.bars
        ]
        df = pd.DataFrame(rows)
        return df


# ------------------------------------------------------------------------- 策略/预警
@dataclass
class Signal:
    """策略产生的交易信号。"""

    ts_code: str
    strategy: str
    action: str            # buy / sell
    price: float
    reason: str = ""
    dt: Optional[datetime] = None
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertEvent:
    """一条命中并待发送的预警。"""

    ts_code: str
    name: str
    rule_name: str
    level: str = "info"
    message: str = ""
    current_price: Optional[float] = None
    threshold: Optional[float] = None
    dt: Optional[datetime] = None

    @property
    def dedupe_key(self) -> str:
        """去重键：同一股票 + 同一规则。"""
        return f"{self.ts_code}.{self.rule_name}"


@dataclass
class Trade:
    """一次已撮合的成交（回测所用）。"""

    ts_code: str
    side: str                # buy / sell
    price: float
    shares: float
    commission: float
    dt: Optional[datetime] = None
    reason: str = ""