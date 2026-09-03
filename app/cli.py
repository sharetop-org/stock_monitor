"""命令行入口。

用法：
    python -m app.cli test-source             # 冒烟测试数据源
    python -m app.cli once                    # 立即跑一次监控（不进调度）
    python -m app.cli monitor                  # 启动定时轮询监控
    python -m app.cli backtest --strategy ma_cross [--symbol 600519.SH] [--start ..] [--end ..] [--plot out.png]
"""
from __future__ import annotations

import argparse
import logging
import os
from typing import List, Optional

from .bootstrap import build_backtest_engine, build_datasource, build_monitor_engine
from .config import load_config

log = logging.getLogger(__name__)


def _init_logging(level_name: str = "INFO") -> None:
    from .config import PROJECT_ROOT

    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(PROJECT_ROOT / "logs" / "stock-monitor.log", encoding="utf-8"),
        ],
    )


# ------------------------------------------------------------------ 子命令
def cmd_test_source(args) -> None:
    cfg = load_config()
    src = build_datasource(cfg)
    syms = cfg.watch_symbols or ["600519.SH"]
    print(f"数据源: {src.name}")
    quotes = src.get_realtime_quotes(syms)
    print(f"实时行情 获取 {len(quotes)} 只:")
    for code, q in quotes.items():
        print(f"  {code:<12} {q.name:<6} 现价 {q.last_price:>10.2f}  涨跌 {q.change_pct:+.2f}%")

    period = cfg.monitor_config().get("kline_period", "1d")
    klines = src.get_realtime_klines(syms, period=period, count=10)
    print(f"实时K线 获取 {len(klines)} 只:")
    for code, s in klines.items():
        print(f"  {code}: {len(s.bars)} 根K线")
    src.close()


def cmd_once(args) -> None:
    cfg = load_config()
    engine = build_monitor_engine(cfg)
    res = engine.tick()
    print("单次监控结果:", res)


def cmd_monitor(args) -> None:
    cfg = load_config()
    engine = build_monitor_engine(cfg)
    interval = int(cfg.monitor_config().get("poll_interval_seconds", 60))

    from .scheduler import build_scheduler

    scheduler = build_scheduler(engine.tick, interval)
    scheduler.start()
    log.info("监控已启动，轮询间隔 %s 秒，自选股 %s", interval, cfg.watch_symbols)
    try:
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("收到退出信号…")
        scheduler.shutdown(wait=False)


def cmd_low_alert(args) -> None:
    """N日新低/新高监测并邮件报警(复用 app.monitor.financial_monitoring_and_alerting)。
    邮件发送走项目统一 notifier: app.alert.notifier.mail_sender_new.MailNew。"""
    from .monitor.financial_monitoring_and_alerting import run

    cfg = load_config()
    # 低点监测用独立清单(合并 symbols: 与 stocks:, 每股窗口单独配置)
    cli_symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    cli_windows = None
    if args.windows:
        cli_windows = sorted({int(x) for x in args.windows.split(",") if x.strip()})
    specs = cfg.low_alert_specs(cli_symbols or None, windows_fallback=cli_windows)
    # 新高监测: 每股 high_days > --high-days 兜底 > 默认 1250; 0 关闭
    high_specs = None
    if args.high_days is None:
        high_specs = cfg.high_alert_specs(cli_symbols or None)
    elif args.high_days > 0:
        high_specs = cfg.high_alert_specs(cli_symbols or None,
                                          window_fallback=args.high_days)
    if not specs:
        raise SystemExit("watchlist.yaml 无股票且未指定 --symbols")

    receiver = args.to or os.environ.get("MAIL_ALERT_TO", "")
    if not receiver:
        raise SystemExit("请用 --to 或环境变量 MAIL_ALERT_TO 指定收件邮箱")

    run(specs, receiver, interval=args.interval, high_specs=high_specs, state_path=args.state)


def cmd_low_backtest(args) -> None:
    """『过去N个交易日新低买入』回测(复用 app.strategy.days_backtest)。

    达到指定交易日新低即买入并统计总收益, 从项目入口启动。
    """
    from .strategy.days_backtest import run

    cfg = load_config()
    symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()] \
        or cfg.watch_symbols
    if not symbols:
        raise SystemExit("请用 --symbols 指定股票代码(或先配置 watchlist.yaml)")

    run(symbols, low_days=args.low_days, buy_amount=args.buy_amount,
        high_days=args.high_days)


def cmd_backtest(args) -> None:
    from .core.registry import STRATEGIES

    cfg = load_config()
    strategy_name = args.strategy or "ma_cross"
    cls = STRATEGIES.get(strategy_name)
    strategy = cls(**_strategy_params(cfg, strategy_name))
    symbols = args.symbols or cfg.watch_symbols

    from .backtest.reporter import export_csv, plot_curve, print_summary

    engine = build_backtest_engine(cfg)
    result = engine.run(symbols, strategy, start_date=args.start, end_date=args.end)
    print_summary(result, strategy_name)
    outdir = cfg.backtest_config().get("report_dir", "data/backtest")
    export_csv(result, outdir)
    if args.plot:
        plot_curve(result, args.plot)


def _strategy_params(cfg, name: str) -> dict:
    for s in cfg.strategy_specs:
        if s.get("name") == name:
            return s.get("params", {}) or {}
    return {}


# ------------------------------------------------------------------ 参数
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stock-monitor", description="A股策略 + 价格预警")
    p.add_argument("--log-level", default="INFO")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("test-source", help="冒烟测试数据源").set_defaults(func=cmd_test_source)
    sub.add_parser("once", help="立即跑一次监控").set_defaults(func=cmd_once)
    sub.add_parser("monitor", help="启动定时轮询监控").set_defaults(func=cmd_monitor)

    la = sub.add_parser("low-alert", help="监控N日新低/新高并邮件报警")
    la.add_argument("--symbols", default=None, help="股票代码, 逗号分隔")
    la.add_argument("--windows", default=None, help="低位全局兜底窗口(交易日天数), 逗号分隔; 未配置该股则用此值, 再缺省 1250")
    la.add_argument("--high-days", type=int, default=None, help="新高全局兜底窗口(交易日), 缺省 1250; 每股可在 watchlist.yaml 配 high_days; 传 0 关闭新高监测")
    la.add_argument("--to", default=None, help="收件邮箱, 或环境变量 MAIL_ALERT_TO")
    la.add_argument("--interval", type=int, default=0, help="轮询间隔秒, 0=只跑一次")
    la.add_argument("--state", default=None, help="去重状态文件路径(默认 alert_state.json)")
    la.set_defaults(func=cmd_low_alert)

    lb = sub.add_parser("low-backtest", help="过去N个交易日新低买入回测")
    lb.add_argument("--symbols", default=None, help="股票代码, 逗号分隔(缺省用自选股)")
    lb.add_argument("--low-days", type=int, default=1250, help="低位回看窗口(交易日), 默认 1250(≈5年)")
    lb.add_argument("--buy-amount", type=float, default=10000.0, help="单次买入金额, 默认 10000")
    lb.add_argument("--high-days", type=int, default=None, help="收盘价突破N日新高即卖出全部持仓(算胜率/盈亏比), 缺省只买不卖")
    lb.set_defaults(func=cmd_low_backtest)

    b = sub.add_parser("backtest", help="回测策略")
    b.add_argument("--strategy", default=None)
    b.add_argument("--symbols", default=None)
    b.add_argument("--start", default=None)
    b.add_argument("--end", default=None)
    b.add_argument("--plot", default=None)
    b.set_defaults(func=cmd_backtest)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _init_logging(getattr(args, "log_level", "INFO"))
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())