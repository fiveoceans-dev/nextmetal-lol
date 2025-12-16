# 📦 Data Formats: Watch-Mode Capture → Training

Purpose: produce lossless-enough, time-synchronized traces that flow directly into training without bespoke adapters. Defaults are compression-friendly but reversible; everything is versioned.

---

## Session Layout

```
session_YYYYMMDD_HHMMSS/
├── frames.mp4               # H.264/H.265 video with per-frame timestamps
├── events.parquet           # Input + system events, time-aligned
├── audio.mp4 (optional)     # Voice/game audio, timestamped
├── metadata.json            # Capture + system metadata
└── integrity.sha256         # Hashes of all artifacts
```

Versioning: metadata.json includes `format_version` (semver). Changes to schema bump minor; breaking changes bump major.

---

## Timing & Sync

- Single monotonic clock (nanoseconds) stamped on every event and every frame.
- Frame index is stored in events.parquet (`frame_ref`) to align input and pixels.
- Drift detection: record `clock_drift_ppm` if measured; log dropped frames in metadata.

---

## Frames (Video)

- Container: MP4
- Codec: H.264 (default) or H.265 for size; intra-refresh to reduce artifacts.
- Target: 15–30 FPS for first builds; higher later if perf allows.
- Each frame carries a timestamp; store a frame manifest if the container doesn’t expose it cleanly.
- Optional debug: short PNG bursts for QA.

---

## Events (Parquet Schema)

| Column | Type | Notes |
|--------|------|-------|
| `t_ns` | int64 | Monotonic timestamp |
| `event_type` | string | `key_down`, `key_up`, `mouse_move`, `mouse_click`, `wheel`, `focus`, `frame` |
| `key_code` | int32, nullable | Key code when applicable |
| `mouse_x` | float32, nullable | Normalized 0–1 relative to window |
| `mouse_y` | float32, nullable | Normalized 0–1 relative to window |
| `mouse_button` | string, nullable | `left`, `right`, `middle` |
| `delta` | float32, nullable | Scroll delta or wheel |
| `frame_ref` | int64, nullable | Frame index for alignment |
| `window_id` | string | Active window identifier |
| `session_id` | string | UUID |
| `hash` | string | Integrity hash of the row payload |
| `metadata` | map<string, string> | Extensible key/values (e.g., ping, FPS) |

Rows are append-only per session. Compression: Snappy or ZSTD. Partition: one Parquet file per session to start; shard later if needed.

---

## Metadata (metadata.json)

```json
{
  "format_version": "1.0.0",
  "session_id": "uuid",
  "captured_at": "2024-01-01T12:00:00Z",
  "game": "League of Legends",
  "patch": "XX.Y",
  "resolution": [1920, 1080],
  "refresh_hz": 60,
  "capture_fps": 30,
  "codec": "h264",
  "bitrate_kbps": 8000,
  "input_device": "keyboard+mouse",
  "window_id": "...",
  "dropped_frames": 0,
  "clock_drift_ppm": 0.0,
  "consent": { "record_screen": true, "record_audio": false },
  "privacy": { "chat_redacted": true, "pii_regions": [] },
  "env": { "os": "...", "client_version": "...", "gpu": "..." }
}
```

---

## Integrity & Privacy

- integrity.sha256 contains hashes for frames.mp4, events.parquet, audio.mp4 (if present), metadata.json.
- Redaction: by default, exclude chat overlays and system notifications; configurable PII masks.
- Consent recorded in metadata and enforced at capture start; audio off by default.

---

## Ready-for-Training Expectations

- No custom adapters: Parquet events + MP4 frames + JSON metadata are directly loadable in PyTorch/JAX pipelines.
- Deterministic alignment: `frame_ref` + `t_ns` guarantee exact pairing of inputs and pixels.
- Compression-balanced: MP4 keeps storage sane; loss-sensitive work can use occasional raw PNG bursts.
- Extensible: add new event fields via `metadata` map without breaking schema; bump version for new columns.
