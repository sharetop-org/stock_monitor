"""APScheduler 定时调度封装。"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def build_scheduler(tick_fn, interval_seconds: int):
    """构建一个后台调度器，每 interval_seconds 秒调用一次 tick_fn。

    Returns: (scheduler, stop_callable)。调用 stop() 优雅退出。
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    if interval_seconds <= 0:
        raise ValueError("poll_interval_seconds 必须为正数")

    def _safe_tick():
        try:
            res = tick_fn()
            log.debug("tick 完成: %s", res)
        except Exception as exc:  # noqa: BLE001
            log.exception("tick 异常: %s", exc)

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(_safe_tick, "interval", seconds=interval_seconds,
                      id="monitor.tick", name="行情轮询", max_instances=1, coalesce=True)
    return scheduler