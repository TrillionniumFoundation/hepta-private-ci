# Explicit recovery of cancelled question-relevance work

Date: 2026-10-14. PR #1697. Implementation parent0ff4579790662ebe413cdd46e201dca2031d4b36.
At publication this recovery code is submitted, not observed tested or executed.
Local container and both Python interfaces returned ClientError. Prior cross-check
patch61d5f106 publishes earlier local measurements, not new current-turn results.

## Observed interruption, not an absent or still-running experiment

Original source644799a3ec45e18e77ce4ad772029f67fee55db7, run38512395172,
job115683615689 is completed/CANCELLED. Full decoded logs were inspected.
The job began04:38:06Z and cancellation appeared05:23:23Z. Its workflow has a
45-minute limit; timing is consistent with that limit, but the cancellation
reason beyond the reported status was not independently established.

The original tests and input SHA checks passed. Logs report completion of the
frozen arm at04:42:04Z, repeat-empty at04:56:30Z and nonempty-aligned at05:12:44Z.
The reverse-label arm had not reported completion before cancellation. The
retained artifact is11872208169,3,523,640 bytes/526 uploaded files, SHA256:
601cd09ae82cc6915121aaf8bb0eac5c1fe7c8b370c9d4a832bc6e5d54b91bac.
The download succeeded but local rehashing did not execute. Exact member hashes
and terminal optimizer states must therefore be verified by the hosted recovery.

A prior followthrough requiring the full completed-success artifact remains
blocked. It is not fixed by changing the old cancelled run to success, accepting
a partial checkpoint, removing reverse control, or silently borrowing an older
Reader. No such reinterpretation is performed.

## Recovery policy fixed before resumed model work

Preserve the scientific four-arm plan, all28 original dated TRAIN examples,
14 original pairs/13 supplementary donors, fixed eight epochs, LoRA seed/rank/
learning rate, original SELECT requests and all diagnostic limits. Existing
training/loss/snapshot owners remain unchanged. The trial gains an explicit
execution subset option; omitted means the old four-arm schedule and metadata.
Subset outputs retain the full scientific plan and state clearly that they do
not complete the full study. Existing full-result validation rejects them.

Reuse frozen_reader, repeat_empty and nonempty_aligned only when their exact
complete raw files match the fsynced journal and raw seals, all27 callable input
slots plus the original unavailable slot validate,14 TRAIN diagnostics and4
SELECT audit slots are complete, and trained candidates have final receipts,
112 completed updates/864 measured forwards and all pinned adapter files. The
post-cancellation ZIP must pass its external SHA and every internal member hash;
truncated/corrupt journals stop recovery rather than being repaired. Outcome
quality is not a reuse criterion.

Restart nonempty_reversed ONLY when the exact fixed cancelled artifact has no
final training receipt or raw arm result and its optimizer journal contains an
incomplete training prefix. Restart from the original base and seed through the
same trainer. This is NOT optimizer-state continuation: no checkpoint with lost
Adam moments, RNG or gradient state is presented as a valid resume. The abandoned
prefix and its observed work are preserved as additional cost. An unfinished
last update has unknown remaining cost, never zero. No automatic retry is added.

Before combination, original and restarted plan, train-plan, token-compilation
and public-input files must be byte-identical. All trained initial adapter hashes
must agree. Reload every retained and new saved candidate with the original strict
snapshot/compose/attach/verify_resident path. This validation adds load costs but
no new generation or optimization for the three complete arms. It does not
invent the historical in-memory integrity field lost with the final report;
that absence is explicit, and the new strict saved-byte verification is labelled
as current verification rather than a claim about past process state.

## Distinct recovery result and provenance

Recovered results use hepta.reader.relevance-recovery.v1.result, not the old
question-relevance result schema. Original run/source/status and cancelled ZIP
pin are recorded in recovery-manifest.json alongside origin per arm and a full
material file census. Each reused raw/scores/diagnostic file is copied byte-for-
byte; old and new event chains remain separate. No synthetic combined journal
claims a single uninterrupted execution. Newly measured reverse-arm calls and
updates, reused historical calls, abandoned prefix, loading and verification
costs are reported separately. Missing SELECT reference/donor positions remain.

The recovery validator is opt-in and requires an externally pinned complete new
archive, exact execution-source binding, full file hashes and every final model
receipt. The old followthrough success guard remains unchanged in this increment;
a recovered artifact must be explicitly admitted through this distinct validated
origin in a follow-on invocation. No production/Reader gate is issued by recovery.

## Tests and execution routing

25 new stdlib regression definitions cover execution subset isolation, unchanged
scientific plan, actual journal work, open/failed updates, duplicate/overlapping
attempts, corrupt/truncated chains, receipt/file mismatch, no overwrite/symlink,
all original raw/audit positions, target chronology and incomplete outcome files.
They are submitted definitions until an actual test run completes. The19 prior
supplementary SELECT checks are now on the remote branch; their earlier local
pass remains historical and is not a current-source hosted result.

The dedicated recovery workflow requires all inherited question training and
SELECT followthrough suites before model work. Commits marked [recovery-only]
route away from the old all-arm retraining workflow, because that would duplicate
two completed fits; the full test suite instead executes in the recovery lane.
No test or scientific control is dropped. A separate read-only recovery-inventory
workflow reports actual archived counts without loading any model. Its pending
state at publication is not evidence that either saved checkpoint is reusable.

The recovery job permits60 minutes for the single unfinished arm plus verification,
not a larger optimization budget. Scientific targets, eight epochs, per-call
limits and original failed projection tolerances are unchanged; full-logits-v1
remains the only path used here. All previous cancelled/failed artifacts remain.
No semantic score, independent review, new unseen task, shared-cost benefit,
Group/NDU improvement or five-experiment completion follows from recovery.
