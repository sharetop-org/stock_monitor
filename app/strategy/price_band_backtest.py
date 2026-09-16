#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""指定区间 + 固定买入价/卖出价 的「价格带」回测策略。

思想: 在 [开始, 结束] 区间内, 当(前复权)收盘价 <= 买入价 时买入一手仓位,
     当(前复权)收盘价 >= 卖出价 时卖出全部持仓。卖出后可再逢低买入(可反复),
     从而形成多笔独立交易, 用于统计胜率/盈亏比。

口径(与 days_backtest 一致):
  - 信号: 用「前复权(before)」收盘价与设定价格比较(消除分红/拆股造成的价格断层);
  - 成交: 用「不复权(normal)」当日真实收盘价下单, 1手(100股)内取整, 买不起一手则买一手;
  - 分红: 已实施(状态5)的现金分红计入现金、送转股并入持股数;
  - 指标: 总收益、XIRR复合年化、胜率、盈亏比、最大回撤、每笔买入/成交明细。

用法样例:
    python -m app.cli price-backtest --symbols 600519.SH,600036.SH \\
        --start 2015-01-01 --buy-price 30 --sell-price 60 --buy-amount 100000

⚠️ buy_price 与 sell_price 按前复权价格给出, 且应满足 buy_price < sell_price,
   否则同一天可能既触发买又触发卖(不符合价差常理)。
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from app.datasource.sharetop_source import get_share_client as get_client
from app.strategy.days_backtest import get_name, prep_adj, to_aligned_table, xirr


def _hist(client, symbol: str, adjust: str) -> pd.DataFrame:
    """拉取某只股票的日K并做时间排序; adjust='before'=前复权, 'normal'=不复权。"""
    d = client.klines.get_history_data(symbol, period="d",
                                       count=60000, adjust=adjust, as_df=True)
    if not isinstance(d, pd.DataFrame) or d.empty:
        return pd.DataFrame()
    return prep_adj(d)


def _dividend_events(client, symbol: str, tax_mode: str = "before") -> list:
    """取该股已实施(状态5)的分红/送转事件 → [(除权日, 每股现金, 每股送转股数), ...]。
    与 days_backtest 口径一致, 接口异常时返回空列表。"""
    try:
        div = client.financials.stock_dividend(symbols=[symbol], as_df=True)[symbol].copy()
        div["ex"] = pd.to_datetime(div["ex_rights_dividend_date"], errors="coerce")
        div = div.dropna(subset=["ex"])
        div = div[div["current_status"].astype(str) == "5"]     # 仅统计已实施完成(5)
        div = div.sort_values("ex").reset_index(drop=True)
        cash_col = "dps_before_tax" if tax_mode == "before" else "dps_after_tax"
        div["cash_ps"] = div[cash_col].fillna(0) / 10.0                 # 每10股 → 元/股
        div["bonus_ps"] = div["bonus_share_ratio"].fillna(0) / 10.0     # 送股/股
        div["cap_ps"] = div["capitalization_ratio"].fillna(0) / 10.0    # 转增/股
        return list(zip(div["ex"], div["cash_ps"], div["bonus_ps"] + div["cap_ps"]))
    except Exception:
        return []


