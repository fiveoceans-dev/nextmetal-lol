from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

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
        self.frame_interval_ns = int(1_000_000_000 / max(1, self.fps))
        self.last_frame_bytes: Optional[bytes] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.reader_stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._latest_capture_ns: Optional[int] = None
        self._last_consumed_capture_ns: Optional[int] = None
        self.blank_frame: Optional[bytes] = None

    def _init_devices(self):
        try:
            self.cap = cv2.VideoCapture(self.device_index)
            if not self.cap.isOpened():
                raise RuntimeError(f"Could not open webcam device {self.device_index} - camera may not be available or permissions denied")
        except Exception as e:
            error_str = str(e)
            if "access has been denied" in error_str.lower() or "camera" in error_str.lower():
                raise RuntimeError(f"Camera access denied. Grant camera permissions in System Settings > Privacy & Security > Camera\nOriginal error: {e}")
            else:
                raise
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
        self.blank_frame = np.zeros((height, width, 3), dtype=np.uint8).tobytes()
        self.last_frame_bytes = self.blank_frame
        try:
            self.video_writer = FfmpegVideoWriter(
                self.output_dir / "webcam.mp4",
                width=width,
                height=height,
                fps=self.fps,
                pixel_format="bgr24",
            )
            print(f"Recording webcam at {self.fps} fps, resolution {width}x{height}, device {self.device_index}", flush=True)
        except Exception as e:
            if self.cap:
                self.cap.release()
            raise RuntimeError(f"Failed to initialize webcam video writer: {e}") from e
        with self._frame_lock:
            self._latest_frame = frame
            self._latest_capture_ns = time.monotonic_ns()
        self.last_frame_bytes = frame.tobytes()

    def start(self):
        self._init_devices()
        self.reader_stop.clear()
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()
        self.thread = threading.Thread(target=self._capture_frames_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.reader_stop.set()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2.0)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.video_writer:
            self.video_writer.close()
        if self.cap:
            self.cap.release()

    def _capture_frames_loop(self):
        """Main capture loop with precise timing."""
        frame_interval_ns = self.frame_interval_ns
        next_frame_time = time.monotonic_ns()

        while not self.stop_event.is_set():
            try:
                current_ns = time.monotonic_ns()
                if current_ns < next_frame_time:
                    sleep_time = (next_frame_time - current_ns) / 1e9
                    if sleep_time > 0:
                        time.sleep(min(sleep_time, 0.1))
                    continue

                target_ns = next_frame_time
                next_frame_time += frame_interval_ns

                frame_bytes: Optional[bytes] = None
                capture_ns: Optional[int] = None
                duplicate = False

                frame_info = None
                allowed = self.capture_allowed_fn()
                if allowed:
                    frame_info = self._consume_latest_frame()

                if not allowed or frame_info is None:
                    frame_bytes = self.last_frame_bytes or self.blank_frame
                    duplicate = True
                else:
                    frame, capture_ns, stale = frame_info
                    if stale and self.last_frame_bytes is not None:
                        frame_bytes = self.last_frame_bytes
                        duplicate = True
                    else:
                        frame_bytes = frame.tobytes()
                        self.last_frame_bytes = frame_bytes
                        capture_ns = capture_ns or target_ns
                        duplicate = False

                if frame_bytes is None:
                    frame_bytes = self.blank_frame
                    duplicate = True

                self.frame_records.append(
                    FrameRecord(
                        self.frame_index,
                        t_ns=target_ns,
                        t_capture_ns=capture_ns if (capture_ns and not duplicate) else None,
                        is_duplicate=duplicate,
                    )
                )
                self.frame_index += 1
                if duplicate:
                    self.padded_frames += 1

                self.video_writer.write(frame_bytes)

            except Exception as e:
                print(f"Warning: Webcam frame capture failed: {e}", flush=True)
                self.dropped_frames += 1
                time.sleep(0.01)  # Brief pause on error

    def _reader_loop(self):
        while not self.reader_stop.is_set():
            if not self.capture_allowed_fn():
                time.sleep(0.05)
                continue
            if not self.cap:
                break
            ret, frame = self.cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue
            capture_ns = time.monotonic_ns()
            with self._frame_lock:
                self._latest_frame = frame
                self._latest_capture_ns = capture_ns

    def _consume_latest_frame(self):
        with self._frame_lock:
            frame = self._latest_frame
            capture_ns = self._latest_capture_ns
        if frame is None:
            return None
        stale = capture_ns == self._last_consumed_capture_ns
        if not stale:
            self._last_consumed_capture_ns = capture_ns
        return frame, capture_ns, stale
