# learning.artifacts — integration, recovery and qualification runbook

Status: source candidate; not a production activation record.

This runbook is for `LearningArtifactOwnerService` and its fenced
`LearningArtifactOwnerHost`. The authority channel is signed `CURRENT` plus an
independently authenticated restart anchor. There is no `LatestPublishedHead`
trait in this implementation. Cargo package version and edition are inherited
from the workspace; this document does not invent a separate 0.1.0 API policy.

## 1. Candidate identity and truthful qualification

Use `scripts/hepta_artifact_qualification.py` on a clean exact source commit and
on the actual ordered-parent base/source merge. The synthetic merge's tree must
be recomputed with `git merge-tree --write-tree`; merely attaching the right
parents to an arbitrary tree is not qualification.

The runner independently attempts closure, locked all-target build, strict
Clippy, formatting, nextest discovery and package execution. A stale content map
fails qualification but must not hide the other native diagnostics. A wrong
checkout or wrong merge tree is never executed as the requested candidate.

`qualification.json` binds source/base/tested commit and tree, relevant Git
objects, workflow/run/attempt/job/OS, command outcomes, retained log hashes, and
the actual `(binary ID, fully qualified test name)` execution set. Missing,
skipped, duplicate, failed, retried or foreign test identities fail the runner.
A family name in a document is not a passed test. Cross-crate requirements not
executed by this package remain explicitly unmapped in the traceability output.

Run the verifier's regression suite with:

```sh
python3 -m unittest discover -s scripts -p test_hepta_artifact_qualification.py -v
```

For native qualification, use the pinned repository Rust/just/nextest toolchain
and full nonzero commit identities:

```sh
python3 scripts/hepta_artifact_qualification.py \
  --source "$SOURCE_SHA" --base "$BASE_SHA" --lane exact-head \
  --out "$RUNNER_TEMP/artifact-evidence"
```

Do not reuse an evidence directory. Do not use a receipt's own fields as the
independent expected identity passed to `verify_bundle`. Authenticate the
workflow and execution identity separately through the trusted CI boundary.
A checksum establishes byte integrity, not signer identity, operator acceptance
or production authority. Attesting a failure bundle still attests failure.

`.github/workflows/hepta-learning-artifacts-qualification.yml` defines Linux and
macOS exact-head/actual-base lanes and the aggregate `Lane E artifacts required`.
The aggregate rejects failed, cancelled and skipped matrix runs. The existence
or name of this job does **not** configure repository branch protection. Adding
that context to merge protection and release policy is an administrator action;
no such remote settings mutation is claimed by this source change. Existing
required checks must not be removed or weakened.

Completion must be reported as independent dimensions: source mapping, native
candidate qualification, requirement traceability, product caller execution,
operational qualification and independent activation. Do not collapse these
into a static `COMPLETE` label. The native runner never sets `moduleComplete`,
production implementation, acceptance, activation or release to true.

## 2. Reference-host composition contract

The library is not a transport daemon. A production transport, credential
provisioner and deployment profile are still required. The following is the
integration contract, not a claim that an HTTP/UDS server was implemented here.

At startup the host must authenticate configuration and scope, supply its own
trusted clock, load the current writer lease and trust policy, and obtain the
required restart anchor independently of the directory being inspected. On a
non-genesis store, failure to obtain that anchor must not be converted to
`required_current_head = None`. Genesis creation is a separate explicitly
provisioned operation.

Construct exactly one `LearningArtifactOwnerService`. Its writer fence must
remain held for the entire serving lifetime. Do not open a replacement service
for each request or recreate it to erase `recovery_required`. Recover signed
CURRENT, exact predecessor history and pending publication checkpoints before
admitting new operations. More than one pending operation, corrupt checkpoints,
scope mismatch or head rollback keeps all new-write routes unavailable.

If startup reports a pending operation, only reconcile that exact operation
using its authenticated original request. Do not manufacture a new operation
ID, payload, witness, current time or signature to make the old operation appear
complete. Externally supplied current time is never a transport request field.

Readiness requires successful startup reconciliation, a live writer lease,
current authenticated head/withdrawal state and host resource health. Process
liveness is separate. A healthy event loop, no pending operation, or a historic
receipt alone is not proof that the writer may accept a new publication.

### Action-level authentication and authorization requirements

The transport must authenticate a principal before exposing any service method.
A public struct or serializable request is not an authenticated capability.

