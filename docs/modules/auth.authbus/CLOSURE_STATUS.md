# `auth.authbus` repository closure status

Status: **source candidate; production qualification, merge readiness and canary approval remain fail-closed**.

This document records repository-controlled closure only. It does not replace
`IMPLEMENTATION_MAP.json`, `READINESS_CONTRACT.json`, generated exact-candidate
receipts, protected target-host evidence, independent signatures or the
activation decision.

## One source truth and one readiness fact

The committed implementation map is commit-neutral. It contains source and
contract mappings, but no candidate SHA, workflow attempt, runner identity or
artifact receipt. Read-only qualification binds it to the exact checked-out
commit, tree and parent set and writes bound projections only below the runner
temporary directory.

`scripts/check-authbus-source-truth.py` rejects:

- committed bound evidence or hand-maintained release/readiness status files;
- AuthBus workflows with `contents: write` or persisted checkout credentials;
- `git add`, `commit`, `push`, merge/rebase publication or one-shot source
  materializers in AuthBus qualification workflows;
- any static decision that sets production implementation, activation or
  release true.

Detached checkout/reset and read-only Git plumbing remain permitted so a runner
can validate the exact source head and deterministic synthetic merge without
publishing altered source.

`scripts/authbus-readiness-manifest.py` emits the only readiness aggregation. It
requires the full candidate, workflow, toolchain, source, documentation, test,
artifact and target identity set. Every required lane is explicit. Missing,
queued, pending, skipped, cancelled, failed, invalid, cross-candidate or
cross-attempt evidence leaves all of the following false:

```text
productionQualified = false
mergeReady = false
approvedForCanary = false
```

Even a verified production-acceptance bundle may emit only
`approved_for_canary`; production activation, promotion and release remain
separate signed decisions.

## Durable operation identity

The qualified Bao product entry is
`BaoClient::consume_kv_v2_with_durable_authbus_operation`. It accepts an
`EnteredAuthBusOperationHandle`, not caller-provided operation metadata.

The `kernel.operations` owner must first:

1. load the exact durable scope and operation row;
2. verify destination and payload digest;
3. claim the current owner generation and writer fence;
4. consume its own final-use grant;
5. persist the operation as `Indeterminate` before provider I/O;
6. pass the sealed entered handle to Bao.

Bao revalidates the current durable row immediately before AuthBus/provider use
and correlates operation scope, operation ID, owner generation, semantic digest,
AuthBus effect and provider receipt. Recovery reuses the same operation identity
with a later generation/fence; a stale handle, payload drift or a newly invented
retry ID is rejected. Provider success cannot manufacture the independent
terminal reconciliation receipt required by `kernel.operations`.

## Retry-safe bootstrap

The raw authority-host bootstrap constructor is crate-private. The public
administration path uses `bootstrap_retryable`.

A database-without-checkpoint remnant is removable only when inspection proves
it is a pristine post-migration bootstrap artifact: no authority checkpoint,
trusted time, issuer, policy, quota, reservation, archive, recovery work,
frontier root or pending frontier event exists. Any uncertainty, WAL sidecar,
non-empty authority state, unexpected schema or permission/path problem fails
closed. An existing checkpoint without a database is never repaired by source.

Checkpoint creation remains write, file fsync and parent-directory fsync. Fault
and SIGKILL behavior still require protected target-host receipts before the
candidate is production-qualified.

## One lifecycle time authority in Evidence and Agentd

Evidence owns a persistent monotonic `authbus_time_floor` with immutable
identity, forward-only time/revision and delete-forbidden triggers. Replay
admission, outbox enqueue, pending scans, claims, lease renewal, retry,
acknowledgement, quarantine, terminal retention, replay-checkpoint publication,
epoch retirement and operational projections all use this floor.

Agentd obtains admission and final relay time from Evidence rather than directly
from `SystemTime`. Host clock rollback is clamped; a forward jump is retained
across restart. Consequently a rollback cannot make an expired message younger,
extend a lease or delay terminal retention after restart.

The authority database continues to use independently signed
`TrustedTimeSample` values for policy, quota and settlement. The two stores have
different owners but no longer use contradictory wall-clock semantics for the
same Evidence/Agentd lifecycle decision.

