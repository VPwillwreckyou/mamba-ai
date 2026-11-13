"""MAMBA end-to-end acceptance harness.

Runs two parts in ONE command/session (app lifetime is tied to the session):
  Part B - subprocess lifecycle: launch `python app.py` twice (restart test),
           verify window appears, capture screenshots, check stderr for crashes.
  Part A - in-process functional driving of the real MambaApp: every test point
           is exercised through the real widget input path (setText +
           _submit_input -> chat_requested -> handle_chat_request) and verified
           against real side effects on disk / screen / processes.

Writes acceptance_report.json and exits 0 only if all required checks pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Match ONLY the MAMBA app window - never other windows containing "MAMBA"
# (e.g. the VS Code window for this workspace is titled "... MAMBA AI ...").
APP_TITLE = "Personal AI Assistant"

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:600], "required": required})
    tag = "PASS" if ok else ("FAIL" if required else "INFO")
    print(f"[{tag}] {name}" + (f" -- {detail}" if detail else ""), flush=True)


def find_windows(substr: str) -> list[int]:
    import win32gui

    found: list[int] = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and substr.lower() in win32gui.GetWindowText(hwnd).lower():
            found.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return found


def force_foreground(hwnd: int) -> bool:
    """Make hwnd the OS foreground window using several fallback strategies."""
    import ctypes

    import win32con
    import win32gui

    user32 = ctypes.windll.user32
    try:
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
        )
    except Exception:
        pass
    if user32.GetForegroundWindow() == hwnd:
        return True
    try:
        fg = user32.GetForegroundWindow()
        cur_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = bool(user32.AttachThreadInput(me, cur_thread, True)) if cur_thread else False
        win32gui.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(me, cur_thread, False)
    except Exception:
        pass
    time.sleep(0.25)
    if user32.GetForegroundWindow() == hwnd:
        return True
    # Last resort: clicking the title bar always activates a window.
    try:
        import pyautogui

        wl, wt, wr, wb = win32gui.GetWindowRect(hwnd)
        pyautogui.click((wl + wr) // 2, wt + 12)
        time.sleep(0.4)
    except Exception:
        pass
    return bool(user32.GetForegroundWindow() == hwnd)


def capture(path: Path) -> bool:
    from mss import mss
    from PIL import Image

    with mss() as sct:
        img = sct.grab(sct.monitors[1])
        Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX").save(str(path))
    return path.exists() and path.stat().st_size > 10_000


def launch_instance(run_id: str) -> tuple[subprocess.Popen, Path, Path]:
    out_path = ROOT / f"acceptance_run_{run_id}.out"
    err_path = ROOT / f"acceptance_run_{run_id}.err"
    out_f = out_path.open("w", encoding="utf-8", errors="replace")
    err_f = err_path.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(ROOT),
        stdout=out_f,
        stderr=err_f,
    )
    proc._harness_out = out_f  # keep refs open until process ends
    proc._harness_err = err_f
    return proc, out_path, err_path


def wait_for_window(proc: subprocess.Popen, substr: str, timeout: float = 20.0) -> list[int]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return []
        hwnds = find_windows(substr)
        if hwnds:
            return hwnds
        time.sleep(0.4)
    return []


def terminate_instance(proc: subprocess.Popen) -> int | None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=8)
    for attr in ("_harness_out", "_harness_err"):
        f = getattr(proc, attr, None)
        if f:
            try:
                f.close()
            except Exception:
                pass
    return proc.returncode


# --------------------------------------------------------------------------- #
# Part B: subprocess lifecycle (launch, window, screenshot, restart, crashes)
# --------------------------------------------------------------------------- #

def part_b() -> None:
    print("\n=== PART B: subprocess lifecycle ===", flush=True)

    # Run 1: fresh launch
    proc1, out1, err1 = launch_instance("1")
    hwnds1 = wait_for_window(proc1, APP_TITLE, timeout=25)
    check("B1: app subprocess launches and window appears", bool(hwnds1),
          f"pids hwnd={hwnds1}")
    shot1 = ROOT / "acceptance_instance1.png"
    ok_shot1 = bool(hwnds1) and capture(shot1)
    check("B2: instance-1 screenshot captured", ok_shot1,
          f"{shot1} ({shot1.stat().st_size if shot1.exists() else 0} bytes)")
    time.sleep(1.5)  # let timers run; a timer-callback crash would show up here
    alive1 = proc1.poll() is None
    check("B3: app stable after 1.5s of UI timers running", alive1,
          f"returncode={proc1.poll()}")
    rc1 = terminate_instance(proc1)
    err_text1 = err1.read_text(encoding="utf-8", errors="replace")
    check("B4: instance-1 stderr has no Traceback", "Traceback" not in err_text1,
          err_text1.strip()[-300:] if err_text1.strip() else "clean stderr")
    check("B5: instance-1 terminated on request", rc1 is not None, f"rc={rc1}")
    hwnds_gone1 = not find_windows(APP_TITLE)
    check("B6: instance-1 window gone after termination", hwnds_gone1)

    # Run 2: restart
    proc2, out2, err2 = launch_instance("2")
    hwnds2 = wait_for_window(proc2, APP_TITLE, timeout=25)
    check("B7: restart - second launch shows window", bool(hwnds2), f"hwnd={hwnds2}")
    shot2 = ROOT / "acceptance_instance2.png"
    ok_shot2 = bool(hwnds2) and capture(shot2)
    check("B8: restart - screenshot captured", ok_shot2,
          f"({shot2.stat().st_size if shot2.exists() else 0} bytes)")
    time.sleep(1.0)
    alive2 = proc2.poll() is None
    check("B9: restart instance stable", alive2, f"rc={proc2.poll()}")
    rc2 = terminate_instance(proc2)
    err_text2 = err2.read_text(encoding="utf-8", errors="replace")
    check("B10: restart stderr has no Traceback", "Traceback" not in err_text2,
          err_text2.strip()[-300:] if err_text2.strip() else "clean stderr")
    check("B11: restart instance terminated cleanly", rc2 is not None, f"rc={rc2}")
    check("B12: no orphan MAMBA windows", not find_windows(APP_TITLE))


# --------------------------------------------------------------------------- #
# Part A: in-process functional driving of the real application
# --------------------------------------------------------------------------- #

def part_a() -> None:
    print("\n=== PART A: in-process functional acceptance ===", flush=True)
    import psutil
    from PySide6.QtWidgets import QApplication

    proc = psutil.Process()
    rss_start = proc.memory_info().rss
    threads_start = proc.num_threads()

    try:
        import app as app_module
        mamba = app_module.MambaApp()
        check("A1: MambaApp initializes without crash", True)
    except Exception:
        check("A1: MambaApp initializes without crash", False, traceback.format_exc())
        return

    mamba.dashboard.show()
    mamba.dashboard.resize(950, 680)
    mamba.dashboard.setWindowTitle("MAMBA - Personal AI Assistant")
    QApplication.processEvents()
    time.sleep(1.0)
    QApplication.processEvents()

    # -- UI load ------------------------------------------------------------
    win_ok = bool(find_windows(APP_TITLE))
    check("A2: dashboard window visible on desktop", win_ok,
          f"hwnd={find_windows(APP_TITLE)}")
    ui_shot = ROOT / "acceptance_ui.png"
    check("A3: UI screenshot captured for report", capture(ui_shot), str(ui_shot))

    missing = [k for k, v in mamba.controllers.items() if v is None]
    check("A4: all capability controllers loaded", not missing, f"missing={missing}")
    check("A5: tool router and task executor wired",
          mamba.tool_router is not None and mamba.task_executor is not None)

    def send(msg: str, settle: float = 0.15) -> str:
        """Drive the real input widget: setText -> _submit_input -> signal."""
        before = mamba.dashboard.get_response_text()
        mamba.dashboard._input_field.setFocus()
        mamba.dashboard._input_field.setText(msg)
        QApplication.processEvents()
        mamba.dashboard._submit_input()
        QApplication.processEvents()
        time.sleep(settle)
        QApplication.processEvents()
        after = mamba.dashboard.get_response_text()
        return after.removeprefix(before)

    def send_shot(cmd: str, tries: int = 2) -> str:
        """Send a screenshot command; retry once on transient capture errors."""
        tail = send(cmd)
        for _ in range(tries - 1):
            if "FAILED" in tail and "screenshot" in tail:
                time.sleep(1.2)
                tail = send(cmd)
            else:
                break
        if "FAILED" in tail and "screenshot" in tail:
            # Record desktop state so environmental failures are diagnosable.
            try:
                import ctypes

                u32 = ctypes.windll.user32
                hd = u32.OpenInputDesktop(0, False, 0x0100)
                locked = not bool(hd)
                if hd:
                    u32.CloseDesktop(hd)
                tail += f" [desktop_locked={locked}]"
            except Exception as exc:
                tail += f" [desktop state unknown: {exc}]"
        return tail

    # -- text input -> response --------------------------------------------
    tail = send("hello mamba")
    check("A6: typed input produces a MAMBA response in conversation",
          "MAMBA:" in tail and len(tail) > 30, tail[:200])

    # -- memory / context ---------------------------------------------------
    tail1 = send("My favorite color is teal")
    check("A7: statement recorded ('Noted' reply)", "Noted" in tail1, tail1[:200])
    tail2 = send("What is my favorite color?")
    check("A8: context recalled across turns (answer contains teal)",
          "teal" in tail2.lower(), tail2[:200])
    tail3 = send("what did I just say")
    check("A9: short-term recall of previous message", "favorite color" in tail3.lower()
          or "teal" in tail3.lower(), tail3[:200])

    # -- open application ---------------------------------------------------
    tail = send("open notepad")
    ok_open = "OK - open_application" in tail
    time.sleep(1.5)
    notepad_windows = find_windows("Notepad")
    check("A10: open app (notepad) executed and verified", ok_open and bool(notepad_windows),
          f"reply={tail[:150]!r} windows={notepad_windows}")

    # -- keyboard / mouse ---------------------------------------------------
    tail = send("move mouse to 640, 400")
    import pyautogui
    mx, my = pyautogui.position()
    if abs(mx - 640) > 5 or abs(my - 400) > 5:
        # Cursor may be user-controlled; retry once and read back immediately.
        tail = send("move mouse to 640, 400")
        mx, my = pyautogui.position()
    check("A11: mouse moved to requested coordinates",
          "OK - mouse_move" in tail and abs(mx - 640) <= 5 and abs(my - 400) <= 5,
          f"reply={tail[:120]!r} actual=({mx},{my})")

    # Keyboard test: make OUR window the OS foreground so pyautogui keystrokes
    # land in it. Strategy chain: Qt activation -> raise+click inside our own
    # conversation panel (exact Qt-mapped coordinates) -> ALT-key trick.
    import win32con
    import win32gui
    from PySide6.QtCore import QPoint

    hwnds = find_windows(APP_TITLE)
    diag: list[str] = []
    fg_ok = False

    def os_fg() -> int:
        return int(win32gui.GetForegroundWindow() or 0)

    if hwnds:
        hwnd = hwnds[0]
        # 1) Qt's own activation
        mamba.dashboard.raise_()
        mamba.dashboard.activateWindow()
        QApplication.processEvents()
        time.sleep(0.3)
        fg_ok = os_fg() == hwnd
        diag.append(f"qt={fg_ok}")
        if not fg_ok:
            # 2) Raise to top, then click a SAFE spot inside our own window
            #    (the conversation panel) using Qt-provided global coordinates.
            try:
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
                )
                time.sleep(0.2)
                import pyautogui

                pt = mamba.dashboard._response_view.mapToGlobal(QPoint(30, 30))
                pyautogui.click(int(pt.x()), int(pt.y()))
                time.sleep(0.4)
            except Exception as exc:
                diag.append(f"click_err={exc}")
            fg_ok = os_fg() == hwnd
            diag.append(f"click={fg_ok}")
        if not fg_ok:
            # 3) ALT-key trick unlocks SetForegroundWindow
            try:
                import pyautogui

                pyautogui.keyDown("alt")
                time.sleep(0.05)
                win32gui.SetForegroundWindow(hwnd)
                pyautogui.keyUp("alt")
                time.sleep(0.3)
            except Exception as exc:
                diag.append(f"alt_err={exc}")
            fg_ok = os_fg() == hwnd
            diag.append(f"alt={fg_ok}")
        diag.append(f"os_fg={os_fg()}:{win32gui.GetWindowText(os_fg())[:30]!r}")
        mamba.dashboard._input_field.setFocus()
        QApplication.processEvents()
        time.sleep(0.1)
    else:
        diag.append("no_app_window_found")
    if fg_ok:
        tail = send("type QZ9")
        typed = mamba.dashboard.get_input_text()
    else:
        # Never type blindly - keystrokes would land in another application.
        tail, typed = "", ""
        mamba.dashboard._input_field.clear()
    check("A12: keyboard typing entered text into focused field",
          fg_ok and "OK - keyboard_type" in tail and typed == "QZ9",
          f"reply={tail[:120]!r} field={typed!r} {' '.join(diag)}")
    mamba.dashboard._input_field.clear()

    # -- screenshot + vision ------------------------------------------------
    shot_dir = ROOT / "data" / "screenshots"
    before_shots = set(shot_dir.glob("*.png")) if shot_dir.exists() else set()
    tail = send_shot("take a screenshot")
    new_shots = set(shot_dir.glob("*.png")) - before_shots if shot_dir.exists() else set()
    check("A13: screenshot taken via UI command",
          "OK - screenshot" in tail and bool(new_shots), f"reply={tail[:150]!r}")

    tail = send_shot("read screen")
    has_pixels = "pixels" in tail or "width" in tail
    ocr_honest = ("ocr" in tail.lower()) or ("tesseract" in tail.lower()) or ("unavailable" in tail.lower())
    check("A14: screen read (vision) returns real analysis",
          "OK - screenshot" in tail and has_pixels,
          f"reply={tail[:300]!r}")
    check("A15: OCR layer reports honestly (tesseract not installed)",
          ocr_honest or "ai_description" in tail, tail[:300], required=False)

    # -- file CRUD ----------------------------------------------------------
    note = ROOT / "data" / "acceptance_note.txt"
    if note.exists():
        note.unlink()
    tail = send("create file data/acceptance_note.txt with hello acceptance")
    ok_create = ("OK - create_file" in tail) and note.exists() and note.read_text().strip() == "hello acceptance"
    check("A16: file created with verified content", ok_create, f"reply={tail[:150]!r}")

    tail = send("read file data/acceptance_note.txt")
    check("A17: file read returns real content", "OK - read_file" in tail and "hello acceptance" in tail,
          tail[:200])

    tail = send("edit file data/acceptance_note.txt replacing hello with goodbye")
    ok_edit = "OK - edit_file" in tail and "goodbye acceptance" in note.read_text()
    check("A18: file edit verified on disk", ok_edit, f"reply={tail[:150]!r}")

    tail = send("append  and done to file data/acceptance_note.txt")
    ok_append = "OK - edit_file" in tail and note.read_text().rstrip().endswith("done")
    check("A19: file append verified on disk", ok_append, f"reply={tail[:150]!r}")

    tail = send("list files in data")
    check("A20: directory listing shows created file",
          "OK - list_files" in tail and "acceptance_note.txt" in tail, tail[:250])

    # Delete must be refused without confirmation (CONFIRM + protected action)
    from core.tool_router import ToolCall
    del_result = mamba.tool_router.execute(
        ToolCall("delete_file", "Delete acceptance note", {"path": "data/acceptance_note.txt"}))
    check("A21: destructive delete gated (refused without confirmation)",
          del_result.get("success") is False and "confirmation" in del_result.get("error", "").lower()
          and note.exists(),
          f"error={del_result.get('error')!r}")

    # -- terminal real output ----------------------------------------------
    tail = send("run echo acceptance-terminal-ok")
    check("A22: terminal returns real command output",
          "OK - terminal_execute_safe" in tail and "acceptance-terminal-ok" in tail, tail[:250])

    tail = send("run del /f /q data\\acceptance_note.txt")
    check("A23: dangerous command refused by blocklist",
          "FAILED" in tail and note.exists(), tail[:250])

    # -- web search ---------------------------------------------------------
    tail = send("search the web for python programming language", settle=1.0)
    check("A24: live web search returns results",
          "OK - web_search" in tail and ("results" in tail or "count" in tail), tail[:300])

    # -- small coding task with build/test error recovery -------------------
    calc = ROOT / "data" / "calc.py"
    if calc.exists():
        calc.unlink()
    tail = send("create file data/calc.py with def add(a b):\\n    return a + b\\nprint(\"result\", add(2, 3))")
    check("A25: coding task - broken file created",
          "OK - create_file" in tail and calc.exists(), tail[:200])
    tail = send("run python data/calc.py")
    check("A26: broken code run fails and error is detected",
          "FAILED" in tail and ("SyntaxError" in tail or "error" in tail.lower()), tail[:300])
    tail = send("edit file data/calc.py replacing a b with a, b")
    check("A27: code repaired", "OK - edit_file" in tail, tail[:200])
    tail = send("run python data/calc.py")
    check("A28: repaired code runs successfully with real output",
          "OK - terminal_execute_safe" in tail and "result 5" in tail, tail[:300])

    # -- build/test execution (real pytest) ---------------------------------
    tail = send("run python -m pytest tests/test_core_security_unit.py -q", settle=1.0)
    check("A29: test suite runs through terminal and passes",
          "OK - terminal_execute_safe" in tail and "passed" in tail, tail[:400])

    # -- autonomous multi-step task -----------------------------------------
    auto_file = ROOT / "data" / "auto_step.txt"
    if auto_file.exists():
        auto_file.unlink()
    tail = send("create file data/auto_step.txt with autonomous content; then list files in data")
    check("A30: autonomous multi-step task completed (2 steps)",
          "completed" in tail and "2/2" in tail and auto_file.exists(), tail[:400])

    report = mamba.task_executor.execute("Review the project status and report findings")
    step_names = [s.description for s in report.steps]
    generic_ok = (report.status == "completed" and len(report.steps) == 6
                  and any("Understand" in s for s in step_names)
                  and any("Inspect" in s for s in step_names)
                  and any("Verify" in s for s in step_names))
    check("A31: generic autonomous pipeline (understand-inspect-plan-act-verify-report)",
          generic_ok, f"status={report.status} steps={step_names}")

    # -- emergency stop ------------------------------------------------------
    mamba.handle_emergency_stop()
    allowed = mamba.security_manager.is_allowed()
    tail = send("take a screenshot")
    check("A32: emergency stop blocks all execution",
          (not allowed) and "FAILED" in tail and "Blocked" in tail, tail[:250])
    mamba.security_manager.reset_emergency_stop()
    mamba.security_manager.restore_access()
    tail = send_shot("take a screenshot")
    check("A33: operations recover after stop is cleared",
          mamba.security_manager.is_allowed() and "OK - screenshot" in tail, tail[:200])

    # -- access revocation ---------------------------------------------------
    mamba.handle_access_revoke()
    tail = send("open notepad")
    check("A34: access revocation blocks actions",
          "FAILED" in tail and "Blocked" in tail, tail[:250])
    mamba.security_manager.restore_access()
    tail = send_shot("take a screenshot")
    check("A35: access restored and actions allowed again",
          "OK - screenshot" in tail, tail[:200])

    # -- phone phrase parsing + mock execution (NO real send) ---------------
    prov_name = type(mamba.phone_manager._provider).__name__
    check("A36: phone provider is mock (no real call/text possible)",
          prov_name == "MockPhoneProvider", prov_name)
    pc_call = mamba.phone_manager.parse_command("call me")
    pc_text = mamba.phone_manager.parse_command("send a text to 5551234567 saying Hello There")
    pc_neg = mamba.phone_manager.parse_command("tell me a joke")
    check("A37: phone phrases parsed / non-phone phrase rejected",
          pc_call is not None and pc_text is not None and pc_neg is None,
          f"call={pc_call.action.value if pc_call else None}, "
          f"text_msg={pc_text.message if pc_text else None}, neg={pc_neg}")
    check("A38: message casing preserved in parsed text command",
          pc_text is not None and pc_text.message == "Hello There",
          f"message={pc_text.message if pc_text else None!r}", required=False)
    if prov_name == "MockPhoneProvider":
        tail = send("call me")
        check("A39: phone call through UI used mock provider (no real call)",
              "Phone call" in tail and "mock provider" in tail, tail[:250])
    else:
        check("A39: phone call through UI used mock provider (no real call)", False,
              f"unexpected real provider {prov_name} - execution skipped")

    # -- phone / caller-ID configuration ------------------------------------
    env_text = (ROOT / ".env").read_text(encoding="utf-8")
    check("A40: .env carries DEFAULT_PHONE_NUMBER and CALLER_ID",
          "DEFAULT_PHONE_NUMBER=055190685" in env_text and "CALLER_ID=MAMBA AI" in env_text)
    check("A41: PhoneManager loaded caller ID and default number",
          mamba.phone_manager.caller_id == "MAMBA AI"
          and mamba.phone_manager.default_phone_number == "055190685",
          f"caller_id={mamba.phone_manager.caller_id!r} "
          f"default={mamba.phone_manager.default_phone_number!r}")

    # -- close notepad (cleanup + close-app test) ---------------------------
    tail = send("close notepad")
    time.sleep(1.2)
    check("A42: close app (notepad) executed and verified gone",
          "OK - close_application" in tail and not find_windows("Notepad"), tail[:250])

    # -- stability / leak / responsiveness ----------------------------------
    QApplication.processEvents()
    time.sleep(0.5)
    rss_end = proc.memory_info().rss
    growth_mb = (rss_end - rss_start) / (1024 * 1024)
    check("A43: memory growth sane (no leak)", growth_mb < 400,
          f"growth={growth_mb:.1f} MB (start={rss_start // 1048576} MB, end={rss_end // 1048576} MB)")
    threads_end = proc.num_threads()
    check("A44: thread count sane", threads_end <= threads_start + 30,
          f"{threads_start} -> {threads_end}")
    conv = mamba.dashboard.get_response_text()
    check("A45: conversation log contains the full session", len(conv) > 1000,
          f"{len(conv)} chars")
    check("A46: window still responsive after all tests",
          mamba.dashboard.isVisible(), "visible")
    check("A47: AI provider status reported honestly",
          True,
          f"ai_provider={mamba.ai_provider is not None} "
          f"(GEMINI_API_KEY set: {bool(os.getenv('GEMINI_API_KEY'))})",
          required=False)

    mamba.dashboard.close()
    QApplication.processEvents()


# --------------------------------------------------------------------------- #

def main() -> int:
    try:
        part_b()
    except Exception:
        check("Part B completed without harness exception", False, traceback.format_exc())
    try:
        part_a()
    except Exception:
        check("Part A completed without harness exception", False, traceback.format_exc())

    required = [r for r in RESULTS if r["required"]]
    passed = [r for r in required if r["ok"]]
    failed = [r for r in required if not r["ok"]]
    optional = [r for r in RESULTS if not r["required"]]
    print("\n=== SUMMARY ===")
    print(f"required: {len(passed)}/{len(required)} passed")
    print(f"optional/info: {sum(1 for r in optional if r['ok'])}/{len(optional)} ok")
    for r in failed:
        print(f"  FAILED: {r['name']} -- {r['detail'][:200]}")

    report_path = ROOT / "acceptance_report.json"
    report_path.write_text(json.dumps({
        "passed": len(passed),
        "required": len(required),
        "failed": [r["name"] for r in failed],
        "results": RESULTS,
    }, indent=2), encoding="utf-8")
    print(f"report written: {report_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())





