"""控制台/日志通知器（调试用，通常不在配置中启用）。"""
from __future__ import annotations

import logging

from ...core.registry import NOTIFIERS
from ..base import BaseNotifier

log = logging.getLogger(__name__)


@NOTIFIERS.register("console")
class ConsoleNotifier(BaseNotifier):
    name = "console"

    def __init__(self, **kwargs) -> None:
        self.level = kwargs.get("level", "info")

    def send(self, events) -> None:
        evs = events if isinstance(events, list) else [events]
        for e in evs:
            log.info("[预警][console] %s", self.format_lines([e]))