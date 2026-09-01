"""注册表、配置解析、规则判定、去重的离线测试（不发网络请求）。"""
from __future__ import annotations

from app.alert import price_rules as pr
from app.bootstrap import build_rules, build_strategies
from app.config import load_config
from app.core.datatypes import AlertEvent, Quote
from app.core.registry import ALERT_RULES, DATA_SOURCES, NOTIFIERS, STRATEGIES
from app.monitor.state import AlertState


def test_registries_have_expected_plugins():
    assert DATA_SOURCES.has("sharetop")
    assert STRATEGIES.has("ma_cross")
    assert STRATEGIES.has("rsi_oversold")
    assert ALERT_RULES.has("price_level")
    assert ALERT_RULES.has("change_pct")
    assert ALERT_RULES.has("ma_deviation")
    assert NOTIFIERS.has("email")
    assert NOTIFIERS.has("console")


def test_load_config_watchlist_not_empty():
    cfg = load_config()
    assert cfg.watch_symbols
    assert all("." in s for s in cfg.watch_symbols)


def test_build_strategies_and_rules():
    cfg = load_config()
    assert build_strategies(cfg)            # 至少一个启用策略
    rules = build_rules(cfg)
    assert rules and all(hasattr(r, "check") for r in rules)


def test_price_level_rule():
    r = pr.PriceLevelRule("价", compare="ge", target=10)
    q1 = Quote("600519.SH", last_price=10.5, prev_close=10.0)
    q2 = Quote("600519.SH", last_price=9.5, prev_close=10.0)
    assert r.check(q1) is not None
    assert r.check(q2) is None


def test_change_pct_rule():
    r = pr.ChangePctRule("涨跌", max_rise=5.0, max_fall=-5.0)
    up = Quote("600519.SH", last_price=10.5, prev_close=10.0)
    flat = Quote("600519.SH", last_price=10.4, prev_close=10.0)
    assert r.check(up) is not None
    assert r.check(flat) is None


def test_alert_state_dedup():
    st = AlertState(cooldown_seconds=100)
    ev = AlertEvent("600519.SH", name="x", rule_name="r")
    assert len(st.filter_new([ev])) == 1
    assert len(st.filter_new([ev])) == 0  # 冷却期内去重