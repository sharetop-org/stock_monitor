#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全市场「过去N个交易日新低买入」回测扫描 —— 统计盈利占比。

流程:
  1. 用 ShareTop `universes.get(list_status='L')` 拉取全部"正常上市"股票列表;
  2. 过滤出指定年份(默认 2008)之前上市的股票(list_date 年份 < 阈值);
  3. 对每只股票复用 days_backtest.backtest() 做「新低买入」回测;
  4. 统计「获利金额 / 总收益率 / 复合年化收益率 同时>0」的股票数占总数比例。

⚠️ 性能提示: 逐只回测会为每只股票各拉一次约 6 万根日K(前复权+不复权)，对上千只股票
   会带来大量 ShareTop 请求并可能触发限流。建议先用 --limit 小批试跑，再分批/后台跑全量。

用法样例:
    python -m app.cli screen-backtest --limit 20 --low-days 1250
"""
from __future__ import annotations

import time
from typing import List, Optional

import pandas as pd

# 数据源统一工厂 + 复用的单股回测
from app.datasource.sharetop_source import get_share_client as get_client
from app.strategy.days_backtest import backtest, to_aligned_table


# 每股之间的停顿秒数, 降低 ShareTop 访问频次限流
PAUSE = 0.2
# 每股回测失败(网络/限流)时的最大重试次数与停顿秒数
RETRIES = 2
RETRY_SLEEP = 5.0


def fetch_pre_year_list(client, pre_2008_year: int = 2008) -> pd.DataFrame:
    """取全部正常上市 A 股并过滤出 `pre_2008_year` 之前上市的股票。

    universes.get() 返回名单, list_date 形如 "YYYYMMDD"。返回含
    ts_code/name/list_date/list_year 的 DataFrame(已按上市年份升序)。
    """
    uni = client.universes.get(list_status="L", as_df=True)
    if not isinstance(uni, pd.DataFrame) or uni.empty:
        raise RuntimeError("获取股票列表失败或为空(检查 ShareTop 权限)")
    if "list_date" not in uni.columns:
        raise RuntimeError("股票列表缺少 list_date 字段,无法判断上市日期")

    uni = uni.copy()
    uni["list_date"] = pd.to_numeric(uni["list_date"], errors="coerce")
    uni = uni.dropna(subset=["list_date"]).astype({"list_date": "int64"})
    uni["list_year"] = uni["list_date"] // 10000
    uni = uni[uni["list_year"] < int(pre_2008_year)]
    return uni.reset_index(drop=True)


def _run_one(client, symbol: str, name: str, list_year: int,
             low_days: int, buy_amount: float, high_days: Optional[int]) -> dict:
    """对单只股票运行回测, 提取汇总字段; 失败按 RETRIES 重试, 仍失败返回含 err 的记录。"""
    for attempt in range(RETRIES + 1):
        try:
            r = backtest(client, symbol, low_days=low_days,
                         buy_amount=buy_amount, high_days=high_days)
            return {
                "symbol": symbol, "name": name, "list_year": list_year,
                "ihist": r["ihist"], "buys": int(r["buys"]),
                "invested": float(r["invested"]), "div": float(r["div"]),
                "assets": float(r["assets"]), "profit": float(r["profit"]),
                "ret": float(r["ret"]), "annual": (r["annual"] or None),
                "win_rate": float(r["win_rate"]), "pl_ratio": r["pl_ratio"],
                "max_drawdown": float(r["max_drawdown"]),
                "n_trades": int(r["n_trades"]),
            }
        except Exception as exc:  # noqa: BLE001
            if attempt < RETRIES:
                time.sleep(RETRY_SLEEP)
                continue
            return {"symbol": symbol, "name": name, "list_year": list_year,
                    "err": repr(exc)[:200]}
    return {"symbol": symbol, "name": name, "list_year": list_year, "err": "unknown"}


def _summarise(df: pd.DataFrame, total: int, failed: int) -> dict:
    """按「获利金额/净收益率/复合年化 均>0」统计盈利占比, 返回 dict 汇总。"""
    if df is None or df.empty:
        return {"total": total, "ok": 0, "failed": failed, "profit": 0, "ret": 0,
                "annual": 0, "all3": 0, "all3_pct": 0.0}
    d = df
    ok = len(d)
    p = float((d["profit"] > 0).sum())
    r = float((d["ret"] > 0).sum())
    a = float((d["annual"].fillna(-1) > 0).sum())
    all3 = float(((d["profit"] > 0) & (d["ret"] > 0)
                  & (d["annual"].fillna(-1) > 0)).sum())
    return {
        "total": total, "ok": ok, "failed": failed,
        "profit": int(p), "ret": int(r), "annual": int(a),
        "all3": int(all3),
        "all3_pct": (all3 / ok * 100) if ok else 0.0,
    }


# 导出 Excel 时的列与取值口径（按需求给定表头）
EXPORT_COLS = ["symbol", "name", "list_year", "利润(万)", "总收益%", "复合年化%", "胜率%"]


def _export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """把逐股汇总构造成符合导出表头的 DataFrame（默认不导出，传 export_path 才落盘）。"""
    out = pd.DataFrame({
        "symbol": df["symbol"],
        "name": df["name"],
        "list_year": df["list_year"],
        "利润(万)": (df["profit"] / 1e4).round(2),
        "总收益%": (df["ret"] * 100).round(2),
        "复合年化%": (df["annual"] * 100).round(2),
        "胜率%": (df["win_rate"] * 100).round(2),
    })
    return out[EXPORT_COLS]


def export_excel(df: pd.DataFrame, path: str) -> str:
    """把逐股结果写入 Excel 文件，返回写入路径。表头见 EXPORT_COLS。"""
    if df is None or df.empty:
        raise ValueError(f"没有可导出的回测结果, 未写入 {path}")
    frame = _export_frame(df)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="回测结果")
        # 简单加宽首列, 便于查看
        ws = writer.sheets["回测结果"]
        for col, width in zip("ABCDEFG", (12, 12, 8, 10, 10, 10, 8)):
            ws.column_dimensions[col].width = width
    return path


def run_all(low_days: int = 1250, buy_amount: float = 10000.0,
            high_days: Optional[int] = None, pre_2008_year: int = 2008,
            limit: Optional[int] = None,
            export_path: Optional[str] = None) -> pd.DataFrame:
    """扫描早于 pre_2008_year 上市的股票, 打印盈利统计, 返回盈利汇总 DataFrame。

    export_path: 非空时把逐股结果（列: symbol/name/list_year/利润(万)/总收益%/
                 复合年化%/胜率%）写入该 Excel；默认 None = 不保存。
    """
    client = get_client()
    try:
        eligible = fetch_pre_year_list(client, pre_2008_year)
        if limit:
            eligible = eligible.head(int(limit)).reset_index(drop=True)

        total = len(eligible)
        print(f"\n=== 全市场新低买入回测扫描 ===")
        print(f"2008 年前上市的股票数: {total}"
              + (f"（本次仅扫描前 {int(limit)} 只）" if limit else ""))

        rows: List[dict] = []
        ok = 0
        for i, row in enumerate(eligible.itertuples(index=False)):
            sym = row.ts_code
            rec = _run_one(client, sym, row.name, int(row.list_year),
                           low_days=low_days, buy_amount=buy_amount,
                           high_days=high_days)
            if "err" in rec:
                print(f"  [{i+1}/{total}] {sym} 回测失败/跳过: {rec['err']}", flush=True)
                time.sleep(0.4)
            else:
                ok += 1
            rows.append(rec)
            if (i + 1) % 50 == 0 or i + 1 == total:
                print(f"  进度: {i+1}/{total}（成功 {ok}）", flush=True)
            time.sleep(PAUSE)

        df = pd.DataFrame([r for r in rows if "err" not in r])
        s = _summarise(df, total, failed=total - ok)
        _emit_summary(df, s)
        if export_path:
            p = export_excel(df, export_path)
            print(f"\n已保存逐股结果到 Excel: {p} "
                  f"（表头: symbol / name / list_year / 利润(万) / 总收益% / 复合年化% / 胜率%）")
        return df
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def _emit_summary(df: pd.DataFrame, s: dict) -> None:
    """打印盈利占比与分年上市分布 + 逐股排行。"""
    print("\n====== 三盈占比（获利 / 总收益 / 复合年化 都>0）======")
    summary = pd.DataFrame({
        "指标": ["扫描股票总数", "回测成功数", "失败数",
                "获利金额>0", "总收益率>0", "复合年化>0",
                "三者都>0（核心）", "占比（三者都>0 / 成功数）"],
        "数值": [s["total"], s["ok"], s["failed"],
                s["profit"], s["ret"], s["annual"],
                f"{s['all3']} 只", f"{s['all3_pct']:.2f}%"],
    })
    print(to_aligned_table(summary))

    if df.empty:
        return
    agg = df.groupby("list_year").agg(
        n=("symbol", "size"),
        win=("win_rate", "mean"),
        annual=("annual", "mean"),
    ).round({"win": 1, "annual": 2})
    print("\n按上市年份分布（数量 / 复胜率% / 平均复合年化%）:")
    print(to_aligned_table(agg.reset_index()))

    # 按获利金额由高到低展示前 20（供进一步观察）
    top = df.sort_values("profit", ascending=False).head(20).copy()
    top.columns = top.columns.astype(str)
    top["利润(万)"] = (top["profit"] / 1e4).round(2)
    top["总收益%"] = (top["ret"] * 100).round(1)
    top["复合年化%"] = (top["annual"] * 100).round(2)
    top["胜率%"] = (top["win_rate"] * 100).round(1)
    print("\n获利金额 TOP20（按利润降序）:")
    print(to_aligned_table(top[["symbol", "name", "list_year", "利润(万)",
                                "总收益%", "复合年化%", "胜率%"]].head(20)))
    # 展示亏损三指标都小于等于0的例样本量
    neg = df[(df["profit"] <= 0) & (df["ret"] <= 0)].shape[0]
    print(f"\n注: 获利金额<=0 且 总收益率<=0 的股票共 {neg} 只。")