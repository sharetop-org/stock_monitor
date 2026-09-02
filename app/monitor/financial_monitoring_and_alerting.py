#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""创N日新低 邮箱报警监测工具。

快速上手:
    python financial_monitoring_and_alerting.py --symbols 600036.SH,600519.SH

逻辑(与 buy_and_backtest_cal.py 口径一致):
  对每只股票取前复权(before)日K, 对每个观察窗口 w(交易日天数, 默认 1250 约等于 5 年),
  当日收盘价 ≤ 近 w 个交易日滚动最低收盘价, 即判定为"触及 w 日的股价低位";
  任一窗口触发即报警。示例: --windows 1250,360,60 同时监测 5年/360日/60日三个低位。
  当日收盘价 ≤ 近 w 个交易日滚动最低收盘价, 即判定为"触及 w 日的股价低位";
  任一窗口触发即报警。

邮箱(SMTP)配置通过环境变量给出(推荐), 也可改下方 EMAIL_DEFAULT 默认值:
    SMTP_HOST   SMTP_PORT   SMTP_USER   SMTP_PASS   SMTP_FROM   MAIL_TO
    SMTP_SSL=1 表示 465 端口 SSL, 否则 587 STARTTLS。

默认只在价格创出「比上次报警更低的新低」时才再次发信(由状态文件去重), 避免反复轰炸。
"""

from sharetop import ShareTop

import argparse
import json
import os
import time
from datetime import datetime

import pandas as pd

# 邮件发送统一复用项目 notifier：app/alert/notifier/mail_sender_new.py
from app.alert.notifier.mail_sender_new import MailNew
# ShareTop client 统一走项目数据源共享工厂 app/datasource/sharetop_source.py
from app.datasource.sharetop_source import get_share_client as get_client


# 状态文件: 记录已对每只股票报警过的低位价, 避免重复发信
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_state.json")

# 每股监测之间的停顿秒数, 降低 ShareTop 访问频次限流被误判成"数据不足"的概率
PAUSE = 2.0

# 当某股扫描返回"数据不足(?)"时, 额外重试次数与停顿秒数(比常规 PAUSE 更长)
INSUFFICIENT_RETRIES = 3
RETRY_SLEEP = 10.0


def prep_adj(d: pd.DataFrame) -> pd.DataFrame:
    """把 K线原始 DataFrame 规整为按时间升序。"""
    d = d.copy()
    d["trade_time"] = pd.to_datetime(d["trade_time"])
    return d.sort_values("trade_time").reset_index(drop=True)


def get_name(client: ShareTop, symbol: str) -> str:
    """根据 ts_code 获取股票简称。"""
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


# 实时行情里要写进邮件/报警的指标字段
RT_METRIC_FIELDS = (
    "total_market_cap",     # 总市值(元)
    "float_market_cap",     # 流通市值(元)
    "bvps",                 # 每股净资产
    "eps_ttm",              # 每股收益(TTM)
    "forward_pe",           # 动态市盈率
    "static_pe",            # 静态市盈率
    "ttm_pe",               # 市盈率(TTM)
    "pb",                   # 市净率
    "change_percent",       # 涨跌幅(%)
)


def get_realtime_quote(client: ShareTop, symbol: str) -> dict:
    """通过 ShareTop 深度实时行情(stock_deep_quote)取最新报价与估值指标。

    返回 dict：{close, trade_date, *RT_METRIC_FIELDS}；失败返回 {}。
    - close: 最新价(作为对比用的最新价)
    - trade_time 可能是 Unix 秒/毫秒时间戳或 "YYYY-MM-DD" 字符串，统一转日期
    """
    try:
        raw = client.quotes.stock_deep_quote(symbol, as_df=False)
        it = raw[0] if isinstance(raw, list) and raw else None
        if not it:
            return {}
        out = {"close": float(it.get("close") or it.get("last_price") or 0.0) or None}
        t = it.get("trade_time")
        if t:
            try:
                n = int(t)
                if n > 1e12:
                    n = n // 1000            # 毫秒 -> 秒
                out["trade_date"] = datetime.fromtimestamp(n).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                out["trade_date"] = str(t)[:10] or None
        for k in RT_METRIC_FIELDS:
            out[k] = it.get(k)
        return out
    except Exception as exc:  # noqa: BLE001
        print("获取实时行情失败:", symbol, exc)
        return {}


def check_low(client: ShareTop, symbol: str, windows: list) -> dict:
    """监测指定股票是否创出任一观察窗口(交易日天数)的股价低位。

    口径: 前复权日K + 实时行情深度报价(deep_quote)。以实时最新价 close 作为最新价，
    对每个窗口 w, 判断该实时价是否 ≤ 近 w 个交易日(含最新K线)滚动最低收盘价；
    是则判定「触及 w 日低位」，任一窗口触发即 status='hit'。

    返回 dict 关键字段:
      status   : 'hit' | 'no' | 'insufficient'
      hit      : 是否至少一个窗口触发(仅 status=hit/no 有意义)
      windows  : 各窗口明细(list of dict, 含 window/status/low_threshold/...)
      latest_* : 最新(实时)价格与日期
      below_pct : 最新价相对今日更早前历史最低价的涨跌幅(%)
      off_high_pct : 区间最低相对历史最高的涨跌幅(%)
    """
    # 历史K线：ShareTop 风控/限流时会返回非 DataFrame 或缺列的数据, 容错为数据不足。
    # 遇到"访问频次超限"自动退避重试，避免轮询时把限流误判成无权限/无数据。
    def _hist_data(adjust: str, retries: int = 3):
        d = None
        for _ in range(retries):
            try:
                d = client.klines.get_history_data(
                    symbol, period="d", count=6000, adjust=adjust, as_df=True)
            except Exception:
                return pd.DataFrame()
            if isinstance(d, str) and ("频次超限" in d or "频繁" in d):
                time.sleep(5 + _ * 3)             # 退避后重试
                continue
            break
        if not isinstance(d, pd.DataFrame) or d.empty:
            return pd.DataFrame()
        if not {"trade_time", "close", "open", "high", "low"}.issubset(d.columns):
            return pd.DataFrame()
        return d

    qjq = _hist_data("before")
    if qjq.empty:
        return {"symbol": symbol, "name": get_name(client, symbol),
                "status": "insufficient", "hit": False, "windows": []}
    qjq = prep_adj(qjq)

    # 以实时行情最新 close 作为最新价，追加为最新一根K线，再与历史日K对比
    rt = get_realtime_quote(client, symbol)
    rt_close = rt.get("close")
    rt_date = rt.get("trade_date")
    if rt_close is not None:
        _last = pd.to_datetime(qjq["trade_time"].iloc[-1])
        row_time = pd.Timestamp(rt_date) if rt_date else _last
        qjq = pd.concat([
            qjq,
            pd.DataFrame([{"close": rt_close, "trade_time": row_time}]),
        ], ignore_index=True)

    # 上市以来(本次抓取区间)最高收盘价及对应日期
    high_idx = int(qjq["close"].idxmax())
    prior_hist_high = float(qjq["close"].max())
    prior_high_date = pd.to_datetime(qjq["trade_time"].iloc[high_idx]).date()

    results = []
    for w in windows:
        if len(qjq) < w:
            results.append({"window": w, "status": "insufficient",
                            "ihist": qjq["trade_time"].iloc[0].date(), "hit": False,
                            "prior_hist_high": prior_hist_high,
                            "prior_high_date": str(prior_high_date)})
            continue

        low = qjq["close"].rolling(w, min_periods=w).min()
        new_low = (qjq["close"] <= low)                  # 当日是否触及 w 日低位
        last = qjq.iloc[-1]

        prev_behind = qjq["close"].iloc[:-1]             # 今日之前的历史收盘
        prior_hist_low = float(prev_behind.min())        # 今日更早前的最低收盘价
        prior_low_idx = int(prev_behind.idxmin())        # 历史最低价所在行
        prior_low_date = pd.to_datetime(qjq["trade_time"].iloc[prior_low_idx]).date()

        latest_close = float(last["close"])
        latest_date = pd.to_datetime(last["trade_time"]).date()
        low_threshold = float(low.iloc[-1])              # 近 w 日滚动最低价
        hit = bool(new_low.iloc[-1])

        if len(low) > 1:
            low_idx = int(low.iloc[:-1].idxmin())        # 前期最低位所在行
            low_hist_date = pd.to_datetime(qjq["trade_time"].iloc[low_idx]).date()
        else:
            low_hist_date = latest_date

        below_pct = (latest_close / prior_hist_low - 1) * 100 if prior_hist_low else 0.0
        # 当前区间最低位相对历史最高位的涨跌幅(%)
        off_high_pct = (prior_hist_low / prior_hist_high - 1) * 100 if prior_hist_high else 0.0

        results.append({"window": w, "status": "hit" if hit else "no", "hit": hit,
                        "latest_date": latest_date, "latest_close": latest_close,
                        "low_threshold": low_threshold, "low_hist_date": low_hist_date,
                        "prior_hist_low": prior_hist_low, "prior_low_date": str(prior_low_date),
                        "prior_hist_high": prior_hist_high, "prior_high_date": str(prior_high_date),
                        "below_pct": below_pct, "off_high_pct": off_high_pct})

    hits = [r for r in results if r.get("hit")]
    if hits:
        status = "hit"
    elif any(r["status"] == "no" for r in results):
        status = "no"
    else:
        status = "insufficient"

    ref = hits[0] if hits else \
        next((r for r in results if r["status"] == "no"), results[0])

    out = {"symbol": symbol, "name": get_name(client, symbol),
           "status": status, "hit": bool(hits), "windows": results,
           "latest_date": ref["latest_date"], "latest_close": ref["latest_close"],
           "prior_hist_low": ref["prior_hist_low"], "prior_low_date": ref["prior_low_date"],
           "prior_hist_high": ref["prior_hist_high"], "prior_high_date": ref["prior_high_date"],
           "below_pct": ref["below_pct"], "off_high_pct": ref["off_high_pct"],
           "deep": rt}
    if status == "insufficient":
        out["ihist"] = results[0]["ihist"]
    return out


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def should_alert(symbol: str, latest_close: float, state: dict) -> bool:
    """去重: 仅当价格创下低于已报警价位的新低时才再次报警。"""
    prev_low = (state.get(symbol) or {}).get("low")
    if prev_low is None:
        return True
    return latest_close < prev_low - 1e-9



def notify_hits(rows, state, receiver: str) -> int:
    """组装命中的报警邮件并发信; 记录去重状态。返回实际发送数量。"""
    to_alert = [r for r in rows
                if r.get("status") == "hit"
                and should_alert(r["symbol"], r["latest_close"], state)]
    if not to_alert:
        return 0

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 主题里的窗口标签取自实际命中的窗口(每股窗口可不同)
    lab = "/".join(str(x["window"])
                   for x in sorted({x["window"] for r in to_alert
                                    for x in r["windows"] if x.get("hit")}))
    subject = f"[低位报警] {len(to_alert)} 只股票触及 {lab} 日低位 {stamp}"

    def _kv(label, value, value_color=""):
        """一行键值：第一列字段标题，第二列字段内容。"""
        return ("<tr>"
                f"<td style='padding:9px 14px;border-bottom:1px solid #eee;background:#f7f8fa;"
                f"width:26%;font-weight:bold;color:#555;'>{label}</td>"
                f"<td style='padding:9px 14px;border-bottom:1px solid #eee;{value_color};'>{value}</td>"
                "</tr>")

    text_rows = []
    cards = []
    for r in to_alert:
        hit_ws = [x for x in r["windows"] if x.get("hit")]
        ws_lab = "/".join(str(x["window"]) for x in hit_ws)
        ws_detail = "; ".join(f"{x['window']}日低点{x['low_threshold']:.2f}" for x in hit_ws)
        color = "#c0392b" if r["below_pct"] < 0 else "#1e8449"
        high_color = "#c0392b" if r["off_high_pct"] < 0 else "#1e8449"
        deep = r.get("deep") or {}

        def _fnum(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _market(v):
            fv = _fnum(v)
            return "—" if fv is None else f"{fv / 1e8:,.2f} 亿"

        def _num(v):
            fv = _fnum(v)
            return "—" if fv is None else f"{fv:.2f}"

        _cp = _fnum(deep.get("change_percent"))
        text_rows.append(
            f"{r['name']}({r['symbol']})  现价 {r['latest_close']:.2f} 元, 触 {ws_lab} 日低位; "
            f"历史最低 {r['prior_hist_low']:.2f}({r['prior_low_date']}), "
            f"历史最高 {r['prior_hist_high']:.2f}({r['prior_high_date']}), "
            f"区间最低相对历史最高 {r['off_high_pct']:+.2f}%, 较历史最低 {r['below_pct']:+.2f}%")
        text_rows.append(
            f"  估值: 总市值{_market(deep.get('total_market_cap'))}, "
            f"流通市值{_market(deep.get('float_market_cap'))}, "
            f"每股净资产={_num(deep.get('bvps'))}, "
            f"每股收益(TTM)={_num(deep.get('eps_ttm'))}, "
            f"动态PE={_num(deep.get('forward_pe'))}, "
            f"静态PE={_num(deep.get('static_pe'))}, "
            f"PE(TTM)={_num(deep.get('ttm_pe'))}, "
            f"PB={_num(deep.get('pb'))}, "
            f"涨跌幅={'—' if _cp is None else f'{_cp:+.2f}%'}")

        hit_ws_html = f"[{ws_detail}]" if ws_detail else ""
        kv_rows = "".join([
            _kv("代码", f"<b style='{color}'>{r['symbol']}</b>"),
            _kv("名称", r["name"]),
            _kv("现价（元）", f"{r['latest_close']:.2f}"),
            _kv("信号日期", str(r["latest_date"])),
            _kv("命中窗口", f"{ws_lab}日 {hit_ws_html}"),
            _kv("历史最低价（元）", f"{r['prior_hist_low']:.2f}"),
            _kv("历史最低日期", str(r["prior_low_date"])),
            _kv("历史最高价（元）", f"{r['prior_hist_high']:.2f}"),
            _kv("历史最高日期", str(r["prior_high_date"])),
            _kv("区间最低 相对 历史最高", f"{r['off_high_pct']:+.2f}%",
                value_color=f"font-weight:bold;{high_color}"),
            _kv("较历史最低", f"{r['below_pct']:+.2f}%", value_color=f"font-weight:bold;{color}"),
            _kv("涨跌幅（%）", "—" if _cp is None else f"{_cp:+.2f}%",
                value_color=f"font-weight:bold;{'#c0392b' if (_cp is not None and _cp < 0) else '#1e8449'}"),
            _kv("总市值", _market(deep.get("total_market_cap"))),
            _kv("流通市值", _market(deep.get("float_market_cap"))),
            _kv("每股净资产", _num(deep.get("bvps"))),
            _kv("每股收益(TTM)", _num(deep.get("eps_ttm"))),
            _kv("动态市盈率", _num(deep.get("forward_pe"))),
            _kv("静态市盈率", _num(deep.get("static_pe"))),
            _kv("市盈率(TTM)", _num(deep.get("ttm_pe"))),
            _kv("市净率", _num(deep.get("pb"))),
        ])
        cards.append(
            "<div style=\"border:1px solid #e2e2e2;border-radius:6px;margin:14px 0;overflow:hidden;\">"
            f"<div style=\"background:#2c3e50;color:#fff;padding:10px 14px;font-weight:bold;\">"
            f"⚠ {r['name']} <span style='font-weight:normal;font-size:12px;opacity:.85;'>({r['symbol']})</span></div>"
            f"<table style=\"width:100%;border-collapse:collapse;background:#fff;\"><tbody>{kv_rows}</tbody></table>"
            "</div>"
        )
        state[r["symbol"]] = {"low": round(r["latest_close"], 4), "date": r["latest_date"].isoformat()}

    html = (
        "<div style=\"font-family:'Microsoft YaHei',Arial,sans-serif;max-width:620px;margin:0 auto;color:#333;\">"
        "<div style=\"background:#c0392b;color:#fff;padding:14px 20px;border-radius:6px 6px 0 0;"
        "font-size:16px;font-weight:bold;\">⚠ 股票触及 " + lab + " 日低位"
        "<span style=\"font-weight:normal;font-size:12px;opacity:.85;margin-left:10px;\">"
        + stamp + "</span></div>"
        + "".join(cards)
        + "<p style=\"font-size:12px;color:#888;margin:6px 2px 0;\">"
        "前复权收盘价 · 历史低点 = 本次抓取区间内今日之前的最低收盘价 · 由 stock-monitor 自动推送</p>"
        "</div>"
    )
    # print("html:", html)
    # 发信用项目统一 notifier (app/alert/notifier/mail_sender_new.py)；
    # 第5参数是 MIME content_type, 正文为 HTML 必须传 "html"("163" 会导致 text/163 无法解析)
    MailNew('推送通知', subject, html, receiver, "html").send()
    return len(to_alert)


def run(stocks: list, receiver: str, interval: int = 0, state_path: str = None) -> None:
    """持续监测股票价格是否触底, 命中则邮件报警(阻塞轮询)。

    stocks     : 列表, 每个元素为 (symbol, windows_list)。windows_list 为该股
                 各自的新低观察窗口(交易日天数, 如 [250, 60]), 可每股不同。
    receiver   : 收件邮箱
    interval   : 轮询间隔秒, 0=只跑一次即退出
    state_path : 去重状态文件路径(默认 STATE_FILE)
    """
    state_path = state_path or STATE_FILE
    client = get_client()

    while True:
        state = load_state(state_path)
        rows = []
        for s, ws in stocks:
            r = check_low(client, s, ws)
            attempt = 0
            # 出现"数据不足(?)"可能是 ShareTop 限流/瞬时故障, 长停顿后多试几次
            while r["status"] == "insufficient" and attempt < INSUFFICIENT_RETRIES:
                attempt += 1
                time.sleep(RETRY_SLEEP)
                print(f"  {r.get('name', s)}({s}) 数据不足, 等待 {RETRY_SLEEP}s 后第 {attempt} 次重试")
                r = check_low(client, s, ws)
            rows.append(r)
            time.sleep(PAUSE)   # 每股之间停顿, 避免触发 ShareTop 访问频次限流
        for r in rows:
            hit_ws = [x for x in r["windows"] if x.get("hit")]
            if r["status"] == "insufficient":
                since = r.get("ihist", "?")
                print(f"  {r['name']}({r['symbol']}) 数据不足({since}至今), 各窗口跳过")
            elif r["status"] == "no":
                print(f"  {r['name']}({r['symbol']}) 现价 {r['latest_close']:.2f}, 未触任何窗口低位")
            else:
                lab = "/".join(f"{x['window']}日" for x in hit_ws)
                print(f"  {r['name']}({r['symbol']}) 现价 {r['latest_close']:.2f} 已触 {lab} 低位")

        n = notify_hits(rows, state, receiver)
        # save_state(state_path, state)   # 去重状态落盘, 保证跨进程也只在新低价时发信
        stamp = datetime.now().strftime("%H:%M:%S")
        if n:
            print(f"[{stamp}] 已发送 {n} 只报警邮件")
        else:
            print(f"[{stamp}] 无新报警")
        if not interval:
            break
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="创N日新低 邮箱报警(监测)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="股票代码, 多个英文逗号分隔, 如 600036.SH,600519.SH; 缺省读 watchlist.yaml")
    parser.add_argument("--windows", type=str, default=None,
                        help="全局兜底观察窗口(交易日天数), 逗号分隔; 未配置该股则用此值, 再缺省 1250")
    parser.add_argument("--to", type=str, default=os.environ.get("MAIL_ALERT_TO", ""),
                        help="收件邮箱, 或设置环境变量 MAIL_ALERT_TO")
    parser.add_argument("--interval", type=int, default=0,
                        help="轮询间隔秒, 0=只跑一次即退出")
    parser.add_argument("--state", type=str, default=STATE_FILE, help="去重状态文件路径")
    args = parser.parse_args()

    # 股票列表只读 watchlist.yaml(低点监测专用合并清单)，其次 --symbols 覆盖
    from app.config import load_config

    cfg = load_config()
    cli_symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    cli_windows = None
    if args.windows:
        cli_windows = sorted({int(x) for x in args.windows.split(",") if x.strip()})
    # 每股窗口独立: watchlist 该股 low_days/windows > --windows 兜底 > 默认 1250
    specs = cfg.low_alert_specs(cli_symbols or None, windows_fallback=cli_windows)
    if not specs:
        parser.error("watchlist.yaml 无股票且未指定 --symbols")

    if not args.to:
        parser.error("请用 --to 或环境变量 MAIL_ALERT_TO 指定收件邮箱")

    run(specs, args.to, interval=args.interval, state_path=args.state)


if __name__ == "__main__":
    main()