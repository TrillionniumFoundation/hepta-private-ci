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
3. Validate the entire frozen production policy, including `ValidatedScalarizationProfileV1`, before opening either the authority store or the projection store.
4. Authenticate and install the current signed revocation head using the same configured clock as final-use and external admission.
5. Acquire the sole writer lock. `Busy` is an operational conflict, not a retry-success signal.
6. Reopen the journal with bounded metadata admission. Reject symlinks, non-regular files, oversized images, truncation, corruption and hash-chain drift.
7. Verify the stable owner binding and current host fence.
8. Publish readiness only after the above steps and metrics exporter initialization succeed.

After an `Indeterminate` result, poison the current handle, stop mutation admission and reopen from durable state. Do not infer whether the rename was durable from an in-memory return path.

## 4. Required metrics and alerts

Export the `NduOperationalMetricSnapshotV1` fields with source SHA, source tree, host ID, process generation and policy digest. Counters must be monotonic for one process generation; gauges must carry observation time.

| Metric | Required interpretation | Minimum alert condition |
|---|---|---|
| `evaluation_count`, latency total/max and host p50/p95/p99 | Numerical evaluation calls, excluding internal V3 preflight calls; excludes owner-lock/feed wait | p95 above 2 ms or p99 above 5 ms for the qualified workload |
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

### Epoch archive and local retention candidate

`NduProjectionEpochJournalV1` is an additive semantic candidate; the selected V1
store does not invoke it automatically. A reviewed rotation must:

1. close a non-empty bounded active epoch;
2. preserve every operation identity, global sequence and predecessor digest;
3. preserve recorded projections, revocations and current selections;
4. emit a lossless archive transition chained to the preceding checkpoint;
5. reconstruct the new checkpoint from epoch zero before admission;
6. record both the transition digest and complete archive checksum.

Before removing any local archive, call
`plan_projection_archive_retention_v1` with the exact current checkpoint and an
acknowledgement binding minimum external copies, immutable object-version identity,
restore-drill receipt and the exact current monotonic frontier. The returned digest
list is a plan only. The operator-owned deletion path must durably remove references
before bytes, preserve at least one local recovery anchor, and sync the parent
directory. A mismatched checksum/frontier, missing restore receipt or insufficient
copy count is a hard stop.

Do not deploy rotation until a durable epoch manifest/archive store has passed the
same write, sync, rename, directory-sync, ENOSPC, EROFS, process-kill and reopen
matrix on the named target filesystem. Never clear or rename the selected V1
journal to manufacture capacity.

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
10. Validate the resulting policy-digest-bound `NduRestoreDrillReceiptV2`; archive its digest with the exact source and host qualification receipts.

A mismatch, expired backup, zero identity, time regression or false `passed` value fails closed.

## 7. Fault matrix

The target host must retain a receipt for each cut:

| Cut | Required result |
|---|---|
| temp write failure | old authoritative journal remains readable; mutation fails |
| file sync failure | old authoritative journal remains readable; mutation fails |
| rename failure | acknowledgement is conservatively `Indeterminate`; fence the handle and reopen before authoritative reads |
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

## Implemented observation boundary (2026-09-27)

`NduControlRequestV1::MetricsV1` is a read-only request on the existing private
control socket. It returns `NduControlResultV1::MetricsV1`; existing lifecycle
and caller access checks still apply. It does not claim a final-use grant or
modify the journal. Direct metrics reads do not need a healthy projection
journal or a current revocation feed, so an indeterminate-store incident does
not hide its counter behind a journal read. Admission-wrapped requests retain
all V2 fence, feed, deadline and replay checks.

The implementation records actual V2 and V3 evaluation latency, rejected and
quarantined candidates, actual solver iterations (including exhaustion), store
open contention, open/recovery failures, restore failures and ambiguous
rename/directory-sync failures. Quarantine preflight probes do not increment
logical evaluation counts. A successful store open or durable publish updates
the journal-size gauge; an ambiguous publish invalidates it.

