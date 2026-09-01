"""预警去重/冷却状态。

同一 (股票x规则) 在一定冷却期内只发送一次，防止高频轮询导致邮件轰炸。
可在每次进程重启后归零，也可在这里接持久化（如 sqlite/redis）实现跨进程去重。
"""
from __future__ import annotations

import logging
import time
from typing import Dict

from ..core.datatypes import AlertEvent

log = logging.getLogger(__name__)


class AlertState:
    def __init__(self, cooldown_seconds: int = 300) -> None:
        self.cooldown = cooldown_seconds
        self._last: Dict[str, float] = {}

    def is_fresh(self, key: str, now: float = None) -> bool:
        now = now or time.time()
        last = self._last.get(key, 0.0)
        return (now - last) >= self.cooldown

    def mark(self, key: str, now: float = None) -> None:
        self._last[key] = now or time.time()

    def filter_new(self, events: list) -> list:
        """返回通过冷却、应发送的预警，并把它们标记为已发送。"""
        now = time.time()
        fresh = []
        for ev in events:
            key = ev.dedupe_key
            if self.is_fresh(key, now):
                fresh.append(ev)
                self.mark(key, now)
        skipped = len(events) - len(fresh)
        if skipped:
            log.debug("去重丢弃 %d 条预警", skipped)
        return fresh