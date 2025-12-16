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
    parser = argparse.ArgumentParser(description="Capture screen + inputs + audio for LoL sessions. Press 'q' in terminal to stop gracefully.")
    parser.add_argument("--duration", type=int, default=0, help="Capture duration in seconds (0 = until Ctrl+C or 'q')")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Capture FPS (default: 30)")
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
    parser.add_argument(
        "--audio",
        action="store_true",
        help="Record system audio from League of Legends (macOS only)",
    )
    parser.add_argument(
        "--audio-device",
        type=str,
        default=None,
        help="Name of macOS audio loopback device for embedded capture (e.g., 'BlackHole 2ch')",
    )
    parser.add_argument(
        "--check-audio",
        action="store_true",
        help="Check audio capture setup and provide configuration guidance",
    )
    args = parser.parse_args()

    # Handle audio setup check
    if args.check_audio:
        from capture_lib.audio_recorder import AudioRecorder
        from pathlib import Path

        recorder = AudioRecorder(
            output_dir=Path("."),  # Dummy path
            fps=30,
            session_id="test",
            capture_allowed_fn=lambda: True
        )

        setup = recorder.check_audio_setup()
        print("🎵 Audio Capture Setup Check:")
        print(f"   FFmpeg available: {'✅' if setup['ffmpeg_available'] else '❌'}")
        print(f"   BlackHole available: {'✅' if setup['blackhole_available'] else '❌'}")
        print()
        print("📋 Setup Recommendations:")
        for rec in setup['recommended_setup']:
            print(f"   • {rec}")
        print()
        print("🎮 To test audio capture:")
        print("   python capture.py --audio --duration 5")
        return

    run_capture_session(
        duration_seconds=args.duration or None,
        fps=args.fps,
        allow_any_window=args.allow_any,
        forced_window=args.window_name,
        enable_webcam=args.webcam,
        webcam_device=args.webcam_device,
        webcam_resolution=args.webcam_resolution,
        enable_audio=args.audio,
        audio_device=args.audio_device,
    )


if __name__ == "__main__":
    main()
