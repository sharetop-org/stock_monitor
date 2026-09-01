"""回测资金/仓位模型（A 股规则：100 股整手、买不收印花税、卖收印花税）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from ..core.datatypes import Trade

log = logging.getLogger(__name__)


@dataclass
class PortfolioConfig:
    commission: float = 0.0003      # 佣金率
    min_commission: float = 5.0     # 最低佣金(元)
    stamp_tax: float = 0.0005      # 印花税(卖出)
    slippage: float = 0.0016       # 滑点(单边比例)
    lot_size: int = 100             # A 股一手
    max_positions: int = 5


class BacktestPortfolio:
    """现金 + 持仓 + 成交记录。"""

    def __init__(self, starting_cash: float, config: PortfolioConfig) -> None:
        self.cfg = config
        self.cash = float(starting_cash)
        self.positions: Dict[str, float] = {}     # symbol -> shares
        self.trades: list = []
        self.starting_cash = float(starting_cash)

    # ------------------------------------------------------------- 撮合
    def buy(self, symbol: str, price: float, dt=None, reason: str = "") -> Optional[Trade]:
        if len(self.positions) >= self.cfg.max_positions:
            return None
        if self.positions.get(symbol, 0) > 0:
            return None
        exec_price = price * (1 + self.cfg.slippage)
        lots = int(self.cash * 0.98 * (1 - self.cfg.slippage) / (exec_price * self.cfg.lot_size))
        shares = lots * self.cfg.lot_size
        if shares <= 0:
            return None
        gross = exec_price * shares
        commission = max(gross * self.cfg.commission, self.cfg.min_commission)
        total = gross + commission
        if total > self.cash:
            return None
        self.cash -= total
        self.positions[symbol] = self.positions.get(symbol, 0) + shares
        t = Trade(symbol, "buy", exec_price, shares, commission, dt, reason)
        self.trades.append(t)
        return t

    def sell(self, symbol: str, price: float, dt=None, reason: str = "") -> Optional[Trade]:
        shares = self.positions.get(symbol, 0)
        if shares <= 0:
            return None
        exec_price = price * (1 - self.cfg.slippage)
        gross = exec_price * shares
        commission = max(gross * self.cfg.commission, self.cfg.min_commission)
        tax = gross * self.cfg.stamp_tax
        self.cash += gross - commission - tax
        self.positions[symbol] = 0
        t = Trade(symbol, "sell", exec_price, shares, commission + tax, dt, reason)
        self.trades.append(t)
        return t

    # ----------------------------------------------------------------
    def holding(self, symbol: str) -> bool:
        return self.positions.get(symbol, 0) > 0

    def equity(self, close_map: Dict[str, float]) -> float:
        val = self.cash
        for sym, shares in self.positions.items():
            val += shares * close_map.get(sym, 0.0)
        return val

    def record_equity(self, date, close_map):
        pass  # 交由 engine 记录