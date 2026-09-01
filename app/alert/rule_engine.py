"""预警规则引擎：把一批行情适配到一批规则，产出待发送预警。"""
from __future__ import annotations

import logging
from typing import Dict, List

import pandas as pd

from ..core.datatypes import AlertEvent, Quote
from .base import BaseAlertRule

log = logging.getLogger(__name__)


class AlertRuleEngine:
    def __init__(self, rules: List[BaseAlertRule]) -> None:
        self.rules = rules

    def evaluate(
        self,
        quotes: Dict[str, Quote],
        context_klines: Dict[str, pd.DataFrame] | None = None,
    ) -> List[AlertEvent]:
        """对每只股票的行情快照跑所有启用规则。

        Parameters
        ----------
        quotes : {ts_code: Quote}
        context_klines : 需要均线等上下文的规则会用到，{ts_code: OHLCV df}

        Returns
        -------
        List[AlertEvent] = 所有命中的规则结果。
        """
        out: List[AlertEvent] = []
        context_klines = context_klines or {}

        for rule in self.rules:
            if hasattr(rule, "set_klines"):
                rule.set_klines(context_klines)  # type: ignore[attr-defined]
            for quote in quotes.values():
                try:
                    ev = rule.check(quote)
                except Exception as exc:  # noqa: BLE001
                    log.warning("规则 %s 对 %s 执行失败: %s", rule.name, quote.ts_code, exc)
                    continue
                if ev is not None:
                    out.append(ev)
        log.debug("规则引擎产出 %s 条预警", len(out))
        return out