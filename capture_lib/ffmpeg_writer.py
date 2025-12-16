from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional


def _default_ffmpeg_encoder() -> str:
    return "libx264"


def _candidate_encoders(preferred: Optional[str] = None) -> list[str]:
    if preferred:
        return [preferred]
    return ["libx264"]


class FfmpegVideoWriter:
    def __init__(
        self,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: int,
        pixel_format: str,
        encoder: Optional[str] = None,
        bitrate_kbps: Optional[int] = None,
    ):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found on PATH; install ffmpeg or use a different backend.")

        self.output_path = output_path
        self.width = width
        self.height = height
        self.fps = fps
        self.pixel_format = pixel_format
        self.encoder = encoder or _default_ffmpeg_encoder()
        self.bitrate_kbps = bitrate_kbps

        self.proc = None
        last_err: Optional[str] = None
        for enc in _candidate_encoders(encoder):
            cmd = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "+genpts",  # Generate presentation timestamps
                "-f",
                "rawvideo",
                "-pix_fmt",
                self.pixel_format,
                "-s",
                f"{self.width}x{self.height}",
                "-r",
                str(self.fps),  # Input framerate
                "-i",
                "-",
                "-an",
                "-c:v",
                enc,
                "-f",
                "mp4",  # Explicit MP4 format
                "-r",
                str(self.fps),  # Output framerate
                "-g",
                str(self.fps // 2),  # GOP size = 0.5 seconds for better timing
                "-keyint_min",
                str(self.fps // 2),  # Minimum keyframe interval
                "-sc_threshold",
                "0",  # Disable scene change detection for consistent timing
                "-avoid_negative_ts",
                "make_zero",  # Handle timestamp issues
                "-vsync",
                "cfr",  # Constant frame rate
                "-movflags",
                "+faststart",  # Put metadata at start of file
            ]

            if enc == "libx264":
                cmd += ["-preset", "fast", "-crf", "18", "-tune", "zerolatency"]
            elif enc == "h264_videotoolbox":
                # VideoToolbox prefers bitrate control.
                if self.bitrate_kbps:
                    cmd += ["-b:v", f"{self.bitrate_kbps}k"]
                else:
                    cmd += ["-b:v", "8000k"]

            cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(self.output_path)]

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.15)
            if proc.poll() is None:
                self.proc = proc
                self.encoder = enc
                break

            err = b""
            if proc.stderr:
                try:
                    err = proc.stderr.read()
                except Exception:
                    err = b""
            last_err = err.decode(errors="ignore")

        if not self.proc:
            raise RuntimeError(f"ffmpeg failed to start any encoder ({_candidate_encoders(encoder)}): {last_err}")
        if not self.proc.stdin:
            raise RuntimeError("ffmpeg stdin not available")

    def write(self, frame_bytes: bytes) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("ffmpeg process not initialized or stdin closed")

        # Check if ffmpeg process is still alive
        if self.proc.poll() is not None:
            err = b""
            if self.proc.stderr:
                try:
                    err = self.proc.stderr.read()
                except Exception:
                    err = b""
            raise RuntimeError(f"ffmpeg process died unexpectedly: {err.decode(errors='ignore')}")

        try:
            self.proc.stdin.write(frame_bytes)
            # Flush to ensure data is sent immediately
            self.proc.stdin.flush()
        except BrokenPipeError as exc:
            err = b""
            if self.proc.stderr:
                try:
                    err = self.proc.stderr.read()
                except Exception:
                    err = b""
            raise RuntimeError(f"ffmpeg pipe broke: {err.decode(errors='ignore')}") from exc
        except Exception as exc:
            raise RuntimeError(f"Failed to write frame to ffmpeg: {exc}") from exc

    def close(self, timeout_s: float = 10.0) -> None:
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=timeout_s)
        if self.proc.returncode != 0:
            err = b""
            if self.proc.stderr:
                try:
                    err = self.proc.stderr.read()
                except Exception:
                    err = b""
            raise RuntimeError(f"ffmpeg exited with {self.proc.returncode}: {err.decode(errors='ignore')}")