def backtest(client, symbol: str, start=None, end=None,
             buy_price: float = 10.0, sell_price: float = 20.0,
             buy_amount: float = 10000.0, lot: int = 100,
             tax_mode: str = "before") -> dict:
    """在 [start, end] 内按「收盘价≤买入价买入 / ≥卖出价卖出」回测。

    start/end: 指定回测起止日期(可为字符串/日期/Timestamp)。缺省 end=None=截至今日(末根K线),
               start=None=从该股上市日(首根K线)起。区间的信号与成交都只取区间内的K线。
    buy_price/sell_price: 前复权触发价(元)。日内同时≤买且≥卖不成立需 buy<sell。
    """
    qjq = _hist(client, symbol, adjust="before")    # 前复权 → 定买卖信号
    bfq = _hist(client, symbol, adjust="normal")    # 不复权 → 按当日真实价成交
    name = get_name(client, symbol)

    def _empty():
        return {"symbol": symbol, "name": name, "status": "insufficient",
                "ihist": None, "buys": 0, "invested": 0.0, "shares": 0.0,
                "div": 0.0, "assets": 0.0, "profit": 0.0, "ret": 0.0, "annual": 0.0,
                "win_rate": 0.0, "pl_ratio": 0.0, "max_drawdown": 0.0, "n_trades": 0,
                "qhigh": 0.0, "qhigh_d": None, "qlow": 0.0, "qlow_d": None,
                "detail": pd.DataFrame(), "trades": pd.DataFrame()}

    if qjq.empty or bfq.empty:
        return _empty()

    # 对齐两套价格到一致的交易日
    qjq = qjq.set_index("trade_time")
    bfq = bfq.set_index("trade_time")
    common = qjq.index.intersection(bfq.index)
    qjq, bfq = qjq.loc[common], bfq.loc[common]
    qjq = qjq.sort_index()
    bfq = bfq.sort_index()

    # 时间区间过滤
    if start is not None:
        start = pd.Timestamp(start)
        qjq, bfq = qjq[qjq.index >= start], bfq[bfq.index >= start]
    if end is not None:
        end = pd.Timestamp(end)
        qjq, bfq = qjq[qjq.index <= end], bfq[bfq.index <= end]
    if qjq.empty or bfq.empty:
        return _empty()

    # 触发价用前复权收盘, 成交用不复权收盘
    times = bfq.index.tolist()
    qcloses = qjq["close"].to_numpy(dtype=float)
    closes = bfq["close"].to_numpy(dtype=float)
    n = len(closes)

    # 区间内前复权收盘价最高/最低值(及其出现日期)
    qmax_i = int(np.argmax(qcloses))
    qmin_i = int(np.argmin(qcloses))
    qhigh = float(qcloses[qmax_i]); qhigh_d = times[qmax_i]
    qlow = float(qcloses[qmin_i]);  qlow_d = times[qmin_i]

    # 只保留落在回测区间内的分红事件(否则指针会被区间前的首个事件卡住而不前进)
    div_sorted = [e for e in _dividend_events(client, symbol, tax_mode)
                  if times[0] <= e[0] <= times[-1]]
    div_sorted.sort(key=lambda e: e[0])
    div_pt = 0

    # 日度模拟: 单仓位(卖出后可再买的可反复模型)
    position = None             # 当前持仓 {qty,cost,buy_d,div}; None=空仓
    shares = 0.0
    cash = 0.0                  # 已到手现金 = 分红 + 卖出所得
    cash_div = 0.0              # 分红累计
    invested = 0.0              # 已投入本金
    flows = []                  # XIRR 现金流
    closed = []                 # 已了结 & 期末未平仓
    buy_rows = []               # 每笔买入明细
    equity = np.empty(n)
    first_buy_d = None

    for t in range(n):
        dt = times[t]

        # a) 分红 + 送转(当日持有才计入)
        if div_pt < len(div_sorted) and div_sorted[div_pt][0].date() == dt.date():
            _d, dps, bonus = div_sorted[div_pt]
            div_pt += 1
            if dps and shares:
                div_cash = shares * dps
                cash += div_cash
                cash_div += div_cash
                flows.append((dt, div_cash))
                if position:
                    position["div"] += position["qty"] * dps
            bonus = 1.0 + bonus                  # 送转比例转成乘数(如 0.1 → ×1.1)
            if bonus != 1.0 and shares:
                shares *= bonus
                if position:
                    position["qty"] *= bonus

        # b) 买入: 空仓且前复权收盘 ≤ 买入价
        if position is None and qcloses[t] <= buy_price:
            price = closes[t]
            lots = int(buy_amount / price) // lot
            qty = max(lots * lot, lot)          # 买不起一手 → 直接买一手
            cost = qty * price
            position = {"qty": qty, "cost": cost, "buy_d": dt, "div": 0.0}
            shares = qty
            invested += cost
            flows.append((dt, -cost))
            if first_buy_d is None:
                first_buy_d = dt
            buy_rows.append({"买入日期": dt.date(), "前复权价格": round(qcloses[t], 3),
                             "不复权价格": round(price, 2), "买入股数": qty,
                             "实际花费": round(cost, 0)})

        # c) 卖出: 持仓且前复权收盘 ≥ 卖出价 → 当日收盘全部卖出
        if position is not None and qcloses[t] >= sell_price:
            qty = position["qty"]
            proceeds = qty * closes[t]
            cash += proceeds
            flows.append((dt, proceeds))
            closed.append({"buy_d": position["buy_d"], "sell_d": dt, "open": False,
                           "sell_qclose": qcloses[t], "sell_close": closes[t],
                           "cost": position["cost"], "value": proceeds + position["div"]})
            shares = 0.0
            position = None

        equity[t] = shares * closes[t] + cash

    today = times[-1]
    price_now = closes[-1]

    # 期末仍持仓 → 归入已了结(卖出日=今日, 表示仍持有)
    if position is not None:
        closed.append({"buy_d": position["buy_d"], "sell_d": today, "open": True,
                       "sell_qclose": qcloses[-1], "sell_close": price_now,
                       "cost": position["cost"],
                       "value": position["qty"] * price_now + position["div"]})

    assets = shares * price_now + cash
    profit = assets - invested
    ret = assets / invested - 1 if invested else 0.0

    # 资金时间加权年化(XIRR): 期末持仓市值作为最后一笔正现金流
    flows = flows + [(today, shares * price_now)]
    annual = xirr(flows)
    if annual is None and invested and first_buy_d is not None:
        annual = (assets / invested) ** (365.25 / (today - first_buy_d).days) - 1
    if annual is None:
        annual = 0.0

    # 最大回撤: 每日净值 = 持股x收盘 + 累计现金, 跳过建仓前的0占位
    peak = np.maximum.accumulate(equity)
    wm = equity > 0
    max_drawdown = float((equity[wm] / peak[wm] - 1.0).min()) if wm.any() else 0.0

    # 胜率 / 盈亏比(每笔独立交易)
    pnl = [c["value"] - c["cost"] for c in closed]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    n_trades = len(pnl)
    win_rate = len(wins) / n_trades if n_trades else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    pl_ratio = (avg_win / abs(avg_loss)) if avg_loss else (float("inf") if avg_win else 0.0)

    trade_table = pd.DataFrame([
        {"买入日": pd.to_datetime(c["buy_d"]).date(),
         "卖出日": pd.to_datetime(c["sell_d"]).date(),
         "状态": ("持有的" if c["open"] else "已卖出"),
         "卖出前复权价": round(c["sell_qclose"], 3),
         "卖出不复权价": round(c["sell_close"], 2),
         "成本(元)": round(c["cost"], 2),
         "了结价值(元)": round(c["value"], 2),
         "盈亏(元)": round(c["value"] - c["cost"], 2)}
        for c in closed])
    buy_detail = pd.DataFrame(buy_rows, columns=[
        "买入日期", "前复权价格", "不复权价格", "买入股数", "实际花费"])

    return {"symbol": symbol, "name": name, "status": "ok",
            "ihist": times[0].date() if times else None,
            "buys": len(buy_rows), "invested": invested, "shares": shares,
            "div": cash_div, "assets": assets, "profit": profit, "ret": ret,
            "annual": annual, "win_rate": win_rate, "pl_ratio": pl_ratio,
            "max_drawdown": max_drawdown, "n_trades": n_trades,
            "qhigh": qhigh, "qhigh_d": qhigh_d.date(),
            "qlow": qlow, "qlow_d": qlow_d.date(),
            "detail": buy_detail, "trades": trade_table}


