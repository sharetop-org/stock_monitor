"""相对强弱指标（RSI）。"""
from __future__ import annotations

import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder 平滑 RSI，取值 0~100。

    Parameters
    ----------
    series : 价格序列（如收盘价）。
    period : 周期，默认 14。
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder 平滑 = EMA(alpha=1/period)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.fillna(50.0)