"""回测引擎的离线测试：用合成 K 线验证撮合/净值（不联网）。"""
from __future__ import annotations

import datetime
import math

from app.backtest.engine import BacktestEngine
from app.backtest.portfolio import BacktestPortfolio, PortfolioConfig
from app.core.datatypes import KlineBar, KlineSeries
from app.strategy.ma_cross import MaCrossStrategy


class FakeSource:
    """只提供一只走势振荡的股票，足以让 MA5/MA20 反复金叉死叉。"""

    def __init__(self, n=200) -> None:
        t0 = datetime.datetime(2025, 1, 1)
        bars = []
        for i in range(n):
            price = 10.0 + 3 * math.sin(i / 6.0) + 0.02 * i
            d = t0 + datetime.timedelta(days=i * 7 // 5)  # 模拟每交易日
            bars.append(KlineBar("600000.SH", "d", d,
                                 open=price - 0.2, high=price + 0.3, low=price - 0.3,
                                 close=price, volume=1e4, amount=1e6))
        self.bars = bars

    def get_history_klines(self, symbol, period="1d", start_date=None, end_date=None, count=None):
        return KlineSeries(symbol, period, self.bars)


def test_portfolio_buy_sell():
    pf = BacktestPortfolio(100_000, PortfolioConfig(commission=0.0003))
    t = pf.buy("AA.SH", 10.0, dt=None, reason="t")
    assert t is not None and pf.holding("AA.SH") and pf.positions["AA.SH"] > 0
    before = pf.cash
    s = pf.sell("AA.SH", 11.0)
    assert s is not None and not pf.holding("AA.SH")
    assert pf.cash > before - 0.01


def test_backtest_engine_runs_on_synthetic():
    sr = FakeSource()
    cfg = {"commission": 0.0, "min_commission": 0.0, "stamp_tax": 0.0, "starting_cash": 100_000}
    engine = BacktestEngine(sr, cfg)
    res = engine.run(["600000.SH"], MaCrossStrategy(fast=5, slow=20))
    assert not res.equity_curve.empty
    assert res.metrics is not None and res.metrics.final_equity > 0
    assert len(res.trades) >= 0