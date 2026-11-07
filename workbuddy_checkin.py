"""WorkBuddy daily reward. Windows interactive desktop, Python 3.10+.

Only the account menu's Buddy Refuel card is actionable. Optional email uses
the user's configured SMTP authorization code from Windows Credential Manager.
No WorkBuddy tokens, hard-coded screen coordinates, or chat input are used.
"""
from __future__ import annotations

import argparse
import ctypes
from collections import Counter
from ctypes import wintypes
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
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


def native_window_handles(exe):
    import win32gui
    import win32process
    expected = os.path.normcase(str(exe.resolve()))
    handles = []
    def collect(hwnd, unused):
        try:
            if (win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1"
                    and win32gui.GetWindowText(hwnd).strip() == "WorkBuddy"):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if process_executable(pid) == expected:
                    handles.append(hwnd)
        except Exception:
            pass  # A window may disappear during Electron's splash transition.
    win32gui.EnumWindows(collect, None)
    return handles


def find_window(exe):
    import win32gui
    import win32con
    from pywinauto import Desktop
    handles = native_window_handles(exe)
    if len(handles) > 1:
        raise RuntimeError("Multiple WorkBuddy windows; manual review required")
    if not handles:
        return None
    hwnd = handles[0]
    # UIA top-level enumeration omits some hidden Electron/tray windows even
    # with visible_only=False. Find the owned native HWND, restore, then bind UIA.
    if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
        LOG.info("Restoring the hidden/minimized WorkBuddy native window")
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    return Desktop(backend="uia").window(handle=hwnd).wrapper_object()


def workbuddy_running(exe):
    import win32com.client
    expected = os.path.normcase(str(exe.resolve()))
    inventory = []
    for process in win32com.client.GetObject("winmgmts:").ExecQuery(
            "SELECT ProcessId,ParentProcessId,CommandLine FROM Win32_Process WHERE Name='WorkBuddy.exe'"):
        pid = int(process.ProcessId)
        if process_executable(pid) == expected:
            inventory.append({"pid": pid, "parent": int(process.ParentProcessId),
                              "command": str(process.CommandLine or "")})
    return has_main_process(inventory)


def has_main_process(inventory):
    pids = {process["pid"] for process in inventory}
    for process in inventory:
        command = process["command"]
        if "--type=" in command or re.search(r"\.(?:cjs|mjs|js)(?:[\s\"]|$)", command, re.I):
            continue
        if process["parent"] in pids:
            continue
        return True
    return False


def launch_workbuddy(exe):
    import win32api
    import win32con
    # Use the Windows GUI launcher (as Explorer does), rather than inheriting
    # Python's redirected standard handles and scheduler startup window state.
    result = win32api.ShellExecute(0, "open", str(exe), None, str(exe.parent), win32con.SW_SHOWNORMAL)
    if result <= 32:
        raise RuntimeError(f"Windows could not launch WorkBuddy (ShellExecute code {result})")


