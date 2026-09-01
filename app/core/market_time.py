"""A 股交易时段与交易日判断工具。

数据源提供交易日历（`get_trade_calendar`）；在无网络/未加载日历时可回退到
「周一至周五」的近似判断。盘中时段：09:30–11:30、13:00–15:00（以本地时间计，仅用于省请求）。
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional, Set


def is_trading_time(now: Optional[datetime] = None) -> bool:
    """当前是否处于可交易的盘中时段（本地时间）。"""
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周六/周日
        return False
    t = now.time()
    am = time(9, 30) <= t <= time(11, 30)
    pm = time(13, 0) <= t <= time(15, 0)
    return am or pm


_TZ_HINT_MSG = "用 ShareTop get_trade_calendar 拉取真实交易日历更准确"


class TradingCalendar:
    """基于 ShareTop 交易日历的交易日集合（近似用）。"""

    def __init__(self, trade_days: Optional[Set[str]] = None) -> None:
        self._days = trade_days or set()

    def is_trading_day(self, day: Optional[datetime] = None) -> bool:
        day = day or datetime.now()
        if self._days:
            key = day.strftime("%Y%m%d")
            return key in self._days
        # 无日历回退：工作日即可
        return day.weekday() < 5

    def update(self, rows: list) -> None:
        """从 ShareTop get_trade_calendar 的行回填。

        rows 元素为 dict，含 'cal_date' 或 'trade_date' 及 'is_open'/'is_open'=1 表示交易日。
        """
        for r in rows:
            date = r.get("cal_date") or r.get("trade_date")
            is_open = r.get("is_open", r.get("is_trading_day", 1))
            if date and is_open in (1, "1", True, "Y"):
                self._days.add(str(date))