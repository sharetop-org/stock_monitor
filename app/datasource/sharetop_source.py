"""基于 ShareTop SDK 的数据源实现。

用法（token 来自环境变量或传入）：
    src = ShareTopDataSource(token="xxx")
    quotes = src.get_realtime_quotes(["600519.SH"])

行情快照字段（来自 ShareTop quotes.get）：
    symbol, name, last_price, prev_close, open, high, low, volume, amount,
    timestamp, ext.{...}（ext.change_pct 等）。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from sharetop import ShareTop

from ..core.datatypes import KlineBar, KlineSeries, Quote
from ..core.registry import DATA_SOURCES
from .base import BaseDataSource

log = logging.getLogger(__name__)

# ShareTop 匹配中常见的"涨跌幅"字段名（外层或 ext 里）
_PCT_KEYS = ("change_pct", "pct_chg", "change_rate")


def get_share_client(
    timeout: float = 30.0,
    cache_dir: Optional[str] = None,
    require_token: bool = True,
) -> ShareTop:
    """统一构建 ShareTop 客户端，token 各取本项目 .env 的 `SHARETOP_TOKEN`。

    - 先 `app.config.load_config()` 加载项目根 `.env`，再读环境变量，避免各处散落硬编码。
    - `require_token=True`（默认）时，未配置 token 抛清晰报错；设 False 则传空 token，
      由 SDK 走其默认行为（一般仅用于只读公开接口的降级场景）。
    - timeout/cache_dir 与 `ShareTopDataSource` 保持一致，供复用方获得一致的连接行为。
    """
    from ..config import load_config

    load_config()                                   # 加载 .env → os.environ
    token = os.environ.get("SHARETOP_TOKEN")
    if require_token and not token:
        raise SystemExit(
            "缺少 SHARETOP_TOKEN：请在项目根 .env 中配置, 参考 .env.example / config/secrets.yaml")
    return ShareTop(token=token, timeout=timeout, cache_dir=cache_dir)


@DATA_SOURCES.register("sharetop")
class ShareTopDataSource(BaseDataSource):
    name = "sharetop"

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        cache_dir: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        token = token or os.getenv("SHARETOP_TOKEN")
        if not token:
            raise ValueError("sharetop 数据源需要 token（设置 .env 的 SHARETOP_TOKEN 或显式传入）")
        self._client = ShareTop(token=token, timeout=timeout, cache_dir=cache_dir)

    # ------------------------------------------------------------------ 实时行情
    def get_realtime_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        if not symbols:
            return {}
        try:
            raw = self._client.quotes.get(symbols=list(symbols), as_df=False)
        except Exception as exc:  # 网络/鉴权错误等
            log.warning("拉取实时行情失败: %s", exc)
            return {}
        return self._build_quotes(raw)

    def _build_quotes(self, raw) -> Dict[str, Quote]:
        out: Dict[str, Quote] = {}
        if not isinstance(raw, list):
            return out
        for item in raw:
            if not isinstance(item, dict):
                continue
            ts_code = item.get("ts_code") or item.get("symbol")
            if not ts_code:
                continue
            ext = item.get("ext") or {}
            pct = float(next((ext.get(k) for k in _PCT_KEYS if ext.get(k) is not None), 0.0) or 0.0)
            try:
                out[ts_code] = Quote(
                    ts_code=ts_code,
                    name=item.get("name", ""),
                    last_price=self._f(item.get("close", item.get("last_price"))),
                    prev_close=self._f(item.get("pre_close", item.get("prev_close"))),
                    open=self._f(item.get("open")),
                    high=self._f(item.get("high")),
                    low=self._f(item.get("low")),
                    volume=self._f(item.get("volume")),
                    amount=self._f(item.get("amount")),
                    timestamp=self._ts(item.get("timestamp")),
                    extra={"change_pct": pct, **ext},
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("解析某条行情失败 %s: %s", ts_code, exc)
        return out

    # ------------------------------------------------------------------ K 线
    def get_realtime_klines(
        self, symbols: List[str], period: str = "1d", count: int = 120
    ) -> Dict[str, KlineSeries]:
        if not symbols:
            return {}
        # 实时批量端点不支持日线（仅 1m~120m），日线改走静态历史端点逐只拉取。
        if self._is_day_period(period):
            out: Dict[str, KlineSeries] = {}
            for sym in symbols:
                try:
                    out[self._normalize_code(sym)] = self.get_history_klines(
                        sym, period="d", count=count
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("日K拉取 %s 失败: %s", sym, exc)
            return out
        try:
            raw = self._client.klines.get_batch_real_time(
                symbols=list(symbols), period=period, count=count, as_df=False
            )
        except Exception as exc:
            log.warning("拉取实时 K 线失败: %s", exc)
            return {}
        if not isinstance(raw, list):
            log.warning("实时 K 线返回异常: %r", raw)
            return {}
        return self._klines_list_to_series(raw, period)

    def get_history_klines(
        self,
        symbol: str,
        period: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        count: Optional[int] = None,
    ) -> KlineSeries:
        data = self._client.klines.get_history_data(
            symbol, period=self._to_api_period(period), count=count,
            start_time=start_date, end_time=end_date, as_df=True,
        )
        # get_history_data 可能把风控消息作为字符串返回。
        if isinstance(data, str):
            raise RuntimeError(data)
        import pandas as pd
        if not isinstance(data, pd.DataFrame) or data.empty:
            return KlineSeries(symbol, period)
        return self._df_to_series(data, symbol, period)

    @staticmethod
    def _is_day_period(p: str) -> bool:
        return (p or "").lower() in {"1d", "d", "day", "D", "1day"}

    @staticmethod
    def _to_api_period(p: str) -> str:
        """把用户友好的 '1d' 转成 API 能识别的周期（日线为 'd'）。"""
        p = p or "d"
        return "d" if p.lower() in ("1d", "day", "1day") else p

    # ------------------------------------------------------------- 信息 & 工具
    def get_trade_calendar(self, start_date=None, end_date=None) -> List[dict]:
        rsp = self._client.universes.get_trade_calendar(
            start_date=start_date, end_date=end_date, as_df=False
        )
        return rsp if isinstance(rsp, list) else []

    def get_universe(self, market_sign=None, fields="ts_code,name") -> List[dict]:
        rsp = self._client.universes.get(
            market_sign=market_sign, as_df=False, fields=fields  # type: ignore[arg-type]
        )
        return rsp if isinstance(rsp, list) else []

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _f(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _ts(v) -> Optional[datetime]:
        if not v:
            return None
        try:
            n = int(v)
            # 大于 1e12 视为毫秒，否则视为秒
            return datetime.fromtimestamp(n / 1000 if n > 1e12 else n)
        except Exception:  # noqa: BLE001
            return None

    def _to_series_from_compact(self, symbol: str, period: str, compact: dict) -> KlineSeries:
        """从 get_batch_real_time 的 CompactKlineData 结构构造 KlineSeries。快。
        CompactKlineData: {timestamp:[ms,...], open:[..],high:..,low:..,close:..,volume:..,amount:..}
        """
        ts_list = compact.get("timestamp") or []
        n = len(ts_list)
        if n == 0:
            return KlineSeries(symbol, period)
        bars = []
        for i in range(n):
            bars.append(
                KlineBar(
                    ts_code=symbol, period=period, dt=self._ts(ts_list[i]) or datetime.now(),
                    open=self._f(compact["open"][i]), high=self._f(compact["high"][i]),
                    low=self._f(compact["low"][i]), close=self._f(compact["close"][i]),
                    volume=self._f(compact["volume"][i]), amount=self._f(compact["amount"][i]),
                )
            )
        return KlineSeries(symbol, period, bars)

    def _klines_list_to_series(self, raw: List[dict], period: str) -> Dict[str, KlineSeries]:
        out: Dict[str, KlineSeries] = {}
        for it in raw or []:
            symbol = it.get("symbol") or it.get("ts_code") or it.get("stockCode")
            if not symbol:
                continue
            compact = it.get("klines") or it.get("data") or {}
            key = self._normalize_code(symbol)
            out[key] = self._series_from_dict(key, period, compact)
        return out

    def _series_from_dict(self, symbol: str, period: str, compact: dict) -> KlineSeries:
        ts_list = compact.get("timestamp") or []
        n = len(ts_list)
        bars = []
        for i in range(n):
            bars.append(
                KlineBar(
                    ts_code=symbol, period=period, dt=self._ts(ts_list[i]) or datetime.now(),
                    open=self._f(compact["open"][i]), high=self._f(compact["high"][i]),
                    low=self._f(compact["low"][i]), close=self._f(compact["close"][i]),
                    volume=self._f(compact["volume"][i]), amount=self._f(compact["amount"][i]),
                )
            )
        return KlineSeries(symbol, period, bars)

    @staticmethod
    def _normalize_code(symbol: str) -> str:
        """统一成 '600519.SH' 形式。

        兼容输入：
          - '600519.SH'（已带后缀）
          - 'SH600519' （shareTop 批量实时的 stockCode：2 位交易所前缀 + 6 位代码）
          - '600519'   （裸代码，按首位猜测交易所）
        """
        s = (symbol or "").strip()
        if not s:
            return s
        if "." in s:
            return s.upper()
        # 2 位字母前缀（SH/SZ/BJ）形式
        if len(s) == 8 and s[:2].isalpha():
            return f"{s[2:]}.{s[:2].upper()}"
        return ShareTopDataSource._guess_suffix(s)

    @staticmethod
    def _guess_suffix(code: str) -> str:
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        if code.startswith(("4", "8")):
            return f"{code}.BJ"
        return f"{code}.SZ"

    def _df_to_series(self, df, symbol: str, period: str) -> KlineSeries:
        bars = []
        for _, r in df.iterrows():
            dt = r.get("trade_time") or r.get("trade_date") or r.get("dt")
            try:
                from pandas import to_datetime
                dt_ = to_datetime(dt)
            except Exception:  # noqa: BLE001
                dt_ = dt
            bars.append(
                KlineBar(
                    ts_code=symbol, period=period, dt=dt_,
                    open=self._f(r.get("open")), high=self._f(r.get("high")),
                    low=self._f(r.get("low")), close=self._f(r.get("close")),
                    volume=self._f(r.get("volume")), amount=self._f(r.get("amount")),
                )
            )
        return KlineSeries(symbol, period, bars)