def get_or_launch_window(exe, timeout=120):
    # Starting another copy is not a harmless way to activate this Electron app:
    # its startup/repair code may run before the single-instance check.
    window = find_window(exe)
    if window is not None:
        LOG.info("Using the existing WorkBuddy window; no process launched")
        return window
    if workbuddy_running(exe):
        raise RuntimeError("WorkBuddy is already running without a usable window; open it manually. No second copy started")
    LOG.info("WorkBuddy is not running; launching once")
    launch_workbuddy(exe)
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
    if not win32gui.IsWindowVisible(window.handle) or win32gui.IsIconic(window.handle):
        win32gui.ShowWindow(window.handle, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(window.handle)
    except Exception:
        window.set_focus()


def ensure_foreground(window):
    import win32gui
    import win32process
    from pywinauto.controls.hwndwrapper import HwndWrapper
    foreground = win32gui.GetForegroundWindow()
    if foreground and win32process.GetWindowThreadProcessId(foreground)[1] == window.process_id():
        return
    HwndWrapper(window.handle).set_focus()
    foreground = win32gui.GetForegroundWindow()
    if not foreground or win32process.GetWindowThreadProcessId(foreground)[1] != window.process_id():
        raise RuntimeError("WorkBuddy did not become foreground; no click sent. Do not switch windows during UI execution")


def profile_controls(window, config):
    return [m for m in window.descendants(control_type="MenuItem")
            if m.element_info.name == config["account_menu_name"]
            and m.is_visible() and m.is_enabled()]


def diagnostic_snapshot(window, config):
    import win32gui
    try:
        elements = window.descendants()
        kinds = Counter(element.element_info.control_type for element in elements)
        return {"visible": bool(win32gui.IsWindowVisible(window.handle)),
                "minimized": bool(win32gui.IsIconic(window.handle)),
                "control_count": len(elements), "control_types": dict(kinds),
                "profile_matches": sum(element.element_info.name == config.get("account_menu_name") for element in elements),
                "claim_buttons": sum(normalized(element.element_info.name) in {"立即领取", "ClaimNow"} for element in elements),
                "claimed_buttons": sum(normalized(element.element_info.name) in {"今日已领", "今日已领取", "Claimedtoday"} for element in elements)}
    except Exception as error:
        return {"snapshot_error": type(error).__name__}


def save_diagnostic(window, config, stage):
    snapshot = diagnostic_snapshot(window, config)
    LOG.info("UI diagnostics stage=%s summary=%s", stage, json.dumps(snapshot, ensure_ascii=False))
    if config.get("runtime_directory"):
        runtime = Path(os.path.expandvars(config["runtime_directory"]))
        runtime.mkdir(parents=True, exist_ok=True)
        data = {"time": datetime.now().astimezone().isoformat(), "stage": stage, "summary": snapshot}
        (runtime / "last-diagnostic.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def wait_account_ready(window, config, timeout=60, exe=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if exe is not None:
            # Startup repair replaces the splash HWND with the real main HWND.
            current = find_window(exe)
            if current is None:
                time.sleep(0.75)
                continue
            window = current
        card = account_card(window, config)
        profiles = profile_controls(window, config) if card is None else []
        if card is not None or profiles:
            LOG.info("UI ready: card=%s profile_controls=%d", card is not None, len(profiles))
            return window, card, profiles
        time.sleep(0.75)
    save_diagnostic(window, config, "account-not-ready")
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
    from pywinauto import Desktop
    if not desktop_unlocked():
        raise RuntimeError("Desktop locked before action")
    window = control.top_level_parent()
    ensure_foreground(window)
    if not control.is_visible() or not control.is_enabled():
        raise RuntimeError("Target control disappeared or became disabled; no click sent")
    point = control.rectangle().mid_point()
    actual = Desktop(backend="uia").from_point(point.x, point.y)
    for _ in range(8):
        if actual.element_info == control.element_info:
            control.click_input(use_log=False)
            return
        actual = actual.parent()
        if actual is None:
            break
    raise RuntimeError("The target is covered or stale; no click sent")


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
    LOG.info("Stage: restore-and-focus")
    focus_window(window)
    LOG.info("Stage: wait-for-account")
    window, card, profiles = wait_account_ready(window, config, exe=exe)
    if card is None:
        LOG.info("Stage: open-account-menu")
        activate_control(unique(profiles, "account menu trigger (login may be expired)"))
        LOG.info("Stage: wait-for-reward-card")
        card = wait_card(window, config, 15)
    if card is None:
        save_diagnostic(window, config, "card-not-found")
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
    except Exception as error:
        # A transport/UI error can happen after a successful invocation.
        # Reobserve success below instead of repeating an uncertain click.
        LOG.warning("Claim action outcome uncertain; verifying without a second click (type=%s hresult=%s winerror=%s)",
                    type(error).__name__, getattr(error, "hresult", None), getattr(error, "winerror", None))
    deadline = time.monotonic() + 25
    reopened = False
    while time.monotonic() < deadline:
        if not desktop_unlocked():
            raise RuntimeError("Desktop locked while verifying the reward")
        current = account_card(window, config)
        if current is not None and claimed(current):
            LOG.info("Stage: claimed-status-confirmed")
            return "claimed"
        if current is None and not reopened:
            profiles = profile_controls(window, config)
            if len(profiles) == 1:
                LOG.info("Stage: reopen-account-menu-to-verify (no second claim)")
                activate_control(profiles[0])
                reopened = True
        time.sleep(0.75)
    save_diagnostic(window, config, "claim-unconfirmed")
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
    mode.add_argument("--diagnose", action="store_true",
                      help="Restore/open WorkBuddy and save control counts without clicking claim or sending email")
    parser.add_argument("--verbose", action="store_true", help="Also show stage logs in the console")
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
    if args.verbose:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(console)
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
        if args.diagnose:
            if not desktop_unlocked():
                raise RuntimeError("Desktop must be unlocked for UI diagnostics")
            window = get_or_launch_window(exe)
            focus_window(window)
            print(json.dumps(save_diagnostic(window, config, "manual-diagnosis"), ensure_ascii=False))
            return 0
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
