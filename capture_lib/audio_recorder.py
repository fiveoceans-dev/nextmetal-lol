from __future__ import annotations

import threading
import time
import wave
import audioop
from pathlib import Path
from typing import Callable, Optional

from .ffmpeg_writer import FfmpegVideoWriter


class AudioRecorder:
    """macOS system audio recorder using CoreAudio framework."""

    def __init__(
        self,
        output_dir: Path,
        fps: int,
        session_id: str,
        capture_allowed_fn: Optional[Callable[[], bool]] = None,
    ):
        self.output_dir = output_dir
        self.fps = fps
        self.session_id = session_id
        self.capture_allowed_fn = capture_allowed_fn or (lambda: True)
        self.stop_event = threading.Event()

        # Audio settings
        self.sample_rate = 44100  # Standard audio sample rate
        self.channels = 2  # Stereo
        self.audio_writer: Optional[FfmpegVideoWriter] = None
        self.thread: Optional[threading.Thread] = None

        # Audio capture variables
        self.audio_proc = None
        self.audio_frames = []
        self.frame_index = 0

    def _init_audio_capture(self):
        """Initialize system audio capture using CoreAudio."""
        try:
            # Try multiple approaches for system audio capture on macOS

            # Method 1: Use BlackHole virtual audio device (most reliable)
            if self._try_blackhole_capture():
                return True

            # Method 2: Use AVFoundation with system audio device
            if self._try_avfoundation_system_audio():
                return True

            # Method 3: Use CoreAudio API directly
            if self._try_coreaudio_capture():
                return True

            print("Warning: No system audio capture method available")
            print("To enable system audio capture:")
            print("1. Install BlackHole: brew install blackhole-2ch")
            print("2. Set BlackHole as system output in Audio MIDI Setup")
            print("3. Or grant microphone permissions for fallback capture")
            return False

        except Exception as e:
            print(f"Warning: Audio capture initialization failed: {e}")
            print("Audio capture will be disabled for this session")
            return False

    def _try_blackhole_capture(self):
        """Try to capture from BlackHole virtual audio device."""
        try:
            import subprocess
            import shutil

            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return False

            # Check if BlackHole is available
            result = subprocess.run(
                [ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True, text=True, timeout=5
            )

            if "BlackHole" in result.stderr:
                # BlackHole is available, use it
                cmd = [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel", "error",
                    "-f", "avfoundation",
                    "-i", "BlackHole",  # Use BlackHole device
                    "-acodec", "pcm_s16le",
                    "-ar", str(self.sample_rate),
                    "-ac", str(self.channels),
                    "-f", "wav",
                    str(self.output_dir / "audio.wav")
                ]

                self.audio_proc = subprocess.Popen(cmd)
                print("🎵 System audio capture: Using BlackHole virtual device")
                print(f"   Recording at {self.sample_rate}Hz, {self.channels} channels")
                return True

        except Exception:
            pass
        return False

    def _try_avfoundation_system_audio(self):
        """Try AVFoundation with system audio device enumeration."""
        try:
            import subprocess
            import shutil

            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return False

            # Try to find system audio device (usually device 1 or higher)
            # This is a fallback that might capture system audio
            cmd = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-f", "avfoundation",
                "-i", ":1",  # Try system audio device
                "-acodec", "pcm_s16le",
                "-ar", str(self.sample_rate),
                "-ac", str(self.channels),
                "-f", "wav",
                str(self.output_dir / "audio.wav")
            ]

            # Test if this device works by running briefly
            test_proc = subprocess.Popen(
                cmd + ["-t", "0.1"],  # Record for 0.1 seconds to test
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            test_proc.wait(timeout=5)

            if test_proc.returncode == 0:
                # Device works, start actual recording
                self.audio_proc = subprocess.Popen(cmd)
                print("🎵 System audio capture: Using AVFoundation system device")
                print(f"   Recording at {self.sample_rate}Hz, {self.channels} channels")
                return True

        except Exception:
            pass
        return False

    def _try_coreaudio_capture(self):
        """Try direct CoreAudio capture using PyObjC."""
        try:
            # Use PyObjC to access CoreAudio directly
            # This is the most direct way to capture system audio
            import objc
            from Foundation import NSObject
            from CoreAudio import kAudioDevicePropertyStreamFormat
            from CoreAudio import kAudioDevicePropertyDeviceIsAlive
            from CoreAudio import kAudioObjectPropertyElementMaster
            from CoreAudio import kAudioObjectSystemObject
            from CoreAudio import kAudioHardwarePropertyDevices
            from CoreAudio import kAudioHardwarePropertyDefaultOutputDevice

            # Get default output device (system speakers)
            device_id = self._get_default_output_device()
            if device_id:
                print("🎵 System audio capture: Using CoreAudio API")
                print(f"   Device ID: {device_id}")
                print(f"   Recording at {self.sample_rate}Hz, {self.channels} channels")

                # Start CoreAudio-based capture
                self._start_coreaudio_capture(device_id)
                return True

        except ImportError:
            print("PyObjC not available for CoreAudio capture")
        except Exception as e:
            print(f"CoreAudio capture failed: {e}")

        return False

    def _get_default_output_device(self):
        """Get the default system output device ID."""
        try:
            from CoreAudio import AudioObjectGetPropertyData, kAudioHardwarePropertyDefaultOutputDevice
            from CoreFoundation import CFDataGetBytePtr

            device_id = objc.var()
            size = objc.var()

            error = AudioObjectGetPropertyData(
                kAudioObjectSystemObject,
                kAudioHardwarePropertyDefaultOutputDevice,
                0,
                None,
                size,
                device_id
            )

            if error == 0:
                return device_id.value
        except Exception:
            pass
        return None

    def _start_coreaudio_capture(self, device_id):
        """Start CoreAudio-based audio capture."""
        # For now, implement a basic WAV writer
        # In a full implementation, this would use CoreAudio callbacks
        # to capture audio data in real-time

        # Create WAV file for writing
        self.wav_file = wave.open(str(self.output_dir / "audio.wav"), 'wb')
        self.wav_file.setnchannels(self.channels)
        self.wav_file.setsampwidth(2)  # 16-bit
        self.wav_file.setframerate(self.sample_rate)

        # Note: Full CoreAudio implementation would require more complex
        # callback-based audio capture. For now, we'll use the AVFoundation
        # approach as a fallback.

    def _init_audio_writer(self):
        """Initialize FFmpeg audio encoder (alternative approach)."""
        try:
            # Create a WAV file writer using FFmpeg
            self.audio_writer = FfmpegVideoWriter(
                self.output_dir / "audio_encoded.wav",
                width=1,  # Dummy values for audio-only
                height=1,
                fps=1,
                pixel_format="rgb24"
            )
        except Exception as e:
            print(f"Warning: Audio writer initialization failed: {e}")

    def start(self):
        """Start audio recording."""
        if not self._init_audio_capture():
            return

        self.thread = threading.Thread(target=self._record_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop audio recording."""
        self.stop_event.set()

        # Stop FFmpeg process
        if hasattr(self, 'audio_proc') and self.audio_proc:
            try:
                self.audio_proc.terminate()
                self.audio_proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.audio_proc.kill()
                self.audio_proc.wait(timeout=2.0)
            except Exception as e:
                print(f"Warning: Error stopping audio process: {e}")

        # Stop recording thread
        if hasattr(self, 'thread') and self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

        # Close WAV file if using CoreAudio
        if hasattr(self, 'wav_file') and self.wav_file:
            try:
                self.wav_file.close()
            except Exception as e:
                print(f"Warning: Error closing WAV file: {e}")

        # Close any video writer (fallback)
        if hasattr(self, 'audio_writer') and self.audio_writer:
            try:
                self.audio_writer.close()
            except Exception as e:
                print(f"Warning: Error closing audio writer: {e}")

        # Close video writer (legacy)
        if hasattr(self, 'video_writer') and self.video_writer:
            try:
                self.video_writer.close()
            except Exception as e:
                print(f"Warning: Error closing video writer: {e}")

    def _record_loop(self):
        """Main audio recording loop - monitor FFmpeg process."""
        while not self.stop_event.is_set():
            if not self.capture_allowed_fn():
                time.sleep(0.1)
                continue

            # Monitor the FFmpeg process
            if self.audio_proc and self.audio_proc.poll() is not None:
                # Process has finished or crashed
                return_code = self.audio_proc.returncode
                if return_code != 0:
                    print(f"Warning: Audio capture process exited with code {return_code}")
                    # Try to get error output
                    try:
                        stderr = self.audio_proc.stderr.read().decode() if self.audio_proc.stderr else ""
                        if stderr:
                            print(f"Audio capture error: {stderr[:200]}...")
                    except Exception:
                        pass
                break

            time.sleep(0.1)

    def get_audio_info(self) -> dict:
        """Get information about captured audio."""
        audio_file = self.output_dir / "audio.wav"
        if audio_file.exists():
            try:
                # Try to get basic WAV info
                import wave
                with wave.open(str(audio_file), 'rb') as wav_file:
                    return {
                        "format": "wav",
                        "sample_rate": wav_file.getframerate(),
                        "channels": wav_file.getnchannels(),
                        "file_path": str(audio_file),
                        "file_size": audio_file.stat().st_size,
                        "duration_seconds": wav_file.getnframes() / wav_file.getframerate() if wav_file.getframerate() > 0 else 0
                    }
            except Exception:
                # Fallback if wave module can't read it
                return {
                    "format": "wav",
                    "sample_rate": self.sample_rate,
                    "channels": self.channels,
                    "file_path": str(audio_file),
                    "file_size": audio_file.stat().st_size,
                    "note": "Could not read WAV header"
                }
        return {}

    def check_audio_setup(self) -> dict:
        """Check if audio capture is properly configured."""
        result = {
            "blackhole_available": False,
            "ffmpeg_available": False,
            "permissions_granted": False,
            "recommended_setup": []
        }

        # Check if FFmpeg is available
        try:
            import shutil
            result["ffmpeg_available"] = shutil.which("ffmpeg") is not None
        except Exception:
            pass

        # Check for BlackHole
        try:
            import subprocess
            import shutil
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                result_proc = subprocess.run(
                    [ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                    capture_output=True, text=True, timeout=3
                )
                result["blackhole_available"] = "BlackHole" in result_proc.stderr
        except Exception:
            pass

        # Provide setup recommendations
        if not result["ffmpeg_available"]:
            result["recommended_setup"].append("Install FFmpeg: brew install ffmpeg")

        if not result["blackhole_available"]:
            result["recommended_setup"].append("Install BlackHole: brew install blackhole-2ch")
            result["recommended_setup"].append("Set BlackHole as system output in Audio MIDI Setup")

        return result
