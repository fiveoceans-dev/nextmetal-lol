# 🔧 System 0: Core AI Infrastructure

*Robust, observable primitives built for real-world deployment with graceful failure handling.*

---

## 🏗️ Component Architecture (Production-Ready)

```
capture_lib/
├── constants.py               # Configuration constants (FPS, codecs)
├── windows.py                 # Window detection and League of Legends targeting
├── input_logging.py           # Precise keyboard/mouse event capture
├── screen_recorder.py         # High-performance screen capture with timing
├── webcam_recorder.py         # Optional webcam capture with device handling
├── audio_recorder.py          # System audio capture (no microphone)
├── ffmpeg_writer.py           # FFmpeg-based video encoding with timing fixes
├── session.py                 # Orchestration, data sync, and storage
└── coordinator.py             # Legacy coordination (decommissioned)
```

**Key Data Models:**
```python
@dataclass
class FrameRecord:
    """Precise frame metadata with nanosecond timing."""
    frame_index: int
    t_ns: int                    # Presentation timestamp (nanoseconds)
    t_capture_ns: Optional[int]  # Capture timestamp (nanoseconds)
    is_duplicate: bool = False

@dataclass
class InputEvent:
    """Synchronized input events with frame references."""
    t_ns: int                    # Event timestamp (nanoseconds)
    event_type: str             # "key_press", "mouse_move", etc.
    key_code: Optional[int]     # Keyboard key code
    mouse_x: Optional[float]    # Mouse X coordinate
    mouse_y: Optional[float]    # Mouse Y coordinate
    mouse_button: Optional[str] # Mouse button name
    delta: Optional[float]      # Scroll delta
    frame_ref: Optional[int]    # Associated frame index
    window_id: Optional[str]    # Target window identifier
    session_id: Optional[str]   # Capture session identifier
    metadata: Optional[Dict[str, str]]  # Additional context
```

---

## ⚙️ Configuration: Hermetic and Diffable

```python
class AIConfig:
    """Single source of truth with explicit overrides."""

    def __init__(self):
        self.model = ModelConfig()
        self.training = TrainingConfig()
        self.inference = InferenceConfig()
        self.monitoring = MonitoringConfig()

    def load_from_yaml(self, path: str):
        # Env interpolation + signature verification
        pass

    def validate_config(self) -> bool:
        # Fail fast with human-readable diffs
        pass

    def fork_for_experiment(self, experiment: str):
        # Immutable baseline + scoped overrides
        pass
```

Tenets: configs are code-reviewed, cryptographically signed, and versioned; no mutable runtime flags outside emergency playbooks.

---

## 📊 Data Contracts & Storage

**Unified Event Stream Format:**
```python
# All data stored as Parquet with this schema:
event_schema = {
    "t_ns": "int64",              # Primary timestamp (nanoseconds)
    "t_capture_ns": "int64",      # Capture timestamp (nanoseconds)
    "is_duplicate": "bool",       # Frame deduplication flag
    "event_type": "string",       # "frame", "key_press", "mouse_move", etc.
    "stream": "string",           # "screen", "webcam", "input"
    "key_code": "int32",          # Keyboard events
    "mouse_x": "float32",         # Mouse coordinates
    "mouse_y": "float32",
    "mouse_button": "string",     # Mouse button events
    "delta": "float32",           # Scroll wheel delta
    "frame_ref": "int32",         # Links inputs to video frames
    "window_id": "string",        # Target window identifier
    "session_id": "string",       # Capture session identifier
    "metadata": "string"          # JSON-encoded additional data
}
```

**Storage Structure:**
```
session_YYYYMMDD_HHMMSS/
├── frames.mp4          # Screen video (H.264, 30fps)
├── webcam.mp4          # Webcam video (optional)
├── audio.wav           # System audio (44.1kHz stereo)
├── events.parquet      # Unified event stream
└── metadata.json       # Session metadata and statistics
```

**Metadata Format:**
```json
{
  "format_version": "1.0.0",
  "session_id": "session_20241216_204500",
  "fps": 30,
  "dropped_frames": 0,
  "padded_frames": 0,
  "actual_fps": 29.97,
  "capture_fps": 29.95,
  "screen_resolution": [1920, 1080],
  "window_id": "League of Legends",
  "webcam_info": {"device": 0, "resolution": [1280, 720]},
  "audio_info": {"sample_rate": 44100, "channels": 2},
  "start_t_ns": 1734385500000000000,
  "end_t_ns": 1734385560000000000,
  "duration_s": 60.0,
  "validation": {...},
  "trajectories": [...]
}
```

**Data Integrity Guarantees:**
- Nanosecond-precision timestamps with monotonic clocks
- Frame-synchronized input events (no temporal drift)
- Automatic deduplication and validation
- Compressed storage (Parquet/Snappy) with integrity checks

---

## 🔐 Privacy & Security Measures

**Window-Specific Capture:**
- Only captures League of Legends window (when available)
- `--allow-any` flag for testing (captures any window)
- No capture of other applications or desktop
- Clear visual indicators during capture

