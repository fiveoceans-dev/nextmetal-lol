# ICML Tutorial: Raw screen pixel–based League of Legends control


## Quick Start

### Prerequisites
- **Python 3.12+**
- **macOS** (primary platform, with Windows/Linux support)
- **FFmpeg** installed (`brew install ffmpeg` on macOS)
- **Screen Recording permissions** (macOS: System Settings → Privacy & Security → Screen Recording)
- **Accessibility/Input Monitoring permissions** (macOS: grant Terminal/IDE under Privacy → Accessibility)
- **System Audio Capture** (see setup below)

### Installation

1. **Clone and setup virtual environment:**
```bash
# Activate the existing virtual environment
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate     # On Windows
```

2. **Verify dependencies are installed:**
```bash
pip list | grep -E "(opencv|mss|pynput|pandas)"
```

Expected output includes:
- `mss` (screen capture)
- `opencv-python` (computer vision)
- `pynput` (input monitoring)
- `pandas` (data processing)
- `pyarrow` (efficient data storage)

### System Audio Setup (macOS)

To capture system audio (game sounds, not microphone), you need to set up a virtual audio device:

#### **Option 1: BlackHole (Recommended)**
```bash
# Install BlackHole virtual audio device
brew install blackhole-2ch

# Open Audio MIDI Setup (or Audio Settings in System Settings)
# Set BlackHole 2ch as the system output device
```

#### **Option 2: Built-in System Audio**
The system will automatically try to use available system audio devices. If BlackHole isn't available, it will attempt to use macOS's built-in audio capture.

#### **Verification**
After setup, test audio capture:
```bash
python capture.py --audio --duration 5
# Play some audio and check if session_*/audio.wav is created
```

## Usage

### Basic Capture
```bash
python capture.py
```
- Waits until a Riot/LoL window is foregrounded, then locks onto that crop
- Captures League of Legends gameplay only
- Records at 30 FPS
- Saves to timestamped session directory
- Press `q` or `Ctrl+C` to stop

### Advanced Options

```bash
# 60 FPS capture with webcam and system audio
python capture.py --fps 60 --webcam --audio

# Capture with embedded system audio via BlackHole
python capture.py --audio --audio-device "BlackHole 2ch"

# Check audio setup before capturing
python capture.py --check-audio

# 5-minute session
python capture.py --duration 300

# Custom window (bypass LoL detection)
python capture.py --allow-any --window-name "Your Game Window"

# Specific webcam device and resolution
python capture.py --webcam --webcam-device 1 --webcam-resolution 1280x720
```

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--fps` | Capture frame rate (10-240) | 30 |
| `--duration` | Capture duration in seconds (0 = manual stop) | 0 |
| `--webcam` | Enable webcam recording | Disabled |
| `--webcam-device` | Webcam device index | 0 |
| `--webcam-resolution` | Webcam resolution (WIDTHxHEIGHT) | Auto |
| `--audio` | Record system audio from League of Legends (macOS only) | Disabled |
| `--audio-device` | macOS loopback device name for embedded audio (e.g., `BlackHole 2ch`) | Auto |
| `--check-audio` | Check audio capture setup and provide configuration guidance | - |
| `--allow-any` | Bypass LoL window detection | False |
| `--window-name` | Force specific window name | Auto-detect |

## 📁 Output Structure

Each capture session creates a timestamped directory optimized for RL training:

```
session_20241216_143022/
├── frames.mp4          # Screen recording (H.264 CRF 18, 30 FPS, optimized for ML)
├── webcam.mp4          # Webcam recording (optional, same settings)
├── audio.wav           # Game audio (optional, 44.1kHz stereo WAV)
├── events.parquet      # Input + frame timeline (columnar, ML friendly)
├── events.csv          # Same event timeline (human readable / diff friendly)
└── metadata.json       # RL-compatible metadata with validation & trajectories
```

### Data Specifications

** Video Format (ML-Optimized):**
- **Codec**: H.264 with CRF 18 (high quality, efficient compression)
- **Frame Rate**: 30 FPS constant (matches AlphaStar standard)
- **Resolution**: Native game resolution (typically 1920x1080)
- **Color Space**: YUV420p (standard for ML pipelines)
- **Encoding**: Fast preset with zerolatency tuning

** Audio Format (System Audio):**
- **Embedded**: When `--audio` is enabled on macOS, `frames.mp4` includes an AAC track captured directly from the loopback device (BlackHole or similar). A synchronized `audio.wav` is also extracted for ML pipelines.
- **Format**: WAV (uncompressed, high quality) when exported
- **Sample Rate**: 44.1 kHz (CD quality)
- **Channels**: Stereo (2-channel)
- **Codec**: PCM 16-bit
- **Content**: System audio output (speakers) - game sounds, voice chat, UI effects
- **Note**: Captures what you hear from League of Legends, not microphone input
- **Use Cases**: Game sound analysis, ability sound detection, ambient audio context

** Input Events (RL-Compatible):**
- **Timestamps**: Nanosecond precision with monotonic guarantees
- **Synchronization**: Frame-aligned correlation (events linked to video frames)
- **Format**: Parquet + CSV for downstream ML + quick inspection
- **Fields**: timestamp, event_type, key_code, mouse_coords, frame_ref

** Audio Use Cases for AI Training:**
- **Sound-based Rewards**: Ability sounds, combat audio cues
- **Voice Analysis**: Team communication patterns
- **Environmental Context**: Music, ambient sounds, game state audio
- **Multimodal Learning**: Combined vision + audio + input understanding
- **Anomaly Detection**: Unusual audio patterns during gameplay

** Metadata (RL Dataset Standard):**
- **Compatibility**: RLDS, D4RL, OpenAI Gym compatible
- **Validation**: Data integrity checks and quality metrics
- **Trajectories**: Automatic segmentation into 60s training episodes
- **Modalities**: screen_video, input_events, webcam_video (optional)

### Inspecting Captured Events

Parquet files load instantly with pandas/pyarrow, but a CSV export is also provided for quick terminal inspection.

```bash
python - <<'PY'
import pandas as pd
df = pd.read_parquet("session_20241216_143022/events.parquet")
print(df.head())
print(df[df.stream == "input"][["t_ns", "event_type", "mouse_x", "mouse_y"]].head())
PY

