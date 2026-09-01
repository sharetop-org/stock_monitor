#!/usr/bin/env python
"""数据源冒烟测试：验证 ShareTop 连通 + 行情/K线拉取。

用法：
    python scripts/test_source.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["test-source"]))