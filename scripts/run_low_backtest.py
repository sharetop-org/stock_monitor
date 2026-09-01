#!/usr/bin/env python
"""启动"过去N个交易日新低买入"回测（从项目入口）。

用法:
    python scripts/run_low_backtest.py --symbols 600036.SH,600519.SH
    python scripts/run_low_backtest.py --symbols 600519.SH --low-days 60 --buy-amount 10000 --high-days 20
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["low-backtest", *sys.argv[1:]]))