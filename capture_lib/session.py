from __future__ import annotations

import json
import bisect
import queue
import signal
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import platform
from pynput import keyboard

from .constants import DEFAULT_FPS, FRAME_CODEC
from .input_logging import InputEvent, InputLogger
from .screen_recorder import FrameRecord, ScreenRecorder
from .webcam_recorder import WebcamRecorder
from .windows import active_window_name, is_allowed_window, wait_for_capture_target


def write_events(
    events: Iterable[InputEvent],
    screen_frames: List[FrameRecord],
    output_dir: Path,
    *,
    session_id: str,
    window_id: str,
    webcam_frames: Optional[List[FrameRecord]] = None,
):
    rows = []
    for ev in events:
        rows.append(
            {
                "t_ns": ev.t_ns,
                "t_capture_ns": None,
                "is_duplicate": None,
                "event_type": ev.event_type,
                "stream": "input",
                "key_code": ev.key_code,
                "mouse_x": ev.mouse_x,
                "mouse_y": ev.mouse_y,
                "mouse_button": ev.mouse_button,
                "delta": ev.delta,
                "frame_ref": ev.frame_ref,
                "window_id": ev.window_id,
                "session_id": ev.session_id,
                "metadata": ev.metadata,
            }
        )
    for fr in screen_frames:
        rows.append(
            {
                "t_ns": fr.t_ns,
                "t_capture_ns": fr.t_capture_ns,
                "is_duplicate": fr.is_duplicate,
                "event_type": "frame",
                "stream": "screen",
                "key_code": None,
                "mouse_x": None,
                "mouse_y": None,
                "mouse_button": None,
                "delta": None,
                "frame_ref": fr.frame_index,
                "window_id": window_id,
                "session_id": session_id,
                "metadata": None,
            }
        )
    if webcam_frames:
        for fr in webcam_frames:
            rows.append(
                {
                    "t_ns": fr.t_ns,
                    "t_capture_ns": fr.t_capture_ns,
                    "is_duplicate": fr.is_duplicate,
                    "event_type": "frame",
                    "stream": "webcam",
                    "key_code": None,
                    "mouse_x": None,
                    "mouse_y": None,
                    "mouse_button": None,
                    "delta": None,
                    "frame_ref": fr.frame_index,
                    "window_id": window_id,
                    "session_id": session_id,
                    "metadata": None,
                }
            )
    df = pd.DataFrame(rows)
    df = df.sort_values("t_ns", kind="mergesort").reset_index(drop=True)
    df.to_parquet(output_dir / "events.parquet", compression="snappy")
    df.to_csv(output_dir / "events.csv", index=False)


