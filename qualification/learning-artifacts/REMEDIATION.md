# learning.artifacts remediation: evidence first

Baseline: `a126987b84737dbc2ee2592442a314117bddb4a2` (2026-09-27 review).
This is an engineering qualification runbook, not product activation or release.

## Corrected baseline

The owner is `LearningArtifactOwnerService`, over `LearningArtifactOwnerHost`.
The registry head is distributed through signed CURRENT records. A
`LatestPublishedHead` trait, reservation journal, refcount GC, and a
`LearningArtifactsRankerAdapter` are not established by this review and are not
implementation targets for an imagined parallel subsystem. The actual reader is
`PinnedCognitiveRanker`. Its current-view errors invalidate the cache; an
unsupported prediction cell is a different, explicit abstention case.

The implementation map already retains `productionImplementation`,
`productExecutionProved`, `independentAcceptance`, `activation` and `release` as
false. Its `sourceBase` is provenance, not a field to rewrite to the tested head.
No global COMPLETE flag is introduced. Existing manifests remain unchanged.

## Exact-head evidence

The new workflow runs Ubuntu/macOS on the exact source and an actual-base,
ordered-parent ephemeral merge. `pull_request`, `merge_group`, main pushes and
explicit dispatch are covered without a paths filter. Dispatch/initial pushes
without a base use the source parent; that case is **not** advertised as an
independent integration against a newer main.

Build, strict Clippy, format, complete test discovery, package tests and the
existing Lane E closed-world check run independently. A failed closure check
still fails qualification, but no longer prevents all artifact Rust tests from
being attempted. This is not a bypass or a replacement for the global gate.

Tests use the repository's `just test`, including ignored cases and with zero
retries. The verifier matches the complete discovered multiset against actual
JUnit cases, rejects empty inventories and failed/skipped/retried/unknown
outcomes, and requires eleven native regression families. A library service
regression is **not** a process-kill E2E or a power-loss qualification.

Each run writes a create-new evidence directory with source/base/tested SHA,
tested tree, source object seals, exact argv, exit code, duration, stdout/stderr
hashes, JUnit results and operation-to-declared-test mappings. Unmapped operations
remain `unmapped_or_not_executed`; filename similarity is not proof of coverage.
A matching hash only proves integrity, not who executed the tests. Consumers must
verify the trusted GitHub repository, workflow source, run ID, attempt and check
result; independent provenance/acceptance remains required. Do not ingest an
arbitrary uploaded JSON as release authority.

`Lane E artifacts required` is the stable aggregator. Missing, failed, cancelled
or skipped matrix execution is not success. Repository administrators must add
this context (GitHub Actions app) to the existing main/merge-queue rules **without
removing CI required or Architecture required**. This patch does not claim to
have changed repository administration settings or any release workflow.

## Remaining global Lane E blockers

Run 36092481108, job 107937631517, reported eleven findings on the baseline:
learning.operator operation-set drift; traceability case-set drift; a missing
signed evaluation re-export token; and eight legacy-writer findings in Agentd's
objective_ingress, intelligence_product_runner and intelligence_product files.
Each needs source/semantic triage. Test-only references must be distinguished
from production paths by a tested parser, not file-wide string exemptions.

The verifier source also contains two different coverage-tool pins and two
attestation pins in its required-token checks. Reconcile workflow and checker as
one reviewed change; do not insert inert comments merely to satisfy token scans.
These global findings are **not fixed by independent artifacts qualification**.

## Production writer integration acceptance

Keep the existing signed lease, trusted signer registry, writer OS fence,
create-only snapshots and independently authenticated restart anchor. A host
must reject non-genesis startup without an independently persisted current-head
anchor. Recovery completes before routing requests. An indeterminate write
keeps the service unavailable until reconciliation; no blind same-path retries.

A production adapter still needs authenticated transport and action-specific
permissions for publish, inspect, recover, rotate and restore. External signing
keys must not be embedded in manifests, tests, logs or backups. Rotation uses a
new authority epoch and independently provisioned trust; expired credentials do
not grant new mutation rights. Stopping admission is followed by draining and
**dropping** the owner to release its process fence, not just a status flag.

Backup policy must preserve matching payload/registry/withdrawal/lifecycle/head
receipts and their independent trust anchor. Restore into a fresh protected root,
validate canonical bytes and the current withdrawal/head authority, then admit
reads. Never restore an old head as current or clear tombstones by fallback.
Backup erasure requires an inventory of all replicas and explicit retained
exceptions. Logical revocation is not physical deletion. No GC is certified by
this change, and no reference-count implementation is asserted.

## Durability, API and observability follow-through

Audit file and parent-directory sync at every create/rename/delete boundary.
Host-owned ancestor protection remains mandatory until a reviewed directory
capability replaces path traversal. Unsupported directory-sync platforms must
fail or explicitly remain unqualified, never silently advertise power-loss
safety. SIGKILL and real power loss are separate acceptance campaigns.

Extract owner recovery, authority validation and publication coordination in
small behavior-preserving changes with original tests. Introduce an I/O fault
boundary only with tests for the actual storage operations. Do not create an
alternate registry or change durable V1/V2/V3 formats as a refactoring shortcut.

Metrics must distinguish stale current view, invalid signature, revoked
artifact, unsupported model cell, writer contention, recovery-required state,
capacity limit, corrupt bytes and indeterminate I/O. Do not use artifact IDs or
secret-bearing payloads as metric labels. Proposed metric names and thresholds
are not production telemetry until instrumentation and alert delivery are tested.

Before any stable API release: inventory external callers, freeze the narrow
facade, retain historical decode fixtures, document migration/rollback, and
validate compatibility across previous snapshots. No version bump substitutes
for this evidence. State-machine properties, concurrency schedule tests, parser
fuzzing, process-kill E2E, power-loss harnesses and measured capacity curves are
still required, not inferred from the existing regression suite.