def run(symbols, start=None, end=None, buy_price=10.0, sell_price=20.0,
        buy_amount=10000.0, lot=100, export_path=None) -> "pd.DataFrame":
    """对一组股票运行『价格带买卖』回测并打印汇总/明细。返回结果 DataFrame。

    export_path: 非空时把逐股结果写入该 Excel；默认 None = 不保存。
    """
    client = get_client()
    try:
        return run_with_client(client, symbols, start=start, end=end,
                               buy_price=buy_price, sell_price=sell_price,
                               buy_amount=buy_amount, lot=lot, export_path=export_path)
    finally:
        try:
            client.close()
        except Exception:
            pass


def run_with_client(client, symbols, start=None, end=None,
                    buy_price=10.0, sell_price=20.0,
                    buy_amount=10000.0, lot=100, export_path=None) -> "pd.DataFrame":
    """给定已验证的 sharetop client 执行回测并打印(避免入口重复建连接)。

    export_path: 非空时把逐股结果写入该 Excel；默认 None = 不保存。
    """
    rows = [backtest(client, s, start=start, end=end,
                     buy_price=buy_price, sell_price=sell_price,
                     buy_amount=buy_amount, lot=lot) for s in symbols]
    res = pd.DataFrame(rows)
    # 写入导出所需列(区间/买卖价), 便于 export_frame 复用
    res["start"] = str(start) if start is not None else "上市首日"
    res["end"] = str(end) if end is not None else "今日"
    res["buy_price"] = buy_price
    res["sell_price"] = sell_price

    pd.set_option("display.width", 260)
    show = res[["symbol", "name", "buys", "invested", "div", "assets", "profit"]].copy()
    for c in ("invested", "div", "assets", "profit"):
        show[c] = show[c].astype("int64")
    show["总收益率%"] = (res["ret"] * 100).round(2)
    show["复合年化%"] = (res["annual"] * 100).round(2)
    show["胜率%"] = (res["win_rate"] * 100).round(1)
    show["盈亏比"] = res["pl_ratio"].astype(float).round(2)
    show["最大回撤%"] = (res["max_drawdown"] * 100).round(1)
    show["前复权最高"] = res["qhigh"].round(2)
    show["前复权最低"] = res["qlow"].round(2)
    show.columns = ["代码", "名称", "买入次", "投入本金", "现金分红", "总资产", "获利",
                    "总收益率(%)", "复合年化(%)", "胜率(%)", "盈亏比", "最大回撤(%)",
                    "前复权最高", "前复权最低"]
    span = f"{start or '上市首日'} ~ {end or '今日'}"
    print(f"策略: {span} 区间内 前复权收盘<=买入价({buy_price}元)买入 / >=卖出价({sell_price}元)卖出, "
          f"每次买入 {int(buy_amount):,}元(买不起一手则买一手), 卖出后可反复再买, XIRR=复合年化")
    print(to_aligned_table(show))

    # 逐行一一对应打印, 彻底避免列错位
    print("\n===== 单只明细(键值一一对应) =====")
    for _, r in res.iterrows():
        print(f"{r['name']} {r['symbol']}")
        print(f"  回测区间    : {r['ihist']} ~ 今日")
        print(f"  买入区间信号: 前复权收盘 <= {buy_price} 元")
        print(f"  卖出区间信号: 前复权收盘 >= {sell_price} 元")
        print(f"  区间前复权最高: {r['qhigh']:.2f} 元 ({r['qhigh_d']})")
        print(f"  区间前复权最低: {r['qlow']:.2f} 元 ({r['qlow_d']})")
        print(f"  累计买入次数: {int(r['buys'])} 次")
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
            print("  " + to_aligned_table(r["detail"]).replace("\n", "\n  "))
        if r["trades"] is not None and not r["trades"].empty:
            print("  每笔交易盈亏明细(状态=持有的 表示期末仍未达到卖出价, 按当日收盘市值结算, 非真实卖出):")
            print("  " + to_aligned_table(r["trades"]).replace("\n", "\n  "))
        print()

    print("\n说明:")
    print(" - 买卖信号取前复权收盘价(消除分红送转造成的价格断层), 成交按当日不复权真实收盘价。")
    print(" - 买入次=0 表示区间内该股始终高于买入价(或空间不足), 未触发买入。")
    print(" - 现金分红按税前元/股累加, 送转股已并入持股数。卖出后可再逢低买入(可反复)。")
    print(" - 明细中 状态=已卖出 为真实达到卖出价触发; 状态=持有的 是期末未达卖出价, 按当日收盘市值标注(非真实卖出)。")
    if export_path:
        p = export_excel(res, export_path)
        print(f"\n已保存逐股结果到 Excel: {p}")
    return res


