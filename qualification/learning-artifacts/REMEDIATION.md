# learning.artifacts remediation and acceptance record

## Baseline and claim boundary

Baseline: `a126987b84737dbc2ee2592442a314117bddb4a2` (2026-09-25).
This document accompanies a qualification-infrastructure candidate, not a
production activation, security acceptance, power-loss certificate, or release.
No completion percentage is an acceptance criterion.

The source uses `LearningArtifactOwnerService`, a fenced owner host, a signed
CURRENT chain, and an independently retained restart anchor. The service already
scans unfinished operations at startup. There is no demonstrated need to invent
a parallel `LatestPublishedHead` store. `PinnedCognitiveRanker` is the real Agentd
read consumer. Existing implementation-map authority flags are false and remain
false. Earlier prose claiming blanket COMPLETE, GC/refcounts/reservation journals,
or a LearningArtifactsRankerAdapter is not authoritative source documentation.

## Implemented qualification contract

The dedicated workflow runs metadata, individual native lanes, and actual-base
synthetic-merge qualification independently. A closed-world metadata failure does
not prevent Rust jobs from starting. The aggregate is always scheduled and fails
unless all expected job groups and all 13 lane receipts succeed.

Native lanes are build, strict lint, format, owner, storage, lifecycle, selection,
revocation, pinned load, publication, and the complete crate test set. These are
execution partitions of existing tests, NOT proof that every desired security,
property, fuzz, chaos, snapshot-fallback or production-E2E scenario already exists.
Every Rust test lane runs locked all-target compilation first and invokes the
repository's `just test` recipe. Nextest retries are disabled. The JUnit report
must contain at least one executed test, consistent suite/case counts, no duplicate
identities, and no reported failures, skips, or retries. Nextest 0.9.103 does not
report every filtered/ignored test in JUnit: this is not an ignored-test inventory
certificate. Filters select the named existing modules; an empty selection fails.

Every receipt binds exact source commit/tree, relevant Git source blobs, tested
tree/commit, workflow run/attempt/repository, job and lane, command inventory,
exit codes, output byte counts/SHA-256, and test identity digest. The collector
recomputes source bindings and the actual-base merge tree, verifies every retained
output, rejects missing/extra/duplicate/stale receipts, and keeps activation,
independent acceptance, and release false even on success.

Receipt digests detect inconsistent output; they are NOT signatures or proof of
who executed tests. Consumers must obtain artifacts from this exact trusted
workflow run, validate its GitHub job conclusions, and apply independent workflow
review/attestation policy. Locally generated JSON is never a hosted CI certificate.
Artifacts currently have 14-day retention; long-term release evidence must be
exported to the separately governed evidence store before expiry.

Run the receipt regression suite:

```sh
python3 -m unittest discover -s scripts -p 'test_hepta_artifact_qualification.py' -v
```

## Branch and release gate installation

Required check name: `learning.artifacts exact-head required`.
Creating this workflow does not install a repository ruleset. An administrator
must add that exact check, with the GitHub Actions app identity, WITHOUT removing
`CI required` or `Architecture required`. Require the actual PR candidate and
current base; requalify after either changes. The release gate must reject absent,
skipped, cancelled, stale, or failed checks and validate the aggregate artifact.
Do not force merge around the existing Lane E closure failure. Do not replace
failed checks by successful synthetic statuses. This PR does not modify protection
settings or the production release controller.

## Open implementation and evidence obligations

| Workstream | Current disposition | Required acceptance evidence |
| --- | --- | --- |
| Original Lane E closed-world failure | Diagnosis still required | Exact verifier findings resolved, old Lane E green on current head and base merge |
| Dedicated artifact execution | Workflow and receipt validator implemented | All 13 receipts and GitHub job conclusions on the final commit |
| Required check enforcement | Check emitted; repository setting not changed | Protected-branch/ruleset export and a blocked negative PR |
| Writer daemon/transport | Existing library service; no new production daemon in this change | Authenticated client-to-daemon-to-owner durable E2E and explicit startup wiring |
| Durability/dirfd confinement | Existing host/storage implementation unchanged | Filesystem/platform fault matrix, directory synchronization review, hostile-ancestor tests |
| Owner decomposition/storage injection | Not implemented in this change | Behavior-preserving refactor and unchanged canonical/recovery golden fixtures |
| Property/concurrency/fuzz/chaos | Existing tests partitioned; new native methods not claimed | Model invariants, parser corpus, real SIGKILL harness, capacity/benchmark artifacts |
| Production operations/metrics | Acceptance contract below; instrumentation not implemented here | Named operator, deployed metrics, alert and restore exercises |

The two coverage-tool versions and attestation pins in the old Lane E verifier
are both present in different workflow jobs. Their coexistence alone is NOT the
established cause of the failed closed-world step. No version check has been
removed to manufacture a green result.