| Action | Required host authorization | Additional conditions |
| --- | --- | --- |
| Read status | Scoped observer | Redacted bounded output; no signing key material |
| Publish | Scoped publisher | Exact request identity, live lease, current head, no unrelated recovery |
| Recover | Scoped recovery operator | Existing operation and immutable request; no ID substitution |
| Install withdrawal frontier | Dataset authority | Authenticated same-scope monotonic extension |
| Drain | Host lifecycle controller | Close new admission; retain fence and pending recovery |
| Rotate trust, restore, migrate or erase | Separate administrative authority | Routes closed; explicit durable intent and independently retained evidence |

Never accept caller-provided trusted signer registration, unverified actor
strings, file-derived expected receipts, unbounded body sizes or client clocks.
Ordinary repository edits do not require a deployment authorization ceremony;
actual external effects and trust changes do.

## 3. Drain and shutdown semantics implemented by the service

`begin_drain()` is idempotent and one-way for that service instance. After it is
called, a previously unseen publication is rejected with `Draining` before a new
Prepared checkpoint or payload path is created. An exact acknowledged retry can
still read its original DENY_ALL receipt. A pending publication can still be
reconciled; an unrelated operation remains fenced by `RecoveryRequired`.

`is_drained()` is true only after drain was requested and the instance has no
known uncertain operation. It is not a fresh disk-integrity scan, a lease check
or a readiness proof. An unreadable checkpoint discovered during publication
keeps recovery required and therefore prevents successful drain completion.

The service deliberately retains the OS writer fence even after becoming
drained. The fence is released only when the owner is dropped. There is no
`resume` method or force-success override.

The embedding host must close new admission, durably record stop intent in its
own authenticated lifecycle protocol, then call `begin_drain`. It may reconcile
only the existing operation while draining. At a shutdown deadline, terminate
with pending state preserved rather than clearing the checkpoint or reporting
successful drain. A restarted host must consult its durable stop intent before
reopening routes. This library's in-memory flag does not itself implement
cross-process persistent Stop/Kill semantics.

Regression source in `src/owner/drain_tests.rs` covers denial without Prepared,
exact terminal replay without reopening admission, pending recovery with writer
exclusion, and corrupt checkpoints that never become drained. These tests must
actually run on the final candidate; their presence is not pass evidence.

## 4. Storage and target-host durability

Create-only payloads, registries, witnesses and checkpoints must never be
truncated, overwritten or silently adopted after indeterminate I/O. Reconcile
the exact target against independently retained identity. No old snapshot may
be substituted to hide a revoked predecessor or a more recent signed head.

`create_beneath_trusted_root` rejects lexical escape and ordinary symlink
ancestors. It is not an `openat2`/dirfd capability. Trusted ancestor protection
against concurrent replacement remains mandatory; do not advertise this path
as safe in a hostile writable directory. The crate's no-unsafe policy remains
in force. A future capability backend must fit that boundary or live in a
separately reviewed owner with a narrow interface.

File synchronization does not establish every containing directory's persistence.
The selected host must identify and qualify parent-directory synchronization
for creation, head publication, rename and authorized deletion, including retry
after a directory-sync failure. A successful file write is not sufficient to
mark a missing directory durability step complete. Windows, network/FUSE mounts
and other unqualified filesystem profiles must not inherit Unix power-loss
claims from this document.

The retained SIGKILL tests exercise process death and lock release, not power
loss. Target-filesystem qualification must independently cut execution around
file creation/write/fsync, directory fsync, registry publication, signed head,
checkpoint and acknowledgement. After each restart validate exact bytes,
receipts, chain, withdrawal scope, pending phase and externally anchored head.
Record filesystem, mount options, kernel, storage/cache policy and actual crash
method in the result. Do not label an exception-injection or normal process exit
as a power-loss test.

## 5. Backup, restoration, keys and migration

Backup requires a consistent cut established under the authoritative writer
fence and a closed admission route. Preserve exact immutable payloads, registry
history, withdrawal/lifecycle snapshots, publication checkpoints and their
independently retained receipts/head anchors. Include a bounded file manifest
with digest and size; never include private signing keys or bearer tokens.
A copy without consistency and identity evidence is not a recovery point.

Restore into a fresh protected destination, not over the active root. Verify
bytes and receipt bindings before use, then compare recovered CURRENT and
withdrawal state to independently authenticated current anchors. Reject a valid
but stale backup that would undo withdrawal or head monotonicity. Keep transport
closed through reconciliation. Rehearse restoration on the target host before
claiming disaster-recovery readiness.