# 导出 Excel 时的列与取值口径
export_cols = ["symbol", "name", "start", "end", "buy_price", "sell_price",
               "买入次", "投入本金", "现金分红", "总资产", "利润(万)", "总收益%",
               "复合年化%", "胜率%", "盈亏比", "最大回撤%", "前复权最高", "前复权最低"]


def export_frame(res: pd.DataFrame) -> pd.DataFrame:
    """把逐股结果构造成符合导出表头的 DataFrame（默认不导出，传 export_path 才落盘）。"""
    return pd.DataFrame({
        "symbol": res["symbol"],
        "name": res["name"],
        "start": res["start"],
        "end": res["end"],
        "buy_price": res["buy_price"].astype(float).round(2),
        "sell_price": res["sell_price"].astype(float).round(2),
        "买入次": res["buys"].astype(int),
        "投入本金": res["invested"].round(0).astype(int),
        "现金分红": res["div"].round(0).astype(int),
        "总资产": res["assets"].round(0).astype(int),
        "利润(万)": (res["profit"] / 1e4).round(2),
        "总收益%": (res["ret"] * 100).round(2),
        "复合年化%": (res["annual"] * 100).round(2),
        "胜率%": (res["win_rate"] * 100).round(2),
        "盈亏比": res["pl_ratio"].astype(float).round(2),
        "最大回撤%": (res["max_drawdown"] * 100).round(2),
        "前复权最高": res["qhigh"].round(2),
        "前复权最低": res["qlow"].round(2),
    })[export_cols]


