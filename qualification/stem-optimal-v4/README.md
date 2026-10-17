# Hepta Stem V4 — original EmbeddingGemma 2 + real 4096-Head shadow / Bellman control

**DRAFT · RESEARCH_ONLY · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO MAIN MERGE · NO CELL SPLIT · NO FINALUSE.**

Frozen base is the research-only V3 hard-charge BANKING77 cohort and the V1 three-pretrained-model reference. This child preserves all original V1–V3 files and their prior independent evidence; it never changes `main`, a production Stem, native Neuron, NDU, Worker, CAS/CNS, or any authority owner.

## Three falsifiable pieces

1. **Actual original EmbeddingGemma 2**: `google/embeddinggemma-2@914f7f89142e33e77833254d9c9b90c3cef7303b`, full upstream `model.safetensors` 1,488,915,288 bytes, SHA256 `197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79`. The runner streams and hashes the actual safetensors before any model load, rejects unexpected bytes and remote Python, selects text-only `vision_config=None, audio_config=None`, enforces CPU FP32 (never fp16), native `Classification` instruction and exact 96 original texts. Only TRAIN labels enter the physical producer. All original TEST labels are opened after predictions and their SHA seals on another runner.
2. **Equal-Head but *not* equal-representation/cost intervention**: The 768D native EmbeddingGemma representation is deterministically projected to 384D by `(x[0]+x[1])/2`, `(x[2]+x[3])/2`, etc., then L2 normalized. This is a deliberately lossy **research bridge**, not an EmbeddingGemma officially trained 384D Matryoshka representation. The preexisting V1 `4 × 6,914` gated Head is trained for exactly 100 Adam updates (seed 17, LR .006) using the *same* 64 FIT / 32 heldout V3 question identities as the three baseline models. The center-score, frozen Head and learned Head are all reported; 32 cases on one publisher cannot select a stem.
3. **Physical Head fleet, bounded cheap System 2 baseline**: On one real frozen EmbeddingGemma feature, allocate each of 4,096 Head tensors (28,319,744 FP32 scalars), run a measured batch with exactly 32 active Heads, record Head-only batch p95/p99, RSS and nullable energy/end-to-end p99. Separately, `system2_v4.py` implements exact rational finite-horizon, fully bounded Bellman candidate selection on pre-boundary forecasts with explicit stop and resource budget. It is not a trained NDU, FBSDE or evidence of reasoning lift.

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
