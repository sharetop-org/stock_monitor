"""平均真实波幅（ATR）。"""
from __future__ import annotations

import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    """TR = max(high - low, |high - prev_close|, |low - prev_close|)。"""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1.0 / period, adjust=False).mean()