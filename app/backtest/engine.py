"""事件驱动回测引擎。

信号在当日收盘价计算（策略 evaluate），成交在下一根 K 线的开盘价撮合，
严格避免前视偏差。基准为对每只股票均价的等权买入持有组合。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from ..datasource.base import BaseDataSource
from ..strategy.base import BaseStrategy
from .metrics import BacktestMetrics
from .portfolio import BacktestPortfolio, PortfolioConfig

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)  # 列: dt, total, cash, benchmark
    trades: List = field(default_factory=list)
    metrics: Optional[BacktestMetrics] = None


class BacktestEngine:
    def __init__(self, data_source: BaseDataSource, config: Optional[dict] = None) -> None:
        config = config or {}
        self.source = data_source
        self.period = config.get("period", "1d")
        self.pcfg = PortfolioConfig(
            commission=float(config.get("commission", 0.0003)),
            min_commission=float(config.get("min_commission", 5.0)),
            stamp_tax=float(config.get("stamp_tax", 0.0005)),
            slippage=float(config.get("slippage", 0.0016)),
            max_positions=int(config.get("max_positions", 5)),
        )
        self.starting_cash = float(config.get("starting_cash", 100_000))

    def run(
        self,
        symbols: List[str],
        strategy: BaseStrategy,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BacktestResult:
        # 1) 拉历史 K 线
        dfs: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                series = self.source.get_history_klines(
                    sym, period=self.period, start_date=start_date, end_date=end_date
                )
                df = series.to_frame()
                if not df.empty:
                    df = df.sort_values("dt").reset_index(drop=True)
                    dfs[sym] = df
            except Exception as exc:  # noqa: BLE001
                log.warning("回测拉取 %s 失败: %s", sym, exc)

        if not dfs:
            raise RuntimeError("回测未能加载任何 K 线，请检查数据源与代码/日期")

        pf = BacktestPortfolio(self.starting_cash, self.pcfg)
        timeline = sorted({d for df in dfs.values() for d in pd.to_datetime(df["dt"])})
        if not timeline:
            raise RuntimeError("K 线为空")

        rows = []
        pending: Dict[str, str] = {}  # symbol -> action 待次日开盘执行
        warmup = 5  # 至少需要几根 K 线才开始评估

        for idx, day in enumerate(timeline):
            close_map = self._closes_on(dfs, day)
            # a) 执行上一日(或更早)触发的信号：以当日开盘价成交
            for sym, action in list(pending.items()):
                bar = self._bar_on(dfs, sym, day)
                if bar is None:
                    continue  # 该标的今日无交易，顺延
                if action == "buy":
                    pf.buy(sym, bar["open"], dt=day, reason="strategy buy")
                elif action == "sell":
                    pf.sell(sym, bar["open"], dt=day, reason="strategy sell")
                del pending[sym]

            # 2) 基于截至今日收盘的信号，为「下一个交易日」排程
            for sym, df in dfs.items():
                trunc = df[df["dt"] <= day]
                if len(trunc) < warmup:
                    continue
                sigs = strategy.evaluate(trunc.reset_index(drop=True))
                for sig in sigs:
                    if not pf.holding(sym) and len(pf.positions) < pf.cfg.max_positions:
                        if sig.action == "buy":
                            pending[sym] = "buy"
                    elif sig.action == "sell":
                        pending[sym] = "sell"

            # 3) 记录当日净值
            total = pf.equity(close_map)
            rows.append({"dt": day, "total": total, "cash": pf.cash,
                         "stock_value": total - pf.cash})

        eq = pd.DataFrame(rows) if rows else pd.DataFrame()
        metrics = BacktestMetrics.compute(eq, self.starting_cash, pf.trades)
        return BacktestResult(equity_curve=eq, trades=pf.trades, metrics=metrics)

    # ----------------------------------------------------------------
    @staticmethod
    def _closes_on(dfs: Dict[str, pd.DataFrame], day) -> Dict[str, float]:
        out = {}
        for sym, df in dfs.items():
            sub = df[df["dt"] == day]
            if len(sub):
                out[sym] = float(sub["close"].iloc[0])
        return out

    @staticmethod
    def _bar_on(dfs: Dict[str, pd.DataFrame], sym: str, day):
        df = dfs.get(sym)
        if df is None:
            return None
        sub = df[df["dt"] == day]
        return sub.iloc[0] if len(sub) else None