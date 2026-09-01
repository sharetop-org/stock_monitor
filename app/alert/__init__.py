"""预警层：规则引擎 + 通知器。

新增规则：继承 BaseAlertRule 实现 `check(quote, ctx)` 并 @ALERT_RULES.register("类型")，
在 config/alerts.yaml 注册；
新增通知渠道：继承 BaseNotifier 实现 `send(event)` 并 @BASE_NOTIFIER.register("名字")，
在 config/settings.yaml 的 notify.channels 里启用。
"""
from __future__ import annotations

from .base import BaseAlertRule, BaseNotifier
from .rule_engine import AlertRuleEngine
from . import price_rules  # noqa: F401 触发规则注册
from .notifier import console, email  # noqa: F401 触发通知器注册

__all__ = ["BaseAlertRule", "BaseNotifier", "AlertRuleEngine"]