import numpy as np
import pandas as pd

# ShareTop client 统一走项目数据源共享工厂 app/datasource/sharetop_source.py
from app.datasource.sharetop_source import get_share_client as get_client


def prep_adj(d):
    d = d.copy()
    d["trade_time"] = pd.to_datetime(d["trade_time"])
    return d.sort_values("trade_time").reset_index(drop=True)


def get_name(client, symbol):
    """根据 ts_code 获取股票简称(universes 返回 list, 取第一个匹配项)。"""
    try:
        rows = client.universes.get(ts_code=symbol, as_df=False)
        if isinstance(rows, list) and rows:
            hit = next((r for r in rows if r.get("ts_code") == symbol), rows[0])
            return hit.get("name", symbol)
        if isinstance(rows, dict):
            return rows.get("name", symbol)
    except Exception:
        pass
    return symbol


def xirr(flows):
    """年化内部收益率(XIRR)。

    flows: [(日期, 金额)]。以最早日期为基准年限,
    求解 r 使 Σ 金额_i / (1+r)^((日期_i-基准)/365.25) = 0。
    区间加倍搜索 + 二分收敛; 失败返回 None。
    """
    if not flows or len(flows) < 2:
        return None
    ref = min(d for d, _ in flows)
    tt = [(d - ref).days / 365.25 for d, _ in flows]
    amts = [a for _, a in flows]

    def f(r):  # 定义 in 范围内单调
        return sum(a * (1 + r) ** (-t) for a, t in zip(amts, tt))

    lo, hi = -1 + 1e-6, 1.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:                       # 同号 → 拓宽上界
        while flo * fhi > 0 and hi < 1e16:
            hi *= 2
            fhi = f(hi)
    if flo * fhi > 0:                       # 仍同号(例: 全复制/无解)
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-12 or hi - lo < 1e-13:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def backtest(client, symbol, window_start=None, low_days=1250,
             buy_amount=10000.0, lot=100, tax_mode="before", high_days=None):
    """过去 low_days 个交易日新低买入 策略回测。

    口径:
      - 前复权(before)价判断: 当日收盘价 ≤ 过去 low_days 个交易日滚动低点 → 买入
        (low_days 为交易日数量, 直接指定, 如 1250≈5年, 250≈1年)
      - 不复权(normal)价作为当天真实成交价下单, 1手(100股)内取整(买不起一手则买一手)
      - 日度模拟: 分红/送转/可选卖出, 每日净值 = 持股x收盘 + 现金 → 最大回撤/胜率/盈亏比
      - high_days: 若给出, 当日收盘价 ≥ 最近 N 个交易日最高收盘价(突破N日新高)时, 当日收盘卖出全部持仓(算胜率/盈亏比); 默认 None = 只买不卖
      - 最终资产 = 期末市值 + 累计现金(分红+卖出所得)

    window_start: 回测起点。默认 None = 以该公司上市日(首根K线)为起点。
    """
    lookback = int(low_days)
    name = get_name(client, symbol)

    qjq = prep_adj(client.klines.get_history_data(symbol, period="d",
                                                  count=60000, adjust="before", as_df=True))
    bfq = prep_adj(client.klines.get_history_data(symbol, period="d",
                                                  count=60000, adjust="normal", as_df=True))

    # 回测起点：默认取该股上市日(首根K线时间)
    if window_start is None:
        window_start = qjq["trade_time"].iloc[0]
    else:
        window_start = pd.Timestamp(window_start)

    # 1) 前复权定买入日期
    qjq["low"] = qjq["close"].rolling(lookback, min_periods=lookback).min()
    new_low = qjq["close"] <= qjq["low"]              # 当日创指定年新低
    buy_dates = qjq.loc[new_low & (qjq["trade_time"] >= window_start), "trade_time"].reset_index(drop=True)

    if buy_dates.empty:
        return {"symbol": symbol, "name": name, "low_days": low_days, "high_days": high_days,
                "ihist": qjq["trade_time"].iloc[0].date(),
                "buys": 0, "invested": 0.0, "shares": 0.0,
                "div": 0.0, "assets": 0.0, "profit": 0.0, "ret": 0.0, "annual": 0.0,
                "win_rate": 0.0, "pl_ratio": 0.0, "max_drawdown": 0.0, "n_trades": 0,
                "detail": pd.DataFrame(), "trades": pd.DataFrame()}

    # 2) 不复权真实价 + 按整手取整下单
    price = bfq.set_index("trade_time")["close"].loc[buy_dates].astype(float)
    qjq_price = qjq.set_index("trade_time")["close"].loc[buy_dates].astype(float)  # 当日前复权价
    lots = (buy_amount / price // lot).astype(int)
    shares_ea = (lots * lot).clip(lower=lot)   # 金额买不起一手时, 直接买一手(100股)
    cost_ea = shares_ea * price

    # 3) 分红 + 送转
    try:
        div = client.financials.stock_dividend(symbols=[symbol], as_df=True)[symbol].copy()
        div["ex"] = pd.to_datetime(div["ex_rights_dividend_date"], errors="coerce")
        div = div.dropna(subset=["ex"])
        div = div[div["current_status"].astype(str) == "5"]    # 仅统计已实施完成(5)的分红/送转
        div = div.sort_values("ex").reset_index(drop=True)
        cash_col = "dps_before_tax" if tax_mode == "before" else "dps_after_tax"
        div["cash_ps"] = div[cash_col].fillna(0) / 10.0                # 元/股
        div["bonus_ps"] = div["bonus_share_ratio"].fillna(0) / 10.0    # 送股/股
        div["cap_ps"] = div["capitalization_ratio"].fillna(0) / 10.0   # 转增/股
        dividend_events = list(
            zip(div["ex"], div["cash_ps"], div["bonus_ps"] + div["cap_ps"]))
    except Exception:
        dividend_events = []

    # 4) 日度模拟: 买入/分红/送转/可选卖出/每日净值
    # 4) 日度模拟: 买入/分红/送转/可选卖出 → 每日净值 → 最大回撤 / 胜率 / 盈亏比
    bar_of = pd.Series(np.arange(len(bfq)), index=bfq["trade_time"])
    buy_bar = bar_of.loc[buy_dates].astype(int).to_numpy()
    closes = bfq["close"].to_numpy(dtype=float)
    div_sorted = sorted(dividend_events, key=lambda e: e[0])
    # 卖出基准: 最近 N 日最高收盘价(前移一天, 避免买入当日即触发), 收盘价突破它即卖出
    if high_days:
        roll_high = pd.Series(closes).rolling(
            int(high_days), min_periods=int(high_days)).max().shift(1).to_numpy()
    else:
        roll_high = None

    cost_np = cost_ea.to_numpy(dtype=float)
    shares_np = shares_ea.to_numpy(dtype=float)

    units = []            # 每笔持仓: {qty, cost, buy(idx), cash(分红累计), buy_d}
    shares = 0.0
    cash = 0.0            # 已到手现金 = 分红 + 卖出所得
    cash_div = 0.0
    flows = []            # XIRR 现金流: 买入- / 分红+ / 卖出+ / 期末+
    closed = []           # 已了结 & 期末未平仓: {buy_d, sell_d, cost, value}
    equity = np.empty(len(closes))

    div_pt = 0
    buy_pt = 0
    for t in range(len(closes)):
        dt = bfq["trade_time"].iloc[t]

        # a) 分红 + 送转
        if div_pt < len(div_sorted) and (div_sorted[div_pt][0]).date() == dt.date():
            _d, dps, bonus = div_sorted[div_pt]
            div_pt += 1
            if dps:
                div_cash = shares * dps
                cash += div_cash
                cash_div += div_cash
                flows.append((dt, div_cash))
                for u in units:
                    u["div"] += u["qty"] * dps
            bonus = 1.0 + bonus
            if bonus != 1.0:
                shares *= bonus
                for u in units:
                    u["qty"] *= bonus

        # b) 买入
        if buy_pt < len(buy_dates) and int(buy_bar[buy_pt]) == t:
            q = shares_np[buy_pt]
            c = cost_np[buy_pt]
            units.append({"qty": q, "cost": c, "buy": t, "div": 0.0, "buy_d": dt})
            shares += q
            flows.append((dt, -c))
            buy_pt += 1

        # c) 卖出: 全局突破——收盘价达到最近 high_days 日新高时, 当日收盘卖出全部持仓
        if roll_high is not None and not np.isnan(roll_high[t]) and closes[t] >= roll_high[t]:
            for u in units[:]:
                if t > u["buy"]:   # 买入当日不卖(买入价是低位, 不可能已突破)
                    proceeds = u["qty"] * closes[t]
                    cash += proceeds
                    shares -= u["qty"]
                    flows.append((dt, proceeds))
                    closed.append({"buy_d": u["buy_d"], "sell_d": dt,
                                   "cost": u["cost"], "value": proceeds + u["div"]})
                    units.remove(u)

        equity[t] = shares * closes[t] + cash

    today = bfq["trade_time"].iloc[-1]
    price_now = bfq["close"].iloc[-1]

    # 期末未平仓归入交易统计, 供胜率/盈亏比计算
    for u in units:
        closed.append({"buy_d": u["buy_d"], "sell_d": today,
                       "cost": u["cost"], "value": u["qty"] * price_now + u["div"]})

    invested = cost_ea.sum()
    assets = equity[-1]                 # 期末市值 + 现金(分红/卖出)
    profit = assets - invested
    ret = assets / invested - 1 if invested else 0.0

    # 资金时间加权年化(XIRR): 期末持仓市值作为最后一笔正现金流
    flows = flows + [(today, shares * price_now)]
    annual = xirr(flows)
    if annual is None:
        annual = (assets / invested) ** (365.25 / (today - buy_dates.iloc[0]).days) - 1

    # 最大回撤: 每日净值 = 持股x收盘 + 累计现金, 用 cummax (只在有持仓的区间计算)
    peak = np.maximum.accumulate(equity)
    wm = equity > 0                      # 跳过建仓前的0净值占位
    max_drawdown = float((equity[wm] / peak[wm] - 1.0).min()) if wm.any() else 0.0

    # 胜率 / 盈亏比 (按每笔买入的独立交易)
    pnl = [c["value"] - c["cost"] for c in closed]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    n = len(pnl)
    win_rate = len(wins) / n if n else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    pl_ratio = (avg_win / abs(avg_loss)) if avg_loss else (float("inf") if avg_win else 0.0)

    trade_table = pd.DataFrame([
        {"买入日": pd.to_datetime(c["buy_d"]).date(), "卖出日": pd.to_datetime(c["sell_d"]).date(),
         "成本(元)": round(c["cost"], 2), "了结价值(元)": round(c["value"], 2),
         "盈亏(元)": round(c["value"] - c["cost"], 2)}
        for c in closed])

    # 每次买入明细(时间 + 前复权价)
    buy_detail = pd.DataFrame({
        "买入日期": pd.to_datetime(buy_dates).dt.date.values,
        "前复权价格": qjq_price.round(3).values,
        "不复权价格": price.round(2).values,
        "买入股数": shares_ea.values,
        "实际花费": cost_ea.round(0).astype(int).values,
    })

    return {"symbol": symbol, "name": name, "low_days": low_days, "high_days": high_days,
            "ihist": qjq["trade_time"].iloc[0].date(),
            "buys": int(len(buy_dates)), "invested": invested,
            "shares": shares, "div": cash_div, "assets": assets,
            "profit": profit, "ret": ret, "annual": annual,
            "win_rate": win_rate, "pl_ratio": pl_ratio, "max_drawdown": max_drawdown,
            "n_trades": len(closed),
            "detail": buy_detail, "trades": trade_table}


def run(symbols, low_days=1250, buy_amount=10000.0, high_days=None) -> "pd.DataFrame":
    """对一组股票运行『过去 low_days 交易日新低买入』回测并打印汇总/明细。

    返回结果 DataFrame, 每行对应一只股票的回测汇总(供项目入口复用)。
    """
    client = get_client()
    try:
        return run_with_client(client, symbols, low_days=low_days,
                               buy_amount=buy_amount, high_days=high_days)
    finally:
        try:
            client.close()
        except Exception:
            pass


def run_with_client(client, symbols, low_days=1250, buy_amount=10000.0,
                    high_days=None) -> "pd.DataFrame":
    """给定已验证的 sharetop client 执行回测并打印(避免入口重复建连接)。"""
    rows = [backtest(client, s, low_days=low_days, buy_amount=buy_amount, high_days=high_days)
            for s in symbols]
    res = pd.DataFrame(rows)
    low_days = int(res["low_days"].iloc[0])
    high_days_show = None
    if res["high_days"].notna().any():
        high_days_show = int(res["high_days"].iloc[0])

    pd.set_option("display.width", 250)
    show = res[["symbol", "name", "ihist", "buys", "invested", "div", "assets", "profit"]].copy()
    show["ihist"] = pd.to_datetime(show["ihist"]).dt.strftime("%Y-%m")
    # 金额列转整数, 去掉 .0 避免视觉错位
    for c in ("invested", "div", "assets", "profit"):
        show[c] = show[c].astype("int64")
    show["总收益率%"] = (res["ret"] * 100).round(2)
    show["复合年化%"] = (res["annual"] * 100).round(2)
    show["胜率%"] = (res["win_rate"] * 100).round(1)
    show["盈亏比"] = res["pl_ratio"].astype(float).round(2)
    show["最大回撤%"] = (res["max_drawdown"] * 100).round(1)
    show.columns = ["代码", "名称", "行情起始", "买入次", "投入本金", "现金分红", "总资产", "获利",
                    "总收益率(%)", "复合年化(%)", "胜率(%)", "盈亏比", "最大回撤(%)"]
    sell_desc = f"收盘达到{high_days_show}日新高卖出" if high_days_show else "只买不卖"
    print(f"策略: 过去{low_days}个交易日新低, 每次买入 {int(buy_amount):,}元(买不起一手则买一手), 卖出规则={sell_desc}, XIRR=复合年化收益率")
    print(show.to_string(index=False, justify="center"))

    # 逐行一一对应打印, 彻底避免列错位
    print("\n===== 单只明细(键值一一对应) =====")
    for _, r in res.iterrows():
        print(f"{r['name']} {r['symbol']}")
        print(f"  低点回看    : {int(r['low_days'])} 个交易日")
        print(f"  累计买入次  : {int(r['buys'])} 次")
        print(f"  累计投入本金: {int(r['invested']):,} 元")
        print(f"  当前持股    : {int(r['shares']):,} 股")
        print(f"  现金分红累计: {int(r['div']):,} 元")
        print(f"  最终总资产  : {int(r['assets']):,} 元")
        print(f"  获利金额    : {int(r['profit']):,} 元")
        print(f"  总收益率    : {r['ret']*100:+.2f}%")
        print(f"  复合年化收益率 : {r['annual']*100:+.2f}%(XIRR)")
        print(f"  胜率        : {r['win_rate']*100:.1f}% / 盈亏比 {r['pl_ratio']:+.2f} / 交易 {int(r['n_trades'])} 笔")
        print(f"  最大回撤    : {r['max_drawdown']*100:.2f}%")
        if r["detail"] is not None and not r["detail"].empty:
            print("  买入明细(时间 + 前复权价):")
            print(r["detail"].to_string(index=False, justify="center"))
        if r["trades"] is not None and not r["trades"].empty:
            print("  每笔交易盈亏明细(卖出日=今日 表示仍持有):")
            print(r["trades"].to_string(index=False, justify="center"))
        print()

    print("\n说明:")
    print(f" - 『{low_days}个交易日新低』指当日前复权收盘价 ≤ 过去 {low_days} 个交易日滚动最低收盘价, 即跌破最近 {low_days} 个交易日的低点即买入(≈{low_days/250:.1f}年)。")
    print(" - 买入次=0 表示该股为长期上行趋势, 从未创出过低点, 策略自然无信号。")
    print(" - 现金分红按税前元/股累加,送转股已并入持股数。")
    return res


if __name__ == "__main__":
    """
    使用样例命令：python -m app.cli low-backtest --low-days 1250 --symbols 600054.SH --high-days 1250
    """
    import sys
    import argparse

    # --name=value 风格参数:  --symbols 必填
    parser = argparse.ArgumentParser(description="过去N个交易日新低买入回测")
    parser.add_argument("--low_days", type=int, default=1250,
                        help="低点回看天数(交易日), 默认1250(≈5年)")
    parser.add_argument("--buy_amount", type=float, default=10000.0,
                        help="单次买入金额, 默认10000")
    parser.add_argument("--symbols", type=str, required=True,
                        help="股票代码, 多个用英文逗号分隔, 必填, 如 600054.SH,600519.SH")
    parser.add_argument("--high_days", type=int, default=None,
                        help="卖出规则: 收盘价突破N日新高即卖出全部持仓(算胜率/盈亏比); 缺省=只买不卖")
    args = parser.parse_args()

    if not args.symbols:
        parser.error("参数 --symbols 必传: 请用 --symbols='600054.SH,600519.SH' 指定要回测的股票代码")

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    run(symbols, low_days=args.low_days, buy_amount=args.buy_amount, high_days=args.high_days)