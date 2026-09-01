"""技术指标库（纯 pandas 实现，无额外依赖）。

每个指标是一组可复用于 Series 的函数。策略可自由组合这些指标。
"""
from .ma import sma, ema
from .rsi import rsi
from .macd import macd
from .atr import atr

__all__ = ["sma", "ema", "rsi", "macd", "atr"]