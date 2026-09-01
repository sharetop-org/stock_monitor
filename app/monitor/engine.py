"""定时轮询监控引擎。

一个 tick() 的流程：
  1) 拉取选定股票的实时行情；
  2) （可选）对每只股票跑启用策略，产出买入/卖出信号并记日志；
  3) （可选）用行情 + 每只股票的 K 线跑预警规则，产出命中事件；
  4) 去重（冷却）后交给各启用通知器发送。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ..alert.base import BaseAlertRule, BaseNotifier
from ..alert.price_rules import MaDeviationRule
from ..alert.rule_engine import AlertRuleEngine
from ..core import market_time
from ..core.datatypes import Signal
from ..datasource.base import BaseDataSource
from ..monitor.state import AlertState
from ..strategy.base import BaseStrategy

log = logging.getLogger(__name__)


class MonitorEngine:
    def __init__(
        self,
        data_source: BaseDataSource,
        watchlist: List[str],
        *,
        strategies: Optional[List[BaseStrategy]] = None,
        alert_rules: Optional[List[BaseAlertRule]] = None,
        notifiers: Optional[List[BaseNotifier]] = None,
        alert_state: Optional[AlertState] = None,
        settings: Optional[dict] = None,
    ) -> None:
        settings = settings or {}
        self.source = data_source
        self.watchlist = list(watchlist)
        self.strategies = strategies or []
        self.rule_engine = AlertRuleEngine(alert_rules or [])
        self.notifiers = notifiers or []
        cooldown = int((settings.get("notify") or {}).get("dedupe_cooldown_seconds", 300))
        self.alert_state = alert_state or AlertState(cooldown)

        self.mon_cfg = settings.get("monitor", {})
        self.period = self.mon_cfg.get("kline_period", "1d")
        self.kline_count = int(self.mon_cfg.get("kline_count", 120))
        self.run_strategies = bool(self.mon_cfg.get("run_strategies", True))
        self.run_alerts = bool(self.mon_cfg.get("run_alerts", True))
        self.only_hours = bool(self.mon_cfg.get("only_trading_hours", True))

    # ------------------------------------------------------------------ 主循环
    def tick(self) -> dict:
        if self.only_hours and not market_time.is_trading_time():
            log.debug("非交易时段，跳过本轮")
            return {"status": "skipped"}

        symbols = [s for s in self.watchlist if s]
        if not symbols:
            log.warning("自选股为空")
            return {"status": "skip-empty"}

        quotes = self.source.get_realtime_quotes(symbols)
        if not quotes:
            log.warning("本轮未获取到行情")
            return {"status": "no-quotes", "nested": 0}

        result: Dict = {"status": "ok", "quotes": len(quotes), "signals": 0, "alerts": 0}

        if self.strategies and self.run_strategies:
            signals = self._run_strategies(symbols)
            result["signals"] = len(signals)

        if self.rule_engine.rules and self.run_alerts:
            needs_kline = any(isinstance(r, MaDeviationRule) for r in self.rule_engine.rules)
            kline_frames = self._load_klines(symbols) if needs_kline else None
            events = self.rule_engine.evaluate(quotes, kline_frames)
            fresh = self.alert_state.filter_new(events)
            if fresh:
                for nb in self.notifiers:
                    try:
                        nb.send(fresh)
                    except Exception as exc:  # noqa: BLE001
                        log.error("通知器 %s 发送失败: %s", nb.name, exc)
            result["alerts"] = len(fresh)
        return result

    # ------------------------------------------------------------------ 内部
    def run_strategy_on(self, strat: BaseStrategy, kline_df) -> List[Signal]:
        return list(strat.evaluate(kline_df))

    def _run_strategies(self, symbols: List[str]) -> List[Signal]:
        frames = self._load_klines(symbols)
        out: List[Signal] = []
        for code, df in frames.items():
            for strat in self.strategies:
                try:
                    for sig in strat.evaluate(df):
                        out.append(sig)
                        log.info("[策略 %s] %s %s @ %.2f  %s",
                                 strat.name, sig.ts_code, sig.action.upper(), sig.price, sig.reason)
                except Exception as exc:  # noqa: BLE001
                    log.warning("策略 %s 对 %s 执行异常: %s", strat.name, code, exc)
        return out

    def _load_klines(self, symbols: List[str]) -> Dict[str, object]:
        series = self.source.get_realtime_klines(symbols, self.period, self.kline_count)
        return {code: s.to_frame() for code, s in series.items()}