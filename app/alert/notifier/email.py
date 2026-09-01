"""邮件通知器（SMTP）。

配置从环境变量(.env)或构造函数读取：
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    SMTP_USE_SSL, EMAIL_FROM, EMAIL_TO
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Dict, Union

from ...core.registry import NOTIFIERS
from ..base import BaseNotifier

log = logging.getLogger(__name__)


@NOTIFIERS.register("email")
class EmailNotifier(BaseNotifier):
    name = "email"

    def __init__(self, level: str = "info", **cfg: Any) -> None:
        self.level = level
        self.enabled = True
        self.host = cfg.get("host") or os.getenv("SMTP_HOST", "")
        self.port = int(cfg.get("port") or os.getenv("SMTP_PORT", "465"))
        self.user = cfg.get("user") or os.getenv("SMTP_USER", "")
        self.password = cfg.get("password") or os.getenv("SMTP_PASSWORD", "")
        self.use_ssl = str(cfg.get("use_ssl", os.getenv("SMTP_USE_SSL", "true"))).lower() in ("1", "true", "yes")
        self.from_addr = cfg.get("from_addr") or os.getenv("EMAIL_FROM", "")
        self.to_addrs = cfg.get("to_addrs") or _split(os.getenv("EMAIL_TO", ""))
        if not (self.host and self.user and self.to_addrs):
            log.warning("邮件通知器配置不完整，将被禁用（检查 SMTP_HOST/USER/EMAIL_TO）")
            self.enabled = False

    def send(self, events) -> None:
        if not self.enabled:
            log.info("邮件未启用，跳过发送 %d 条预警", len(events) if isinstance(events, list) else 1)
            return
        evs = events if isinstance(events, list) else [events]
        body = self.format_lines(evs)
        subject = f"【stock-monitor 预警】{len(evs)} 条新预警"
        try:
            self._deliver(subject, body)
            log.info("已发送邮件通知（%d 条预警）至 %s", len(evs), self.to_addrs)
        except Exception as exc:  # noqa: BLE001
            log.error("邮件发送失败: %s\n%s", exc, body)

    def _deliver(self, subject: str, body: str) -> None:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = formataddr(("stock-monitor", self.from_addr))
        msg["To"] = ", ".join(self.to_addrs)
        msg["Subject"] = Header(subject, "utf-8")
        if self.use_ssl:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as s:
                s.login(self.user, self.password)
                s.sendmail(self.from_addr, self.to_addrs, msg.as_string())
        else:
            with smtplib.SMTP(self.host, self.port, timeout=15) as s:
                s.starttls()
                s.login(self.user, self.password)
                s.sendmail(self.from_addr, self.to_addrs, msg.as_string())


def _split(v: str) -> list:
    return [x.strip() for x in (v or "").split(",") if x.strip()]