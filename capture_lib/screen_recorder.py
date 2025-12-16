from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
import ctypes
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import mss  # type: ignore
except Exception:  # pragma: no cover - mss only needed on desktop hosts.
    mss = None

from .ffmpeg_writer import FfmpegVideoWriter


@dataclass
class FrameRecord:
    frame_index: int
    t_ns: int
    t_capture_ns: Optional[int] = None
    is_duplicate: bool = False


class ScreenRecorder:
    """Platform-aware screen recorder that captures only the target LoL window."""

    def __init__(
        self,
        output_dir: Path,
        fps: int,
        session_id: str,
        window_id: str,
        capture_allowed_fn: Optional[Callable[[], bool]] = None,
        monitor_bbox: Optional[Dict[str, int]] = None,
        audio_device: Optional[str] = None,
    ):
        system = platform.system()
        if system == "Darwin":
            self._recorder = _MacScreenRecorder(
                output_dir=output_dir,
                fps=fps,
                session_id=session_id,
                window_id=window_id,
                monitor_bbox=monitor_bbox,
                audio_device=audio_device,
            )
        else:
            self._recorder = _MssScreenRecorder(
                output_dir=output_dir,
                fps=fps,
                session_id=session_id,
                window_id=window_id,
                capture_allowed_fn=capture_allowed_fn,
                monitor_bbox=monitor_bbox,
            )

    def start(self) -> None:
        self._recorder.start()

    def stop(self) -> None:
        self._recorder.stop()

    # Proxy frequently-used attributes for callers.
    @property
    def frame_records(self) -> List[FrameRecord]:
        return self._recorder.frame_records

    @property
    def dropped_frames(self) -> int:
        return self._recorder.dropped_frames

    @property
    def padded_frames(self) -> int:
        return self._recorder.padded_frames

    @property
    def monitor(self) -> Dict[str, int]:
        return self._recorder.monitor

    @property
    def output_path(self) -> Path:
        return self._recorder.output_path

    @property
    def start_t_ns(self) -> Optional[int]:
        return getattr(self._recorder, "start_t_ns", None)

    @property
    def end_t_ns(self) -> Optional[int]:
        return getattr(self._recorder, "end_t_ns", None)

    @property
    def has_audio_track(self) -> bool:
        return bool(getattr(self._recorder, "has_audio_track", False))

    @property
    def audio_source(self) -> Optional[str]:
        return getattr(self._recorder, "audio_device_name", None)


class _BaseScreenRecorder:
    output_path: Path
    monitor: Dict[str, int]
    frame_records: List[FrameRecord]
    dropped_frames: int
    padded_frames: int

    def start(self) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - interface only
        raise NotImplementedError


