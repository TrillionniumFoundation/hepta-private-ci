# Cognitive store: product read, recovery measurement and lifecycle reconciliation

This implementation note extends `TECHNICAL.md` and the existing retention ADR.
The current canonical state remains `CURRENT_STATE.json`. Source implementation,
actual execution, independent host acceptance and release remain separate.

## Retained architecture

`hepta-memory::CognitiveStore` remains the only physical SQLite owner. Agentd's
`AgentdProductionWriterHost` is still the production semantic-write facade.
Memory/source/fact/projection mutations and committed provenance retain their
existing transaction; no second fact database, writer or execution service is
introduced. Uncertain publication and lost acknowledgements remain reconcile-first.

## Direct source and product capability

The inherited source candidate already implements trusted deployment commit/tree
comparison before signed bootstrap recovery, a V2 bootstrap receipt distinguishing
the authenticated pre-lease cut from the post-lease cut, final authority/expiry
checks before active-pointer publication, and authenticated operational transitions
after lease expiry. These are direct Rust/Python source, not pending patch files.
Obsolete source-identity finalizer workflows and their patch are retired.

`AgentdProductionWriterHost::read_capability` derives `DurableCognitiveReadStore`
from the SAME recovered generation. Its `lane_c_snapshot_page` accepts 1..=512
heads and an exact-cut continuation. Revalidation regenerates the same bounded
page under the current owner cut and rejects drift. It does not open another
connection or expose the raw owner. The normal host integration regression writes,
corrects and tombstones through the sealed production host; its reader rejects the
old continuation and observes the terminal frontier. It does not enable the
qualification write seam. Fixture authority is not independently administered
production authority.

The raw `DurableCognitiveStore` facade alias is qualification-only. The API probe
compiles the actual Cargo-emitted metadata in three profiles: default, host-unified
and qualification. Every profile has a successful read-capability control. Normal
profiles must reject the raw alias, all profiles must reject private backend access
and semantic writes through the reader, and qualification must retain its explicit
raw-fixture control. Missing dependencies, compiler failures, unrelated Rust errors,
zero-test runs and missing metadata cannot count as a denied capability. This is
an API visibility regression, not proof against hostile in-process code or OS access.
The named physical owner and trusted host still require deployment access control.

## Complete recovery measurement

The `PERF-DURABLE` profiles now execute optimized `--release` binaries at 256 and
16,384 records; history profiles remain separate correctness/growth workloads. The
release recovery commands run `cognitive_store_recovery_perf` with three independently
fenced recoveries each. The program seeds
only a temporary owner and invokes the actual descriptor-backed recovery function.
Each run compares the exact cut and exhausts the bounded page reader.

It records end-to-end descriptor recovery time, anchor acquisition (pool scheduling
plus SQLite lock wait), held transaction time (capture plus commit acknowledgement),
page durations, active database size, total cognitive-root bytes including retained
generations, sampled RSS, sampled extra disk growth and fixture-verifier durations.
The 5 ms sampler observes lower bounds, not exact peaks. Directory scans perturb the
workload; compare only equally instrumented runs. Non-Linux RSS is explicitly null,
not zero. Three observations are not a statistically supported p95/p99 claim.
Fixture-verifier timings are not live signed-file or external authority latency.
No target-host SLO is accepted from this repository-only program.

The selected-host ceremony must additionally record signed-file verification,
revocation detection, actual temporary-copy high-water marks, backup/recovery storage,
crash/restart and deployment-specific device behavior. Preserve existing SLO targets;
do not relax them to fit missing measurements.

## Per-storage-owner lifecycle receipts

`tools/cognitive-store-host-bootstrap/lifecycle.py` extends the existing trusted-host
operational tooling with read-only Ed25519 verification. It never opens SQLite,
deletes files, signs a receipt, calls an erasure provider or performs unlearning.
Private keys exist only in isolated tests. OpenSSL Ed25519 verification failure or
missing tooling fails closed.

The trusted host pins BOTH the requested signed plan digest and the independently
installed owner-trust digest. Trust binds revision, expiry, signer identity, key epoch
and revocation. Coordinator and storage-owner keys must be distinct. The signed plan
binds request id, Agent, writer generation, exact cut, policy digest, complete inventory
digest and each storage obligation. An obligation is keyed by storage class AND owner;
multiple independent backup/export owners cannot collapse into one success entry.

Every plan must cover all nine classes: active SQLite, WAL/journal, retired generations,
backups, cold segments, caches, exports, derived artifacts and trained parameters.
Non-applicability requires an explicitly planned owner-signed absence observation.
Omitted classes, duplicate obligations/receipts, signature drift, mismatched inventories,
stale/future observations, unknown fields, duplicate JSON keys and oversized inputs
are rejected. Each input is bounded to 256 KiB and at most 128 obligations/receipts.

Only physical-storage or cryptographic-erasure attestations satisfy an erase obligation.
A logical tombstone, ordinary revocation or rebuilt projection does not. Parameter
unlearning has a separate requirement and method. Missing, pending, indeterminate and
failed observations stay incomplete. A successful result is named
`owner_attested_complete`; `physical_erasure_independently_proved`,
`target_host_qualified` and `authorized_effects` remain false. Signatures authenticate
what each trusted owner attested; they are not an independent examination of media.
The host's inventory completeness and actual owner operations remain external evidence.

Run the read-only reconciliation after collecting real externally signed observations:

```sh
python3 tools/cognitive-store-host-bootstrap/lifecycle.py \
  --plan /trusted/operation-plan.json \
  --receipts /trusted/storage-owner-receipts.json \
  --trusted-owners /trusted/current-owner-trust.json \
  --expected-trust-sha256 "$TRUST_DIGEST" \
  --expected-plan-sha256 "$REQUESTED_PLAN_DIGEST"
```

