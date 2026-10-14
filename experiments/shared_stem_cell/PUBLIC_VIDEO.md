# Public temporal-video Cell experiment

Research-only. This profile uses the ten small MP4 examples committed in the
`ryukenzen/360action` repository at tree `6e99f3e...`. The source repository does
not declare a license in its repository metadata; source MP4s and derived frames
must **not** be uploaded as workflow artifacts or promoted to a production corpus.
The source README and exact Git blob identities are retained for attribution and
audit. This limited use is not a license determination.

## Question and strong controls

Each source video yields four disjoint eight-frame landmark windows. Every window
appears twice with the identical frame multiset: original presentation and exact
reverse presentation. Presentation timestamps are the same increasing ordinal
sequence in both rows, so the timestamp values do not reveal the label. Source
videos, not windows, are split: six train, two calibration, two holdout.

A single frozen CLIP vision tower encodes frames. Exact frame-SHA caching reuses
features across the forward/reverse pair. Three light Heads receive the same
features and training budget:

- `order_blind`: a parameter-rich mean-pooled static control;
- `endpoint_delta`: a cheap first/last feature-difference Cell;
- `temporal_gru`: a recurrent temporal Cell.

The order-blind output must remain numerically invariant for each paired holdout
multiset. Checkpoint selection uses calibration only. Predictions are sealed before
holdout labels are scored. This is reverse-order detection on ten public examples,
not action recognition, causal video reasoning, future-world evidence, or video
generation.

## Acquisition and execution

The runner verifies the complete pinned Git tree entries, each source blob and the
source README. PyAV explicitly decodes one video stream with monotone PTS. Thirty-two
uniform source landmarks are resized with Pillow LANCZOS to 224x224 PNG; no answer-
dependent frame selection or silent replacement occurs. Extracted source media are
excluded from retained CI artifacts.

```bash
python -m experiments.shared_stem_cell.public_video --output /new/video-study
```

The dedicated workflow installs the pinned decoder/model dependencies, executes
actual public acquisition and CLIP inference, and retains only manifests,
predictions, costs, tests and failure evidence. Missing videos, model material,
decoder support or dependencies fail; no synthetic fallback replaces a public run.
Energy, total FLOPs, peak memory, generalization beyond the two holdout sources and
all product/FinalUse acceptance remain open.