def export_excel(res: pd.DataFrame, path: str) -> str:
    """把逐股结果写入 Excel 文件，返回写入路径。表头见 export_cols。"""
    if res is None or res.empty:
        raise ValueError(f"没有可导出的回测结果, 未写入 {path}")
    frame = export_frame(res)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="回测结果")
        ws = writer.sheets["回测结果"]
        for i, width in enumerate((10, 10, 12, 12, 10, 10, 8, 10, 10, 10, 10, 10, 10, 8, 8, 10, 12, 12)):
            ws.column_dimensions[chr(ord("A") + i)].width = width
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="指定区间+固定买入价/卖出价的价格带回测")
    parser.add_argument("--symbols", type=str, required=True,
                        help="股票代码, 多个用英文逗号分隔, 必填, 如 600519.SH,600036.SH")
    parser.add_argument("--start", default=None, help="开始日期, 如 2015-01-01; 缺省=上市首日")
    parser.add_argument("--end", default=None, help="结束日期, 如 2024-12-31; 缺省=今日(末根K线)")
    parser.add_argument("--buy_price", type=float, default=10.0, help="前复权买入触发价(元)")
    parser.add_argument("--sell_price", type=float, default=20.0, help="前复权卖出触发价(元)")
    parser.add_argument("--buy_amount", type=float, default=10000.0, help="单次买入金额, 默认10000")
    args = parser.parse_args()

    if not args.symbols:
        parser.error("参数 --symbols 必传: 请用 --symbols='600519.SH,600036.SH' 指定股票代码")
    if args.buy_price >= args.sell_price:
        parser.error(f"买入价({args.buy_price}) 应小于 卖出价({args.sell_price}), 否则价差不成立")

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    run(symbols, start=args.start, end=args.end,
        buy_price=args.buy_price, sell_price=args.sell_price, buy_amount=args.buy_amount)