# or open the mirrored CSV
rg -n "" session_20241216_143022/events.csv | head
```

Pro tip: `events.parquet` + `metadata.json` is the canonical data for training; `events.csv` is meant for reviews, diffing, or debugging.

## Troubleshooting

### Common Issues

**"ffmpeg not found"**
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows: Download from https://ffmpeg.org/
```

**"Screen recording permission denied" (macOS)**
- System Settings → Privacy & Security → Screen Recording
- Add your terminal/IDE to allowed apps
- Restart your terminal

**"LoL window not detected"**
- Ensure League of Legends is running in windowed/borderless mode
- Try: `python capture.py --allow-any --window-name "League of Legends"`

**"Webcam not found"**
- Check available devices: `python -c "import cv2; print([cv2.VideoCapture(i).isOpened() for i in range(5)])"`
- Use `--webcam-device N` to specify correct device

**"No audio captured"**
- Install BlackHole: `brew install blackhole-2ch`
- Set BlackHole as system output in Audio MIDI Setup
- Check System Settings → Privacy & Security → Microphone (may be required)
- Verify audio permissions for terminal/IDE

**"Audio is microphone input instead of system audio"**
- The system is designed to capture system audio (speakers), not microphone
- If hearing microphone audio, check your audio device setup
- Make sure BlackHole is set as the system output device

### Performance Tips

- **Lower FPS** (15-30) for longer sessions
- **Close background apps** to reduce system load
- **Use SSD storage** for output directory
- **Monitor system resources** during capture

## Development

### Project Structure
```
├── capture.py              # Main CLI script
├── capture_lib/            # Core capture modules
│   ├── session.py         # Orchestration and I/O
│   ├── screen_recorder.py # Video capture
│   ├── webcam_recorder.py # Camera capture
│   ├── input_logging.py   # Keyboard/mouse monitoring
│   ├── windows.py         # Window detection
│   ├── ffmpeg_writer.py   # Video encoding
│   └── constants.py       # Configuration
├── MASTERPLAN.md          # System architecture
```

### Adding Features
- Edit `capture_lib/` modules for core functionality
- Update `capture.py` for CLI options
- Test with `--allow-any` flag for development

## Research & Standards

Based on analysis of leading game AI projects (DeepMind AlphaStar, OpenAI Dota 2):

** Key Findings:**
- **Video Quality**: H.264 MP4 with CRF 18-23 provides optimal quality/size balance for ML training
- **Frame Rate**: 30 FPS captures APM while maintaining manageable file sizes
- **Input Sync**: Nanosecond timestamps with frame alignment essential for RL training
- **Dataset Format**: Parquet + JSON metadata compatible with major RL frameworks

** Implemented Standards:**
- Data validation and integrity checking
- Trajectory segmentation for RL training episodes
- Multimodal synchronization guarantees
- Quality metrics and error detection

## Data Pipeline

This capture system feeds into the full AI pipeline:

1. **Watch-Mode** (this system): Collect expert gameplay data with validation
2. **Developer-Mode**: Train AI models on trajectory-segmented data
3. **Game-Mode**: Deploy trained AI for autonomous play
