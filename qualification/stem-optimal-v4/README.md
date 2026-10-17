# Hepta Stem V4 — original EmbeddingGemma 2 + real 4096-Head shadow / Bellman control

**DRAFT · RESEARCH_ONLY · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO MAIN MERGE · NO CELL SPLIT · NO FINALUSE.**

Frozen base is the research-only V3 hard-charge BANKING77 cohort and the V1 three-pretrained-model reference. This child preserves all original V1–V3 files and their prior independent evidence; it never changes `main`, a production Stem, native Neuron, NDU, Worker, CAS/CNS, or any authority owner.

## Three falsifiable pieces

1. **Actual original EmbeddingGemma 2**: `google/embeddinggemma-2@914f7f89142e33e77833254d9c9b90c3cef7303b`, full upstream `model.safetensors` 1,488,915,288 bytes, SHA256 `197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79`. The runner streams and hashes the actual safetensors before any model load, rejects unexpected bytes and remote Python, selects text-only `vision_config=None, audio_config=None`, enforces CPU FP32 (never fp16), native `Classification` instruction and exact 96 original texts. Only TRAIN labels enter the physical producer. All original TEST labels are opened after predictions and their SHA seals on another runner.
2. **Equal-Head but *not* equal-representation/cost intervention**: The 768D native EmbeddingGemma representation is deterministically projected to 384D by `(x[0]+x[1])/2`, `(x[2]+x[3])/2`, etc., then L2 normalized. This is a deliberately lossy **research bridge**, not an EmbeddingGemma officially trained 384D Matryoshka representation. The preexisting V1 `4 × 6,914` gated Head is trained for exactly 100 Adam updates (seed 17, LR .006) using the *same* 64 FIT / 32 heldout V3 question identities as the three baseline models. The center-score, frozen Head and learned Head are all reported; 32 cases on one publisher cannot select a stem.
3. **Physical Head fleet, bounded cheap System 2 baseline**: On one real frozen EmbeddingGemma feature, allocate each of 4,096 Head tensors (28,319,744 FP32 scalars), run a measured batch with exactly 32 active Heads, record Head-only batch p95/p99, RSS and nullable energy/end-to-end p99. Separately, `system2_v4.py` implements exact rational finite-horizon, fully bounded Bellman candidate selection on pre-boundary forecasts with explicit stop and resource budget. It is not a trained NDU, FBSDE or evidence of reasoning lift.

## V5 physical source-parameter coverage admission (new, not complete checkpoint identity)

The real original EmbeddingGemma text-only loader now **streams every tensor**
from its SHA-256-pinned 740M-parameter original safetensors, converts the source
values to FP32, and checks that each unique physically loaded FP32 text parameter
is supported by an exact **shape + byte-value** match in the original checkpoint.
It fails before any task forward if a parameter was newly randomly initialized,
replaced, missing, nonfinite or changed. The additional work is included in the
same load/cold-start wall and complete CPU/RSS receipts. No network access,
train labels or Test labels are required by the check itself.

This is a **value-origin check** and not an issuer signature, certified logical
source-name mapping, or tamper-proof host attestation. Source values from unused
vision/audio weights remain available in the original archive; the loaded FP32
270M-class parameter count and disabled modality configs are separately checked.
Some legitimate architecture conversions could fail closed due to tensor reshape,
quantization or tied-parameter aliasing until explicitly audited. Do **not**
remove the bound to get a passing green build.

The independent reviewer requires the new strict tensor-coverage receipt, but
has no original model material and therefore cannot independently re-run the
full 1.49GB census. This is separately disclosed as **self-reported** model work.
Real hosted execution and exact-head passing CI remain pending until observed.

## V5 FIT-only zero-Head-SGD calibrated centroid control

The genuine EmbeddingGemma 2 producer now produces a fourth descriptive score
arm from **the same 96 real pretrained features**, with **no extra model
forward** and **zero Head SGD steps**. It derives the four class centroids on the
64 registered FIT examples, excludes each FIT example from its own class
prototype when selecting a temperature, evaluates **all 7 fixed positive
candidate temperatures** on only the 64 FIT labels, then freezes the lowest
FIT-only leave-one-out Brier temperature before scoring all 32 label-free heldout
embeddings. The independent late-label reviewer checks the fixed candidate grid,
train-only invariants, source IDs, costs and calibrated 32-item predictions.
It reports the new accuracy/Brier beside original centroid, frozen Head and
100-SGD trained Head, not as any official stem winner.

This is an *EG2-only* new matched-input cheap control. Historical Granite47/97
V3 receipts only allow postseal temperature **sensitivity**, not an actual
FIT-only calibrated output; do not compare their postseal-oracle temperature
scores as if they were equivalently trained controls. A fair cross-model
calibrated-control experiment remains an explicit future gate.

## Original mmBERT140 comparator denial (observed V3 physical failure)

