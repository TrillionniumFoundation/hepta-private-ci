# utility.ndu operator runbook

## 1. Scope and authority boundary

This runbook operates the named `utility.ndu` owner, durable projection store, qualification receipts, backup retention and restore drills. It grants no final-use authority, artifact selection, activation, promotion, merge or release authority. A passing source test is not an off-host backup receipt, and a successful restore drill is not permission to activate a stochastic artifact.

The authoritative product path is the named Agentd process configured with an exact descriptor digest, external final-use signer, independently authenticated revocation feed, host generation fence and one durable writer. Never replace that path with a test fixture, direct journal write or manually edited receipt.

## 2. Required deployment inputs

Before enrollment, record and independently review:

- exact binary digest, source commit and source tree;
- canonical private `store_root` and authority directory;
- named production caller identity and host generation;
- authority signer identity and versioned public key;
- independently controlled revocation distributor and current signed feed head;
- protected clock profile;
- selected writer identity and owner-lock location;
- backup policy ID and revision;
- encrypted off-host destination digest and encryption-profile digest;
- metrics exporter identity and alert destination;
- rollback binary, compatible schema and last accepted restore-drill receipt.

Reject enrollment if any digest is zero, any path is non-canonical, group/other write permission is present, authority and revocation keys are not independent, or the protected clock/off-host destination cannot be verified.

## 3. Startup and reopen procedure

1. Verify the exact descriptor digest before parsing it.
2. Verify Agentd identity and nonzero spawn generation.
3. Authenticate and install the current signed revocation head.
4. Acquire the sole writer lock. `Busy` is an operational conflict, not a retry-success signal.
5. Reopen the journal with bounded metadata admission. Reject symlinks, non-regular files, oversized images, truncation, corruption and hash-chain drift.
6. Validate the frozen production policy, including `ValidatedScalarizationProfileV1`, before store open or mutation.
7. Verify the stable owner binding and current host fence.
8. Publish readiness only after the above steps and metrics exporter initialization succeed.

After an `Indeterminate` result, poison the current handle, stop mutation admission and reopen from durable state. Do not infer whether the rename was durable from an in-memory return path.

## 4. Required metrics and alerts

Export the `NduOperationalMetricSnapshotV1` fields with source SHA, source tree, host ID, process generation and policy digest. Counters must be monotonic for one process generation; gauges must carry observation time.

| Metric | Required interpretation | Minimum alert condition |
|---|---|---|
| `evaluation_count`, latency total/max and host p50/p95/p99 | End-to-end deterministic evaluation at the authenticated owner boundary | p95 above 2 ms or p99 above 5 ms for the qualified workload |
| `convergence_runs`, `convergence_iterations`, `convergence_exhaustions` | Bounded preference solver outcome | any unexpected exhaustion; sustained iteration growth |
| `candidate_rejections` | Policy-admitted but infeasible candidate count | abrupt rate change or rejection of `abstain` |
| `candidate_quarantines` | Malformed non-abstain candidate isolated by V3 semantics | nonzero sustained rate; any quarantine schema not recognized |
| `store_busy` | Competing writer/open attempt | any occurrence outside a controlled takeover |
| `store_indeterminate` | Rename may have committed without acknowledged directory durability | page immediately; fence writes until reopen |
| `reopen_failures`, `restore_failures` | Durable-state validation failure | any occurrence |
| `journal_bytes` | Current bounded journal image size | approach to registered capacity or unexpected regression |
| `backup_age_seconds` | Age of newest verified off-host backup | greater than policy maximum or missing gauge |

Never attach candidate payloads, keys, signatures, raw grants or sensitive axis values to metrics.

## 5. Backup creation and retention

A backup is acceptable only when all of the following are true:

1. The owner exports a bounded validated journal image from an authoritative, non-indeterminate handle.
2. The image digest and current journal-head digest are recorded.
3. The image is encrypted under the registered encryption profile before leaving the host boundary.
4. The encrypted object is written to the registered off-host destination using immutable/versioned object semantics.
5. The returned object-version identity is hashed into the receipt.
6. A read-after-write verification retrieves the exact object version and confirms the encrypted-object digest.
7. The retention set contains at least `minimum_copies`, never exceeds `retention_copies`, and never deletes the last known-good object before a newer object has passed a restore drill.
8. Revocation and deletion policy is applied to every retained copy; restoring an older image must not resurrect a revoked projection.

