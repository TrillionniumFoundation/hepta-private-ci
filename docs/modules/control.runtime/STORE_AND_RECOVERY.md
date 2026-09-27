# control.runtime: store, recovery and qualification runbook

This is the operating contract for the **source candidate**, not an activation receipt. Component states come only from `IMPLEMENTATION_MAP.json` and its generated `CURRENT_STATE.json`. Existing planner and journal algorithms remain in scope. The global production writer, real independent anchor provider, authority/executor/reconciler composition and independent acceptance are not established by the new storage API.

## 1. Ownership and input admission

`PlannerStoreV1` is a single-host owner-local file store. The caller supplies a dedicated private directory, nonzero store identity, pinned Ed25519 verification key and `PlannerAnchorV1`. The store contains no production signing key. The independently configured anchor must return authenticated CURRENT state, linearize compare-and-swap, reject stale expectations and distinguish an uncertain transport result from acknowledgement. A local test signer is not this production authority.

The filesystem profile requires a private local directory and reliable OS locks, atomic same-directory rename, file `sync_all` and directory `sync_all`. The current code is not a hostile same-UID directory sandbox, distributed lock, network-filesystem qualification or hardware durability guarantee. Directory/key/profile provisioning is an explicit deployment task, not inferred from successful construction.

`PlannerDecisionEnvelopeV1::from_plan` first reruns native finalization over the supplied current projections. It stores five length-framed canonical sections: snapshot, feasible candidate bodies, prepared input, consumed NDU projection and final receipt. Every section hashes to the corresponding native digest. Rejected source candidate bodies and opaque owner profiles remain referenced by their existing digests; consumers that need those bodies must resolve them from their authoritative owners. `decode` checks archival framing and integrity only. `revalidate` requires fresh native projections; neither operation grants execution authority.

## 2. On-disk format and bounds

`HCPSTR01` identifies schema version one. The header contains store identity, physical generation and predecessor root. A record contains a bounded length, logical sequence, operation identity, complete envelope bytes and a domain-separated chained checksum. The independently signed checkpoint binds store identity, generation, committed sequence and chain root.

| Dimension | Candidate bound |
| --- | ---: |
| Records retained in the current generation | 4096 |
| One complete envelope | 1 MiB |
| Whole generation file | 64 MiB |
| Directory entries inspected by retention | 64 |
| Generation retention parameter | 1–16 |

Compaction rewrites all semantic records and identities into a successor generation. It does not discard old decisions or turn the 4096-record ceiling into an unlimited log. Retention removes old physical generations only after the current generation validates. Capacity exhaustion rejects new writes. A production rolling-retention/archive design remains required before long-running activation.

## 3. Commit ordering and uncertainty

The order is: hold the OS writer lock; validate the current external anchor; check identity and capacity; encode the complete frame; mark the handle poisoned; append; synchronize the file; perform external signed compare-and-swap; verify the returned signature and exact checkpoint; publish the in-memory record and clear poison.

Equal identity and equal body are idempotent. Reused identity with a different body is a conflict. Once writing starts, any I/O, signing or transport error leaves the handle poisoned. The caller must not continue with another append or infer whether the original request committed. Drop and reopen, then reconcile using the original identity and body.

| Failure window | Required interpretation |
| --- | --- |
| Before the first persistent byte | No successful append; retry after repairing the cause. |
| Partial or complete frame, old external anchor | Unacknowledged suffix; reopen truncates to the acknowledged prefix. |
| External anchor advanced, reply lost | Reopen verifies the committed frame; equal replay returns idempotent success. |
| External anchor advanced, committed bytes missing/corrupt | Rollback/truncation or integrity failure; no silent repair to success. |
| Anchor unavailable or signature invalid | Fail closed; do not invent a local CURRENT checkpoint. |

## 4. Restart procedure

Open the exact configured store identity and pinned key under the exclusive writer lock. Read the independently current signed checkpoint. Open its named generation and verify the header, bounded records, sequence, unique operation identities, checksums and final root. Only bytes beyond that externally acknowledged prefix may be truncated. Synchronize the recovered length before serving reads or writes.

A partial or complete `generation.pending` file is not a selection token. Generation selection comes from the external signed checkpoint. Do not choose the largest filename, latest modification time or longest apparently valid local chain.

