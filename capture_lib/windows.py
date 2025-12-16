from __future__ import annotations

import platform
import subprocess
import time
from typing import Dict, Iterable, List, Optional, Tuple

ALLOWED_APP_NAMES = {
    "League of Legends",
    "League of Legends (TM) Client",
    "LeagueofLegends",
    "LeagueClientUx",
    "LeagueClient",
    "LeagueClientUxRender",
    "Riot Client",
    "RiotClientServices",
}
AX_PROMPTED = False


def active_window_name() -> Optional[str]:
    system = platform.system()
    try:
        if system == "Darwin":
            script = 'tell application "System Events" to get the name of the first process whose frontmost is true'
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, check=False
            )
            return result.stdout.strip() if result.returncode == 0 else None
        if system == "Windows":
            import win32gui  # type: ignore

            hwnd = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(hwnd)
        if system == "Linux":
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None
    return None


def is_allowed_window(name: Optional[str]) -> bool:
    if not name:
        return False
    n = name.lower()
    n_nospace = n.replace(" ", "")
    return any(a.lower() in n or a.lower().replace(" ", "") in n_nospace for a in ALLOWED_APP_NAMES)


def _normalize_names(names: Iterable[str]) -> List[str]:
    normed: List[str] = []
    for n in names:
        n_lower = n.lower()
        normed.append(n_lower)
        normed.append(n_lower.replace(" ", ""))
    return normed


