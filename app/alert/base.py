"""预警抽象基类。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional

from ..core.datatypes import AlertEvent


class BaseAlertRule(ABC):
    """预警规则的抽象。`check` 返回命中时的 AlertEvent，无命中返回 None。"""

    type: str = "base"
    level: str = "info"

    def __init__(self, name: str, **params) -> None:
        self.name = name
        self.params: Dict = dict(params)

    @abstractmethod
    def check(self, quote) -> Optional[AlertEvent]:
        """针对单只股票的行情快照判定是否命中。"""

    def _event(self, quote, message: str, current: float = None, threshold=None) -> AlertEvent:
        return AlertEvent(
            ts_code=quote.ts_code,
            name=quote.name,
            rule_name=self.name,
            level=self.level,
            message=message,
            current_price=current if current is not None else quote.last_price,
            threshold=threshold,
        )


class BaseNotifier(ABC):
    """通知器的抽象：把一条（或多条）预警送达一个渠道。"""

    name: str = "base"

    @abstractmethod
    def send(self, events) -> None:
        """events: 传 Single AlertEvent 或 List[AlertEvent]。异常务必自行捕获，防止中断主流程。"""

    def format_lines(self, events) -> str:
        lines = []
        for e in events:
            price = f" 现价 {e.current_price:.2f}" if e.current_price is not None else ""
            lines.append(f"[{e.level}] {e.ts_code} {e.name or ''} - {e.rule_name}{price}: {e.message}")
        return "\n".join(lines)