def write_metadata(
    output_dir: Path,
    session_id: str,
    fps: int,
    dropped_frames: int = 0,
    padded_frames: int = 0,
    actual_fps: Optional[float] = None,
    capture_fps: Optional[float] = None,
    screen_resolution: Optional[Tuple[int, int]] = None,
    window_id: str = "",
    webcam_info: Optional[Dict[str, object]] = None,
    start_t_ns: Optional[int] = None,
    end_t_ns: Optional[int] = None,
    dropped_frames_estimated: Optional[int] = None,
):
    metadata = {
        "format_version": "1.0.0",
        "session_id": session_id,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "game": "League of Legends",
        "resolution": list(screen_resolution) if screen_resolution else [],
        "refresh_hz": None,
        "capture_fps": fps,
        "actual_capture_fps": actual_fps,
        "measured_capture_fps": capture_fps,
        "codec": FRAME_CODEC,
        "bitrate_kbps": None,
        "input_device": "keyboard+mouse",
        "window_id": window_id,
        "dropped_frames": dropped_frames,
        "dropped_frames_estimated": dropped_frames_estimated,
        "padded_frames": padded_frames,
        "start_t_ns": start_t_ns,
        "end_t_ns": end_t_ns,
        "duration_s": ((end_t_ns - start_t_ns) / 1e9) if (start_t_ns and end_t_ns) else None,
        "clock_drift_ppm": 0.0,
        "consent": {"record_screen": True, "record_audio": False, "record_webcam": bool(webcam_info)},
        "privacy": {"chat_redacted": True, "pii_regions": []},
        "env": {
            "os": platform.platform(),
            "client_version": "",
            "gpu": "",
        },
        "webcam": webcam_info or {},
    }
    with open(output_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def _compute_fps_from_frame_times(frame_records: List[FrameRecord]) -> Optional[float]:
    if len(frame_records) > 1:
        span_ns = frame_records[-1].t_ns - frame_records[0].t_ns
        if span_ns > 0:
            return (len(frame_records) - 1) / (span_ns / 1e9)
    return None


def _compute_fps_from_capture_times(frame_records: List[FrameRecord]) -> Optional[float]:
    captured = [fr for fr in frame_records if not fr.is_duplicate and fr.t_capture_ns is not None]
    if len(captured) > 1:
        span_ns = captured[-1].t_capture_ns - captured[0].t_capture_ns  # type: ignore[operator]
        if span_ns > 0:
            return (len(captured) - 1) / (span_ns / 1e9)
    return None


def _assign_frame_refs(events: List[InputEvent], screen_frames: List[FrameRecord]) -> None:
    if not events or not screen_frames:
        return
    frame_times = [fr.t_ns for fr in screen_frames]
    frame_indices = [fr.frame_index for fr in screen_frames]
    for ev in events:
        idx = bisect.bisect_right(frame_times, ev.t_ns) - 1
        if idx < 0:
            idx = 0
        elif idx >= len(frame_indices):
            idx = len(frame_indices) - 1
        ev.frame_ref = frame_indices[idx]


def run_capture_session(
    duration_seconds: Optional[int] = None,
    fps: int = DEFAULT_FPS,
    allow_any_window: bool = False,
    forced_window: Optional[str] = None,
    enable_webcam: bool = False,
    webcam_device: int = 0,
    webcam_resolution: Optional[Tuple[int, int]] = None,
):
    session_id = str(uuid.uuid4())
    stop_flag = threading.Event()

    def handle_sigint(signum, frame):
        stop_flag.set()

    def on_hotkey_press(key):
        try:
            if hasattr(key, 'char') and key.char == 'q':
                print("\n'q' pressed - stopping capture gracefully...", flush=True)
                stop_flag.set()
        except AttributeError:
            pass

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    # Start hotkey listener for 'q' key
    hotkey_listener = keyboard.Listener(on_press=on_hotkey_press)
    hotkey_listener.start()

    target = wait_for_capture_target(allow_any_window, forced_window, stop_flag)
    if not target:
        print("Capture aborted before start.")
        return
    window_name, bbox = target
    if stop_flag.is_set():
        print("Capture aborted before start.")
        return

    def capture_allowed() -> bool:
        if allow_any_window:
            return True
        name = active_window_name()
        if forced_window:
            return bool(name and forced_window in name)
        return is_allowed_window(name)

    session_dir = Path(f"session_{time.strftime('%Y%m%d_%H%M%S')}")
    session_dir.mkdir(parents=True, exist_ok=True)

    events_q: "queue.SimpleQueue[InputEvent]" = queue.SimpleQueue()
    input_logger = InputLogger(
        events_q,
        session_id=session_id,
        window_id=window_name or "",
        capture_allowed_fn=capture_allowed,
        window_bbox=bbox,
    )
    screen_recorder = ScreenRecorder(
        session_dir,
        fps=fps,
        session_id=session_id,
        window_id=window_name or "",
        capture_allowed_fn=capture_allowed,
        monitor_bbox=bbox,
    )

    webcam_recorder = None
    if enable_webcam:
        webcam_recorder = WebcamRecorder(
            session_dir,
            fps=fps,
            device_index=webcam_device,
            resolution=webcam_resolution,
            capture_allowed_fn=capture_allowed,
        )

    started = False
    error: Optional[BaseException] = None
    start_t_ns: Optional[int] = None
    try:
        input_logger.start()
        screen_recorder.start()
        if webcam_recorder:
            webcam_recorder.start()
        started = True

        start_time = time.time()
        start_t_ns = time.monotonic_ns()
        print(
            f"Recording started (session: {session_id}, window: {window_name}, target_fps: {fps}, "
            f"webcam: {'on' if webcam_recorder else 'off'})",
            flush=True,
        )
        print("Press 'q' in terminal or Ctrl+C to stop capture gracefully.", flush=True)
        while not stop_flag.is_set():
            if duration_seconds and (time.time() - start_time) >= duration_seconds:
                break
            time.sleep(0.1)
    except BaseException as exc:
        error = exc
        stop_flag.set()
        print(f"Capture interrupted: {exc}", flush=True)
    finally:
        # Stop hotkey listener
        hotkey_listener.stop()

        if started:
            end_t_ns = time.monotonic_ns()
            input_logger.stop()
            screen_recorder.stop()
            if webcam_recorder:
                webcam_recorder.stop()

            events: List[InputEvent] = []
            while not events_q.empty():
                events.append(events_q.get())

            _assign_frame_refs(events, screen_recorder.frame_records)

            write_events(
                events,
                screen_recorder.frame_records,
                session_dir,
                session_id=session_id,
                window_id=window_name or "",
                webcam_frames=webcam_recorder.frame_records if webcam_recorder else None,
            )

            actual_fps = _compute_fps_from_frame_times(screen_recorder.frame_records)
            capture_fps = _compute_fps_from_capture_times(screen_recorder.frame_records)
            webcam_actual_fps = (
                _compute_fps_from_frame_times(webcam_recorder.frame_records) if webcam_recorder else None
            )
            webcam_capture_fps = (
                _compute_fps_from_capture_times(webcam_recorder.frame_records) if webcam_recorder else None
            )
            webcam_info = None
            if webcam_recorder:
                webcam_info = {
                    "enabled": True,
                    "device_index": webcam_device,
                    "target_fps": fps,
                    "actual_fps": webcam_actual_fps,
                    "capture_fps": webcam_capture_fps,
                    "dropped_frames": webcam_recorder.dropped_frames,
                    "resolution": webcam_recorder.output_resolution,
                    "padded_frames": webcam_recorder.padded_frames,
                }

            elapsed = time.time() - start_time
            elapsed_ns = (end_t_ns - start_t_ns) if (start_t_ns and end_t_ns) else None
            elapsed_s = (elapsed_ns / 1e9) if elapsed_ns else elapsed
            screen_video_duration_s = len(screen_recorder.frame_records) / float(fps) if fps else 0.0
            dropped_estimated = None
            if fps and elapsed_s:
                expected_frames = int(round(elapsed_s * float(fps)))
                dropped_estimated = max(0, expected_frames - len(screen_recorder.frame_records))

            write_metadata(
                session_dir,
                session_id=session_id,
                fps=fps,
                dropped_frames=screen_recorder.dropped_frames,
                padded_frames=screen_recorder.padded_frames,
                actual_fps=actual_fps,
                capture_fps=capture_fps,
                screen_resolution=(screen_recorder.monitor["width"], screen_recorder.monitor["height"]),
                window_id=window_name or "",
                webcam_info=webcam_info,
                start_t_ns=start_t_ns,
                end_t_ns=end_t_ns,
                dropped_frames_estimated=dropped_estimated,
            )
            fps_msg = f"{actual_fps:.2f}" if actual_fps is not None else "n/a"
            capture_fps_msg = f"{capture_fps:.2f}" if capture_fps is not None else "n/a"
            webcam_msg = (
                f", webcam actual_fps: {webcam_actual_fps:.2f}, capture_fps: {webcam_capture_fps:.2f}, "
                f"dropped_frames: {webcam_recorder.dropped_frames}, padded_frames: {webcam_recorder.padded_frames}"
                if webcam_recorder and webcam_actual_fps is not None and webcam_capture_fps is not None
                else ""
            )
            print(
                f"Recording stopped after {elapsed_s:.1f}s | video_duration_s: {screen_video_duration_s:.1f} | "
                f"frames: {len(screen_recorder.frame_records)} | "
                f"events: {len(events)} | dropped_frames: {screen_recorder.dropped_frames} "
                f"(est {dropped_estimated}) | "
                f"padded_frames: {screen_recorder.padded_frames} | "
                f"actual_fps: {fps_msg}, capture_fps: {capture_fps_msg} (target {fps}){webcam_msg}",
                flush=True,
            )
            print(
                f"Saved session {session_id} to {session_dir} "
                f"(video: frames.mp4 @ {fps} fps, events: events.parquet/events.csv, meta: metadata.json"
                f"{', webcam: webcam.mp4' if webcam_recorder else ''})",
                flush=True,
            )
        else:
            print("Capture not started; nothing to save.")

        if error:
            raise error