These observations are process-local, approximate under concurrent reads and
reset on restart. Journal bytes describe the most recently observed NDU store,
not a sum of all stores. Scrapers must bind the process/host generation and must
not use the counters as authority or durable outcomes. `backup_age_seconds`
remains null: no external encrypted-backup transport or acknowledgement source
has been wired. A local `backup_bytes()` export is never counted as off-host
backup success. The deployment exporter, alert destination, independently
governed backup service and target-host restore drill still require real
integration and external receipts.

## Admission deadlines and qualification scope

External V2 deadlines are revalidated after owner-lock/feed waits, after durable
replay admission, before returning a cached response, and at physical mutation
entry after the final lifecycle/feed guard. A longer-lived final-use grant does
not extend its envelope. Detected clock regression fails closed. An expiry
before replay admission consumes no replay slot; expiry after reservation leaves
Pending and requires reconciliation by the original mutation identity. Do not
turn a post-reservation timeout into a fresh ID or interpret it as authorization.

Both core qualification lanes explicitly include `ndu_stochastic_admission` and
`ndu_stochastic_lifecycle`; the independent-evaluation command runs the entire
evaluator library, including convergence and well-posedness tests. These are
executable signed-evidence and numerical-policy regression tests, not proof of
an independently operated deployment evaluator or its real artifact dataset.
The `ENOSPC`/`EROFS` source tests inject operating-system error numbers at the
persistence boundary; they are not a physically full disk or mounted read-only
production filesystem. Preserve this distinction in acceptance records.


## Protected-host bootstrap and envelope entry (2026-09-27)

`load_ndu_production_bootstrap_v2` accepts only
`schema=hepta.agentd.ndu-bootstrap.v2` and `trust_profile=protected-host-v1`.
The pinned descriptor must contain `production_trust.caller_id` and
`production_trust.profile_digest` matching the independently supplied
`NduProductionHostTrustV1`. The host supplies one `AuthorityClock` and one
`AuthorityFrontierStore<FinalUseFrontier>`; their concrete enrollment and
protected/durable implementation are external deployment evidence, not facts
inferred from a Rust trait or a nonzero digest.

The same clock drives envelope expiry, signed revocation-feed freshness and
final-use grant checks. Failure never falls back to system time. The existing
`AgentdConfig::with_ndu_owner_host` attaches the existing named owner; the writer
remains `NduProjectionStoreV1`, not a second process or a parallel journal.
The authority frontier binds both revocations and claimed nonces and is checked
again on reopen. It does not by itself prove whole-directory projection/replay
rollback resistance; deployment still requires the external journal frontier
and coordinated backup evidence described above.

Protected-host control ingress requires external admission V2 for Prepare and
Apply (`NDU-ADMIT-012` otherwise). The caller binding must match the descriptor
(`NDU-ADMIT-013` otherwise); this string is not caller authentication by itself.
Authentication still comes from the private control-channel host boundary and
the exact final-use grant. A feed-bound host rejects the legacy direct mutation
method; production mutations use the head-bound, lifecycle-guarded control
path. Read-only Metrics remains accessible through the private control socket
when the clock/feed/store is unavailable and never claims current authority.
The V1 command-line local bootstrap rejects a protected-host descriptor rather
than silently creating providers. An embedding host must supply enrolled
providers and attach the V2 owner explicitly.

## Real mounted-filesystem qualification

The host suite builds `ndu-mounted-filesystem-qualification` from the exact
candidate and runs `scripts/hepta-ndu-mounted-filesystem.py`. It creates two
fresh private 4 MiB tmpfs fixtures, never a production directory. One fixture is
filled until an actual ENOSPC is observed; the other is remounted read-only and
must return EROFS, not merely EACCES. The open native writer must reject before
commit and preserve its authoritative image. After capacity or write access is
restored, a new handle must reopen the same journal, reject an older backup
that predates revocation, remain unable to resurrect the revoked selection,
and successfully commit a new projection.

