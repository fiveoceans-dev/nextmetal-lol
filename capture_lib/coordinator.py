from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from enum import Enum


class CaptureState(Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    CAPTURING = "capturing"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class FrameData:
    """Unified frame data structure for all modalities."""
    timestamp_ns: int
    frame_index: int
    modality: str  # 'screen', 'webcam', 'audio'
    data: bytes
    metadata: Dict[str, Any]


@dataclass
class CaptureEvent:
    """Synchronized capture event."""
    frame_index: int
    target_timestamp_ns: int
    actual_timestamp_ns: Optional[int] = None
    frames: Dict[str, FrameData] = None
    inputs: List = None

    def __post_init__(self):
        if self.frames is None:
            self.frames = {}
        if self.inputs is None:
            self.inputs = []


class CaptureCoordinator:
    """
    Professional timing coordinator for synchronized multimodal capture.

    Features:
    - High-precision timing using CLOCK_MONOTONIC
    - Event-driven capture triggers
    - Automatic synchronization across modalities
    - Comprehensive error recovery
    - Resource management and cleanup
    """

    def __init__(self, fps: int = 30):
        self.fps = fps
        self.frame_interval_ns = int(1e9 / fps)
        self.state = CaptureState.IDLE

        # Timing
        self.start_time_ns: Optional[int] = None
        self.current_frame_index = 0
        self.next_frame_time_ns: Optional[int] = None

        # Synchronization
        self.capture_barrier = threading.Barrier(4)  # screen, webcam, audio, input
        self.frame_ready = threading.Condition()
        self.current_capture_event: Optional[CaptureEvent] = None

        # Threads
        self.threads: List[threading.Thread] = []
        self.stop_event = threading.Event()

        # Callbacks
        self.on_frame_captured: Optional[Callable[[CaptureEvent], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None

        # Statistics
        self.stats = {
            'frames_captured': 0,
            'frames_dropped': 0,
            'timing_errors': 0,
            'sync_errors': 0,
            'start_time': None,
            'end_time': None
        }

    def start_capture(self) -> bool:
        """Start synchronized capture session."""
        if self.state != CaptureState.IDLE:
            return False

        try:
            self.state = CaptureState.INITIALIZING
            self.start_time_ns = time.monotonic_ns()
            self.next_frame_time_ns = self.start_time_ns
            self.stats['start_time'] = self.start_time_ns

            self.state = CaptureState.CAPTURING
            return True

        except Exception as e:
            self.state = CaptureState.ERROR
            if self.on_error:
                self.on_error(e)
            return False

    def stop_capture(self) -> Dict[str, Any]:
        """Stop capture and return statistics."""
        if self.state != CaptureState.CAPTURING:
            return self.stats

        self.state = CaptureState.STOPPING
        self.stop_event.set()
        self.stats['end_time'] = time.monotonic_ns()

        # Wait for threads to finish
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=2.0)

        self.state = CaptureState.IDLE
        return self.stats

    def wait_for_frame(self, modality: str, timeout_s: float = 1.0) -> Optional[CaptureEvent]:
        """Wait for the next frame to be captured."""
        with self.frame_ready:
            if self.frame_ready.wait(timeout=timeout_s):
                return self.current_capture_event
        return None

    def submit_frame(self, modality: str, frame_data: FrameData) -> None:
        """Submit a captured frame for synchronization."""
        with self.frame_ready:
            if not self.current_capture_event:
                return

            self.current_capture_event.frames[modality] = frame_data

            # Check if all modalities have submitted their frames
            expected_modalities = {'screen', 'webcam', 'audio'}
            submitted_modalities = set(self.current_capture_event.frames.keys())

            if expected_modalities.issubset(submitted_modalities):
                # All frames ready, notify waiting threads
                self.frame_ready.notify_all()

    def create_capture_event(self, frame_index: int) -> CaptureEvent:
        """Create a new synchronized capture event."""
        target_time = self.start_time_ns + (frame_index * self.frame_interval_ns)

        with self.frame_ready:
            self.current_capture_event = CaptureEvent(
                frame_index=frame_index,
                target_timestamp_ns=target_time
            )

        return self.current_capture_event

    def advance_frame(self) -> int:
        """Advance to the next frame and return its index."""
        self.current_frame_index += 1

        # Calculate next target time
        if self.next_frame_time_ns:
            self.next_frame_time_ns += self.frame_interval_ns

        return self.current_frame_index

    def get_timing_stats(self) -> Dict[str, Any]:
        """Get detailed timing statistics."""
        if not self.start_time_ns:
            return {}

        current_time = time.monotonic_ns()
        elapsed_ns = current_time - self.start_time_ns
        expected_frames = elapsed_ns // self.frame_interval_ns

        return {
            'elapsed_seconds': elapsed_ns / 1e9,
            'current_frame': self.current_frame_index,
            'expected_frames': expected_frames,
            'frame_deficit': self.current_frame_index - expected_frames,
            'timing_drift_ns': (current_time - self.next_frame_time_ns) if self.next_frame_time_ns else 0
        }

    def register_thread(self, thread: threading.Thread) -> None:
        """Register a capture thread for management."""
        self.threads.append(thread)

    def handle_error(self, modality: str, error: Exception) -> None:
        """Handle capture errors gracefully."""
        print(f"Error in {modality} capture: {error}", flush=True)
        self.stats['sync_errors'] += 1

        if self.on_error:
            self.on_error(error)