## Production writer integration contract

Use the existing owner service as the single mutation authority. The process must
hold the OS writer fence for its lifetime; clients may not receive arbitrary
mutable registry/file handles. Authenticate each request before decoding an
operation into the writer boundary. Bind authorization to action, registry/scope,
operation ID, intended content and epoch; distinguish read status, publish,
recovery, key rotation, export and restore privileges.

Startup must authenticate configuration and trust roots, acquire the writer lock,
validate the independently retained current-head anchor, recover canonical state,
and enumerate unresolved publications before advertising readiness. Liveness only
means the process is responsive; readiness requires authenticated current state,
no unresolved indeterminate write, trusted paths, and available durable capacity.
Do not infer readiness from a successful TCP accept or a nonempty directory.

For pending publications, expose read-only diagnostics and authenticated recovery
of the SAME operation and bound request. A reissued operation ID with different
semantics must conflict. Never delete a suspect checkpoint to clear readiness.
Graceful shutdown closes admission, drains the active bounded operation, syncs
state, and only then releases the writer fence. An uncertain write remains
uncertain across restart; it is not converted to success by shutdown.

No transport, authority keys, or operational credentials are shipped in this
change. Deployment must provision owner and independent selector/recovery trust
with explicit epochs, validity intervals, revocation and rollover policy. Key
rotation must retain the trust needed to verify historical records, reject new
writes under revoked authority, and bind a new independent restart anchor. A
rollback restores eligible bytes, not an old authority epoch or revoked head.

## Filesystem and recovery acceptance

Qualify each supported OS/filesystem independently. File fsync, process-crash
recovery and power-loss durability are different claims. Audit synchronization of
all containing directories after namespace creation, publication and authorized
deletion. Cross-file ordered checkpoints are not a multi-file atomic transaction.
A host-designated root plus lexical/symlink checks is not a dirfd/openat2 capability;
concurrent hostile ancestor replacement remains a separate confinement obligation.

The crash harness must interrupt before and after each publication durable phase,
after signed CURRENT publication, and before acknowledgement; restart under the
same independent anchor and reissue the exact operation. Retain persisted phase,
registry and payload receipts, signed head, error category and final eligibility.
Do not assert refcount or GC invariants until those facilities are actually
implemented and included in the source inventory.

Process SIGKILL tests must not be labelled power-loss tests. Power-loss testing
requires a disposable VM/block-device/filesystem harness capable of discarding
unflushed writes. Never run destructive fault injection on a production root.

## Backup, restore, withdrawal and migration

Export a consistent, fenced set of immutable payloads, registry/lifecycle/withdrawal
snapshots, signed head chain, checkpoints and their independent receipts. Keep
private signing keys out of artifact backups. Encrypt backups under separately
managed credentials and retain an inventory with integrity digests and generation.

Restore into a fresh private root, verify every canonical record and independent
receipt, then obtain current withdrawal/revocation/head evidence from the authority.
A valid older backup is not proof of present eligibility. Never start a writer
against an older head just because newer files are missing. A withdrawal must
invalidate affected live selection immediately; physical deletion from replicas
and backups is a distinct authorized operation with a recorded completion deadline.

Reject unknown schema versions. A migration must read the old version, validate
canonical history, write a new create-only representation, verify round-trip and
current eligibility, and publish under fencing with a new receipt. Never rewrite
historical evidence in place. Preserve V1 compatibility and V2/V3 admission
bindings. Rehearse restore and rollback using mixed-version golden fixtures.

## Observability and stable API acceptance

Use bounded, low-cardinality event/reason enums for busy lock, admission rejection,
invalid signature, stale head, scope mismatch, capacity, corrupt state, indeterminate
I/O, recovery pending/completed and unsupported ranker cells. Bind audit events to
operation ID, registry generation and receipt digest; do not place secrets,
artifact bytes, arbitrary user strings or unbounded IDs in metric labels.

Required measurements: writer lock delay, publication phase duration, recovery
backlog age, failed current-view verification, snapshot replay duration, capacity
utilization, rejected replay drift, ranker abstention/error counts and explicit
reload requests. Security/currentness failures must not become silent fail-open
ranking. Unsupported prediction abstention is a distinct bounded reason.

No numerical SLO or throughput is asserted without a retained target-host
benchmark identifying filesystem, hardware, compiler, dataset size and percentile
method. Current declared safety caps remain unchanged: 4,096 durable records,
8 MiB V1 snapshots, 64 MiB candidate payload and 4 KiB head witness.

Before a stable API release, inventory all reexports and named callers, designate
a narrow verified facade, deprecate bypass-prone compatibility entrypoints, and
prove caller migration and historical decode compatibility. A version bump alone
is not evidence of semantic compatibility or production completion.
