from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import cv2
import mss
import numpy as np

from .constants import FRAME_CODEC


@dataclass
class FrameRecord:
    frame_index: int
    t_ns: int


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
        self.video_writer = None
        self.frame_index = 0
        self.last_capture_start: Optional[float] = None
        self.dropped_frames = 0
        self.sct = mss.mss()
        self.monitor = monitor_bbox or self.sct.monitors[0]

    def _init_writer(self):
        width = self.monitor["width"]
        height = self.monitor["height"]
        fourcc = cv2.VideoWriter_fourcc(*FRAME_CODEC)
        self.video_writer = cv2.VideoWriter(
            str(self.output_dir / "frames.mp4"), fourcc, float(self.fps), (width, height)
        )
        print(f"Recording video at {self.fps} fps, resolution {width}x{height}", flush=True)

    def start(self):
        self._init_writer()
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        time.sleep(0.1)
        if self.video_writer:
            self.video_writer.release()
        self.sct.close()

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

            frame_time_ns = time.monotonic_ns()
            img = np.array(self.sct.grab(self.monitor))
            frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            self.video_writer.write(frame)
            self.frame_records.append(FrameRecord(self.frame_index, frame_time_ns))
            self.frame_index += 1
            next_capture = capture_start + interval

