# Framework refactor: concrete source convergence

## Scope

The current implementation base is
[3c8dabe46598599e91b2b8b80081e09069ff9426](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/3c8dabe46598599e91b2b8b80081e09069ff9426)
from #6006. Keep the controlled App Server execution boundary, thin Agentd
assembly, original fact owners, role/secret boundaries, original intent/outbox
acknowledgement and read-only reconciliation. An unknown effect remains unknown.

This candidate combines focused repairs with their original parent histories.
It does not establish an ordinary CLI learning chain, independent deployed
B/C ownership, full physical-cost measurement, or whole-daemon/Root recovery.

## Source inputs

| Input | Exact source | Change |
| --- | --- | --- |
| #6035 | 086cc7d21bb958c348e352395f0355793ba2de94 | Accepted Submit survives response-waiter loss; original supervisor cancellation wins |
| #6034 | 21d2699b7ac7831f355f5acb9570a90da077dbe3 | Stage only the affected generation record; install after original durable append |
| #6047 | 98730dda67417a93689835f4961d3e807abf107d | Preserve typed evaluation Pending/Indeterminate through original error wrappers |
| #6018 | 95894b8c958a1fab691f7779942f5fb25b778f9f | Exact generic control-function locator with original negative source controls |

All four inputs have the same actual common base, 3c8dabe. Their changed paths
are disjoint. A combined source requires its own qualification; separate pass
counts are not summed into a combined or ordinary-chain result.

The Windows containment remains an independent candidate, #6038, based on
ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80. Its source, original deletion
observation and platform qualifications must not be attributed to this merge.

## Implemented behavior

### Accepted learning handoff

The original SQLite delivery claim precedes enqueue. A dropped response waiter
used to discard an already-claimed Submit before the actor wrote a checkpoint.
The actor now discards only abandoned read-only requests. Accepted Submit work
remains with its original supervisor, original expiry and cancellation token.

The four added cases exercise the real SQLite outbox and actor: dropped waiter,
cancellation before dequeue, cancellation during original attestation, and
expired accepted input. Stage observations in those mechanism tests are explicit
fixtures; they are not ordinary deployed A/B/C experiments. The claim-before-send
crash window and complete daemon death still require original read-only
reconciliation. They do not authorize a replacement worker or a new dispatch.

### Generation journal hot path

A transition previously cloned the complete GenerationJournal, including every
retained historical result buffer. It now computes only the affected next record
and the checked reservation delta. The original write/flush/sync succeeds before
the staged record is installed. Writer poisoning, dispatch-token consumption,
capacity checks and cold replay keep their existing semantics.

The regression cases retain a historical 64 KiB result buffer through unrelated
transitions and inject an actual writer-file failure without dropping the
original lock. These are mechanism checks, not a throughput or fair-batching
benchmark. Whole-history cold replay and the owner lock are still present.

### Typed evaluation uncertainty

CellEvaluationErrorV1, ProductEvaluationExecutionErrorV1 and
ProductEvaluationError now expose their actual typed causes. The original Q24
classifier retains execution Pending, provider/store/holdout/evidence
Indeterminate and Cell generation Pending/CommitUncertain through original
receipt and I/O wrappers.

Missing, Rejected, Unavailable, Corrupt, StaleFence, generic Poisoned and error
message text do not manufacture durable uncertainty. The existing real
file-journal pending/missing cases retain the original call counts, execution
anchor and holdout bytes. No source traversal creates execution or retry
authority.

## Existing foundations retained

### Version and state

CellBackendManifestV2 binds source/bundle, components, runtime/device, input,
state and output schemas, evolution and adoption evidence. Resumable learning
also binds weights, optimizer, RNG, sampler and training cursor.

Cell bundle Preserve requires all components to be identical. Reset binds an
initializer and target checkpoint. Migrate binds a transform, source checkpoint,
target checkpoint and qualification. Rollback still advances generation from
the current predecessor. The cutover readback validator compares the complete
plan after the original owner has authenticated its receipt; it is not itself
an authentication, installation or recovery service.

### Evaluation and cost

The existing comparison reads original drained Cell journals, charges failed,
cancelled and rejected attempts, requires all declared stages and preserves
unmeasured metrics as unknown. Required metrics with unknown observations refuse
qualification. Independent final holdout and signed role separation remain.

Its declared frozen cost scope is TaskLedgersBeforeFinalHoldout. Final holdout,
signing and publication overhead are not thereby measured, and a wall/CPU
coverage contract is not a claim that physical energy or all external costs are
known. Full experiment accounting requires those actual meter/owner observations.

