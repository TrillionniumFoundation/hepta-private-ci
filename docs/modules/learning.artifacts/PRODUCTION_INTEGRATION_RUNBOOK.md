# learning.artifacts: production integration and recovery runbook

Status: integration contract and remediation handoff; not a deployed daemon.
Baseline: `a126987b84737dbc2ee2592442a314117bddb4a2` (2026-09-25).
Owner: learning-platform; durability counterpart: durability-kernel.

## 1. Corrections and actual interfaces

The authoritative writer is `LearningArtifactOwnerService` over
`LearningArtifactOwnerHost`. Currentness uses `SignedCurrentArtifactHeadV1`, a
verified head chain and an independently retained restart anchor. There is no
`LatestPublishedHead` trait in this implementation. Agentd uses
`PinnedCognitiveRanker`, not `LearningArtifactsRankerAdapter`. Cargo edition and
version are workspace-inherited; this change does not announce a 1.0 release.

`IMPLEMENTATION_MAP.json` already separates source mapping, product execution,
acceptance, activation and release. Its production claims remain false. Do not
replace those independent states with an undifferentiated completion label.
The original Lane E workflow had a `rust-closure` job and a `synthetic-merge` job,
not a separate job for each artifact testing category.

The registry is bounded and append-only. This implementation does not contain a
production reservation/refcount/GC subsystem. Such subsystems must not be assumed
by an acceptance checklist or invented in execution receipts.

## 2. What this change implements

Before preparation or terminal-receipt lookup, the service now verifies actual
payload digest/length, the complete V3 admission and the head signature against
configured head-signing keys. On replay it reconstructs the full transaction
intent/state and binds registry and witness receipts. Payload, manifest, signed
head and witness drift are rejected even when an operation was acknowledged.

An exact acknowledged replay returns the original DENY_ALL historical receipt.
It does not renew an expired lease, witness or selection authority. New and
non-terminal publications still pass the owner's live lease, signer, withdrawal
and current-head checks. Historical replay requires its verifying key to remain
available in the configured trust material; arbitrary key removal is not a
transparent history migration.

An unreadable checkpoint now retains a recovery fence. `current_registry_view`
rejects while recovery is pending, and unrelated publications remain blocked.
This change does not make raw diagnostic registry access a product authorization
API. Consumers must use the authenticated current-view boundary.

Private request-identity and transaction-recovery helpers are extracted beneath
`src/owner/`; public signatures and durable formats are unchanged. The full
`owner_host.rs` decomposition and an injectable storage backend are not complete.

## 3. Deployment preconditions

A named embedding process must own one service instance for one authorized root.
No new network listener, transport, daemon binary or production route is installed
by this change. Before enabling such a route, independently qualify its request
codec, peer authentication, per-action authorization, bounded request/response
sizes, concurrency admission, shutdown and audit behavior.

Provision the root outside untrusted workspaces, with owner-only permissions and
protected ancestors. A signed writer lease does not authenticate a network peer.
Do not grant a model, payload or caller-selected path filesystem authority.
Keep signing private keys out of the artifact root, logs and backup bundles.

Production restart of a populated root must supply an independently retained
signed current-head anchor. Never compute the expected anchor or receipt from the
suspect backup/directory being validated. Genesis bootstrap is a separately
approved operation, not an automatic fallback when recovery fails.

## 4. Startup, readiness and shutdown

Startup order is: authenticate deployment configuration and trust material;
validate root and restart anchor; call `LearningArtifactOwnerService::open`;
inspect `recovery_required`; reconcile the exact original request when necessary;
verify `current_registry_view(now)`; only then enable the product read/write route.

Liveness means the embedding process can respond to a bounded health request.
Readiness additionally requires a current valid lease/head, matching scope and
binding, successful startup reconciliation and available storage budget. An empty
genesis store can have an administrative bootstrap route without claiming a
selected artifact is ready for consumers.

On graceful shutdown, stop admitting new requests, drain bounded in-flight work,
retain unfinished operation identity and independent receipts, then drop the
service and its writer fence. A timeout must leave recoverable checkpoints; it
must not truncate state or remove a lock file to steal an active writer's lease.

## 5. Failure handling

| Condition | Action |
| --- | --- |
| Rejected payload/admission before preparation | Return rejection; do not reuse an orphaned path if an earlier low-level call created one. |
| Exact acknowledged retry | Return the original historical receipt; do not renew authority. |
| Request drift for an existing operation | Reject; do not reinterpret the stored operation. |
| Non-terminal checkpoint | Fence unrelated writes and authenticated product reads; resume only the exact operation. |
| Unreadable or inconsistent checkpoint | Keep the fence; preserve evidence and escalate to recovery tooling. |
| Writer fence busy | Reject startup or apply a bounded host retry policy; never delete the active lock. |
| Stale/mismatched signed head | Fail closed; obtain independent current authority, not an older backup. |
| Missing/corrupt snapshot or payload | Fail closed; do not silently fall back to an older artifact. |

`WitnessDurable` precedes `Acknowledged`; therefore a physical signed head may
exist before acknowledgement. The invariant is that no acknowledged receipt or
service-authorized current read is returned for incomplete recovery, not that
an interrupted publication can never create a head file.

## 6. Durability qualification still required