`NduBackupPolicyV1` requires at least two copies, a nonzero revision, a bounded retention count, a bounded maximum age, a nonzero off-host destination digest and a nonzero encryption-profile digest.

Backup transport is an external operation. Repository tests validate the receipt and store semantics but do not prove that a production object store, KMS or network transfer occurred.

## 6. Restore drill

Run the drill on an isolated target host or namespace with no production writer lock.

1. Select an immutable off-host object version within the policy age limit.
2. Authenticate destination, object version and encryption profile; decrypt into a private temporary location.
3. Verify the backup digest before opening it.
4. Open an empty restore root and call the bounded restore path.
5. Reopen from disk in a fresh process.
6. Compare restored journal head with the source journal head.
7. Verify selected projections, revoked projections and full-capacity behavior; no revocation may resurrect.
8. Record restored record count, source/restored heads, backup size, timestamps, operator identity and target-host digest.
9. Mark `passed=true` only after every comparison succeeds.
10. Validate the resulting `NduRestoreDrillReceiptV1`; archive its digest with the exact source and host qualification receipts.

A mismatch, expired backup, zero identity, time regression or false `passed` value fails closed.

## 7. Fault matrix

The target host must retain a receipt for each cut:

| Cut | Required result |
|---|---|
| temp write failure | old authoritative journal remains readable; mutation fails |
| file sync failure | old authoritative journal remains readable; mutation fails |
| rename failure | old authoritative journal remains readable; mutation fails |
| rename succeeds, directory sync fails | handle becomes `Indeterminate`; reopen decides authoritative state |
| process kill after temp write/file sync/before rename | reopen old image; stale temp is discarded |
| process kill after rename/before or after directory sync | reopen the complete new image; never a torn image |
| writer contention | second writer receives `Busy`; first writer remains authoritative |
| corrupt/truncated journal | reopen fails closed without allocation beyond the registered bound |
| restore regression | older valid backup cannot remove later state or revocation |
| disk full/read-only filesystem | fail before commit; old state and reopen remain valid |

The repository process-kill test exercises real child processes at each persistence cut. Target-host acceptance must repeat the matrix on the selected filesystem and kernel; a GitHub-hosted runner is not automatically the production target host.

## 8. Incident response

### `Busy`

Identify the current lock owner and host generation. Do not delete the lock file while a live owner may exist. Controlled takeover requires fencing the old generation, observing termination and then reopening.

### `Indeterminate`

Stop writes, retain logs and the exact mutation identity, close the poisoned handle, reopen, query the mutation outcome and reconcile by identity. Never blindly replay a final-use grant.

### corruption or truncation

Quarantine the live image, preserve forensic copies, deny readiness and restore only from a verified non-regressing backup. Record `reopen_failures` and the restore receipt.

### disk full or read-only filesystem

Stop admissions, preserve the old authoritative image, restore capacity or permissions, reopen and verify the journal head before resuming.

### stale revocation feed or protected clock failure

Deny all fresh admission and mutation. Read-only historical inspection may continue only if its API does not claim current authorization.

## 9. Qualification and promotion gate

Before activation or promotion, require all of the following on one exact candidate:

- source-head and deterministic synthetic-merge suites pass;
- Control caller regressions pass;
- strict NDU package/target Clippy passes with `-D warnings`;
- named-owner and normal-process tests pass;
- named-host latency, durability, capacity and identity receipt passes;
- current/withdrawn/revoked stochastic lifecycle and signed selection tests pass;
- independently controlled convergence and well-posedness receipts are present;
- target-host fault matrix passes;
- newest off-host backup is within policy age;
- a current restore-drill receipt validates;
- operator, security and release owners approve the exact source and evidence set.

Any missing, cancelled, skipped, stale or identity-mismatched receipt is a stop condition.

## 10. Rollback

Rollback uses an explicitly compatible binary and schema. Fence the active generation, preserve the current journal and receipts, verify the rollback binary digest, reopen without automatic legacy adoption and repeat the restore/non-resurrection checks. Do not roll back across a policy, authority epoch, owner binding or schema boundary without a reviewed migration.
