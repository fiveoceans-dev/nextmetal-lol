# League of Legends AI Capture System

A high-performance multimodal data collection system for autonomous League of Legends AI development. Captures screen gameplay, webcam footage, and keyboard/mouse inputs with precise synchronization for machine learning training.

## 🚀 Quick Start

### Prerequisites
- **Python 3.12+**
- **macOS** (primary platform, with Windows/Linux support)
- **FFmpeg** installed (`brew install ffmpeg` on macOS)
- **Screen Recording permissions** (macOS: System Settings → Privacy & Security → Screen Recording)

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

## 🎮 Usage

### Basic Capture
```bash
python capture.py
```
- Captures League of Legends gameplay only
- Records at 30 FPS
- Saves to timestamped session directory
- Press `q` or `Ctrl+C` to stop

### Advanced Options

```bash
# 60 FPS capture with webcam
python capture.py --fps 60 --webcam

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
| `--allow-any` | Bypass LoL window detection | False |
| `--window-name` | Force specific window name | Auto-detect |

## 📁 Output Structure

Each capture session creates a timestamped directory:

```
session_20241216_143022/
├── frames.mp4          # Screen recording (H.264, 30 FPS)
├── webcam.mp4          # Webcam recording (optional)
├── events.parquet      # Input events (compressed, fast)
├── events.csv          # Input events (human-readable)
└── metadata.json       # Session statistics and info
```

### Data Formats

**Events Data** includes:
- **Screen frames**: Video frames with timestamps
- **Keyboard events**: Key presses/releases with scan codes
- **Mouse events**: Clicks, moves, scrolls with coordinates
- **Webcam frames**: Optional camera footage
- **Synchronization**: All events linked by nanosecond timestamps

## 🔧 Troubleshooting

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

### Performance Tips

- **Lower FPS** (15-30) for longer sessions
- **Close background apps** to reduce system load
- **Use SSD storage** for output directory
- **Monitor system resources** during capture

## 🧪 Development

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
├── system0.md            # Core infrastructure
├── system1.md            # Watch-Mode (data collection)
├── system2.md            # Developer-Mode (AI training)
└── system3.md            # Game-Mode (autonomous play)
```

### Adding Features
- Edit `capture_lib/` modules for core functionality
- Update `capture.py` for CLI options
- Test with `--allow-any` flag for development

## 📊 Data Pipeline

This capture system feeds into the full AI pipeline:

1. **Watch-Mode** (this system): Collect expert gameplay data
2. **Developer-Mode**: Train AI models on captured data
3. **Game-Mode**: Deploy trained AI for autonomous play

See `MASTERPLAN.md` for complete system architecture.

## ⚖️ Legal & Ethical

- **Research Only**: Designed for academic and research purposes
- **Privacy First**: Captures only active gameplay windows
- **Riot Compliance**: Respects League of Legends terms of service
- **Data Control**: All captured data remains local to your machine

## 🤝 Contributing

1. Follow the existing code structure
2. Test on multiple platforms when possible
3. Update documentation for new features
4. Ensure graceful error handling

---

**Built for the future of competitive gaming AI** ⚡🎮