The receipt binds exact source SHA/tree, lane, host/kernel, binary SHA-256,
observed errno, bounded fill size, the native phase sequence, exit status and
successful unmount cleanup. Missing sudo/mount support fails qualification;
it is never a skip, injected-error substitute or a green receipt. This is real
Linux/tmpfs failure evidence, not a qualification of an untested production
storage stack. The existing named-host durability and process-kill matrix still
run independently on the configured host filesystem.

## Complete backup-policy binding

Use `canonical_backup_policy_digest_v1` with `NduRestoreDrillReceiptV2` and
`validate_restore_drill_receipt_v2` for new integrations. The digest covers ID,
revision, minimum/retained copies, maximum age, destination and encryption
profile. A receipt cannot be relabelled with another destination, encryption
scheme, retention count or age limit while reusing its policy ID/revision.
The V1 receipt validator remains a compatibility reader, not complete policy
binding. Neither version manufactures an off-host upload acknowledgement,
a decryption observation, a successful restore, retention execution or
permission to delete a backup. Keep the backup-age gauge unset until a real
verified off-host transfer supplies the observation.

## 2026-09-28 executable additions

Request `{"operation":"metrics_v2"}` on the existing private control socket for
latency/uncertainty histograms, rejection categories, persistence results and
owner storage health. This endpoint does not wait on the owner lock: `null`
readiness means unknown/contended, not healthy. The legacy metrics endpoint is
unchanged. Counters are approximate process-local observations; tag them with
host generation. The memory-fallback count is zero because the owner has no
fallback branch, not because failed opens are ignored. Backup age remains null
until a verified off-host backup integration updates it.

On `OwnershipChanged`, unsafe mode/UID/hard links, corrupt image, or
`Indeterminate`, stop mutation admission and retain the original directory and
lock object. Do not remove lock files, clear journals, restore an old prefix or
restart with a new operation identity to conceal an unknown outcome. Restore
permissions/ownership under the supervisor, then reopen and reconcile the exact
operation identity with the authenticated owner's historical Outcome endpoint.
No old acknowledgement is fresh authority. Existing crash, real ENOSPC/EROFS,
reopen and permission/identity regression tests remain mandatory.

Every suite now writes `evidence-manifest.json`. Recheck a downloaded directory
with `python3 scripts/hepta_ndu_evidence.py verify --root /absolute/evidence`.
Aggregation requires all six suites in both lanes, exact command vectors and
strict filters, exit codes, unchanged source/tree, two-parent merge identity,
native host observations and every retained command-log checksum. The archive is
losslessly compressed and create-only; it does not truncate a live journal.

The separately named `NDU encrypted evidence publication` workflow is manual,
default-branch-only, uses the trusted workflow revision and never executes
candidate code with AWS credentials. Preconfigure the protected `ndu-evidence`
environment, repository-specific IAM OIDC audience/subject trust, and these
reviewed variables: `NDU_EVIDENCE_ROLE_ARN`, `NDU_EVIDENCE_REGION`,
`NDU_EVIDENCE_ACCOUNT`, `NDU_EVIDENCE_BUCKET`, `NDU_EVIDENCE_KMS_ARN`.
Do not invent destinations or broaden IAM trust to make a job green. This repo
may use immutable repository-ID OIDC subjects; check the actual subject format.

The publisher requires the expected account and versioned bucket, conditional
create (`If-None-Match: *`), SHA-256, SSE-KMS and readback of the exact returned
version with matching KMS key. It retains a publication receipt only on complete
success. The account/bucket/KMS policy and target deployment still require real
operator enrollment and a live run. SSE-KMS here is evidence encryption at rest,
not a claim of client-side-encrypted production journal backups.

Learning governance reuses `admit_with_artifact_lifecycle_v2`: training dataset
withdrawals, CURRENT registry/witness/trust, independently verified signed
selection, producer/selector roles, convergence and well-posedness are checked
before admission. Rollback is a new governed selection of a still-eligible
predecessor, never a stale journal restore or reversal of a revocation. A solver
proposal or this numerical admission receipt remains DENY_ALL. A target-host
online learning/rollback drill is a separate acceptance requirement.
