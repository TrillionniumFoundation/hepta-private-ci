# Shared Stem / Cell / NDU research continuation: P0–P5

**Status:** research-only execution and acceptance checklist. No new owner, model selection, policy waiver, or production permission. This is a work ledger, not a completed evaluation. Do not reinterpret prior receipts as freshly generated results.

## Immutable boundaries

- Source must be pinned by exact Git commit/tree; no green check from a different SHA is portable.
- An experiment result requires an actual complete execution receipt, source/model/tokenizer/preprocessor SHA-256s, sealed predictions before scoring, and independently observed outcomes.
- Maintain existing `blocking-ci`, Architecture, HNMF, artifact selection, revocation, and FinalUse gates. A PR is not production-ready because its mechanics tests pass.
- Per-request shared Stem parameters and objective remain frozen. Cell split, consolidation, candidate encoder changes, and topology changes publish *next-snapshot candidates only*.
- No private records, gradients, caches, or embeddings may cross scope boundaries on the basis of tensor similarity.

## P0 — reproducible executed evidence

**Current repair:** `.github/workflows/hepta-neuron-next-round-matrix.yml` explicitly pins `packaging==25.0` in the Python 3.13 CPU regression environment because `safetensors==0.7.0` imports `packaging.version`. The earlier run 38510873932 reported `ModuleNotFoundError: No module named 'packaging'`; its 24 errors remain failed historical evidence.

Acceptance:
1. Complete the same exact-HEAD full focused suite with no skipped imports/tests, including publication, retention, generation, cost and tamper cases.
2. Retain `pip freeze`, exact HEAD, full standard output and raw failed attempts. If installation or assertions fail, publish failure unchanged.
3. Separate job results: execution-regressions, HF architecture compatibility, public pretrained canary, architecture convergence, blocking-ci. Never infer one from another.

## P1 — shared Stem and Head resource frontier

Reuse `experiments/shared_stem_cell/execution.py`, `head_training.py`, `head_artifacts.py`, `head_batch.py`, and `experiments/shared_stem_head_matrix/runner.py` from the existing stacked research line. Compare:
- Frozen Head, linear, gated, post-Encoder low-rank residual, sparse expert, frozen no-change; the latter low-rank operator is **not** backbone LoRA.
- One physically shared Stem versus actual replicated full 421M weights; include a small/medium Stem control, same Reader and task cohort, and quality-matched rather than only parameter-matched comparisons.
- Logical cells 8/64/256/1024/4096 at separately fixed active concurrency, then vary concurrency. Count distinct physical Encoder forwards and reuse by exact compatible source, scope, ordering, and model identities.
- End-to-end total training/search/inference/evaluation/migration work, peak resident and transient bytes, p50/p95/p99, failed requests, queueing, energy **only if measured**, and old/new task quality.

**Gate:** no “savings” from parameter sharing alone when Encoder forwards are repeated; no “equal compute” from equal training steps or declared upper bounds. Declare missing counters null.

## P2 — specialization and low-cost consolidation

Reuse `experiments/shared_stem_cell/consolidation.py`, `partial_consolidation.py`, `residual_consolidation.py`, `ridge_consolidation.py`, and existing candidate-only split training. Preserve teacher bank and inherited parent as comparators.

- SVD-based ridge solves a different objective from AdamW/KL. Report both rather than pooling their scores.
- Compare shared+per-Cell correction, standalone linear, retained specialist bank, partial bank and no-change using precisely frozen same features, train-only targets and calibration-only selection.
- Count teacher-target generation, fitting, SVD/optimizer work, calibration, export and reload, plus shared+residual **two-Head** inference per row.
- Retain each old/new/negative-transfer result per Cell; calibration nonregression is not independent retention certification.
- Structural splits/consolidations only create versioned offline candidates. No selected-generation mutation and no loss of parent rollback reference.

**Gate:** independently scored future/held-out group improvement under cost and retention constraints; otherwise no specialization claim.

## P3 — true multimodal differentiation

Reuse `experiments/shared_stem_cell/media_execution.py`, `public_media.py`, `calibrated_fusion.py` and modality intervention probes.

- Freeze and pin text, vision, audio and temporal-video towers. Report token/patch/frame-level access, per-modality projection and connector costs; do not treat a pooled text embedding as a sufficient image/time representation.
- Register paired text→text, image→text, audio→text, video→text, text→image and text→audio tasks, with separate decoders and licenses for generation tasks.
- Complete joint, text-only, image-only, masked, donor-swapped and contradictory-evidence cases using exactly the same trained joint model and held-out case IDs.
- Report whether each sensor contributes information *needed* for independent task success; require external labels and provenance. Qwen text-only reference is not an image-capable Reader.

**Gate:** complete real natural modality cohorts, paired holdouts, modality ablations, task success, resource/retention results. Fixture connector paths are insufficient.

## P4 — shared Critic with bounded System 2

Use existing `system2_execution.py`, `ndu_continuation.py`, `paired_capture.py`, `paired_critic.py`, and `empirical_continuation.py`.

- Compare no search, truly fixed depth, replay/routing, vanilla tree, and NDU stop/continue under the *same* proposer, verifier, public task, independent observer and actual metering. No dummy critic, dummy work or candidate answer leakage.
- Train/freeze critic using predeclared paired stop/continue observations; groups used for fitting/calibration/final evaluation must be disjoint. Verifier acceptance is not the objective label.
- Supported group-average value bounds must not be represented as pointwise guarantees. Unsupported bins or unmeasured costs lead to abstention/frozen control, not a positive continuation value.
- Count all generator forwards, tokenization, critic, verification, retries, publication, failed executions and conditional-branch expansion.

**Gate:** prospective independent task gain over *both* fixed-depth and search-only controls at equal total resource/quality frontier, with stable abstention and cost limits.

## P5 — finite-tree BSDE then coupled FBSDE

Reuse `codex-rs/hepta-ndu/research/finite_tree_bsde.py` and `qualification/neuron-stem/fbsde_study.py`. Distinguish analysis-model stochastic time from neural-network layer depth.

1. Keep exact-rational finite belief-tree enumeration as the oracle for small tasks, with distinct OR, AND and chance semantics, admissible/public-information actions, and an explicit stop action.
2. Check local forward/BSDE residuals, global terminal condition, **both** sides of each interface, nonanticipativity and conditional covariance convention `Z Sigma = B`. Reject singular/ill-conditioned profiles without a separately admitted subspace method.
3. Validate a decoupling/continuation field for the *same* terminal objective, including global regularity/horizon admission. Small local residuals or the right final leaf alone do **not** imply a global solution.
4. Compare finite BSDE to exact cheap probability/Bellman algebra wherever the latter applies. Only introduce nonlinear/coupled learned fields in tasks where that cheaper control is not equivalent.
5. Separately measure solver approximation error, actual independent task utility, compute/latency, OOD, old-task retention and numerical stability. Failure to converge is an observed unsupported attempt.
6. Compress an admitted continuation field into one shared Critic; evaluate new held-out compositions and cost without recomputing the full tree. Do not equate low BSDE loss with independent language reasoning or a theorem of emergent cognition.

**Gate:** independently witnessed, cost-adjusted advantages and validated mathematical/qualification conditions before any native NDU consumer or production selection. No per-Cell complete FBSDE instance.

## Dependency chain

`P0 CI/reproducibility → P1 physical sharing/quality → P2 retention/consolidation → P3 genuine multimodal task gains → P4 independent continuation value → P5 global-consistency numerical qualification`.

Parallel exploratory work is allowed, but downstream **capability claims** must not inherit unmet upstream gates. None of these gates can be satisfied by an experiment plan alone.