A file `sync_all` alone does not prove containing-directory durability. A complete
host/storage implementation must order payload file sync and payload-directory
sync before recording PayloadDurable, registry file/directory sync before
RegistryDurable, witness/head file/directory sync before WitnessDurable, and
checkpoint-directory sync before acknowledging a persisted checkpoint. Directory
creation and deletion need corresponding parent sync rules. Post-hoc sync after
returning an acknowledgement is insufficient.

The existing lexical/trusted-root path checks are not a dirfd/openat2 capability.
Hostile concurrent ancestor replacement must be prevented by the deployment, or
closed by a separately implemented OS-capability backend. No such backend or
power-loss guarantee is added here. Network filesystems, unsupported directory
sync implementations and multi-host writers are unqualified.

The new Unix child-process test terminates the writer at Prepared, PayloadDurable,
RegistryDurable, WitnessDurable and Acknowledged, then checks restart, writer
exclusion, exact retry and request-drift rejection. This is process-crash testing,
not a power-cut, filesystem journal replay or block-device fault test.

## 7. Trust rotation, backup and restore

Rotation requires independently provisioned successor trust, monotonic authority
epochs and valid lease/head evidence. Stop ingress before replacing an in-process
trust configuration; hot key reload is not implemented here. Retain public keys
needed to authenticate history while rejecting their use for new work according
to current revocation policy. Never derive a new trusted signer from payload data.

Back up immutable payloads, registry/withdrawal/lifecycle snapshots, checkpoints,
and their retained receipts under an authenticated backup manifest. Retain the
latest accepted external head and withdrawal frontier independently of the backup.
Restore into a new protected root, validate all hashes, scope and chains, compare
against the independent current anchor, reconcile pending operations and confirm
readiness before route activation. Do not overwrite the suspect root in place.

Withdrawal is not physical erasure. A deletion plan must include all payload
replicas, caches and backup retention classes. Record an erasure/audit receipt
separately; never claim deletion merely because a registry entry is revoked.
Signing private keys require a separate secret-management recovery process.

## 8. Telemetry contract for the embedding host

The following are proposed metric/event names, not installed exporters:
`artifact_publish_total{outcome}`, `artifact_recovery_required`,
`artifact_checkpoint_read_errors_total`, `artifact_request_drift_total`,
`artifact_writer_fence_busy_total`, `artifact_current_view_rejections_total`,
`artifact_phase_duration_seconds{phase}`, and
`artifact_ranker_abstentions_total{reason}`. Use bounded labels; do not label metrics
with operation IDs, raw digests, payloads or caller-supplied strings.

Structured events should bind schema version, process/release identity, scope,
operation digest, phase, current-head digest, stable error code and outcome. Never
log key bytes, artifact contents or authorization bearer credentials. Alert on a
new recovery fence, signature failure, checkpoint corruption or sustained ranker
abstention. Numeric SLOs and alert thresholds require target-host measurements.

## 9. Capacity and compatibility

The supported source limits remain: payload 64 MiB, registry/auxiliary snapshot
8 MiB, durable artifact records 4096, datasets per V2 manifest 64, lineage digests
1024, predecessors 64 and iteration-ledger events 384. These are resource limits,
not measured throughput. Benchmark cold load/hash, every durable publication
phase, restart with maximum history, withdrawal propagation and lock contention.
No capacity or latency benchmark was executed for this change.

Keep the public service/current-view facade and historical record readers stable.
Any future schema migration needs a new identified format, golden old/new
fixtures, independent rollback tests and a reversible cutover that cannot erase
current revocations. A binary rollback is not permission to replay an old current
head. Narrowing legacy public APIs requires a closed-world caller inventory;
source version or module size alone does not authorize their removal.

## 10. Qualification, traceability and remaining acceptance work

The artifact qualification workflow runs Linux and macOS on exact source and an
ordered-parent synthetic merge. It independently attempts closed-world validation,
locked build, strict Clippy, rustfmt, discovery and all package tests. A failure
of the closed-world command remains a failure but does not suppress native tests.
JUnit must match the complete discovered test multiset, with no skipped cases,
retries, missing families or extra cases. The generated receipt binds source/base/
tested commit, tree, source objects, runner/job/attempt, command outcomes and logs.
Its hash proves integrity only; consumers still verify the hosting run's identity.

The verifier and its 12 tests are reused from the reviewed hardening branch
commit `ff7dfac280768b711c8a2a170657e34302590f8b`; the workflow is adapted to this
branch and real integration-base resolution. The Python tests passed locally.
Rust build, formatting, lint and crash execution remain unverified until their
exact candidate jobs complete successfully.

Traceability rows explicitly distinguish declared tests that executed from
unmapped or unexecuted rows. A package run does not fill absent requirement/test
mappings by inference. Do not use a module-native receipt as whole-system product
activation or independent acceptance.

The named check `Lane E artifacts required` rejects failed, skipped or cancelled
matrix jobs. Defining that job is not the same as installing a branch-protection
rule. Preserve `CI required` and `Architecture required`; adding this check to
merge/release policy still needs an authorized repository administration change.
That change was not applied in this session.

The baseline Lane E log reported 11 cross-family findings: operator/case inventory,
a signed evaluator export and legacy Agentd ledger entry points. They are not
fixed or waived by this change. The full daemon/transport/authz, parent-directory
ordering, dirfd backend, power-loss harness, full owner decomposition, storage
trait, model/concurrency/fuzz qualification, telemetry exporters, measured SLOs,
complete traceability and stable-version acceptance remain open.