class _MacScreenRecorder(_BaseScreenRecorder):
    """
    High-performance macOS recorder.

    Uses ffmpeg/avfoundation to record the exact Riot/LoL window crop at a constant
    30 FPS so downstream mp4 playback matches real-time duration.
    """

    def __init__(
        self,
        output_dir: Path,
        fps: int,
        session_id: str,
        window_id: str,
        monitor_bbox: Optional[Dict[str, Any]],
        audio_device: Optional[str] = None,
    ):
        if not monitor_bbox:
            raise RuntimeError(
                "Could not resolve window bounds. Ensure Screen Recording + Accessibility permissions are granted."
            )

        self.output_dir = output_dir
        self.output_path = output_dir / "frames.mp4"
        self.fps = fps
        self.session_id = session_id
        self.window_id = window_id
        self.audio_device_name = audio_device

        self.bounds_pt = {
            "left": float(monitor_bbox.get("left", 0) or 0),
            "top": float(monitor_bbox.get("top", 0) or 0),
            "width": float(monitor_bbox.get("width", 0) or 0),
            "height": float(monitor_bbox.get("height", 0) or 0),
        }

        self.frame_records: List[FrameRecord] = []
        self.dropped_frames = 0
        self.padded_frames = 0
        self.start_t_ns: Optional[int] = None
        self.end_t_ns: Optional[int] = None
        self.has_audio_track = False
        self._audio_device_index: Optional[int] = None
        self._avfoundation_listing: Optional[str] = None

        self._ffmpeg = shutil.which("ffmpeg")
        self._ffprobe = shutil.which("ffprobe")
        if not self._ffmpeg or not self._ffprobe:
            raise RuntimeError("ffmpeg/ffprobe is required on macOS. Install via `brew install ffmpeg`.")

        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_lines: List[str] = []
        self._stop_event = threading.Event()

        self._display_layout = self._load_display_layout()
        self._display_info = self._select_display_for_bounds(self.bounds_pt)
        self.bounds_px = self._resolve_pixel_bounds(monitor_bbox, self._display_info)

        if not self.bounds_px["width"] or not self.bounds_px["height"]:
            raise RuntimeError("Resolved League window bounds are empty; ensure the client is visible.")

        self.monitor = {
            "width": self._even(int(self.bounds_px["width"])),
            "height": self._even(int(self.bounds_px["height"])),
            "left": int(self.bounds_px["left"]),
            "top": int(self.bounds_px["top"]),
        }

        self._display_index = int(self._display_info["index"]) if self._display_info else 0
        self._device_index = self._pick_screen_device(self._display_index)
        if self._device_index is None:
            raise RuntimeError("Could not map League window to an avfoundation screen device.")

        if self.audio_device_name:
            audio_pick = self._pick_audio_device(self.audio_device_name)
            if not audio_pick:
                raise RuntimeError(
                    f"Audio device '{self.audio_device_name}' not found. "
                    "Use --audio-device to specify a valid loopback (e.g., 'BlackHole 2ch')."
                )
            self._audio_device_index, resolved_name = audio_pick
            if resolved_name.lower() != self.audio_device_name.lower():
                print(
                    f"ℹ️  Using audio device '{resolved_name}' for embedded capture (requested '{self.audio_device_name}')",
                    flush=True,
                )
            self.audio_device_name = resolved_name
            self.has_audio_track = True
        else:
            self._audio_device_index = None
            self.has_audio_track = False

    def start(self) -> None:
        self.start_t_ns = time.monotonic_ns()
        cmd = self._build_command()
        try:
            self._ffmpeg_proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:  # pragma: no cover - best-effort logging
            raise RuntimeError(f"Failed to launch ffmpeg for screen capture: {exc}") from exc

        print(
            f"🎥 Recording League window via ffmpeg (display {self._display_index}, {self.monitor['width']}x{self.monitor['height']} @ {self.fps} fps)",
            flush=True,
        )

        if self._ffmpeg_proc.stderr:
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, args=(self._ffmpeg_proc.stderr,), daemon=True
            )
            self._stderr_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
            try:
                if self._ffmpeg_proc.stdin:
                    self._ffmpeg_proc.stdin.write(b"q\n")
                    self._ffmpeg_proc.stdin.flush()
            except Exception:
                pass
            try:
                self._ffmpeg_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._ffmpeg_proc.kill()
                self._ffmpeg_proc.wait(timeout=5)

        self.end_t_ns = time.monotonic_ns()

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2)

        if self._ffmpeg_proc and self._ffmpeg_proc.returncode not in (0, None):
            tail = "\n".join(self._stderr_lines[-10:])
            raise RuntimeError(f"ffmpeg exited with {self._ffmpeg_proc.returncode}:\n{tail}")

        self._collect_frame_records()

    # Internal helpers -------------------------------------------------

    def _build_command(self) -> List[str]:
        display = self._display_info or {}
        crop_x = int(self.bounds_px["left"])
        crop_y = int(self.bounds_px["top"])
        crop_w = int(self.bounds_px["width"])
        crop_h = int(self.bounds_px["height"])

        if display:
            crop_x = max(0, int(round(self.bounds_px["left"] - display.get("left_px", 0))))
            crop_y = max(0, int(round(self.bounds_px["top"] - display.get("top_px", 0))))
            max_w = int(display.get("width_px", crop_w)) - crop_x
            max_h = int(display.get("height_px", crop_h)) - crop_y
            crop_w = min(crop_w, max_w)
            crop_h = min(crop_h, max_h)

        crop_w = self._even(max(2, crop_w))
        crop_h = self._even(max(2, crop_h))
        filter_chain = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale=trunc(iw/2)*2:trunc(ih/2)*2"

        input_spec = str(self._device_index)
        if self._audio_device_index is not None:
            input_spec = f"{self._device_index}:{self._audio_device_index}"

        cmd = [
            self._ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-thread_queue_size",
            "1024",
            "-f",
            "avfoundation",
            "-capture_cursor",
            "1",
            "-capture_mouse_clicks",
            "0",
            "-framerate",
            str(self.fps),
            "-pix_fmt",
            "uyvy422",
            "-i",
            input_spec,
            "-vf",
            filter_chain,
            "-c:v",
            "h264_videotoolbox",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.fps),
            "-vsync",
            "cfr",
            "-movflags",
            "+faststart",
        ]

        if self._audio_device_index is not None:
            cmd += [
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "44100",
                "-ac",
                "2",
            ]

        cmd += [
            str(self.output_path),
        ]
        return cmd

    def _drain_stderr(self, stream) -> None:
        while not self._stop_event.is_set():
            line = stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="ignore").strip()
            if decoded:
                self._stderr_lines.append(decoded)

    def _collect_frame_records(self) -> None:
        probe = self._probe_video()
        frame_count = probe.get("frames") or 0
        width = probe.get("width") or self.monitor["width"]
        height = probe.get("height") or self.monitor["height"]

        self.monitor["width"] = int(width)
        self.monitor["height"] = int(height)

        if not frame_count:
            # Fall back to elapsed time if frame probe failed.
            if self.start_t_ns and self.end_t_ns:
                elapsed = (self.end_t_ns - self.start_t_ns) / 1e9
                frame_count = max(0, int(round(elapsed * self.fps)))
            else:
                frame_count = 0

        self.frame_records = []
        if frame_count and self.start_t_ns:
            interval = int(1_000_000_000 / self.fps)
            for idx in range(frame_count):
                t_ns = self.start_t_ns + (idx * interval)
                self.frame_records.append(FrameRecord(idx, t_ns=t_ns, t_capture_ns=t_ns))

        if self.start_t_ns and self.end_t_ns:
            elapsed = max(0.0, (self.end_t_ns - self.start_t_ns) / 1e9)
            expected_frames = int(round(elapsed * self.fps))
            self.dropped_frames = max(0, expected_frames - frame_count)

    def _probe_video(self) -> Dict[str, Optional[int]]:
        cmd = [
            self._ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,width,height,duration",
            "-of",
            "json",
            str(self.output_path),
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            tail = exc.stderr.strip() if hasattr(exc, "stderr") and exc.stderr else ""
            print(f"⚠️  ffprobe failed to inspect video: {tail}", flush=True)
            return {}

        info = json.loads(proc.stdout or "{}")
        streams = info.get("streams") or []
        if not streams:
            return {}
        stream = streams[0]
        frames = stream.get("nb_read_frames")
        try:
            frames = int(frames) if frames is not None else None
        except Exception:
            frames = None

        width = stream.get("width")
        height = stream.get("height")
        return {"frames": frames, "width": width, "height": height}

    def _load_display_layout(self) -> List[Dict[str, float]]:
        layout: List[Dict[str, float]] = []
        try:
            import Quartz  # type: ignore

            max_displays = 16
            display_ids = (ctypes.c_uint32 * max_displays)()
            count = ctypes.c_uint32(0)
            result = Quartz.CGGetActiveDisplayList(max_displays, display_ids, ctypes.byref(count))
            if result != Quartz.kCGErrorSuccess:
                return layout

            for idx in range(count.value):
                did = display_ids[idx]
                bounds = Quartz.CGDisplayBounds(did)
                width_px = Quartz.CGDisplayPixelsWide(did)
                height_px = Quartz.CGDisplayPixelsHigh(did)
                width_pt = bounds.size.width or 1.0
                height_pt = bounds.size.height or 1.0
                origin_x = bounds.origin.x
                origin_y = bounds.origin.y
                scale_x = float(width_px) / float(width_pt)
                scale_y = float(height_px) / float(height_pt) if height_pt else scale_x

                layout.append(
                    {
                        "display_id": int(did),
                        "index": idx,
                        "left_pt": float(origin_x),
                        "top_pt": float(origin_y),
                        "width_pt": float(width_pt),
                        "height_pt": float(height_pt),
                        "left_px": float(origin_x) * scale_x,
                        "top_px": float(origin_y) * scale_y,
                        "width_px": float(width_px),
                        "height_px": float(height_px),
                        "scale_x": scale_x,
                        "scale_y": scale_y,
                    }
                )
        except Exception:
            return layout
        return layout

    def _select_display_for_bounds(self, bounds: Dict[str, float]) -> Optional[Dict[str, float]]:
        if not self._display_layout:
            return None
        cx = bounds.get("left", 0.0) + bounds.get("width", 0.0) / 2.0
        cy = bounds.get("top", 0.0) + bounds.get("height", 0.0) / 2.0
        for info in self._display_layout:
            left = info.get("left_pt", 0.0)
            top = info.get("top_pt", 0.0)
            width = info.get("width_pt", 0.0)
            height = info.get("height_pt", 0.0)
            within_x = left <= cx <= (left + width)
            within_y = top <= cy <= (top + height)
            if within_x and within_y:
                return info
        return self._display_layout[0]

    def _resolve_pixel_bounds(
        self,
        bounds: Dict[str, Any],
        display_info: Optional[Dict[str, float]],
    ) -> Dict[str, float]:
        pixel_rect = bounds.get("pixel_rect")
        if isinstance(pixel_rect, dict):
            return {
                "left": float(pixel_rect.get("left", 0) or 0),
                "top": float(pixel_rect.get("top", 0) or 0),
                "width": float(pixel_rect.get("width", 0) or 0),
                "height": float(pixel_rect.get("height", 0) or 0),
            }

        scale_x = display_info.get("scale_x", 1.0) if display_info else 1.0
        scale_y = display_info.get("scale_y", scale_x) if display_info else scale_x
        base_left_px = display_info.get("left_px", 0.0) if display_info else 0.0
        base_top_px = display_info.get("top_px", 0.0) if display_info else 0.0
        base_left_pt = display_info.get("left_pt", 0.0) if display_info else 0.0
        base_top_pt = display_info.get("top_pt", 0.0) if display_info else 0.0

        left_delta = self.bounds_pt["left"] - base_left_pt
        top_delta = self.bounds_pt["top"] - base_top_pt

        return {
            "left": float(base_left_px + left_delta * scale_x),
            "top": float(base_top_px + top_delta * scale_y),
            "width": float(self.bounds_pt["width"] * scale_x),
            "height": float(self.bounds_pt["height"] * scale_y),
        }

    def _get_avfoundation_listing(self) -> str:
        if self._avfoundation_listing is not None:
            return self._avfoundation_listing
        cmd = [self._ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception:
            return ""
        self._avfoundation_listing = (proc.stderr or "") + (proc.stdout or "")
        return self._avfoundation_listing

    def _pick_screen_device(self, target_screen: int) -> Optional[int]:
        text = self._get_avfoundation_listing()
        mapping: Dict[int, int] = {}
        for match in re.finditer(r"\[(\d+)\]\s+Capture screen\s+(\d+)", text):
            device_index = int(match.group(1))
            screen_number = int(match.group(2))
            mapping[screen_number] = device_index

        if target_screen in mapping:
            return mapping[target_screen]
        if mapping:
            return mapping[sorted(mapping.keys())[0]]
        return None

    def _pick_audio_device(self, preferred: Optional[str]) -> Optional[Tuple[int, str]]:
        text = self._get_avfoundation_listing()
        entries: List[Tuple[int, str]] = []
        section = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lower = line.lower()
            if "avfoundation video devices" in lower:
                section = "video"
                continue
            if "avfoundation audio devices" in lower:
                section = "audio"
                continue
            match = re.match(r"\[(\d+)\]\s+(.*)", line)
            if not match:
                continue
            idx = int(match.group(1))
            name = match.group(2).strip()
            if section == "audio":
                entries.append((idx, name))
        if not entries:
            return None

        if preferred:
            pref = preferred.lower()
            for idx, name in entries:
                if pref in name.lower():
                    return idx, name

        # Fallback to the first audio device if preference not found
        return entries[0]

    @staticmethod
    def _even(value: int) -> int:
        if value % 2 != 0:
            return max(0, value - 1)
        return value


class _MssScreenRecorder(_BaseScreenRecorder):
    """Fallback recorder for Windows/Linux or macOS environments without avfoundation access."""

    def __init__(
        self,
        output_dir: Path,
        fps: int,
        session_id: str,
        window_id: str,
        capture_allowed_fn: Optional[Callable[[], bool]] = None,
        monitor_bbox: Optional[Dict[str, int]] = None,
    ):
        if not mss:
            raise RuntimeError("mss is required for screen capture on this platform")

        self.output_dir = output_dir
        self.output_path = output_dir / "frames.mp4"
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
        self.sct = mss.mss()

        if monitor_bbox:
            self.monitor = monitor_bbox
        else:
            primary_monitor = self.sct.monitors[1] if len(self.sct.monitors) > 1 else self.sct.monitors[0]
            self.monitor = {
                "width": primary_monitor["width"],
                "height": primary_monitor["height"],
                "left": primary_monitor["left"],
                "top": primary_monitor["top"],
            }
            if self.monitor["width"] == 0 or self.monitor["height"] == 0:
                self.monitor = {"width": 1920, "height": 1080, "left": 0, "top": 0}

        self.last_frame_bytes: Optional[bytes] = None

    def _init_writer(self) -> None:
        width = self.monitor["width"]
        height = self.monitor["height"]
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid video dimensions: {width}x{height}. Check monitor configuration.")

        self.video_writer = FfmpegVideoWriter(
            self.output_path,
            width=width,
            height=height,
            fps=self.fps,
            pixel_format="rgb24",
        )
        print(f"🎥 Recording screen region {width}x{height} via mss (target {self.fps} fps)", flush=True)

    def start(self) -> None:
        self._init_writer()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.video_writer:
            self.video_writer.close()
        self.sct.close()

    def _capture_loop(self) -> None:
        frame_interval_ns = int(1_000_000_000.0 / self.fps)
        next_frame_time = time.monotonic_ns()

        while not self.stop_event.is_set():
            current_time = time.monotonic_ns()
            if current_time < next_frame_time:
                sleep_time = (next_frame_time - current_time) / 1e9
                if sleep_time > 0:
                    time.sleep(min(sleep_time, 0.1))

            if not self.capture_allowed_fn():
                next_frame_time += frame_interval_ns
                continue

            capture_start_ns = time.monotonic_ns()
            try:
                shot = self.sct.grab(self.monitor)
            except Exception as exc:
                error_msg = str(exc)
                if "CoreGraphics.CGWindowListCreateImage" in error_msg:
                    print("❌ Screen capture not available in this environment (sandboxed)", flush=True)
                    break
                print(f"Warning: Screen capture error: {exc}", flush=True)
                self.dropped_frames += 1
                time.sleep(0.01)
                continue

            frame_bytes = self._process_frame(shot)
            if frame_bytes:
                self.frame_records.append(
                    FrameRecord(
                        self.frame_index,
                        t_ns=capture_start_ns,
                        t_capture_ns=capture_start_ns,
                        is_duplicate=False,
                    )
                )
                self.frame_index += 1
                self.video_writer.write(frame_bytes)
                self.last_frame_bytes = frame_bytes
            else:
                self.dropped_frames += 1

            next_frame_time += frame_interval_ns

    def _process_frame(self, shot) -> Optional[bytes]:
        try:
            frame_bytes = getattr(shot, "rgb", None)
            if frame_bytes is None:
                raw = getattr(shot, "raw", None)
                if raw is not None:
                    import numpy as np  # type: ignore

                    width = int(self.monitor["width"])
                    height = int(self.monitor["height"])
                    bgra = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4))
                    rgb = bgra[:, :, 2::-1]
                    frame_bytes = rgb.tobytes()
            return frame_bytes
        except Exception:
            return None