**Audio Privacy:**
- Captures system audio output only (speakers/headphones)
- No microphone access or voice recording
- Game sounds, voice chat, UI effects only
- BlackHole virtual audio device support

**Data Handling:**
- Local storage only (no cloud upload)
- Session-based organization with timestamps
- Graceful failure without data loss
- No personally identifiable information captured

**Error Handling Security:**
- Sandboxed environment detection
- Permission failure graceful degradation
- No crashes or data corruption on failures
- Clear error messages without sensitive information

---

## 💾 Storage & Data Management

**Local File-Based Storage:**
- **Parquet Format**: Columnar storage for efficient analysis (Snappy compression)
- **Video Files**: H.264 MP4 with precise timing (FFmpeg encoding)
- **Audio Files**: WAV format (44.1kHz, 16-bit stereo)
- **Metadata**: JSON with session statistics and validation

**Data Synchronization:**
- **Frame-Referenced Events**: All input events linked to video frames
- **Temporal Alignment**: Nanosecond-precision timestamp correlation
- **No Data Loss**: Atomic writes with validation
- **Session Isolation**: Each capture session in separate directory

**Performance Characteristics:**
- **Real-time Writing**: No buffering delays during capture
- **Compressed Storage**: Efficient disk usage
- **Fast Loading**: Parquet enables quick data analysis
- **Metadata Rich**: Complete session information for debugging/training

---

## 🔌 Model Interfaces (No Mystery Meat)

```python
class TorchModelInterface(AIModelInterface):
    """Inference with explicit latency budget."""

    def __init__(self):
        self.device = self._place()
        self.compiled_model = None

    async def inference(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        processed = self._preprocess_input(input_data)
        with torch.no_grad():
            output = (self.compiled_model or self.model)(processed)
        result = self._postprocess_output(output)
        await self._log_inference_metrics(time.perf_counter() - start, result)
        return result
```

Principles: explicit latency budgets, deterministic preprocessing, backpressure instead of silent degradation, telemetry emitted on every call.

---

## 📊 Telemetry & Observability

```python
class AIMonitoring:
    """SRE-grade signals in the training and serving path."""

    async def monitor_inference(self, model_name: str, elapsed: float, success: bool):
        await self.metrics.record_inference(model_name, elapsed, success)
        await self.tracing.add_span("inference", elapsed)
        if elapsed > self.thresholds[model_name]:
            await self.alerting.send_alert("Latency breach", {"model": model_name, "latency": elapsed})
```

Everything emits traces; anomalies trigger alerts and automatic dampening; profiles feed back into training priorities.

---

## 🧪 Robustness & Error Handling

**Graceful Failure Modes:**
- **Screen Capture Fails**: Continues with webcam/audio if available
- **Webcam Permission Denied**: Disables webcam, continues with screen/audio
- **Audio Device Issues**: Disables audio, continues with visual capture
- **Empty Data Sets**: Handles no-frame scenarios without crashes

**Environment Adaptation:**
- **Sandbox Detection**: Identifies restricted environments
- **Permission Checking**: Validates access before attempting capture
- **Fallback Configurations**: Automatic resolution adjustment (1920x1080 default)
- **Platform Compatibility**: macOS primary, Windows/Linux support

**Quality Assurance:**
- **Timing Validation**: Ensures frame rates match specifications
- **Data Integrity**: Validates Parquet files and metadata consistency
- **Session Completeness**: Verifies all components captured successfully
- **Performance Monitoring**: Tracks FPS, dropped frames, and latencies

---

## 🚀 CLI Interface & Usage

**Command Line Interface:**
```bash
# Full multimodal capture
python capture.py --duration 300 --fps 30 --webcam --audio --webcam-device 0 --webcam-resolution 1280x720

# Test capture (any window)
python capture.py --duration 10 --allow-any

# Check audio setup
python capture.py --check-audio

# Stop capture: Press 'q' or Ctrl+C
```

**Configuration Options:**
| Flag | Description | Default | Example |
|------|-------------|---------|---------|
| `--duration N` | Seconds to capture | ∞ | `--duration 60` |
| `--fps N` | Target frame rate | 30 | `--fps 60` |
| `--webcam` | Enable webcam | Off | `--webcam` |
| `--webcam-device N` | Camera device | 0 | `--webcam-device 1` |
| `--webcam-resolution WxH` | Camera resolution | 640x480 | `--webcam-resolution 1280x720` |
| `--audio` | Enable system audio | Off | `--audio` |
| `--allow-any` | Capture any window | Off | `--allow-any` |

**Production Deployment:**
- **Container Ready**: No external dependencies except FFmpeg
- **Cross-Platform**: macOS primary, Windows/Linux support
- **Resource Efficient**: Minimal CPU/memory usage
- **Data Safe**: Local storage, no network transmission
- **User Control**: Clear start/stop with visual feedback

---

**System 0 delivers production-grade multimodal capture: robust, private, and timing-precise. Every frame and input event captured with nanosecond accuracy for flawless AI training data.**
