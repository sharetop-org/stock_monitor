"""全局配置加载与校验（YAML + .env）。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

log = logging.getLogger(__name__)

# 默认项目根 = 本项目目录的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


@dataclass
class AppConfig:
    settings: Dict[str, Any] = field(default_factory=dict)
    symbols: List[str] = field(default_factory=list)
    stocks: List[Dict[str, Any]] = field(default_factory=list)
    strategy_specs: List[Dict[str, Any]] = field(default_factory=list)
    stock_strategy_map: Dict[str, List[str]] = field(default_factory=dict)
    alert_specs: List[Dict[str, Any]] = field(default_factory=list)
    per_stock_alerts: List[Dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------ 便捷访问
    @property
    def watch_symbols(self) -> List[str]:
        return self.symbols or [s.get("ts_code") for s in self.stocks if s.get("ts_code")]

    def data_source_config(self) -> Dict[str, Any]:
        return self.settings.get("data_source", {})

    def monitor_config(self) -> Dict[str, Any]:
        return self.settings.get("monitor", {})

    def backtest_config(self) -> Dict[str, Any]:
        return self.settings.get("backtest", {})

    def notify_config(self) -> Dict[str, Any]:
        return self.settings.get("notify", {})


def load_config(config_dir: Optional[Path] = None) -> AppConfig:
    """加载 .env 以及 config/*.yaml 并做基本校验。"""
    config_dir = config_dir or CONFIG_DIR
    # .env 在项目根
    load_dotenv(PROJECT_ROOT / ".env")

    cfg = AppConfig()

    cfg.settings = _read_yaml(config_dir / "settings.yaml") or {}
    watch = _read_yaml(config_dir / "watchlist.yaml") or {}
    cfg.symbols = [s for s in watch.get("symbols", []) if s]
    cfg.stocks = watch.get("stocks", [])
    if not cfg.symbols:
        cfg.symbols = [s.get("ts_code") for s in cfg.stocks if s.get("ts_code")]

    strat = _read_yaml(config_dir / "strategies.yaml") or {}
    cfg.strategy_specs = strat.get("strategies", [])
    for smap in strat.get("stock_strategies", []) or []:
        if smap.get("ts_code"):
            cfg.stock_strategy_map[smap["ts_code"]] = smap.get("strategies", [])

    alerts = _read_yaml(config_dir / "alerts.yaml") or {}
    cfg.alert_specs = alerts.get("rules", [])
    cfg.per_stock_alerts = alerts.get("per_stock_rules", []) or []

    _validate(cfg)
    return cfg


def _validate(cfg: AppConfig) -> None:
    if not cfg.settings:
        log.warning("settings.yaml 为空")
    if not cfg.watch_symbols:
        log.warning("自选股为空（watchlist.yaml）")


def _read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        log.warning("配置文件不存在: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"解析配置失败 {path}: {exc}") from exc