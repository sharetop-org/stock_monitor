"""通知器集合。

新增渠道：继承 BaseNotifier，装饰 @NOTIFIERS.register("名字")，
然后在 config/settings.yaml 的 notify.channels 里启用。
"""
from __future__ import annotations

from . import console, email  # noqa: F401  触发注册