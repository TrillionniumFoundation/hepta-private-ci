# Hepta utility evaluation — evidence checkpoint

Frozen at 2026-11-13T03:52:53.358275+00:00. **HOLD. Real qualified authorized task chains: 0.**

This checkpoint preserves the previous published evidence and adds exact source preparation, isolated materialization, the failed native preflight, and the completed read-only missing-material diagnosis. It grants no runtime authority and makes no Adopt, complete NoUpdate, deployment, independent-evaluation or real-consumer success claim.

## Current source and actual execution

The source branch remains at `cc57c7198db6293ccca562253c42fffbe2a04633`, tree `b7b357c07b5539769a068c6b9b009629f5612d1e`. The original source-gate job `1a1d23c92f3-2564-1cb4` completed successfully: the closure gate recorded 492 explicit ok cases, the self-test passed, and the complete caller check passed. These results apply to that exact source; the new provider preparation is excluded.

The isolated materialization job `1a1d2d20686-392-36` completed successfully with all 15,188 physical source entries and the exact source inventory. Its detached Git state uses the separately observed index SHA256 `95547dcfed1945bb06b5400468ec228037cff5374b674ca033a7f66468b34193`. It did not run native behavioral tests. See [complete materialization placement](../utility-evaluation-20261112-36fa/cc57-isolated-materialization-v1/reconciliation-01/PLACEMENT.json) and [Root review](cc57-isolated-materialization-root-review-v1/REVIEW.json).

The subsequent native job `1a1d2e908ac-392-5a` ended normally as **failed, exit 1**, without timeout, cancellation or automatic retry. Its exact error was `ValueError: RUSTY_V8_ARCHIVE actual existing file required`. It dispatched **zero behavioral test commands**. The wrapper's original `UnknownMissingBefore` remains unchanged; a separately successful admission inventory comparison is not substituted for its missing before snapshot. See [47-entry failure capture](native-cc57-isolated-v1/attempt-01/PLACEMENT.json) and [Root refusal review](native-cc57-isolated-v1/attempt-01/ROOT_PREFLIGHT_REFUSAL_REVIEW.json).

The one read-only diagnostic job `1a1d2f968fe-392-69` succeeded. The fixed V8 archive path returned `ENOENT` in both observations; the existing binding was fully read and matched all 39,884 bytes and SHA256 `7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506`. The observed parent and input identities remained stable. The cause, writer and time of loss are **Unknown**. This diagnostic performed no repair or native retry. See [complete diagnostic placement](native-cc57-isolated-v1/v8-readonly-observation-v1/PLACEMENT.json).

## Frozen source preparation

The evidence contains immutable original and successor source packets for the Root resident provider, fresh Training and B preparation, shared original Training/Evaluation readback, the Linux cfg correction, mechanism tests, the narrow test-helper filename correction, explicit typed calls, fresh material/staged T→B/E preparation, Selector local opaque readback, Version-owned same-C NextUse/readiness, and the append-only test mount. The local combined candidate contains 53 changed or new Rust paths at this freeze. It remains **unformatted, uncompiled and unexecuted**.

The Version-owned NextUse service keeps the original context and same consumer; its new path checks the original absolute Version deadline before and after each real handler. The old read service remains unchanged outside the narrow addition. The six new mechanism tests and their mount are source proposals, not measured successes. See [NextUse placement](version-next-use-seam-v1/PLACEMENT.json), [Selector placement](original-evaluated-selector-local-readback-v1/PLACEMENT.json), and [test mount](version-next-use-test-mount-increment-v1/PLACEMENT.json).

The original 33 Root CI parent cases are preserved and six additional parents are prepared in the workflow and source guards. The partial caller inspection removed eight ambiguous method receivers through explicit typed calls. It is not the complete 6,619-file caller gate. Further complete registration, original formatting/lint/test gates, dual-UID owner processes, the full Fresh → Version → same C path and daemon/Root cold recovery remain outstanding.

## Evidence publication recovery

The first large tree request returned an actual 422 timeout/size error with no tree SHA. The expected 4,287-file leaf was absent when probed. A smaller first batch created immutable tree `53bbb8c9e94f117de2cae423948eef6acdf2f193` with 3,717 files; no commit or ref was moved. Transient tool state then became unavailable while the local files and Git objects remained intact.

This is an explicitly reconstructed checkpoint, not a claim that the unpublished 4,287-file plan was recovered exactly. It uses the fully recovered 3,896-file map, the unchanged 3,638-file published leaf, actual agent placements, and byte-verified local artifacts. Some Root-local SDK serializations that existed only in transient state are unavailable. The complete original H source/materialization/native/diagnostic records are retained. No H job was repeated because of state loss. The prior unpublished README and manifest are archived under `publication-recovery-v1/UNPUBLISHED_4287_*`; they describe historical intent, not a successful publication.

All 3,637 previous non-README paths are preserved byte-for-byte. The previous README is archived [here](checkpoints/README_3638FILES_BEFORE_ISOLATED_MATERIALIZATION_AND_NATIVE_REVIEW.md), including its earlier provenance and failure history. The full reconstructed map is persisted as a separate immutable Git object before tree publication; its identity is recorded in the evidence commit message. Full API leaf readback and independent Git Merkle hashes are required before moving the evidence ref.

## Evaluation semantics and remaining acceptance

External user objectives, consequence predictions, policies, critic estimates, independently observed results and the public reward/cost contract remain separate. Missing authorization, outcomes, cost evidence, provenance, independence or original owner authority remains **Unknown / InsufficientEvidence**. Complete unfavorable comparison can support **Ineligible / NoUpdate** only when its evidence and hard gates are complete. Missing material or infrastructure failure is not objective fraud.

The required acceptance remains: a real authorized A → its original Training owner → independent B → Adopt or complete NoUpdate → a new actual consumer C → daemon and Root cold recovery. Model material must be obtainable and authorized, with actual consumer readback. Content identity alone cannot establish availability, legal authority or adoption. No real task satisfying that complete chain is counted here.

See [machine-readable checkpoint](publication-recovery-v1/CHECKPOINT.json) and [reconstruction provenance](publication-recovery-v1/RECONSTRUCTION_PROVENANCE.json).