## Outstanding ordinary production assembly

The ordinary main still calls startup.receive(). A direct replacement with
receive_q24_learning cannot solve the current dependency: prepared learning input
requires an already-completed A, original Ledger history and original evaluator
authorization, whereas ordinary startup precedes A.

The actual Q24 circuit profile is not called by main. The ordinary root profile
parser has no complete Q24 Source/Cell/Generator/Ledger capability handoff.
Training's Generator key is a different original authority and cannot be reused
as A's fact producer. Task success is not a business Outcome.

The next complete production slice needs all of the following original inputs:

1. Original Source publication readback and committed Cell decision owner.
2. Original witnessed LedgerWriter and its activated learning trust.
3. The registered Generator signing owner, frozen completeness profile and
   run-to-episode binding. No substitute key or fixture profile.
4. An independent Observer's actual terminal business Outcome, with its original
   target, unit, observation window and signature.
5. Evaluator Dataset-cut authorization and late assembly under the retained
   supervisor, followed by actual Training, B/retention, Root CURRENT adoption
   and distinct C custody.

A producer must follow successful source publication and recheck the original
RunStart/currentness. It must persist its exact original Decision, signature,
operation identity and predecessor before contacting Ledger. Record identity is
the original run; snapshot identity covers the complete original RunStart.
Candidate/selected values come from the committed Cell decision. Only an actual
verified deterministic policy can claim probability one.

The operation identity must bind source publication, Cell decision, Ledger
binding, full RunStart and Generator/profile/trust identity. An acknowledgement
loss requires original full-record/authentication/witness readback. Re-signing
the same record with new times changes authentication identity and is not safe
deduplication. IndeterminateAfterLedgerCommit remains unresolved until the
original owner's recovery protocol establishes its state.

The existing circuit_learning_outbox_v1 has one row per run. Its immutable
request claim and ACK mean the original learning iteration completed NextUse.
It must not be reused as a Decision-append ACK. The fact producer needs its own
original stage journal/claim; only the genuine later Dataset cut can feed the
existing learning claim and NextUse acknowledgement.

## Windows remains a separate functional blocker

The retained original job 130668671332 checked out
a49776ffdea3547ed407a710bb19e93377b29535, with run head d0f6507e08f7f5c5855f5164d07c049a34d1a6d9,
on windows-2025-vs2026 image 20261103.298.1. Its outside-root files and directories
were deleted in TargetOnly, ParentOnly and Both permission cells. Neither
retained them. Duplicate log printing is not another independent experiment.

#6038 refuses the affected elevated path before preparation/ACL/token/child
effects and propagates the typed failure without unrestricted fallback. It
intentionally disables both affected elevated readonly and workspace-write
execution. The original deletion matrix and successful-operation controls remain;
refusal does not qualify them or close the functional P0. No conclusion about
all installations or attribution to MEM follows from this observation.

## Common merge provenance

The three actual two-parent merges are d1ed6f28a5400b98a07f004e9afb13c298c3d6d0,
60b6608012d241e5c57e6a052ecf86c50bcb5847 and
3094bdffa883385c45f189bc704d36a971d085a5. GitHub readback confirms their exact
parent lists and trees. The last merge changes precisely the 15 input paths;
every resulting blob matches its original input. The preparation child adds
only this record and the exact convergence-branch trigger for the existing
inference-maintenance workflow. No test command, expected assertion or owner
boundary is replaced.

## Qualification

Record each result against its exact source/tree, command, native log and
fresh JUnit where applicable. Keep earlier failed runs and unknown states.

The #6034 input at 21d2699b passed its original inference-maintenance run
43127681844/job130883821365: 96 native tests passed, 0 failed, 1 skipped;
format and unchanged-source checks passed. Its previous 445a28cb run retains
its overall formatting failure. Those are input-source results only.

The #6035 input at 086cc7d2 passed its original Shared Cell run
43127066547/job130881735265: 1,269 native tests passed, 0 failed, 77 skipped,
including all four new handoff cases. Its original fresh JUnit and source
identity checks passed. Its separate daemon/Root/maintenance workflow was still
running at preparation time.

At preparation time, evaluation-uncertainty native CI was queued. Windows
containment native CI was running. No combined-source
pass, ordinary Adopt/NoUpdate chain or full daemon/Root cold-restart pass is
claimed by this document. The managed local executor was unavailable; GitHub
source operations and the original GitHub CI are the available execution path.
