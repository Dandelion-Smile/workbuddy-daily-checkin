"""WorkBuddy daily reward. Windows interactive desktop, Python 3.10+.

Only the account menu's Buddy Refuel card is actionable. Optional email uses
the user's configured SMTP authorization code from Windows Credential Manager.
No WorkBuddy tokens, hard-coded screen coordinates, or chat input are used.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from mail_notifications import mail_settings, notify_success

BASE = Path(__file__).resolve().parent
LOG = logging.getLogger("workbuddy_daily")


def normalized(text):
    return re.sub(r"\s+", "", text or "")


def load_config():
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8-sig"))
    exe = Path(os.path.expandvars(config["workbuddy_exe"]))
    if not exe.is_file() or exe.name.lower() != "workbuddy.exe":
        raise RuntimeError("WorkBuddy executable missing; update config.json")
    if not config.get("account_menu_name"):
        raise RuntimeError("account_menu_name is required")
    return config, exe


def configure_logging(runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(runtime / "checkin.log", maxBytes=500_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)


def desktop_unlocked():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
    user32.SwitchDesktop.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    handle = user32.OpenInputDesktop(0, False, 0x0100)
    if not handle:
        return False
    try:
        return bool(user32.SwitchDesktop(handle))
    finally:
        user32.CloseDesktop(handle)


def process_executable(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buf))
        if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(length)):
            return os.path.normcase(buf.value)
        return ""
    finally:
        kernel.CloseHandle(handle)


def unique(items, description):
    if len(items) != 1:
        raise RuntimeError(f"Expected one {description}; found {len(items)}")
    return items[0]


def find_window(exe):
    from pywinauto import Desktop
    expected = os.path.normcase(str(exe.resolve()))
    matches = [w for w in Desktop(backend="uia").windows(title="WorkBuddy", visible_only=False)
               if process_executable(w.process_id()) == expected]
    if len(matches) > 1:
        raise RuntimeError("Multiple WorkBuddy windows; manual review required")
    return matches[0] if matches else None


def workbuddy_running(exe):
    import win32process
    expected = os.path.normcase(str(exe.resolve()))
    return any(process_executable(pid) == expected
               for pid in win32process.EnumProcesses() if pid)


def get_or_launch_window(exe, timeout=60):
    # Starting another copy is not a harmless way to activate this Electron app:
    # its startup/repair code may run before the single-instance check.
    window = find_window(exe)
    if window is not None:
        LOG.info("Using the existing WorkBuddy window; no process launched")
        return window
    if workbuddy_running(exe):
        raise RuntimeError("WorkBuddy is already running without a usable window; open it manually. No second copy started")
    LOG.info("WorkBuddy is not running; launching once")
    subprocess.Popen([str(exe)], cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window = find_window(exe)
        if window is not None:
            return window
        time.sleep(1)
    raise RuntimeError("No WorkBuddy window after startup; no additional copy started")


def focus_window(window):
    import win32con
    import win32gui
    # Electron's top-level Pane may not expose the UIA Window pattern. Restore
    # by native handle instead of relying on that optional pattern.
    if win32gui.IsIconic(window.handle):
        win32gui.ShowWindow(window.handle, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(window.handle)
    except Exception:
        window.set_focus()


def profile_controls(window, config):
    return [m for m in window.descendants(control_type="MenuItem")
            if m.element_info.name == config["account_menu_name"]
            and m.is_visible() and m.is_enabled()]


def wait_account_ready(window, config, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        card = account_card(window, config)
        profiles = profile_controls(window, config) if card is None else []
        if card is not None or profiles:
            return card, profiles
        time.sleep(0.75)
    raise RuntimeError("WorkBuddy interface is blank, repairing or not ready; stopped without clicking or restarting it")


def account_card(window, config):
    menus = [m for m in window.descendants(control_type="Menu")
             if m.element_info.name == config["account_menu_name"] and m.is_visible()]
    if not menus:
        return None
    menu = unique(menus, "account menu")
    names = {normalized(c.element_info.name) for c in menu.descendants()}
    if not names.intersection({"Buddy加油站", "BuddyRefuel"}):
        return None
    return menu


def visible_buttons(menu):
    return [b for b in menu.descendants(control_type="Button") if b.is_visible()]


def claimed(menu):
    statuses = {"今日已领", "今日已领取", "Claimedtoday", "Alreadyclaimedtoday"}
    for button in visible_buttons(menu):
        label = normalized(button.element_info.name)
        if label in statuses or re.fullmatch(r"\+\d+(?:\.\d+)?[✓✔]", label):
            return True
    return False


def activate_control(control):
    # Resolve the supported pattern before invoking. Do not click again if an
    # invocation raises after it may have reached the application.
    from pywinauto.uia_defines import NoPatternInterfaceError
    if not desktop_unlocked():
        raise RuntimeError("Desktop locked before action")
    try:
        invoke = control.iface_invoke
    except NoPatternInterfaceError:
        # Fallback derives the click point from this specific live control.
        control.click_input()
    else:
        invoke.Invoke()


def wait_card(window, config, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        card = account_card(window, config)
        if card is not None:
            return card
        time.sleep(0.5)
    return None


def perform_checkin(config, exe):
    if not desktop_unlocked():
        raise RuntimeError("Desktop locked or no interactive desktop; waiting for unlock")
    window = get_or_launch_window(exe)
    focus_window(window)
    card, profiles = wait_account_ready(window, config)
    if card is None:
        activate_control(unique(profiles, "account menu trigger (login may be expired)"))
        card = wait_card(window, config, 15)
    if card is None:
        raise RuntimeError("Buddy Refuel card unavailable; login, event or UI may have changed")
    if claimed(card):
        return "already_claimed"
    allowed = {normalized(label) for label in config["claim_button_labels"]}
    candidates = [b for b in visible_buttons(card)
                  if b.is_enabled() and normalized(b.element_info.name) in allowed]
    button = unique(candidates, "enabled daily claim button")
    LOG.info("Claiming the daily reward")
    try:
        activate_control(button)
    except Exception:
        # A transport/UI error can happen after a successful invocation.
        # Reobserve success below instead of repeating an uncertain click.
        LOG.warning("Claim action outcome uncertain; verifying without a second click")
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if not desktop_unlocked():
            raise RuntimeError("Desktop locked while verifying the reward")
        current = account_card(window, config)
        if current is not None and claimed(current):
            return "claimed"
        time.sleep(0.75)
    raise RuntimeError("Claim was attempted but success was not confirmed; retry later")


def load_confirmed_success(config, exe, runtime, day):
    """Read a check-in confirmed today for this exact account and installation."""
    try:
        last = json.loads((runtime / "last-success.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if (isinstance(last, dict) and last.get("date") == day
            and last.get("status") in {"claimed", "already_claimed"}
            and last.get("account_menu_name") == config["account_menu_name"]
            and last.get("exe") == str(exe)):
        return last
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scheduled", action="store_true",
                        help="Run only at/after 10:00 and once successfully per day")
    mode.add_argument("--validate", action="store_true",
                        help="Validate configuration and dependency imports without controlling apps")
    mode.add_argument("--notify-only", action="store_true",
                      help="Send today's pending confirmation email from a verified result, without opening WorkBuddy")
    args = parser.parse_args()
    config, exe = load_config()
    if args.validate:
        from pywinauto import Desktop  # noqa: F401 -- verify UI dependency only for validation
        if config.get("email_notification", {}).get("enabled", False):
            mail_settings(config)
        print("OK: configuration, WorkBuddy executable and pywinauto imports")
        return 0
    runtime = Path(os.path.expandvars(config["runtime_directory"]))
    configure_logging(runtime)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, False, "Local\\WorkBuddyDailyCheckIn1000")
    if not mutex:
        LOG.error("Could not acquire the single-instance mutex")
        return 75
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        return 0
    try:
        now = datetime.now()
        today = now.date().isoformat()
        marker = runtime / "last-success.json"
        if args.notify_only:
            if not config.get("email_notification", {}).get("enabled", False):
                raise RuntimeError("Email notification is not enabled; run setup-email.cmd first")
            last = load_confirmed_success(config, exe, runtime, today)
            if last is None:
                raise RuntimeError("No confirmed check-in today for this account; no email sent and WorkBuddy was not opened")
            LOG.info("Sending today's pending notification without opening WorkBuddy")
            outcome = notify_success(config, runtime, today, last["status"])
            LOG.info("Notification-only result: %s", outcome)
            return 0
        if args.scheduled:
            if now.hour < 10:
                return 0
            last = load_confirmed_success(config, exe, runtime, today)
            if last is not None:
                # The check-in already succeeded. Retry only its pending email.
                notify_success(config, runtime, today, last["status"])
                return 0
        LOG.info("Starting daily check-in")
        result = perform_checkin(config, exe)
        # Do not mark a new calendar day if a run crossed midnight.
        result_state = {"date": today, "status": result,
                        "account_menu_name": config["account_menu_name"], "exe": str(exe),
                        "checked_at": datetime.now().astimezone().isoformat()}
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(result_state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(marker)
        LOG.info("Success: %s", result)
        # Persist the check-in before email so SMTP failures cannot lose the
        # successful result or trigger another claim on the next scheduled run.
        notify_success(config, runtime, today, result)
        return 0
    except Exception as error:
        # Store only an error type and short message; never dump application trees.
        LOG.error("%s: %s", type(error).__name__, str(error)[:400])
        return 75
    finally:
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # Configuration/import failures happen before the normal logger exists.
        fallback = Path(os.environ.get("LOCALAPPDATA", str(BASE))) / "WorkBuddyDailyAutomation"
        fallback.mkdir(parents=True, exist_ok=True)
        with (fallback / "bootstrap-error.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().isoformat()} {type(error).__name__}: {str(error)[:400]}\n")
        sys.exit(75)
