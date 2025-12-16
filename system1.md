# 🎥 System 1: Watch-Mode

*Frictionless, privacy-first capture that converts human skill into clean training signal.*

---

## 🎯 Core Intelligence

Watch-Mode is the intake valve for the whole AGI trajectory. It must disappear into the background, extract maximal signal, and never leak privacy.

| Layer | Tech | Musk Constraint | Output |
|-------|------|-----------------|--------|
| **Visual** | Detectron2 + custom lightweight CNNs | Zero dropped frames at 240FPS | Pixel-accurate state |
| **Temporal** | Transformer-based sequencers | Sub-ms input timing | Action-time pairs with causality |
| **Behavioral** | Multimodal fusion | Bias detection always on | Strategy fingerprints |
| **Contextual** | Long-context transformers | No desync allowed | Situation-aware traces |

---

## 📊 Multimodal Capture Without Drag

Streams: 4K gameplay frames, input events (sub-ms), audio cues, network/FPS telemetry, map objectives.

Processing: real-time segmentation, action intent prediction, automatic quality scoring, bias checks by role/elo/champion, privacy filters with redaction.

Architecture (lean and inspectable):
```
Watch-Mode Pipeline
├── Perception Engine       # Frame → structured state
├── Temporal Engine         # Inputs → sequences with timing
├── Fusion Engine           # Aligns modalities, scores quality
└── Privacy Engine          # Consent + sanitization + audit
```

---

## 🗂️ Dataset Form: Built for the Training Flywheel

```python
class ExpertGameplayDataset:
    """Lossless, aligned trajectories ready for System 2."""
    visual_frames: List[np.ndarray]
    action_sequences: List[Action]
    game_states: List[GameState]
    strategic_labels: List[Strategy]
    quality_scores: List[float]
    player_metadata: Dict[str, Any]
```

Features: expert trajectory mining, counterfactual synthesis, skill-balanced sampling, continuous quality scoring. Exported in a standard format so Developer-Mode can ingest without bespoke adapters.

---

## 🔄 Execution Loop (Always Improving)

1) Context detect → start capture; 2) adaptive quality (resolution/fps based on fight intensity); 3) inline quality and privacy filters; 4) post-game scoring; 5) ship to System 2 with lineage metadata.

Real-time intelligence: predictive capture for high-value moments, contextual filtering to skip noise, per-player playstyle modeling to surface diverse strategies.

---

## 📤 Handoff to Developer-Mode

Dataset layout:
```
ExpertTrajectoryDataset/
├── raw_gameplay/
├── processed_features/
├── expert_trajectories/
├── strategic_annotations/
├── counterfactuals/
└── quality_metadata/
```

APIs: fetch trajectories by skill/meta/patch; generate counterfactuals; compute quality reports; emit drift alerts back to Watch-Mode.

---

## 🏁 Excellence Metrics

- Capture completeness 99.9% for meaningful interactions.
- Timing accuracy <1ms; visual accuracy sub-pixel.
- Diversity balanced across champions/roles/regions; bias monitors always-on.
- Privacy: consent per modality; full audit chain; zero PII leakage.
- Throughput: thousands of concurrent sessions with <100ms ingest latency.

---

Watch-Mode is the silent superpower: high-signal, low-drag data that fuels relentless learning without compromising trust.
