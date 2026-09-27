# learning.eval execution closeout and recovery amendment

## Delivery identity and scope

The active delivery path for this closeout is PR #1011,
`fix/learning-eval-full-convergence-20260926`. PR #1051 and its branch remain
historical comparison material; the two branches must not be independently
merged as if they were additive, independently qualified implementations.
The compared heads were `9d291c7fce494cb41645f14b664fd46ab585d2ec` (#1051)
and `8f36765e766bca49f8754e05c91d7ec3974f54c1` (#1011 after the anchor fix).
Their common base was `a126987b84737dbc2ee2592442a314117bddb4a2`.
The histories diverge. This document does not claim that #1051's commits have
been merged, or that every unique historical change has been accepted.

This is an additive execution/recovery amendment. Preserve the detailed design,
production contract, recovery contract, native mapping and canonical registries.
It is not a replacement for their generated projections, a passing CI receipt,
or an independent acceptance certificate.

## Existing candidate implementation versus this closeout

The candidate already contains write-ahead attempt identity, durable attempt
history, holdout reconciliation, publication phases, typed measured outcome
channels and the recorded product facade. In particular, `outcome_runner.rs`
is included through `recorded_runner.rs`, while outcome channel and receipt
exports are registered in `lib.rs`. Do not classify the outcome implementation
as absent merely because it is not a top-level module named `outcome_runner`.

This closeout adds:

| Change | Source | Verification source |
| --- | --- | --- |
| Poison the anchored wrapper across every attempted append until both journal and independent anchor acknowledge | `src/attempt_journal_anchor.rs` | `tests/attempt_anchor_acknowledgement.rs` |
| Per-command, failure-preserving, read-only execution receipts | `scripts/hepta-learning-eval-exact.py` | `scripts/test_hepta_learning_eval_exact.py` |
| Separate fixed-head and ordered-parent merge jobs | `.github/workflows/hepta-learning-eval-exact.yml` | Exact commit, tree and ordered-parent validation in the recorder |

Paths beginning with `src/` or `tests/` in the table are relative to
`codex-rs/hepta-intelligence-eval/`.

## Anchored append acknowledgement contract

Before an append is attempted, the wrapper verifies that its file-journal
anchor agrees with its retained independent anchor. It then marks the wrapper
poisoned. The poisoned flag is cleared only after the journal append, the
post-append anchor read, and any required independent compare-and-swap all
succeed. An idempotent append whose anchor is unchanged does not unnecessarily
advance the authority.

Any error after the write attempt requires recovery before this wrapper can
serve `append`, `latest`, `history` or `pending` again. This deliberately includes
known transition conflicts: the current implementation favors one conservative
recovery rule over error-class-dependent continued use of an already entered
write boundary. This rule does not mean that every failed transition committed.
Recovery must inspect the authoritative journal and independently retained
anchor instead of guessing from the error class.

A complete post-anchor tail can be recovered only through the existing
`recover_with_anchor` prefix validation. A larger sequence number alone is not
proof of valid history. An older complete backup must not lower the independent
anchor. A lost acknowledgement is not permission to clear final-holdout
consumption or re-execute the attempt.

New source tests cover accepted-but-unacknowledged anchor writes, journal-tail
commit before anchor acknowledgement, blocked operations on a poisoned handle,
and complete-old-backup rejection. Their test authority is an in-memory fault
fixture, not a qualified external anchor service. These tests do not replace the
existing process-termination and selected-storage-topology qualifications.

## Exact immutable-tree execution protocol

The additional workflow preserves the existing convergence workflow and its
artifact schema. It does not silently substitute a new schema for the existing
target-host evidence verifier.

For a pull request, two jobs are created:

- `exact-head`: checkout the event's full candidate SHA.
- `exact-merge`: checkout the event's full merge SHA and require the exact ordered
  parents `[event.base.sha, event.head.sha]`.

Push and manual runs test one exact head. A head result cannot stand in for a
merge result, and two CI jobs are not independent human/operator acceptance.

The recorder verifies the full SHA, tracked worktree cleanliness and tree
identity before execution, and verifies them again after execution. Commands
are run without a shell using explicit argument vectors and working directories.
Each executed command has timestamps, exit code, status, a retained combined
output log and a SHA-256 digest. A missing executable has no invented exit code.
A timeout kills the subprocess group. Commands after the first failure are
marked `not_run_after_failure`, never `passed`.

The command set retains owner/consumer compilation, API positive/negative
fixtures, owner and consumer regressions, fault injection, the declared storage
profile, the 85 percent library-line coverage threshold, strict lint and
formatting. The storage profile is a synthetic source-level profile, not a
production capacity claim. Its denominator and expected counters are checked.

Outputs are written only under:

```
.hepta-evidence/learning-eval/head/
.hepta-evidence/learning-eval/merge/
```

`convergence.json` in these subdirectories uses schema
`hepta.learning-eval.exact-execution.v1`. It binds the tested commit/tree,
candidate, base, ordered parents, workflow run/attempt/job identifiers, command
receipts and output digests. It is distinct from the existing convergence
workflow's root-level artifact and schema. Artifact names include tree kind,
tested SHA, run ID and attempt. Upload is attempted on failure as well as success.
A setup failure before the recorder starts is not a source qualification.

No qualification command updates `CURRENT_STATUS.json`, an implementation map,
an execution dossier, or any other tracked source file. Only all required
commands passing, output validation passing and unchanged source allow
`sourceQualifiedByThisRun=true` in that execution's receipt. Target-host,
independent-acceptance, activation and release claims stay false.

## Documentation/status consistency still requiring closure

The older `TECHNICAL.md` paragraph naming the raw `ProductEvaluationRunnerV1`
as the canonical product composition must not be read as overriding the actual
default public API and the recorded facade's durable-journal requirement.
The raw runner is a compatibility surface behind `trusted-inprocess-eval`;
production composition uses the recorded runner. Likewise, historical `None`
write-domain prose must be reconciled with the canonical ownership registry,
not resolved by granting this module another owner's write authority.

This amendment records those discrepancies rather than pretending the canonical
projection synchronization has been completed. The generator-controlled
`TECHNICAL.md`, implementation map, native mapping and canonical status must be
regenerated/verified together before declaring the documentation gate closed.
Detailed design content must be retained. Neither a new document nor a source
file's existence is evidence that the exact final tree compiled or passed tests.

## Observed execution and open gates

The six hermetic Python recorder regressions were executed successfully in the
local working environment during this closeout. They cover exact SHA/clean-tree
validation, ordered merge parents, failed-command evidence, no external authority
on success, mutation during execution, and launch errors. This is a test of the
recorder, not of the Rust evaluator or of a real host.

The Rust anchor regressions are committed source. Their execution status, the
complete evaluator test suite, coverage, strict lint and both exact trees must
be taken from the final commit's Actions results. Do not carry an intermediate
commit's passing or queued state forward to a later head. No production gate is
marked complete by this closeout document.

Remaining acceptance obligations include a concrete authenticated host identity,
provider and outcome provenance, independent anchor storage outside the journal
rollback domain, durable publication storage and pending-discovery/reconciliation,
process-termination testing at each real persistence boundary, and sustained
capacity/recovery testing at that selected topology. A file-backed fixture or a
GitHub-hosted synthetic profile is not proof of those external properties.

Real future-calendar outcomes, independent result sources, retention, privacy,
unlearning and statistical power require actual bounded observations and
independent attestations. Record the exact window, data/lineage identifiers,
issuer, permissions/revocations, measurement contract, analysis plan and artifacts.
Do not manufacture observations or self-sign an acceptance record to close these
gates. Missing host data and independent acceptance remain open, not successful.

## Recovery/operator sequence

On an indeterminate append or anchor acknowledgement, stop using the handle.
Retain the attempt identity and all independent anchors. Reopen the locked
journal against the authoritative retained anchor, prove its prefix, reconcile
any complete valid tail, and enumerate bounded pending attempts. Reconcile
holdout and publication records through their owners; do not clear a consumed
holdout or rerun the evaluation to repair missing evidence. An unverifiable old
backup, mismatched binding or stale writer is a hard stop requiring investigation.

Only after the final head and ordered merge qualify should an independently
bound target-host qualification be evaluated. Production selection, activation,
promotion and release still require their separate authorities.
