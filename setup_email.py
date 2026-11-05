"""Interactive local configuration. Never pass an authorization code on the command line."""
import argparse
from datetime import date
from getpass import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

from mail_notifications import (MailConfigurationError, MailSendError, credential_target,
                                mail_settings, open_authenticated_connection, send_test)

BASE = Path(__file__).resolve().parent


def notify_confirmed_today(config):
    from workbuddy_checkin import load_confirmed_success
    runtime = Path(os.path.expandvars(config["runtime_directory"]))
    exe = Path(os.path.expandvars(config["workbuddy_exe"]))
    if load_confirmed_success(config, exe, runtime, date.today().isoformat()) is None:
        print("未找到今天已领取的确认记录；下次脚本确认领取后会发送通知。")
        return
    # The standard runner supplies the same single-instance lock and daily email
    # deduplication as the scheduled task, without any desktop automation.
    try:
        result = subprocess.run([sys.executable, str(BASE / "workbuddy_checkin.py"), "--notify-only"],
                                capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        print("授权已保存，但今日补发未能完成。请运行 notify-now.cmd 重试。")
        return
    if result.returncode == 0:
        print("已执行今天的领取通知补发，请检查收件箱；当天已发送过则会跳过。")
    else:
        print("授权已保存，但今日通知补发失败。请查看 checkin.log，并运行 notify-now.cmd 重试。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="Send a clearly marked configuration test email")
    args = parser.parse_args()
    config_file = BASE / "config.json"
    config = json.loads(config_file.read_text(encoding="utf-8-sig"))
    settings = mail_settings(config)
    if args.test:
        send_test(config)
        print("测试邮件已提交，请检查收件箱或垃圾邮件。它不会占用当天的领取通知记录。")
        return 0
    print("WorkBuddy 邮件通知设置（仅在本机输入授权码）")
    print(f"发件邮箱：{settings['sender']}")
    print(f"收件邮箱：{settings['recipient']}")
    print("请先按 QQ 邮箱官方帮助开启 SMTP 并获取授权码：")
    print("https://help.mail.qq.com/detail/0/1087")
    print("请不要输入 QQ 登录密码。授权码不会写入配置文件或显示出来。")
    # Refuse getpass's echoing fallback if this is not a real interactive console.
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=__import__("getpass").GetPassWarning)
        secret = getpass("请输入 QQ 邮箱授权码，输入后按回车：").replace(" ", "").strip()
    if not secret or len(secret) != 16 or not secret.isascii() or not secret.isalnum():
        raise MailConfigurationError("需要 16 位 QQ 邮箱授权码，请重新运行设置")
    # Check SMTP login before persisting the secret or enabling notifications.
    connection = open_authenticated_connection(settings, secret)
    connection.close()
    # Preserve unrelated settings edited while the authorization prompt was open.
    current = json.loads(config_file.read_text(encoding="utf-8-sig"))
    latest = mail_settings(current)
    if any(latest[key] != settings[key] for key in ("sender", "recipient", "smtp_host", "smtp_port")):
        raise MailConfigurationError("邮箱配置在输入期间被修改；请重新运行设置")
    import win32cred
    win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC,
                         "TargetName": credential_target(settings),
                         "UserName": settings["sender"],
                         "CredentialBlob": secret.encode("utf-8"),
                         "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                         "Comment": "WorkBuddy daily check-in SMTP authorization"}, 0)
    latest["enabled"] = True
    current["email_notification"] = latest
    temporary = config_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_file)
    print("设置完成。授权码已保存在当前 Windows 用户的凭据管理器中。")
    notify_confirmed_today(current)
    print("日常领取脚本将继续发送通知；可双击 test-email.cmd 单独测试邮件。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (MailConfigurationError, MailSendError) as error:
        print(str(error))
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("已取消。")
        sys.exit(1)
    except Exception as error:
        print(f"设置失败（{type(error).__name__}），请检查本机运行环境后重试。")
        sys.exit(1)
