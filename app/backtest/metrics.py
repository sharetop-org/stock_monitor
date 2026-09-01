"""回测绩效指标计算。"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

TRADING_DAYS = 244  # A 股一年约 244 个交易日


@dataclass
class BacktestMetrics:
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    sharpe: float = 0.0
    max_drawdown_pct: float = 0.0
    volatility_pct: float = 0.0
    win_rate_pct: float = 0.0
    trade_count: int = 0
    final_equity: float = 0.0

    def to_dict(self) -> dict:
        return {
            "总收益率(%)": round(self.total_return_pct, 2),
            "年化收益率(%)": round(self.annual_return_pct, 2),
            "夏普比率": round(self.sharpe, 3),
            "最大回撤(%)": round(self.max_drawdown_pct, 2),
            "年化波动率(%)": round(self.volatility_pct, 2),
            "胜率(%)": round(self.win_rate_pct, 2),
            "成交次数": self.trade_count,
            "期末权益": round(self.final_equity, 2),
        }

    @classmethod
    def compute(cls, equity: pd.DataFrame, starting_cash: float, trades=None) -> "BacktestMetrics":
        m = cls()
        if equity is None or equity.empty:
            return m
        total = equity["total"].to_numpy(dtype=float)
        final = total[-1]
        m.final_equity = final
        m.total_return_pct = (final / starting_cash - 1) * 100
        n_days = len(equity)
        years = n_days / TRADING_DAYS
        if years > 0:
            m.annual_return_pct = ((final / starting_cash) ** (1 / years) - 1) * 100
        # 日收益率序列
        daily = pd.Series(total).pct_change().dropna()
        if len(daily) >= 2:
            std = daily.std()
            mean = daily.mean()
            m.volatility_pct = std * math.sqrt(TRADING_DAYS) * 100
            m.sharpe = (mean / std) * math.sqrt(TRADING_DAYS) if std > 0 else 0.0
        # 最大回撤
        running_max = pd.Series(total).cummax()
        drawdown = (pd.Series(total) / running_max - 1).min()
        m.max_drawdown_pct = (drawdown * 100 if math.isfinite(drawdown) else 0.0)
        # 成交统计
        m.trade_count = len(trades or [])
        m.win_rate_pct = _winrate(trades or [])
        return m


def _winrate(trades) -> float:
    """按「买→卖」配对近似计算胜率。"""
    buys = []
    wins = 0
    pairs = 0
    for t in trades:
        if t.side == "buy":
            buys.append((t.ts_code, t.price))
        elif t.side == "sell" and buys:
            code, bprice = buys.pop(-1)
            pairs += 1
            if t.price > bprice:
                wins += 1
    return (wins / pairs * 100) if pairs else 0.0