# NDU-DMGP convergence gate register (research-only)

**Status:** DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.
**Frozen parent:** `86194d2afaee2cadccc0ef3d824dfc3879d8950d` (the A0–A5 shadow arm implementation, PR #3441).
**No authority changes:** canonical `utility.ndu`, `neuron.runtime`, CNS, external action/selection, wire V1s and artifact promotion are unchanged.

This stack deliberately **converges** already implemented independent research slices rather than inventing new proof:
- `signed_evidence.py` and its adversarial tests are carried from PR #3435 (source blob `18085db7c27c20b7adcc708efcc9d6f318c8bd2a` before additional hardening).
- `causal_credit.py`, `history_closure.py` and their tests are carried from PR #3420 (source blobs `c2f5612a6dee2591a03ceba3613c29da04d60069`, `2ee383cc05863fdc0799ff5236234fa94ed797c2`).
- They are added alongside the existing PR #3441 synthetic `experiment.py` and `reference.py`. All are automatically discovered in **one** CI job; this is not a merge into `main`.

## Blocker acceptance rule

An executed Python/cryptographic regression test closes at most a **research code-path or evidence-format** defect. It never independently proves that a model generated output, an external observer observed it, a GPU performed the measured work, or a deployment grant exists.

| ID | Scientific blocker | Present source-level verification | Required *external* closure evidence | Status |
|---|---|---|---|---|
| DMGP-01 | NDU reward truth | Frozen IDs; observed-vs-forecast separation; detached observer/host Ed25519 envelope with out-of-band keys; cross-arm pair and split checks | Independently trusted Observer/host keys + real task outcomes, fixed objective, trained and frozen Critics, measured costs, nonrepeated clusters and future-only independent evaluation | OPEN |
| DMGP-02 | Cross-modal consistency | Semantic plan, entity/time checks, bidirectional claim digests; audiovisual skew and modality constraints on signed observations | Real text/image/audio/video reverse-perception outputs, evidence ranges and independent human/perceptual synchronization checks | OPEN |
| DMGP-03 | Conditional covariance | Joint context support, centered sample moments, raw-rank-before-shrinkage, bounded PSD fallback; malformed covariance rejects | Real *decoder-expert* joint candidate interventions in train split, out-of-time calibration, condition/sensitivity, sampling propensities and distribution-shift review | OPEN |
| DMGP-04 | Resource efficiency | Exact integer work identity, separated controller/decoder/verifier fields; signed host-meter format, strict end-to-end lower bound | Same hardware, paired quality and budgets, actual CPU/GPU/VRAM/RSS/energy/p95/p99, 64/256/1024/4096 Cell recovery/resource tests | OPEN |
| DMGP-05 | Stable learning | Freeze ID and KL/update trust checks, next-generation-only proposal, synthetic retention/future bounds | Real trained Actor/Critic/Decoder candidate, signed CAS/snapshot compatibility, genuinely future independent windows, old-task retention, rollback and independent selection | OPEN |
| DMGP-06 | Causal global credit | Prospective factorial signed-fixture schema, complete coalitions, Shapley conservation, interaction and prospective history-vs-state audit | Randomized interventions from real Cell/Circuit owners, consistent outcome support and causal assumptions, memory/state closure review with independent clusters | OPEN |
| DMGP-07 | Markov/closure | Train-only compressed vs history-augmented out-of-time residual diagnostic | Heldout realistic traces, delayed outcomes, state sufficiency tests under policy changes; passing finite probes is not a Markov theorem | OPEN |
| DMGP-08 | A0–A5 superiority and gate | Six disjoint synthetic arms, paired cases, run/trace identity, numeric fail-closed tests | Registered familywise power/sample-size; real matched multicriteria utility; A5 **must** beat all cheaper baselines in equal-budget independent future observations | OPEN |

## Statistical discipline

The detached signature verifier reports quality-only diagnostics. When at least 32 matched future episodes exist, its A5-vs-A0–A4 bounds use a **fixed five-comparison familywise 95% one-sided Hoeffding bound** on quality differences in [-1,1]. Independent *clusters*, not just distinct IDs, are an unverified assumption. Therefore `independent_clusters_verified=false`, `production_blockers_closed=false`, `no_promotion_authority=true` are mandatory even with a positive synthetic estimate. Covariance from A0–A5 **policy-arm returns** is not automatically the covariance of decoder experts.

A5 and A1 were tied on the parent synthetic fixture; A5 had extra controller overhead. Preserve this as negative evidence; do not tweak synthetic reward after observing it merely to manufacture a win.

## Required execution and evidence

```bash
python3 -m compileall -q qualification/ndu-dmgp-shadow
python3 -m unittest discover -s qualification/ndu-dmgp-shadow -p 'test_*.py' -v
python3 qualification/ndu-dmgp-shadow/experiment.py
```

The read-only GitHub Actions job must verify the **exact PR head** before the test suite. Native Rust/CNS integration, pretrained backend, real media, target hardware, independent operator and release evidence must have separate exact-source receipts. A queued CI job is not success.

These schemas do **not** provide runtime capability, token-free model calls, effect authority, self-issued trust roots, Cell Split, production NDU selection or promotion. `MANIFEST.json` must keep all production flags false, and no test may flip them.