The original V3 mmBERT job `117331622649` on run `39002204047` completed
successfully but logged that `embeddings.tok_embeddings.weight` was **newly
initialized**, not loaded from original pretrained bytes. As a result, a V3
receipt SHA and genuine 96 forward sequence count are **not** proof of an intact
pretrained 140M model. V4 retains the complete historical V3 review and
prediction ZIPs, but the V4 reviewer **strips mmBERT from eligible descriptive
pretrained comparisons** and emits a fixed `ORIGINAL_PRETRAINED_TOKEN_EMBEDDING_NOT_LOADED`
quarantine with the exact run/job IDs. This is source-bound to an independently
fetched job log in this research analysis, **not** a new issuer-signed model
integrity certificate checked on the scoring runner. A future repaired loader
must independently prove every required tensor and preserve original model/label
isolation; no silent checkpoint swap or retconned score is allowed.

## Fixed postseal zero-SGD centroid-temperature sensitivity

The independent reviewer adds a **complete fixed 1, 1/4, 1/16, 1/64**
centroid temperature sweep for the two eligible historical Granite arms, all
using the sealed original centroid probabilities. The diagnostic is computed
**only after reopening original publisher TEST labels** and cannot select a
winning temperature from those same labels. It **does not** claim a train-only
calibrated baseline, future task utility, nor use heldout information in any
model producer. A future true competitor must train its calibrator on fit/cal
only and freeze it before independent heldout labels are observed.

## V6 independent calibrated-output algebraic replay

The postseal observer now recomputes every EmbeddingGemma train-only control
probability directly from the **already sealed** uncalibrated centroid vector
using the FIT-selected temperature: `softmax(log(p_original) / T)`. It rejects
reordered, forged, altered or substituted 32-row calibrated probabilities.
This adds **no model forward, no training, no label access and no extra budget**
to the original producer. The independent scorer cannot prove the FIT-only
LOO loss curve or hidden raw pretrained features from a self-reported digest
alone; only the algebraically checkable test-time transform is independently
verified. A full train-only replay requires separately admitted frozen FIT
features and their source-backed provenance. Research-only / DENY_ALL.

## Strict evidence custody and nonclaims

The hosted workflow first downloads immutable publisher CSV bytes and verifies both source SHAs, exports an unlabelled heldout source roster, then runs 4 original pretrained CPU jobs on the SAME roster. It seals source and output digests, then an independent later job **re-downloads the original source** before scoring. It reuses the original three-model V3 reviewer unchanged and audits the fourth model with `review_v4.py`; missing/synthetic/queued model jobs are not marked successful. Model issuer signatures, human-independent provenance, full GPU energy, simultaneous 4096 requests, future data families, Head learned skill lift, actual Cell Split, stochastic NDU/FBSDE and multimodal decoding are **not provided**.

Reproducing *source/mechanism-only* checks (no pretrained inference):

```sh
cd qualification/stem-optimal-v4
python -m unittest -q test_v4
python -O -m unittest -q test_v4
```

The read-only workflow on a same-repository authored branch runs original heavyweight model jobs; a pull-request event runs only the source tests to prevent untrusted-PR model/weight execution. No job has write credentials or permission to modify protected branches. There is **no positive promotion path**: any results remain `HOLD_NO_GO`. Original `blocking-ci`, security, architecture, target-host telemetry, signed Artifact CAS, FinalUse, independent future-window and OOD/retention qualification are separate mandatory gates.

## Remaining work for real NDU System 2

Train a separate estimator using **genuine, independently observed** later task outcomes; compare deterministic stopping, learned Bellman continuation and bounded stochastic FBSDE with identical candidate/feature sources, CPU + energy/call costs and source/time-disjoint test sets. Only if their observed risk-adjusted task utility exceeds the cheaper deterministic baseline while old-task retention and safety stay intact should any NDU policy be considered for native shadow consumer qualification. Short-horizon local existence and a low numerical residual do **not** imply a global, unique graph solution or improved task accuracy.

## V7 independent train-only LOO feature-custody evidence

The producer exports a bounded, original **FIT-only 64x384 FP32** feature
witness with exact roster/model/projection and calibration digest. There are
**no TEST targets or TEST feature vectors** in the witness. An independent
Torch-free (Python stdlib only) runner recomputes all 64 leave-one-out
centroid losses across the same seven fixed temperatures **before downloading
original publisher TEST labels**; it checks the exact input FP32 bytes and
FIT-only labels, the seven reported FP32 losses under tight numeric tolerance,
the selected minimum, and separately SHA-verifies the original witness file.
The later independent human-label reviewer reruns this same check and binds
its output into the descriptive, unconditional HOLD_NO_GO report.

This witness is produced by the same original Encoder job and is a
**model-source-bound numerical replay**, NOT an independent second pretrained
forward, issuer signature, hardware attestation, learned reasoning, safe
Cell Split, or a new source-independent future evaluation. Any selected
model or qualified calibration claim remains DENIED.
