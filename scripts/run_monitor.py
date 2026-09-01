#!/usr/bin/env python
"""启动定时轮询监控（阻塞）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["monitor"]))