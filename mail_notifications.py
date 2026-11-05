"""SMTP notifications; secrets live in the current user's Windows credential store."""
from __future__ import annotations

from datetime import date, datetime
from email.message import EmailMessage
from email.utils import format_datetime, parseaddr
import hashlib
import json
import logging
from pathlib import Path
import smtplib
import ssl

LOG = logging.getLogger("workbuddy_daily")
NOTICE = "今日的workbuddyy积分已经领取"
TEST_NOTICE = "WorkBuddy 邮件通知配置测试。这是一封测试邮件，不代表今日积分已经领取。"


class MailConfigurationError(RuntimeError):
    pass


class MailSendError(RuntimeError):
    pass


def mail_settings(config):
    settings = config.get("email_notification", {})
    for key in ("sender", "recipient"):
        address = settings.get(key, "")
        if (not isinstance(address, str) or "\r" in address or "\n" in address
                or parseaddr(address)[1] != address
                or not address or address.count("@") != 1
                or not all(address.split("@"))):
            raise MailConfigurationError(f"A valid email {key} is required")
    if settings.get("smtp_host") != "smtp.qq.com" or settings.get("smtp_port") != 465:
        raise MailConfigurationError("This setup expects QQ SMTP over TLS: smtp.qq.com:465")
    if not settings["sender"].lower().endswith("@qq.com"):
        raise MailConfigurationError("Use the complete QQ sender email address")
    return settings


def credential_target(settings):
    return "WorkBuddyDailyAutomation/SMTP/" + settings["sender"].lower()


def read_authorization_code(settings):
    import win32cred
    try:
        saved = win32cred.CredRead(credential_target(settings), win32cred.CRED_TYPE_GENERIC)
        value = saved["CredentialBlob"]
        if isinstance(value, bytes):
            # pywin32 CredWrite expects text and CredRead returns UTF-16LE
            # bytes for that text. Keep UTF-8 compatibility for older stores.
            encoding = "utf-16-le" if b"\x00" in value else "utf-8"
            secret = value.decode(encoding)
        else:
            secret = value
        if (not isinstance(secret, str) or len(secret) != 16 or not secret.isascii()
                or not secret.isalnum()
                or saved.get("UserName", "").lower() != settings["sender"].lower()):
            raise ValueError("Invalid credential")
        return secret
    except Exception:
        # Never include raw credential errors or any credential blob in logs.
        raise MailConfigurationError("Run setup-email.cmd to save the QQ SMTP authorization code") from None


def open_authenticated_connection(settings, secret):
    connection = None
    try:
        connection = smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"],
                                      local_hostname="localhost", timeout=20,
                                      context=ssl.create_default_context())
        connection.login(settings["sender"], secret)
        return connection
    except smtplib.SMTPAuthenticationError as error:
        if connection is not None:
            connection.close()
        raise MailSendError(f"QQ SMTP 拒绝登录（SMTP {error.smtp_code}）。请确认授权码属于发件邮箱，且 SMTP 服务已开启。") from None
    except Exception as error:
        if connection is not None:
            connection.close()
        raise MailSendError(f"SMTP connection/authentication failed ({type(error).__name__})") from None


def send_message(settings, secret, body, subject, message_key):
    message = EmailMessage()
    message["From"] = settings["sender"]
    message["To"] = settings["recipient"]
    message["Subject"] = subject
    message["Date"] = format_datetime(datetime.now().astimezone())
    token = hashlib.sha256(message_key.encode("utf-8")).hexdigest()[:32]
    message["Message-ID"] = f"<workbuddy.{token}@qq.com>"
    message.set_content(body, charset="utf-8")
    connection = open_authenticated_connection(settings, secret)
    try:
        refused = connection.send_message(message, from_addr=settings["sender"],
                                          to_addrs=[settings["recipient"]])
        if refused:
            raise MailSendError("SMTP server refused the recipient")
    except MailSendError:
        raise
    except Exception as error:
        raise MailSendError(f"SMTP submission failed ({type(error).__name__})") from None
    finally:
        # A failed QUIT after SMTP accepted DATA must not turn success into a
        # retry. Close the socket without another SMTP command.
        try:
            connection.close()
        except OSError:
            pass


def notify_success(config, runtime: Path, day, result):
    if result not in {"claimed", "already_claimed"}:
        raise ValueError("Email requires a confirmed check-in result")
    date.fromisoformat(day)
    if day != date.today().isoformat():
        LOG.info("Skipping a stale check-in notification")
        return "stale"
    if not config.get("email_notification", {}).get("enabled", False):
        LOG.info("Email notification is not enabled; run setup-email.cmd")
        return "disabled"
    settings = mail_settings(config)
    identity = {"date": day, "recipient": settings["recipient"], "sender": settings["sender"],
                "account_menu_name": config["account_menu_name"], "exe": config["workbuddy_exe"]}
    marker = runtime / "mail-success.json"
    try:
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if isinstance(saved, dict) and all(saved.get(key) == value for key, value in identity.items()):
            return "already_sent"
    except (FileNotFoundError, ValueError):
        pass
    secret = read_authorization_code(settings)
    message_key = json.dumps(identity, sort_keys=True, ensure_ascii=False)
    send_message(settings, secret, NOTICE, "WorkBuddy 积分领取通知", message_key)
    runtime.mkdir(parents=True, exist_ok=True)
    identity["accepted_at"] = datetime.now().astimezone().isoformat()
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(marker)
    LOG.info("Daily notification accepted by SMTP server")
    return "sent"


def send_test(config):
    settings = mail_settings(config)
    secret = read_authorization_code(settings)
    send_message(settings, secret, TEST_NOTICE, "WorkBuddy 邮件通知测试",
                 "test:" + datetime.now().astimezone().isoformat())