def window_bbox(candidate_names: Iterable[str]) -> Optional[Dict[str, int]]:
    raw_names = list(dict.fromkeys(candidate_names))
    targets = _normalize_names(raw_names)
    system = platform.system()
    try:
        if system == "Darwin":
            try:
                import Quartz  # type: ignore
                import AppKit  # type: ignore

                global AX_PROMPTED
                if not AX_PROMPTED and hasattr(Quartz, "AXIsProcessTrustedWithOptions"):
                    Quartz.AXIsProcessTrustedWithOptions({Quartz.kAXTrustedCheckOptionPrompt: True})
                    AX_PROMPTED = True

                def _match_window_list(list_option):
                    window_list = Quartz.CGWindowListCopyWindowInfo(list_option, Quartz.kCGNullWindowID)
                    matches: List[Dict[str, int]] = []
                    for win in window_list:
                        owner = (win.get("kCGWindowOwnerName", "") or "").lower()
                        name = (win.get("kCGWindowName", "") or "").lower()
                        owner_nospace = owner.replace(" ", "")
                        name_nospace = name.replace(" ", "")
                        candidate = [owner, name, owner_nospace, name_nospace]
                        if any(t in c for t in targets for c in candidate):
                            bounds = win.get("kCGWindowBounds") or {}
                            left = int(bounds.get("X", 0))
                            top = int(bounds.get("Y", 0))
                            width = int(bounds.get("Width", 0))
                            height = int(bounds.get("Height", 0))
                            if width > 1 and height > 1:
                                matches.append({"left": left, "top": top, "width": width, "height": height})
                    return matches

                matches = _match_window_list(Quartz.kCGWindowListOptionOnScreenOnly)
                if not matches:
                    matches = _match_window_list(Quartz.kCGWindowListOptionAll)
                if matches:
                    matches.sort(key=lambda b: b["width"] * b["height"], reverse=True)
                    return matches[0]
            except Exception:
                pass

            # Accessibility API focused window (requires Accessibility permission).
            try:
                import Quartz  # type: ignore

                app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
                app_name = (str(app.localizedName() or "")).lower().replace(" ", "")
                if any(t in app_name for t in targets):
                    app_ref = Quartz.AXUIElementCreateApplication(app.processIdentifier())
                    err, focused = Quartz.AXUIElementCopyAttributeValue(app_ref, Quartz.kAXFocusedWindowAttribute, None)
                    if err == Quartz.kAXErrorSuccess and focused:
                        err_p, pos = Quartz.AXUIElementCopyAttributeValue(focused, Quartz.kAXPositionAttribute, None)
                        err_s, size = Quartz.AXUIElementCopyAttributeValue(focused, Quartz.kAXSizeAttribute, None)
                        if err_p == Quartz.kAXErrorSuccess and err_s == Quartz.kAXErrorSuccess and pos and size:
                            left = int(pos.x)
                            top = int(pos.y)
                            width = int(size.width)
                            height = int(size.height)
                            if width > 1 and height > 1:
                                return {"left": left, "top": top, "width": width, "height": height}
            except Exception:
                pass

            # AppleScript fallback.
            for name in raw_names:
                safe_name = name.replace('"', '\\"')
                script = f'''
                    tell application "System Events"
                        ignoring case
                            set proc_list to (every process whose name contains "{safe_name}")
                        end ignoring
                        if proc_list is {{}} then return "NONE"
                        tell window 1 of first item of proc_list
                            set p to position
                            set s to size
                            return (item 1 of p) & "," & (item 2 of p) & "," & (item 1 of s) & "," & (item 2 of s)
                        end tell
                    end tell
                '''
                result = subprocess.run(
                    ["osascript", "-e", script], capture_output=True, text=True, check=False
                )
                if result.returncode != 0:
                    continue
                out = result.stdout.strip()
                if out == "NONE" or "," not in out:
                    continue
                try:
                    left, top, width, height = [int(x) for x in out.split(",")]
                except Exception:
                    continue
                if width > 1 and height > 1:
                    return {"left": left, "top": top, "width": width, "height": height}
            return None

        if system == "Windows":
            import win32gui  # type: ignore

            target_hwnd = None

            def _enum_handler(hwnd, _ctx):
                nonlocal target_hwnd
                if target_hwnd is not None:
                    return
                title = win32gui.GetWindowText(hwnd)
                t_norm = title.lower()
                t_nospace = t_norm.replace(" ", "")
                if any(t in t_norm or t in t_nospace for t in targets) and win32gui.IsWindowVisible(hwnd):
                    target_hwnd = hwnd

            win32gui.EnumWindows(_enum_handler, None)
            if target_hwnd is None:
                return None
            left, top, right, bottom = win32gui.GetWindowRect(target_hwnd)
            return {"left": left, "top": top, "width": right - left, "height": bottom - top}

        if system == "Linux":
            search_patterns = list(dict.fromkeys(targets))
            window_id = None
            for pat in search_patterns:
                search = subprocess.run(
                    ["xdotool", "search", "--name", pat],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if search.returncode == 0 and search.stdout.strip():
                    window_id = search.stdout.strip().splitlines()[0]
                    break
            if not window_id:
                search = subprocess.run(
                    ["xdotool", "search", "--class", "|".join(search_patterns)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if search.returncode == 0 and search.stdout.strip():
                    window_id = search.stdout.strip().splitlines()[0]
            if not window_id:
                return None

            geom = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", window_id],
                capture_output=True,
                text=True,
                check=False,
            )
            if geom.returncode != 0:
                return None
            vals: Dict[str, int] = {}
            for line in geom.stdout.splitlines():
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                vals[key.strip()] = int(val.strip())
            if not {"X", "Y", "WIDTH", "HEIGHT"} <= vals.keys():
                return None
            return {"left": vals["X"], "top": vals["Y"], "width": vals["WIDTH"], "height": vals["HEIGHT"]}
    except Exception:
        return None
    return None


def wait_for_capture_target(
    allow_any_window: bool,
    forced_window: Optional[str],
    stop_event,
    poll_seconds: float = 0.5,
) -> Optional[Tuple[str, Optional[Dict[str, int]]]]:
    if allow_any_window:
        return (forced_window or active_window_name() or "", None)

    target_label = forced_window or "League of Legends"
    last_log = 0.0
    last_hint = 0.0
    while not stop_event.is_set():
        name = active_window_name()
        allowed = False
        if forced_window:
            allowed = bool(name and forced_window in name)
        else:
            allowed = is_allowed_window(name)

        bbox: Optional[Dict[str, int]] = None
        if allowed:
            candidates = [name or target_label] + list(ALLOWED_APP_NAMES)
            bbox = window_bbox(candidates)
            if bbox:
                return (name or target_label, bbox)
            else:
                print(
                    f"Detected '{name or target_label}' but could not read bounds yet; waiting...",
                    flush=True,
                )
                now = time.time()
                if now - last_hint >= 15.0:
                    print(
                        "Hint: ensure Screen Recording permission is granted to this terminal/IDE "
                        "and the client is in windowed/borderless mode (not exclusive fullscreen).",
                        flush=True,
                    )
                    last_hint = now

        now = time.time()
        if now - last_log >= 5.0:
            status = name or "none"
            suffix = "" if allowed else " (not matched)"
            print(f"Waiting for '{target_label}' window... (current: {status}{suffix})", flush=True)
            last_log = now
        time.sleep(poll_seconds)
    return None

