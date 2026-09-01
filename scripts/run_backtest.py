#!/usr/bin/env python
"""跑策略回测。默认走 config/strategies.yaml 里第一个启用的策略。"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--strategy", default=None)
    a.add_argument("--symbols", default=None)
    a.add_argument("--start", default=None)
    a.add_argument("--end", default=None)
    a.add_argument("--plot", default=None)
    opts, extra = a.parse_known_args()
    args = ["backtest"]
    for k in ("strategy", "symbols", "start", "end", "plot"):
        v = getattr(opts, k, None)
        if v:
            args += [f"--{k}", v]
    raise SystemExit(main(args))