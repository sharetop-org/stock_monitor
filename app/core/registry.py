"""轻量插件注册表。

用简单的 类注册表(name -> class) 把「实现类」与「配置里的字符串名字」解耦，
做到新增扩展只需在当前包注册，即可被 YAML 配置引用。
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, Generic, Optional, Type, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class Registry(Generic[T]):
    """按名字注册/获取实现类，name 大小写不敏感以容忍手写配置。"""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: Dict[str, Type[T]] = {}

    def register(self, name: str) -> Callable[[Type[T]], Type[T]]:
        """装饰器；用 `@registry.register("name")` 标注实现类。"""

        def deco(cls: Type[T]) -> Type[T]:
            key = self._normalize(name)
            if key in self._items:
                log.warning("注册表[%s]中 %r 被重复注册，后者覆盖前者", self._kind, name)
            self._items[key] = cls
            return cls

        return deco

    def get(self, name: str) -> Type[T]:
        key = self._normalize(name)
        if key not in self._items:
            raise KeyError(
                f"{self._kind} 实现 '{name}' 未注册。可用实现: {sorted(self._items)}"
            )
        return self._items[key]

    def get_or_none(self, name: str) -> Optional[Type[T]]:
        return self._items.get(self._normalize(name))

    def has(self, name: str) -> bool:
        return self._normalize(name) in self._items

    def names(self) -> list:
        return sorted(self._items)

    @staticmethod
    def _normalize(name: str) -> str:
        return name.strip().lower() if isinstance(name, str) else name


# ------------------------------------------------------------------ 各领域注册表
# 注意：这里不能 import 各 base 类，否则形成「strategy→registry→strategy」的循环导入。
# 各领域实现只需导入本模块的注册表单例并注册自己；类型信息由子类自身保证。
DATA_SOURCES: Registry = Registry("数据源")
STRATEGIES: Registry = Registry("策略")
ALERT_RULES: Registry = Registry("预警规则")
NOTIFIERS: Registry = Registry("通知器")