The existing digest-only `PlannerJournalV1` is not automatically imported as full-body history. A migration must supply and validate the missing complete envelopes, preserve identities and revocation semantics, and create a separately admitted successor. That migration API and qualification are still open; do not fabricate bodies from their hashes.

## 5. Compaction, backup and restore

Compaction writes the complete successor generation to a create-new temporary file, synchronizes it, renames it, synchronizes the directory, then switches the independent checkpoint by compare-and-swap. A failed or uncertain switch poisons the handle and requires reopen.

Back up the complete validated generation with its signed checkpoint. Restore only into a destination without the target generation and only when the backup checkpoint equals the independently current frontier. A valid signature on an older backup does not authorize rollback or resurrection of a revoked decision. Preserve the original storage and anchor observations for incident analysis; do not repeatedly rewrite or truncate a failed committed prefix.

Production backup retention, cross-host restore, key rotation, schema migration and filesystem failure rehearsals remain required. The current backup API is not an operational authorization to replace a live deployment.

## 6. Read-only Agentd receipt recovery

The real control socket owns a maximum-1024-entry receipt ledger. It retains only digests and profile/generation bindings, not raw query or context text. `plan_authenticated_context` derives count and bytes from canonical exact-ID records. The one-second planner/host lease uses a monotonic clock. The owner store keeps its separate Unix-time validity contract.

A final-use request must identify a plan this listener actually issued and match the complete ordered response. Retrieval policy, ranker policy and lifecycle generation are checked before and after canonical owner revalidation. An expired, absent or conflicting receipt rejects. Restarting the listener intentionally forgets all receipt leases; re-read context rather than restoring stale in-memory leases. The native V1 plan digest is not redefined as a host authentication token.

This closes source-level membership and freshness checks in the socket path. It does not prove transport delivery, model attachment, effect completion or a durable learning-ledger terminal outcome. Direct internal `AgentdState::response` calls are a lower-level boundary and are not substitutes for the guarded public listener.

## 7. Executable source tests

Run from `codex-rs` on the exact committed candidate, without modifying tracked source:

```sh
cargo test --locked -p codex-hepta-control-plane --all-targets --no-fail-fast
cargo test --locked -p codex-hepta-agentd --lib cognitive_context
cargo test --locked -p codex-hepta-agentd --lib context_receipts
cargo check --locked --all-targets -p codex-hepta-control-plane -p codex-hepta-agentd
cargo clippy --locked --all-targets -p codex-hepta-control-plane -p codex-hepta-agentd -- -D warnings
cargo fmt -p codex-hepta-control-plane -p codex-hepta-agentd -- --check
```

Run status tooling from the repository root:

```sh
python3 scripts/hepta-control-runtime-state-tests.py -v
python3 scripts/hepta-control-runtime-state.py --check --verify-source
```

The added source fixtures exercise planner admission, canonical read/body checks, receipt tampering and expiry, full-envelope integrity, writer exclusion, partial tails, lost anchor replies, stale backups and generation retention. They are not yet substitutes for actual child-process kill at each commit boundary, ENOSPC, filesystem loss, target-host latency, sustained overload or independent review. Command existence and test-function counts are not passing receipts.

## 8. Remaining full product integration

The required target remains:

```text
authenticated owner inputs -> coherent global snapshot -> prepared candidates
 -> NDU evaluation -> durable decision -> authority request
 -> independent current-state authorization -> named executor
 -> terminal receipt -> reconciliation
```

The planner continues to emit `DENY_ALL` requests. A named consumer must use existing authority-owner APIs, bind final payload and current revocations immediately before dispatch, preserve unknown effects as indeterminate, and reconcile with the effect owner. A newly introduced generic callback interface would not, by itself, establish this product path. This global composition is still open.

## 9. Acceptance record requirements

Before activation, retain exact-source and synthetic-merge command receipts, actual compiler/target/OS/filesystem identities, exit codes, bounded complete logs or explicit log truncation, artifact hashes and clean-source checks. A failure or timeout remains a failure even when artifact upload succeeds.

Required unsatisfied external gates include independent semantic review, selected-host qualification, canary admission and rollback rehearsal. Repository work still includes real process-crash/ENOSPC injection, prolonged backlog/capacity, per-target partial-fan-out reconciliation, post-decision revocation and final-payload-drift tests against the actual executor. No current source-author declaration sets these states to accepted or activated.
