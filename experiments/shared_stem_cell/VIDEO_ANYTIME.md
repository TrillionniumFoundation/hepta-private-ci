# Bounded anytime video Cell: actual frame-by-frame frozen CLIP work

**Research only; no production authority, no general NDU/FBSDE claim.** This
extension of the existing source-disjoint public-video order task tests whether
we can physically avoid encoding late frames. It is a new, multi-exit recurrent
model and does **not** retroactively change the original full-frame OrderBlind,
EndpointDelta or TemporalGRU studies.

## Preregistered comparisons

One `AnytimeCell` shares a single frozen CLIP and one 24-wide GRUCell/readout across
four exit depths **2, 4, 6, 8**. Train the recurrent model for **80 AdamW steps**
with the arithmetic mean of four per-exit cross-entropy losses on the original
six training videos (48 train rows). A separate 16-row, two-source calibration
set produces all four depth profiles. The seven frozen confidence thresholds
are `(0,.55,.65,.75,.85,.95,1.01)`; 1.01 forces all eight frames. Among rules matching the **best** fixed-depth
calibration correct count, minimize *unique CLIP frame features* in the
calibration SHA cache simulation, then *physical CLIP calls*, then requested
frame rows; all counters are checked against actual holdout execution. When no adaptive threshold qualifies, select the
best fixed-depth control instead. This fallback is included in the foreground
arm; do **not** turn it into a winning adaptive result. The same fixed calibration
set is reused for routing; it is not an independently validated quality floor.

A separate frame cache is created for **each** of `adaptive`, `fixed_2`,
`fixed_4`, `fixed_6`, `fixed_8` on the **same 16 holdout records**. Each path
actually requests successive two-frame chunks from the frozen CLIP tower;
only when the selected threshold is unmet does the foreground request another
pair. Previously stopped cases never call the tower for their remaining frames.
The same frozen GRU weights are used at all depths. Cache hits and unique
physical frame features are measured within each arm; cross-arm cache reuse is
intentionally forbidden. Original full-depth/head comparators remain in the
separately run existing study. No search or prompts use holdout answers.

**Resource caveats:** The experiment separately runs ALL shadow controls, so
its overall work exceeds a deployed single foreground route. The public video
stager, dataset validator and hash checker read/decode/check all staged frames,
including ones never CLIP-encoded; what the foreground can save is CLIP visual
feature computation, not source MP4 fetching, frame staging, or validation I/O.
Training and calibration also encode full sequences. The second experiment
loads a new frozen CLIP model; it does not borrow invisible model residency or
encodings from the first experiment. Report full load/training/calibration,
physical video calls, unique frames, requested rows, cache hits, and end-to-end
per-arm wall interval including record writes, **separately**. No power/FLOPs or
peak RSS values are imputed. Even fewer physical calls would not prove better
latency without a target-hardware equal-quality comparison.

## Execution

After the original, pinned `public_video` stage+full-frame study:

```bash
python -m experiments.shared_stem_cell.video_anytime \
  --manifest /staged/video-study/manifest.json \
  --output /staged/video-study/anytime
python -m experiments.shared_stem_cell.audit_video_anytime \
  --root /staged/video-study
```

The existing read-only video workflow runs both and retains their **report
files only**, never source MP4, derived PNG or pretrained model weight files.
The pure-standard-library auditor independently recomputes fixed/calibrated
accuracy, the routing grid, the chosen fallback, prediction identities,
per-depth stop traces, holdout correctness and physical-call accounting. It
cannot attest a physical CLIP execution, prove independence of the source
videos, or certify permission to reuse a source dataset that has no recorded
license. The source videos are used only for bounded research experiments.

**Scientific limits:** Forward-versus-reverse of the same eight frames is a
restricted temporal-order diagnostic, not action recognition, video planning,
general causal/System-2 reasoning, video generation or production capability.
Independent future quality, negative transfer, new Cell split gain, persistent
multi-modal generators and FinalUse remain unverified.
