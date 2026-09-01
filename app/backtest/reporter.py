"""回测结果输出（控制台摘要 + 可选 CSV/绘图）。"""
from __future__ import annotations

import logging
import os

from .engine import BacktestResult

log = logging.getLogger(__name__)


def print_summary(result: BacktestResult, strategy_name: str) -> None:
    print(f"\n========== 回测结果：{strategy_name} ==========")
    if result.metrics is None:
        print("（无结果）")
        return
    for k, v in result.metrics.to_dict().items():
        print(f"  {k:<16}: {v}")
    print(f"  成交笔数      : {len(result.trades)}")
    print("=" * 40)


def export_csv(result: BacktestResult, dir_path: str) -> str:
    os.makedirs(dir_path, exist_ok=True)
    eq_path = os.path.join(dir_path, "equity.csv")
    trades_path = os.path.join(dir_path, "trades.csv")
    if not result.equity_curve.empty:
        result.equity_curve.to_csv(eq_path, index=False, encoding="utf-8-sig")
    if result.trades:
        import pandas as pd
        pd.DataFrame(
            [
                {"dt": t.dt, "symbol": t.ts_code, "side": t.side, "price": t.price,
                 "shares": t.shares, "cost": t.commission, "reason": t.reason}
                for t in result.trades
            ]
        ).to_csv(trades_path, index=False, encoding="utf-8-sig")
    log.info("回测已导出: %s , %s", eq_path, trades_path)
    return dir_path


def plot_curve(result: BacktestResult, save_path: str | None = None):
    """可选绘图：未安装 matplotlib 则静默跳过。"""
    if result.equity_curve is None or result.equity_curve.empty:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        log.info("未安装 matplotlib，跳过绘图（可选依赖）")
        return
    df = result.equity_curve
    plt.figure(figsize=(10, 5))
    plt.plot(df["dt"], df["total"], label="组合净值")
    plt.title("Backtest Equity Curve")
    plt.xlabel("date")
    plt.ylabel("equity")
    plt.grid(alpha=0.3)
    plt.legend()
    if save_path:
        plt.savefig(save_path, dpi=120, bbox_inches="tight")
        log.info("曲线已保存: %s", save_path)
    else:
        log.info("请把 run_backtest 的 --plot 指向一个 .png 路径以保存图像")
    plt.close()