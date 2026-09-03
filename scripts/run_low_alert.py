#!/usr/bin/env python
"""启动"N日新低/新高"邮件报警监测（阻塞）。

用法:
    python scripts/run_low_alert.py
    python scripts/run_low_alert.py --symbols 600036.SH,600519.SH --windows 360,60 --to you@example.com
    python scripts/run_low_alert.py --symbols 600036.SH --high-days 1250 --to you@example.com
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["low-alert", *sys.argv[1:]]))