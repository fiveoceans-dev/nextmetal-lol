"""
Capture runner for League of Legends sessions.

Features:
- Waits for Riot/LoL window, captures only that window.
- Screen recording (mp4) + input logging (parquet).
- Optional webcam recording.
- Saves session metadata for downstream processing.
"""

from __future__ import annotations

import argparse
from typing import Optional, Tuple

from capture_lib.constants import DEFAULT_FPS
from capture_lib.session import run_capture_session


def _parse_resolution(val: Optional[str]) -> Optional[Tuple[int, int]]:
    if not val:
        return None
    if "x" not in val.lower():
        raise argparse.ArgumentTypeError("Resolution must be in WIDTHxHEIGHT format, e.g., 1280x720")
    parts = val.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("Resolution must be in WIDTHxHEIGHT format, e.g., 1280x720")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError("Resolution must be in WIDTHxHEIGHT format, e.g., 1280x720")


def main():
    parser = argparse.ArgumentParser(description="Capture screen + inputs for LoL sessions.")
    parser.add_argument("--duration", type=int, default=0, help="Capture duration in seconds (0 = until Ctrl+C)")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Capture FPS")
    parser.add_argument(
        "--allow-any",
        action="store_true",
        help="Bypass LoL window gating (useful for testing or different titles)",
    )
    parser.add_argument(
        "--window-name",
        type=str,
        default=None,
        help="Force a specific window name instead of detecting active window",
    )
    parser.add_argument(
        "--webcam",
        action="store_true",
        help="Record webcam to webcam.mp4 alongside screen capture",
    )
    parser.add_argument(
        "--webcam-device",
        type=int,
        default=0,
        help="Webcam device index (default: 0)",
    )
    parser.add_argument(
        "--webcam-resolution",
        type=_parse_resolution,
        default=None,
        help="Webcam resolution as WIDTHxHEIGHT (e.g., 1280x720). Defaults to device setting.",
    )
    args = parser.parse_args()

    run_capture_session(
        duration_seconds=args.duration or None,
        fps=args.fps,
        allow_any_window=args.allow_any,
        forced_window=args.window_name,
        enable_webcam=args.webcam,
        webcam_device=args.webcam_device,
        webcam_resolution=args.webcam_resolution,
    )


if __name__ == "__main__":
    main()

