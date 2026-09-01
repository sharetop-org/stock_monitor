"""MACD 指标。"""
from __future__ import annotations

import pandas as pd

from .ma import ema


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (dif, dea, hist) 三元组 Series。"""
    dif = ema(series, fast) - ema(series, slow)
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist