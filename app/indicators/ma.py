"""移动平均指标。"""
from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均（SMA）。返回与输入索引对齐的 Series，前 period-1 行为 NaN。"""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """指数移动平均（EMA）。"""
    return series.ewm(span=span, adjust=False).mean()