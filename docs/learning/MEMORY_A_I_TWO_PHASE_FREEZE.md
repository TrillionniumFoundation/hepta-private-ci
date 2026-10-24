# Memory A–I — Two-phase prospective freeze (research only)

**Status:** `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`.

## Why this is needed

The prior single frozen plan in [#3411](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3411) and the physical training receipt audit in [#3481](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3481) both expect final E–I trained Head/Router/Graph/evolution artifact hashes. Those hashes do **not** exist before the actual training. A plan that claims to freeze them before training without an independent past owner receipt is not a genuine prospective preregistration. This fix **does not manufacture evidence** of prior training or any external timestamp.

This module reuses the exact A–I arm definitions, 11 comparisons, source-separated case windows, Reader/Encoder/source/forget identifiers, fixed cost limits, original whole-answer scorer and E–I physical training cost audit. It changes no production authority, model selector or weight owner.

## Mechanism

1. **Phase 1 — protocol (BEFORE training).** An independent owner is expected to receive `PHASE1_SCHEMA` input containing every source-first `common`, `arms`, `cases`, `policy` decision and per-arm publisher **code/config/recipe SHA**. *Only* `artifact_sha256` and `training_receipt_sha256` for E–I are `null`; every other field is fixed. A separately held gold commitment is a reference only. The complete canonical phase-1 digest must be pinned externally before the first training or before the held-out cohort is exposed.
2. **Training (source-disjoint).** Actual E–I Head/Router/Graph/evolution work is performed against only permitted training roots. Keep full original tensor bytes, source ancestry, optimizer journals, allocation and measured resource receipts. No future labels, outputs or post-hoc tuning may enter training or model selection.
3. **Phase 2 — material (AFTER training, BEFORE evaluation).** Commit the final ordinary nine-arm plan, training receipt inventory, source/forget frontiers, Reader and Encoder identity, material bytes/receipt digests and an external evaluation-start cut. Pin the canonical phase-2 digest via an independent owner before any future Reader generation or gold reveal.
4. **Verify and evaluate.** `verify_two_phase` compares every Phase-1 design field against Phase-2, permits ONLY the two E–I material fields to be filled, rechecks the complete E–I training cost/lineage journal and refuses missing, aliased, recomputed or wrong-parent material. `audit_with_two_phase` then calls the original whole-task A–I `audit`, supplying the verified materialized plan and its complete E–I receipts.

Neither local SHA fields, locally generated timestamps nor apparent signer IDs are independent authenticity evidence. A separately trusted evaluator must verify the actual two time-ordered owner records and original model/Reader executions. Without such a verifier, even an otherwise mathematically positive research report remains `HOLD_NO_GO`.

## Test surface and reproduction

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s qa/stem-bakeoff -p 'test_memory_nine_arm_two_phase.py' -v
```

The tests are **synthetic protocol and adversarial fixtures only**. They include source/cohort/window drift, illicit preregistered trained hashes, gold injection, rehashed Phase-2 budget drift, stale frontiers and Readers, borrowed E–I tensor/receipt identities, missing training work and simulated optimizer-event forgery. A passing test or workflow demonstrates fail-closed validation, **not** any executed nine-arm model task or scientific Memory superiority.

## What remains blocked

- P0: Independent phase-1 and phase-2 time-ordered owner attestations; choose one reviewed canonical plan among the parallel draft qualification PRs.
- P1–P5: Same-cohort original A/B/C/D physical retrieval, true E/F memory-task learning, G sparse Router, H genuine learned Meta-Graph with lesions and I equal-cost Split/Merge.
- P6–P7: Original shared Reader answers, independent semantic/citation judgments, two truly *future* time windows and at least 200 independent source groups.
- P8–P9: End-to-end GPU/CPU FLOPs/RSS/latency/storage/rebuild cost, deletion and parameter quarantine, owner authentication, restart and rollback verification.
- P10: Terminal successful required exact-head CI, Architecture, V8, Linux/macOS/Windows, RustSec, and original model jobs. No bypass, artifact promotion or merge merely because a shadow schema passes.
