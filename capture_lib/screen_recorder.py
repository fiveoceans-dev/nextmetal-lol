from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import mss

from .ffmpeg_writer import FfmpegVideoWriter


@dataclass
class FrameRecord:
    frame_index: int
    t_ns: int
    t_capture_ns: Optional[int] = None
    is_duplicate: bool = False


class ScreenRecorder:
    def __init__(
        self,
        output_dir,
        fps: int,
        session_id: str,
        window_id: str,
        capture_allowed_fn: Optional[Callable[[], bool]] = None,
        monitor_bbox: Optional[Dict[str, int]] = None,
    ):
        self.output_dir = output_dir
        self.fps = fps
        self.session_id = session_id
        self.window_id = window_id
        self.capture_allowed_fn = capture_allowed_fn or (lambda: True)
        self.stop_event = threading.Event()
        self.frame_records: List[FrameRecord] = []
        self.video_writer: Optional[FfmpegVideoWriter] = None
        self.thread: Optional[threading.Thread] = None
        self.frame_index = 0
        self.dropped_frames = 0
        self.padded_frames = 0
        self.interval_s = 1.0 / float(self.fps)
        self.sct = mss.mss()
        self.monitor = monitor_bbox or self.sct.monitors[0]

    def _init_writer(self):
        width = self.monitor["width"]
        height = self.monitor["height"]
        self.video_writer = FfmpegVideoWriter(
            self.output_dir / "frames.mp4",
            width=width,
            height=height,
            fps=self.fps,
            pixel_format="rgb24",
        )
        print(f"Recording video at {self.fps} fps, resolution {width}x{height}", flush=True)

    def start(self):
        self._init_writer()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.video_writer:
            self.video_writer.close()
        self.sct.close()

    def _capture_loop(self):
        if not self.video_writer:
            return

        frame_interval_ns = int(self.interval_s * 1e9)  # Convert to nanoseconds for precision
        next_frame_time_ns = time.monotonic_ns()

        while not self.stop_event.is_set():
            if not self.capture_allowed_fn():
                time.sleep(0.05)
                next_frame_time_ns = time.monotonic_ns() + frame_interval_ns
                continue

            current_time_ns = time.monotonic_ns()

            # If we're behind schedule, skip frames to catch up
            if current_time_ns >= next_frame_time_ns + frame_interval_ns:
                # We're more than one frame behind, skip to next scheduled frame
                frames_to_skip = int((current_time_ns - next_frame_time_ns) / frame_interval_ns)
                next_frame_time_ns += frames_to_skip * frame_interval_ns
                self.dropped_frames += frames_to_skip
                continue

            # Wait until exactly the right time for this frame
            sleep_time = (next_frame_time_ns - current_time_ns) / 1e9
            if sleep_time > 0:
                time.sleep(sleep_time)

            # Capture frame at precise time
            capture_start_ns = time.monotonic_ns()
            shot = self.sct.grab(self.monitor)

            # mss provides RGB bytes for fast pipe -> ffmpeg encoding.
            frame_bytes = getattr(shot, "rgb", None)
            if frame_bytes is None:
                # Fallback: raw BGRA -> RGB via numpy (slower).
                raw = getattr(shot, "raw", None)
                if raw is None:
                    raise RuntimeError("mss screenshot does not expose rgb/raw buffers")
                import numpy as np  # type: ignore

                width = int(self.monitor["width"])
                height = int(self.monitor["height"])
                bgra = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4))
                rgb = bgra[:, :, 2::-1]
                frame_bytes = rgb.tobytes()

            # Write frame immediately after capture for minimal latency
            self.video_writer.write(frame_bytes)
            capture_end_ns = time.monotonic_ns()

            self.frame_records.append(
                FrameRecord(self.frame_index, t_ns=capture_start_ns, t_capture_ns=capture_start_ns, is_duplicate=False)
            )
            self.frame_index += 1

            # Schedule next frame precisely
            next_frame_time_ns += frame_interval_ns
