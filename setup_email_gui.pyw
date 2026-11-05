"""Local-only authorization dialog. User enters the secret directly into Windows."""
import contextlib
import io
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

import setup_email


def main():
    root = tk.Tk()
    root.title("WorkBuddy 邮箱授权设置")
    root.geometry("560x350")
    root.minsize(520, 350)
    frame = ttk.Frame(root, padding=22)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="在本机配置 QQ 邮箱通知", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
    config = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8-sig"))
    settings = setup_email.mail_settings(config)
    ttk.Label(frame, text=f"发件邮箱：{settings['sender']}\n收件邮箱：{settings['recipient']}").pack(anchor="w", pady=(12, 10))
    ttk.Label(frame, text="输入官方生成的 16 位 SMTP 授权码（不是 QQ 登录密码）：").pack(anchor="w")
    entry = ttk.Entry(frame, show="*", font=("Segoe UI", 12))
    entry.pack(fill="x", pady=(7, 12))
    status = tk.StringVar(value="可粘贴授权码。验证成功后会保存到 Windows 凭据管理器，\n并补发今天已领取的通知。")
    ttk.Label(frame, textvariable=status, wraplength=510, justify="left").pack(anchor="w", pady=(0, 10))
    events = queue.Queue()
    busy = False

    def run(secret):
        configured = False
        output = io.StringIO()
        try:
            current = setup_email.configure_authorization(secret)
            configured = True
            with contextlib.redirect_stdout(output):
                setup_email.notify_confirmed_today(current)
            events.put((True, "邮箱授权已保存。\n" + output.getvalue().strip()))
        except Exception as error:
            setup_email.record_setup_failure(error)
            prefix = "授权已保存，但补发未完成：\n" if configured else "配置未完成：\n"
            events.put((False, prefix + setup_email.setup_error_message(error)))
        finally:
            secret = None

    def submit(event=None):
        nonlocal busy
        if busy:
            return
        secret = entry.get()
        entry.delete(0, "end")
        busy = True
        button.configure(state="disabled")
        status.set("正在验证并保存授权，请稍候。结果会留在这个窗口里。")
        threading.Thread(target=run, args=(secret,), daemon=True).start()

    def poll():
        nonlocal busy
        try:
            success, message = events.get_nowait()
            status.set(message)
            busy = False
            button.configure(state="normal", text="重新配置" if success else "重试")
        except queue.Empty:
            pass
        root.after(150, poll)

    button = ttk.Button(frame, text="保存授权并补发今日通知", command=submit)
    button.pack(anchor="w")
    entry.bind("<Return>", submit)
    entry.focus_set()
    root.after(150, poll)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        setup_email.record_setup_failure(error)
        from tkinter import messagebox
        messagebox.showerror("WorkBuddy 邮箱配置失败", setup_email.setup_error_message(error))
