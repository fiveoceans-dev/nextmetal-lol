from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional, Tuple

import cv2

from .ffmpeg_writer import FfmpegVideoWriter
from .screen_recorder import FrameRecord


class WebcamRecorder:
    def __init__(
        self,
        output_dir,
        fps: int,
        device_index: int = 0,
        resolution: Optional[Tuple[int, int]] = None,
        capture_allowed_fn: Optional[Callable[[], bool]] = None,
    ):
        self.output_dir = output_dir
        self.fps = fps
        self.device_index = device_index
        self.resolution = resolution
        self.capture_allowed_fn = capture_allowed_fn or (lambda: True)
        self.stop_event = threading.Event()
        self.video_writer: Optional[FfmpegVideoWriter] = None
        self.cap = None
        self.thread: Optional[threading.Thread] = None
        self.frame_records: List[FrameRecord] = []
        self.frame_index = 0
        self.dropped_frames = 0
        self.output_resolution: Optional[Tuple[int, int]] = None
        self.padded_frames = 0
        self.interval_s = 1.0 / float(self.fps)
        self.primed_frame = None

    def _init_devices(self):
        self.cap = cv2.VideoCapture(self.device_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open webcam device {self.device_index}")
        if self.resolution:
            width, height = self.resolution
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        self.cap.set(cv2.CAP_PROP_FPS, float(self.fps))
        try:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass
        ret, frame = self.cap.read()
        if not ret or frame is None:
            raise RuntimeError("Failed to read from webcam")
        height, width = frame.shape[:2]
        self.output_resolution = (width, height)
        self.video_writer = FfmpegVideoWriter(
            self.output_dir / "webcam.mp4",
            width=width,
            height=height,
            fps=self.fps,
            pixel_format="bgr24",
        )
        print(f"Recording webcam at {self.fps} fps, resolution {width}x{height}, device {self.device_index}", flush=True)
        self.primed_frame = frame

    def start(self):
        self._init_devices()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.video_writer:
            self.video_writer.close()
        if self.cap:
            self.cap.release()

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

            if not self.cap:
                break

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

            if self.primed_frame is not None:
                frame = self.primed_frame
                self.primed_frame = None
            else:
                # Read the most recent frame (avoid lagging buffers).
                try:
                    self.cap.grab()
                    self.cap.grab()
                except Exception:
                    pass
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    next_frame_time_ns += frame_interval_ns
                    self.dropped_frames += 1
                    continue

            # Write frame immediately after capture for minimal latency
            self.video_writer.write(frame.tobytes())
            capture_end_ns = time.monotonic_ns()

            self.frame_records.append(
                FrameRecord(self.frame_index, t_ns=capture_start_ns, t_capture_ns=capture_start_ns, is_duplicate=False)
            )
            self.frame_index += 1

            # Schedule next frame precisely
            next_frame_time_ns += frame_interval_ns