## Authentication and compatibility surface

`SignedMessage::authenticate` remains the production admission path. It accepts
only a sealed issuer registration and verifies the canonical issuer/epoch,
message, subject, scope, payload, sequence and expiry preimage with strict
Ed25519 verification.

The structural preverified replay surface is behind the explicit non-default
`legacy-preverified-replay` feature and its public types are deprecated. The
default build does not export it. Closed-world checks ensure the signed path no
longer depends on those structural compatibility types.

## Capability composition

The raw SQLite writer remains crate-private. Product code receives borrowed
execution/read capabilities, not the full authority host. The composition-root
check rejects external production code that holds the full host, bootstrap
facade, admin port or maintenance port, or mints `.admin()`/`.maintenance()`.

The same check treats the durable Bao wrapper as the qualified product entry and
rejects repository production code that calls the low-level bare-operation path
outside the adapter implementation and its sealed wrapper.

## Supply-chain and qualification controls

AuthBus qualification is read-only and uses immutable action/toolchain pins.
The exact source head and deterministic synthetic merge are independently
verified and then joined only when their base/head parents, tree and workflow
run/attempt agree. A final gate rejects failed, cancelled or skipped required
jobs. Generated evidence is temporary runner output; it is never committed back
to the reviewed branch.

A real final merge SHA must be requalified. A PR-head receipt cannot be relabeled
as final-merge evidence.

## Metrics ownership

`AuthBusRuntimeSnapshot::split_by_owner` separates:

- `process_runtime`: owner-acquisition and structural replay counters whose
  lifetime is the process;
- `authority_instance`: checkpoint, mutation, maintenance and latency data owned
  by the exact host/database/checkpoint instance.

Agentd, Evidence, Bao and `kernel.operations` retain ownership of product-route,
provider and reconciliation timing. The machine-readable
`METRICS_OWNERSHIP.json` forbids applying authority-instance labels to process
counters and defines the full product-entry-to-caller-acknowledgement stage set
required in the protected performance receipt.

## Immutable archive capacity and retention

Terminal reservation compaction preserves immutable operation identity in
`authbus_quota_reservation_archive`. The read port exposes a bounded capacity
projection containing row count, estimated canonical bytes and oldest/newest
archive ages. Policy evaluation produces warning/critical alerts and can block
new admission at the critical bound. Capacity pressure never authorizes
deletion.

`ARCHIVE_RETENTION.json` defines the minimum retention window as the maximum of
operation-ID reuse, backup/restore, incident-investigation and canary-rollback
windows. Destructive compaction is deliberately not implemented. It requires a
joint AuthBus/`kernel.operations` signed manifest, an independently observed
terminal operation row, immutable audit export/tombstone, elapsed retention
windows, operator approval and post-compaction frontier/restore verification.
Uncertainty retains both rows.

## Threat boundary

The Linux OFD/POSIX-compatible owner fence excludes another conforming AuthBus
owner process. It is not a mandatory lock against arbitrary code running under
the same UID. Production therefore requires a dedicated AuthBus service
identity, private non-shared state paths, mandatory access control or an
equivalent broker/mount boundary, and an independently governed checkpoint
domain. Qualification must reject deployment where an untrusted same-UID
process can modify the database, WAL, SHM, checkpoint or owner-lock path.

## Remaining external gates

Repository-controlled source closure does not fabricate external evidence. One
unchanged candidate still requires terminal-success receipts for:

- exact source head, deterministic synthetic merge and the real final merge;
- protected target-host crash/filesystem/permission/rollback fault matrix;
- full caller-visible performance matrix, including concurrency 1, 8, 32, 128
  and 256, slow storage, checkpoint failure and recovery/backup overlap;
- real KMS/HSM composition and key rotation/revocation/recovery;
- matched database/checkpoint/trust backup and restore;
- dual-owner and wrong-mount drills;
- independent security-reviewer signature;
- distinct activation-operator signature.

Until those immutable receipts exist and agree, the normative decision remains:

```text
productionQualified = false
mergeReady = false
approvedForCanary = false
productionActivated = false
release = false
```
