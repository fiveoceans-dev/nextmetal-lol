from __future__ import annotations

import json
import bisect
import queue
import signal
import threading
import time
import uuid
import contextlib
import wave
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import platform
from pynput import keyboard

from .constants import DEFAULT_FPS, FRAME_CODEC
from .input_logging import InputEvent, InputLogger
from .screen_recorder import FrameRecord, ScreenRecorder
from .webcam_recorder import WebcamRecorder
from .audio_recorder import AudioRecorder
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
    if not rows:
        print("Warning: No frame or event data captured, skipping events file")
        return

    df = pd.DataFrame(rows)
    df = df.sort_values("t_ns", kind="mergesort").reset_index(drop=True)
    parquet_path = output_dir / "events.parquet"
    csv_path = output_dir / "events.csv"
    df.to_parquet(parquet_path, compression="snappy", index=False)
    df.to_csv(csv_path, index=False)


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
    audio_info: Optional[Dict[str, object]] = None,
    start_t_ns: Optional[int] = None,
    end_t_ns: Optional[int] = None,
    dropped_frames_estimated: Optional[int] = None,
    validation: Optional[Dict[str, any]] = None,
    trajectories: Optional[List[Dict[str, any]]] = None,
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
        "audio": audio_info or {},
        "validation": validation or {},
        "dataset_format": {
            "version": "1.0.0",
            "compatible_with": ["RLDS", "D4RL", "OpenAI Gym"],
            "modalities": ["screen_video", "input_events"] +
                        (["webcam_video"] if webcam_info and webcam_info.get("enabled") else []) +
                        (["game_audio"] if audio_info and audio_info.get("enabled") else []),
            "primary_use": "reinforcement_learning",
            "trajectory_format": "time_aligned_multimodal"
        },
        "trajectories": trajectories or [],
    }
    with open(output_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def _extract_audio_from_video(video_path: Path, output_wav: Path) -> Optional[Dict[str, Any]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("⚠️  ffmpeg not found; cannot extract audio track from video", flush=True)
        return None
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(output_wav),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = result.stderr.strip() if result.stderr else ""
        print(f"⚠️  Failed to extract audio track: {tail}", flush=True)
        return None

    info: Dict[str, Any] = {
        "format": "wav",
        "sample_rate": 44100,
        "channels": 2,
        "file_path": str(output_wav),
        "file_size": output_wav.stat().st_size if output_wav.exists() else None,
        "source": "video_track",
    }
    try:
        with contextlib.closing(wave.open(str(output_wav), "rb")) as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            info["duration_seconds"] = frames / float(rate) if rate else None
    except Exception:
        pass
    return info


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


def validate_capture_data(
    events: List[InputEvent],
    screen_frames: List[FrameRecord],
    webcam_frames: Optional[List[FrameRecord]] = None,
    fps: int = 30
) -> Dict[str, any]:
    """Validate data integrity and return statistics."""
    validation = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "stats": {}
    }

    # Check timestamp monotonicity
    if events:
        timestamps = [ev.t_ns for ev in events]
        if timestamps != sorted(timestamps):
            validation["errors"].append("Input event timestamps are not monotonic")

    if screen_frames:
        frame_times = [fr.t_ns for fr in screen_frames]
        if frame_times != sorted(frame_times):
            validation["errors"].append("Screen frame timestamps are not monotonic")

    # Check frame rate consistency
    if screen_frames and len(screen_frames) > 1:
        expected_frame_interval_ns = int(1e9 / fps)  # nanoseconds per frame
        actual_intervals = []
        for i in range(1, len(screen_frames)):
            interval = screen_frames[i].t_ns - screen_frames[i-1].t_ns
            actual_intervals.append(interval)

        avg_interval = sum(actual_intervals) / len(actual_intervals)
        deviation = abs(avg_interval - expected_frame_interval_ns) / expected_frame_interval_ns

        if deviation > 0.1:  # 10% deviation
            validation["warnings"].append(
                f"Screen frame cadence deviates {deviation * 100:.2f}% from target interval"
            )

        validation["stats"]["avg_frame_interval_ns"] = avg_interval
        validation["stats"]["expected_frame_interval_ns"] = expected_frame_interval_ns

    # Check for missing frames
    if screen_frames:
        expected_frames = len(screen_frames)
        actual_frames = max((fr.frame_index for fr in screen_frames), default=0) + 1
        if actual_frames != expected_frames:
            validation["warnings"].append(f"Frame index gap detected: expected {expected_frames}, got {actual_frames}")

    # Check webcam sync if present
    if webcam_frames and screen_frames:
        webcam_times = [fr.t_ns for fr in webcam_frames]
        screen_times = [fr.t_ns for fr in screen_frames]

        # Webcam should have similar timing to screen
        if len(webcam_times) > 0 and len(screen_times) > 0:
            time_diff = abs(webcam_times[0] - screen_times[0])
            if time_diff > 1e9:  # 1 second difference
                validation["warnings"].append(
                    f"Webcam timestamps start {time_diff / 1e9:.3f}s away from screen frames"
                )

    validation["stats"]["total_events"] = len(events)
    validation["stats"]["total_frames"] = len(screen_frames)
    validation["stats"]["total_webcam_frames"] = len(webcam_frames) if webcam_frames else 0

    validation["valid"] = len(validation["errors"]) == 0
    return validation


def segment_trajectories(
    events: List[InputEvent],
    screen_frames: List[FrameRecord],
    trajectory_duration_s: float = 60.0,  # 1 minute trajectories
    overlap_s: float = 5.0  # 5 second overlap
) -> List[Dict[str, any]]:
    """Segment continuous capture into RL trajectories."""
    if not events or not screen_frames:
        return []

    trajectories = []
    start_time_ns = min(ev.t_ns for ev in events)
    end_time_ns = max(ev.t_ns for ev in events)

    trajectory_duration_ns = int(trajectory_duration_s * 1e9)
    overlap_ns = int(overlap_s * 1e9)

    current_start = start_time_ns

    while current_start < end_time_ns:
        current_end = min(current_start + trajectory_duration_ns, end_time_ns)

        # Get events in this trajectory
        traj_events = [ev for ev in events if current_start <= ev.t_ns <= current_end]

        # Get frames in this trajectory
        traj_frames = [fr for fr in screen_frames if current_start <= fr.t_ns <= current_end]

        if traj_events and traj_frames:  # Only create trajectory if it has both events and frames
            trajectory = {
                "trajectory_id": f"traj_{len(trajectories):04d}",
                "start_time_ns": current_start,
                "end_time_ns": current_end,
                "duration_s": (current_end - current_start) / 1e9,
                "event_count": len(traj_events),
                "frame_count": len(traj_frames),
                "events_start_idx": len(events) - len([ev for ev in events if ev.t_ns >= current_start]),
                "frames_start_idx": len(screen_frames) - len([fr for fr in screen_frames if fr.t_ns >= current_start]),
                "metadata": {
                    "overlap_with_previous": overlap_s if current_start > start_time_ns else 0.0,
                    "game_phase": "unknown",  # Could be enhanced with game state detection
                    "quality_score": min(1.0, len(traj_events) / 100.0)  # Basic quality heuristic
                }
            }
            trajectories.append(trajectory)

        # Move to next trajectory with overlap
        current_start += trajectory_duration_ns - overlap_ns

    return trajectories


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
    enable_audio: bool = False,
    audio_device: Optional[str] = None,
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())

    # Error tracking
    capture_error: Optional[BaseException] = None

    # Create stop event for window detection
    stop_event = threading.Event()

    def handle_sigint(signum, frame):
        stop_event.set()

    def on_hotkey_press(key):
        try:
            if hasattr(key, 'char') and key.char == 'q':
                print("\n'q' pressed - stopping capture gracefully...", flush=True)
                stop_event.set()
        except AttributeError:
            pass

    # Set up signal handlers
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    # Start hotkey listener for 'q' key
    hotkey_listener = keyboard.Listener(on_press=on_hotkey_press)
    hotkey_listener.start()

    # Wait for capture target
    target = wait_for_capture_target(allow_any_window, forced_window, stop_event)
    if not target:
        print("Capture aborted before start.")
        hotkey_listener.stop()
        return {}
    window_name, bbox = target

    def capture_allowed() -> bool:
        if allow_any_window:
            return True
        name = active_window_name()
        if forced_window:
            return bool(name and forced_window in name)
        return is_allowed_window(name)

    system_name = platform.system()
    embed_audio_in_video = enable_audio and system_name == "Darwin"
    audio_device_name = audio_device
    if embed_audio_in_video and not audio_device_name:
        audio_device_name = "BlackHole 2ch"

    # Create session directory
    session_dir = Path(f"session_{time.strftime('%Y%m%d_%H%M%S')}")
    session_dir.mkdir(parents=True, exist_ok=True)

    # Create synchronized recorders
    events_q: "queue.SimpleQueue[InputEvent]" = queue.SimpleQueue()
    input_logger = InputLogger(
        events_q,
        session_id=session_id,
        window_id=window_name or "",
        capture_allowed_fn=capture_allowed,
        window_bbox=bbox,
    )

    screen_recorder = None
    try:
        screen_recorder = ScreenRecorder(
            session_dir,
            fps=fps,
            session_id=session_id,
            window_id=window_name or "",
            capture_allowed_fn=capture_allowed,
            monitor_bbox=bbox,
            audio_device=audio_device_name if embed_audio_in_video else None,
        )
        audio_status = "embedded" if embed_audio_in_video and screen_recorder.has_audio_track else "off"
        print(f"🖥️  Screen recording enabled (audio: {audio_status})", flush=True)
    except Exception as e:
        print(f"⚠️  Screen recording disabled: {e}", flush=True)
        print("   Webcam and audio recording will continue if available", flush=True)
        screen_recorder = None

    webcam_recorder = None
    if enable_webcam:
        try:
            # Webcam recorder with consistent timing
            webcam_recorder = WebcamRecorder(
                session_dir,
                fps=fps,  # Temporary - will redesign later
                device_index=webcam_device,
                resolution=webcam_resolution,
                capture_allowed_fn=capture_allowed,
            )
            print("📹 Webcam recording enabled", flush=True)
        except Exception as e:
            print(f"⚠️  Webcam recording disabled: {e}", flush=True)
            print("   Screen and audio recording will continue", flush=True)
            webcam_recorder = None

    audio_recorder = None
    if enable_audio and not (embed_audio_in_video and screen_recorder and screen_recorder.has_audio_track):
        audio_recorder = AudioRecorder(
            session_dir,
            fps=fps,  # Temporary - will redesign later
            session_id=session_id,
            capture_allowed_fn=capture_allowed,
        )

    start_t_ns: Optional[int] = None
    end_t_ns: Optional[int] = None
    capture_started = False
    start_wall = None

    try:
        input_logger.start()
        if screen_recorder:
            screen_recorder.start()
        if webcam_recorder:
            webcam_recorder.start()
        if audio_recorder:
            audio_recorder.start()

        start_t_ns = time.monotonic_ns()
        start_wall = time.time()
        capture_started = True
        audio_mode = "embedded" if embed_audio_in_video else ("on" if audio_recorder else "off")
        print(
            f"Recording started (session: {session_id}, window: {window_name}, target_fps: {fps}, "
            f"webcam: {'on' if webcam_recorder else 'off'}, audio: {audio_mode})",
            flush=True,
        )
        print("Press 'q' in terminal or Ctrl+C to stop capture gracefully.", flush=True)

        while not stop_event.is_set():
            if duration_seconds and start_wall and (time.time() - start_wall) >= duration_seconds:
                break
            time.sleep(0.1)
    except BaseException as exc:
        capture_error = exc
        print(f"Capture interrupted: {exc}", flush=True)
    finally:
        stop_event.set()
        if audio_recorder:
            audio_recorder.stop()
        if webcam_recorder:
            webcam_recorder.stop()
        if screen_recorder:
            screen_recorder.stop()
        input_logger.stop()
        hotkey_listener.stop()
        end_t_ns = time.monotonic_ns()

    events: List[InputEvent] = []
    while not events_q.empty():
        events.append(events_q.get())

    if screen_recorder and screen_recorder.frame_records:
        _assign_frame_refs(events, screen_recorder.frame_records)

    validation = validate_capture_data(
        events,
        screen_recorder.frame_records if screen_recorder else [],
        webcam_frames=webcam_recorder.frame_records if webcam_recorder else None,
        fps=fps,
    )

    trajectories = segment_trajectories(
        events,
        screen_recorder.frame_records if screen_recorder else [],
        trajectory_duration_s=60.0,
        overlap_s=5.0,
    )

    if screen_recorder or events:
        write_events(
            events,
            screen_recorder.frame_records if screen_recorder else [],
            session_dir,
            session_id=session_id,
            window_id=window_name or "",
            webcam_frames=webcam_recorder.frame_records if webcam_recorder else None,
        )

    screen_frames = screen_recorder.frame_records if screen_recorder else []
    actual_fps = _compute_fps_from_frame_times(screen_frames)
    capture_fps = _compute_fps_from_capture_times(screen_frames)
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

    audio_info = None
    if screen_recorder and screen_recorder.has_audio_track:
        wav_path = session_dir / "audio.wav"
        extracted = _extract_audio_from_video(screen_recorder.output_path, wav_path)
        if extracted:
            audio_info = extracted
            audio_info["enabled"] = True
            print(f"🎧 Extracted embedded audio track to {wav_path}", flush=True)
        else:
            audio_info = {"enabled": True, "source": "video_track", "error": "extraction_failed"}
    elif audio_recorder:
        audio_info = audio_recorder.get_audio_info()
        if audio_info:
            audio_info["enabled"] = True
        else:
            audio_info = {"enabled": False, "error": "Audio capture failed"}

    elapsed_s = None
    if start_t_ns and end_t_ns:
        elapsed_ns = max(0, end_t_ns - start_t_ns)
        elapsed_s = elapsed_ns / 1e9
    elif capture_started and start_wall:
        elapsed_s = max(0.0, time.time() - start_wall)

    screen_frames_count = len(screen_frames)
    screen_video_duration_s = screen_frames_count / float(fps) if fps else 0.0
    dropped_estimated = None
    if fps and elapsed_s is not None:
        expected_frames = int(round(elapsed_s * float(fps)))
        dropped_estimated = max(0, expected_frames - screen_frames_count)

    write_metadata(
        session_dir,
        session_id=session_id,
        fps=fps,
        dropped_frames=screen_recorder.dropped_frames if screen_recorder else 0,
        padded_frames=screen_recorder.padded_frames if screen_recorder else 0,
        actual_fps=actual_fps,
        capture_fps=capture_fps,
        screen_resolution=(
            (screen_recorder.monitor["width"], screen_recorder.monitor["height"])
            if screen_recorder
            else (0, 0)
        ),
        window_id=window_name or "",
        webcam_info=webcam_info,
        audio_info=audio_info,
        start_t_ns=start_t_ns,
        end_t_ns=end_t_ns,
        dropped_frames_estimated=dropped_estimated,
        validation=validation,
        trajectories=trajectories,
    )

    fps_msg = f"{actual_fps:.2f}" if actual_fps is not None else "n/a"
    capture_fps_msg = f"{capture_fps:.2f}" if capture_fps is not None else "n/a"
    webcam_msg = (
        f", webcam actual_fps: {webcam_actual_fps:.2f}, capture_fps: {webcam_capture_fps:.2f}, "
        f"dropped_frames: {webcam_recorder.dropped_frames}, padded_frames: {webcam_recorder.padded_frames}"
        if webcam_recorder and webcam_actual_fps is not None and webcam_capture_fps is not None
        else ""
    )
    safe_elapsed = elapsed_s if elapsed_s is not None else 0.0
    safe_video = screen_video_duration_s if screen_video_duration_s is not None else 0.0

    print(
        f"Recording stopped after {safe_elapsed:.1f}s | video_duration_s: {safe_video:.1f} | "
        f"frames: {screen_frames_count} | events: {len(events)} | dropped_frames: "
        f"{screen_recorder.dropped_frames if screen_recorder else 0} (est {dropped_estimated}) | "
        f"padded_frames: {screen_recorder.padded_frames if screen_recorder else 0} | "
        f"actual_fps: {fps_msg}, capture_fps: {capture_fps_msg} (target {fps}){webcam_msg}",
        flush=True,
    )

    audio_suffix = ""
    if audio_info and audio_info.get("enabled"):
        source_desc = audio_info.get("source", "mic")
        fmt = audio_info.get("format", "wav")
        audio_suffix = f", audio: {fmt} ({source_desc})"

    print(
        f"Saved session {session_id} to {session_dir} "
        f"(video: frames.mp4 @ {fps} fps, events: events.parquet + events.csv, meta: metadata.json"
        f"{', webcam: webcam.mp4' if webcam_recorder else ''}{audio_suffix})",
        flush=True,
    )

    if capture_error:
        raise capture_error

    return {
        "session_id": session_id,
        "duration_s": elapsed_s or 0.0,
        "frames_captured": screen_frames_count,
    }