Paths must be canonical regular single-link files. The digests must come from the
trusted operation context, not from untrusted inputs being verified. Output is a
reconciliation report; exit 2 means incomplete owner evidence. Signing bytes are
`hepta.cognitive.lifecycle-observation.v1` plus NUL, followed by canonical sorted-key
ASCII JSON of `payload`, `signer_id` and `key_epoch`, with compact separators.
Floats are forbidden. See executable validation and real Ed25519 regression vectors
in `lifecycle.py` and `test_lifecycle.py` for the versioned envelope contract.

## Qualification and remaining work

The source-head and deterministic base-merge workflow executes every command in the
committed qualification plan independently, including normal Agentd compilation, actual
host paging, final-use recovery,
expired operational CLI, three-profile API probes, release recovery and lifecycle
receipt tests. Each command keeps its own result and log. All original package,
bootstrap, crash, history, performance and strict Clippy checks remain required.
API diagnostic/source logs and the new recovery reports are retained with the dossier.
The job budget accommodates both optimized profiles; command-specific limits remain.

Local authoring ran 12 API-classification unit tests and 32 lifecycle tests with actual
OpenSSL Ed25519 signatures successfully. This environment did not contain Cargo,
rustc or rustfmt, so native compilation, Rust formatting, native tests, release
measurements and the exact-head/merge matrix are NOT locally passed evidence.
Only actual terminal workflow results on the final source count.

Destructive ancestry-safe hot pruning, encrypted archive segment publication,
checkpoint-aware schema migration and restored-cut equivalence remain required by
ADR-0001. The measurement and receipt reconciler do not implement those operations.
Real backup deletion, derived-artifact erasure, parameter unlearning, independent
signer governance, operator acceptance and release also remain outstanding. No
current or historical data is physically deleted by this change.

## Follow-on: executable encrypted cold archive

The follow-on implementation adds `archive.py`, the native
`cognitive-store-archive-check` adapter and `RecoveredCognitiveReadOnly::open_archive_image`.
It preserves full source/history/tombstone/provenance bytes and verifies the existing
owner cut before encrypted publication and after cold restore. Detailed framing,
independent trust/key/binary bindings and recovery behavior are in `ARCHIVE_RUNBOOK.md`.
It does not prune hot history or physically erase retained generations.

The qualification plan retains independent archive protocol, publication-observation,
owner integration and filesystem commands. The 45 archive protocol and filesystem tests
were executed locally using actual Ed25519/OpenSSL, HKDF and AES-GCM;
most protocol tests substitute native owner admission, which is explicitly not counted
as native validation. A separately required Rust cross-process test uses the real owner,
correction/tombstone history and the native cold-image oracle. No local Rust toolchain
was available, so that integration and the final exact-candidate CI remain unproved until
their terminal results exist. Existing checked-in Rust formatting is normalized using
the fixed-source authoring artifact, not by weakening qualification or skipping checks.
## Exact-candidate qualification closure

The latest closure removes the normal Agentd dependency on the qualification-only raw
durable alias. Agentd opens the one physical owner through
`CognitiveRuntime::open_local_owner`, then passes only the process-scoped runtime or the
bounded read capability onward. Qualification helpers attach that same runtime instead
of using a test-only `AgentdState` mutation method. This preserves one owner and does not
introduce another product path.

A coherent current-cut capture now normalizes the database and every existing
recovery-relevant SQLite sidecar through retained, no-follow descriptors. It accepts the
ordinary SQLite `0644` umask result only when the file is a same-owner, single-link,
non-writable regular file, changes it to `0600`, synchronizes it and rechecks both the
descriptor and pathname identity. Group/world-writable, hard-linked, redirected,
special-bit, owner-mismatched or replaced files remain failures. Descriptor recovery's
strict identity validation is unchanged.

The real archive-owner test installs a fresh single-link native verifier before crossing
the Python archive boundary; production verifier checks are not relaxed to accommodate
Cargo target hard links. Durable 256/16,384 performance profiles now use optimized
binaries, and the bounded 16,384-record command windows reflect the measured workload
rather than treating a debug-process kill as a latency result. These changes still do
not establish target-host qualification, independent acceptance, activation or release.

## Follow-on: selected-host and retention readiness contracts

The repository now includes two additional read-only evidence verifiers. `host_qualification.py` authenticates the complete selected-host ceremony—exact-source bootstrap, publication-fault indeterminacy, canary, crash/restart, witness-gap reconciliation, revocation, fresh-generation rollback and both recovery profiles—against independently pinned plan/trust digests. Its v2 contract binds the rollback to a strictly newer writer generation and distinct authority grant, then requires both recovery profiles to use that new context; a semantic-cut match alone cannot masquerade as fresh-generation rollback. `retention_readiness.py` authenticates ordered immutable-segment owner receipts and an unpublished successor rebuild that preserves the exact cut, head set, tombstone/source/fact/KG frontiers and all rebuild checks. Its v2 range contract rejects reversed, degenerate multi-row, overlapping and reordered segment ranges. Acceptance v2 additionally rejects later approvals built on supplied non-approved prerequisite reviews rather than treating a contradictory approval chain as a merely incomplete set.

Neither tool performs the observed effects. A complete host report does not set target-host qualification, SLO acceptance, activation or release. A complete retention report does not publish a successor, prune hot history, erase a predecessor or prove physical erasure. These contracts make missing, pending, mismatched or stale evidence executable failures without fabricating the remaining external operations.
