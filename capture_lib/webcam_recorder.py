from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import cv2

from .constants import FRAME_CODEC
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
        self.video_writer = None
        self.cap = None
        self.frame_records: List[FrameRecord] = []
        self.frame_index = 0
        self.last_capture_start: Optional[float] = None
        self.dropped_frames = 0
        self.output_resolution: Optional[Tuple[int, int]] = None

    def _init_devices(self):
        self.cap = cv2.VideoCapture(self.device_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open webcam device {self.device_index}")
        if self.resolution:
            width, height = self.resolution
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, float(self.fps))
        ret, frame = self.cap.read()
        if not ret or frame is None:
            raise RuntimeError("Failed to read from webcam")
        height, width = frame.shape[:2]
        self.output_resolution = (width, height)
        fourcc = cv2.VideoWriter_fourcc(*FRAME_CODEC)
        self.video_writer = cv2.VideoWriter(
            str(self.output_dir / "webcam.mp4"), fourcc, float(self.fps), (width, height)
        )
        print(f"Recording webcam at {self.fps} fps, resolution {width}x{height}, device {self.device_index}", flush=True)
        # write first frame immediately so we don't lose it
        self.video_writer.write(frame)
        self.frame_records.append(FrameRecord(self.frame_index, time.monotonic_ns()))
        self.frame_index += 1

    def start(self):
        self._init_devices()
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        time.sleep(0.1)
        if self.video_writer:
            self.video_writer.release()
        if self.cap:
            self.cap.release()

    def _capture_loop(self):
        interval = 1.0 / float(self.fps)
        next_capture = time.perf_counter()
        while not self.stop_event.is_set():
            now = time.perf_counter()
            sleep_for = next_capture - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            capture_start = time.perf_counter()

            if not self.capture_allowed_fn():
                next_capture = capture_start + interval
                continue

            if self.last_capture_start is not None:
                elapsed = capture_start - self.last_capture_start
                if elapsed > interval * 1.1:
                    missed = int(elapsed / interval) - 1
                    if missed > 0:
                        self.dropped_frames += missed
            self.last_capture_start = capture_start

            if not self.cap:
                break
            ret, frame = self.cap.read()
            if not ret or frame is None:
                next_capture = capture_start + interval
                continue
            self.video_writer.write(frame)
            self.frame_records.append(FrameRecord(self.frame_index, time.monotonic_ns()))
            self.frame_index += 1
            next_capture = capture_start + interval
