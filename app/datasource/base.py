"""数据源抽象基类。

项目所有行情获取都经由 `BaseDataSource`，业务层不直接依赖具体数据源，
便于替换/扩展（如换成其他实时行情源、或接模拟数据）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional

from ..core.datatypes import KlineSeries, Quote


class BaseDataSource(ABC):
    name: str = "base"

    # ---------------------------------------------------------------- 实时行情
    @abstractmethod
    def get_realtime_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """拉取多个股票的实时快照，返回 {ts_code: Quote}。失败条目可跳过。"""

    # ------------------------------------------------------------------ K 线
    @abstractmethod
    def get_realtime_klines(
        self, symbols: List[str], period: str = "1d", count: int = 120
    ) -> Dict[str, KlineSeries]:
        """取股票最新 count 根 K 线。period ∈ {1m,5m,15m,30m,60m,120m,1d,...}。"""

    @abstractmethod
    def get_history_klines(
        self,
        symbol: str,
        period: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        count: Optional[int] = None,
    ) -> KlineSeries:
        """按日期区间/数量取历史 K 线（回测用），日期格式 YYYYMMDD。"""

    # ------------------------------------------------------------- 基础信息
    @abstractmethod
    def get_trade_calendar(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[dict]:
        """交易日历，行含 cal_date(YYYYMMDD) 与 is_open。"""

    @abstractmethod
    def get_universe(
        self, market_sign: Optional[List[str]] = None, fields: Optional[str] = None
    ) -> List[dict]:
        """取股票池（如市场 'SSE','SZSE'），返回行字典列表，含 ts_code/name 等。"""

    def close(self) -> None:
        """释放连接资源（约一个可选的 hook）。"""