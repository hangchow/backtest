from __future__ import annotations

from email.message import EmailMessage
import os
import smtplib

from ..config import EmailNotificationConfig


def send_email_notification(config: EmailNotificationConfig, *, subject: str, body: str) -> None:
    """通过标准 SMTP 发送一封纯文本提醒邮件。"""
    if not config.enabled:
        return
    assert config.smtp_host is not None
    assert config.from_address is not None
    if not config.to_addresses:
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = ", ".join(config.to_addresses)
    message.set_content(body)

    password = os.environ.get(config.password_env, "") if config.password_env else ""
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        if config.use_tls:
            smtp.starttls()
            smtp.ehlo()
        if config.username:
            smtp.login(config.username, password)
        smtp.send_message(message)