Keep key identifiers, public trust policy and authority epochs separate from
secret key storage. Rotation requires separately authorized provisioning and a
new serving lifetime; no mutation API added here lets a publisher replace its
own trust roots. Historical terminal receipt reads do not renew expired or
revoked mutation authority. Test wrong-key, revoked-key, purpose/scope and epoch
substitution as part of host qualification.

Logical withdrawal is not physical erasure. Backup retention and deletion must
carry the same scoped withdrawal policy to every replica, backup and restore
point. Preserve minimum non-secret audit evidence where authorized, without
restoring revoked payload availability. Cryptographic erasure requires evidence
that the relevant encryption keys and copies were actually destroyed; it cannot
be inferred from a tombstone.

No automatic schema migration is introduced by this revision. New durable
formats need bounded old/new fixtures, canonical byte rules, an explicit
migration version, interruption recovery, compatibility-reader policy and a
rehearsed rollback that cannot resurrect withdrawn dependencies. Preserve old
readers until all registered callers have migrated.

## 6. Observability contract and capacity

Host observations must be structured and bounded: schema version, event kind,
registry/scope identity, operation identity when applicable, publication phase,
head digest, outcome category and trusted occurrence time. Never log payloads,
secrets, signing bytes, bearer tokens or full arbitrary error bodies. Operation
IDs and digests belong in audit events, not unbounded metrics labels.

Suggested metric families are writer/read lock contention, publication phase
latency, request identity rejection, recovery-required count/age, corrupt
checkpoint count, withdrawal/head freshness rejection, capacity rejection,
drain state and ranker abstention. Use a closed reason enumeration such as
`busy`, `identity_mismatch`, `scope_mismatch`, `stale`, `revoked`, `corrupt`,
`indeterminate`, `capacity`, `draining` and `unsupported_input`. A concrete metrics
exporter, alert routing and host SLOs are not implemented by this specification.

A read-only ranker may abstain or require explicit reload rather than using an
unverified artifact. The product host must distinguish an expected unsupported
query from artifact unavailability, revoked state and failed current-view
verification. Do not infer a successful model load from a successful fallback
response. Thresholds and fail-open/fail-closed policies require a named product
profile and actual measurements.

Existing source ceilings are 64 MiB payloads, 8 MiB durable snapshots and 4,096
durable records. These are enforced representation/resource limits, not measured
throughput or latency. Benchmark cold pinned reads, hashing, current-view checks,
publication fsyncs, maximum-history replay and recovery on the selected host.
Retain input size/history depth, device/filesystem profile, raw samples and
percentiles. No capacity number is published here as a benchmark result.

## 7. Remaining implementation and acceptance ledger

| Work area | Source candidate in this revision | Still required for closure |
| --- | --- | --- |
| Evidence | Binary-qualified execution identities, actual merge-tree check, bounded logs, bundle verification and granular claims | Successful final-head and actual-base native lanes; authenticated CI consumption; configured merge/release protection |
| Writer lifecycle | One-way drain, exact historical retry, pending recovery and retained fence | Named authenticated transport, durable host stop intent, readiness, provisioning and operating deployment |
| Durability | Existing create-only file protocol retained; no weakening | Parent-directory and capability backend closure plus real target-filesystem power-loss execution |
| Decomposition | Request identity and publication recovery helpers retained; drain tests isolated | Further narrow storage/fault-injection boundary and any justified owner-host decomposition |
| Testing | Verifier adversaries plus new drain tests; inherited process-crash tests retained | Native test execution, systematic state-machine properties, concurrent schedules, fuzzing, long-running capacity and migration fixtures |
| Operations | This runbook, explicit capability/authority boundary and source-content mapping | Metrics emitter, alerts, measured capacity, key rotation, backup/restore/migration implementations and rehearsals |

Do not implement a fictional reservation/refcount/GC subsystem just because a
review checklist named it. First identify its real owner and authoritative
state. Any future GC must prove reachability against current and pending
publications, withdrawals, rollback pins and backup policy before deleting
bytes. Unsupported operations are not advertised as implemented capabilities.

The stable public facade should remain the named service and opaque verified
read/selection handles. Subsequent API narrowing must inventory and migrate
actual registered callers instead of breaking them to satisfy a layout target.
Workspace versioning, public API changes and durable format versions are separate
compatibility decisions. No package version bump or production activation is
performed by this runbook.
