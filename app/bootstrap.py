"""依赖组装（构建器模式）：把配置 + 注册表组装成可运行的组件。"""
from __future__ import annotations

import logging
from typing import List

# 触发各扩展包 __init__，从而完成具体实现的自动注册（装饰器副作用）
from . import alert, datasource, strategy  # noqa: F401

from .config import AppConfig, load_config
from .core.registry import ALERT_RULES, DATA_SOURCES, NOTIFIERS, STRATEGIES
from .datasource.base import BaseDataSource
from .strategy.base import BaseStrategy


def build_datasource(cfg: AppConfig) -> BaseDataSource:
    ds = cfg.data_source_config()
    name = ds.get("name", "sharetop")
    cls = DATA_SOURCES.get(name)
    kwargs = {
        "token": None,  # 由数据源自身从环境变量读取
        "timeout": float(ds.get("request_timeout", 30)),
        "cache_dir": ds.get("cache_dir"),
    }
    return cls(**{k: v for k, v in kwargs.items() if v is not None})


def build_strategies(cfg: AppConfig) -> List[BaseStrategy]:
    specs = [s for s in cfg.strategy_specs if s.get("enabled", True)]
    out: List[BaseStrategy] = []
    for spec in specs:
        name = spec.get("name")
        cls = STRATEGIES.get(name)
        params = spec.get("params", {}) or {}
        out.append(cls(**params))  # 实例自动带 name 属性
    return out


def build_rules(cfg: AppConfig):
    """返回 (全局规则, 每股票规则)。均在监控引擎处以全局方式评估。"""
    from .alert.base import BaseAlertRule
    rules: List[BaseAlertRule] = []
    for spec in cfg.alert_specs:
        if not spec.get("enabled", True):
            continue
        cls = ALERT_RULES.get(spec["type"])
        rules.append(cls(spec.get("name", spec["type"]), **(spec.get("params", {}) or {})))
    # per_stock 规则：扩展点，当前合并进全局（按 name 去重可后续实现）
    for entry in cfg.per_stock_alerts or []:
        for spec in entry.get("rules", []) or []:
            cls = ALERT_RULES.get(spec["type"])
            rules.append(cls(f"{entry.get('ts_code')}:{spec.get('name', spec['type'])}",
                             **(spec.get("params", {}) or {})))
    return rules


def build_notifiers(cfg: AppConfig) -> List:
    ncfg = cfg.notify_config()
    if not ncfg.get("enabled", False):
        return []
    notifiers = []
    for ch in ncfg.get("channels", []) or []:
        cls = NOTIFIERS.get(ch["name"])
        inst = cls(**{k: v for k, v in ch.items() if k != "name"})
        notifiers.append(inst)
    return notifiers


def build_monitor_engine(cfg: AppConfig):
    from .monitor.engine import MonitorEngine

    return MonitorEngine(
        build_datasource(cfg),
        cfg.watch_symbols,
        strategies=build_strategies(cfg),
        alert_rules=build_rules(cfg),
        notifiers=build_notifiers(cfg),
        settings=cfg.settings,
    )


def build_backtest_engine(cfg: AppConfig):
    from .backtest.engine import BacktestEngine
    return BacktestEngine(build_datasource(cfg), cfg.backtest_config())