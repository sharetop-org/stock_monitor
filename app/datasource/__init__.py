"""数据源：抽象层 + ShareTop 实现。

新增数据源：在包内新建模块，实现 `BaseDataSource` 并用
`@DATA_SOURCES.register("名字")` 标注，然后在 config/settings.yaml 的 data_source.name 切换到它。
"""
from __future__ import annotations

from .base import BaseDataSource
from . import sharetop_source  # noqa: F401  触发注册

__all__ = ["BaseDataSource"]