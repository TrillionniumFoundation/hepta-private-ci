# Artifact writer integration and qualification runbook

Status: engineering runbook; not evidence of a deployed writer or independent acceptance.
Baseline inspected: `a126987b84737dbc2ee2592442a314117bddb4a2`.

## Real interfaces and completion dimensions

The native interfaces are `LearningArtifactOwnerService`,
`LearningArtifactOwnerHost`, `SignedArtifactWriterLeaseV1`,
`SignedCurrentArtifactHeadV1`, and `PinnedCognitiveRanker`.
`LatestPublishedHead`, a refcount collector and a reservation journal are not
interfaces of this source slice. Do not create a second artifact registry to
match names from a review. The existing signed CURRENT chain and independent
restart anchor, not filesystem modification time, determine the current head.

Track source implementation, reader composition, writer composition,
exact-candidate qualification, target-host durability, independent acceptance,
activation and release separately. Neither a directory of tests nor a successful
source build is production activation. `sourceBase` is historical provenance;
refresh source object bindings separately. Never change `sourceBase` merely to
match the latest commit and never write a containing commit's own SHA inside a
file in that same commit.

## Qualification and merge protection

The stable proposed check is `learning.artifacts exact-head required` in
`.github/workflows/hepta-learning-artifacts-qualification.yml`. It runs for PRs,
main pushes and merge groups without path filters. The source lane checks the
exact source commit; the merge lane creates and checks an ordered-parent commit
with parents `[base, source]`. The aggregate must run even when either lane fails.
Missing, cancelled, skipped, neutral, zero-test, filtered-test and mismatched
receipts are negative evidence. Metadata failure must not suppress diagnostic
compilation, Clippy and native tests; diagnostics do not override the failure.

A repository administrator must add this exact check from GitHub Actions to
branch/ruleset protection while preserving `CI required` and `Architecture
required`. This file and the workflow do not change server-side protection.
Verify the active ruleset separately; never infer protection from a job name.
A release controller must retrieve both receipts from the expected repository,
workflow run and attempt, validate logs and provenance, and require the stable
check's success for the release source. Locally fabricated JSON is not trusted
CI provenance. Production release policy wiring is still a separate deliverable.

Example verifier self-tests:

```sh
python3 -m unittest discover -s scripts -p test_hepta_artifacts_evidence.py -v
```

The generated manifest binds source/base/candidate commits, candidate tree,
source blobs, lane, run, attempt, job, exact commands, exit statuses, log bytes,
SHA-256 digests and executed test identities. Requirements ART-01 through ART-12
are resolved against `qualification/lane-e/TEST_TRACEABILITY.json`, not inferred
from the existence of source files. A receipt's `qualified` field is execution
only; production, acceptance, activation and release remain false.

## Provisioning and trusted startup

1. Provision a dedicated local root on a separately qualified filesystem. Use a
   dedicated OS account, restrictive directory permissions and no writable
   ancestors shared with untrusted users. Reject symlink roots and ancestors.
   Lexical path validation is not a directory capability or a defense against
   concurrent hostile ancestor replacement.
2. Load authority-approved signer trust, signed writer lease, storage binding and
   the authenticated withdrawal frontier. Never obtain an expected digest from
   the file being checked. Keep signing private keys out of the artifact root,
   audit logs and backup payloads.
3. After any prior acknowledged publication, load the independently retained
   signed CURRENT restart anchor. An absent anchor is not permission to bootstrap
   an existing or restored store. Keep the anchor in a separately governed durable
   store; an old internally consistent backup must not lower the anchor.
4. Open `LearningArtifactOwnerService`. Its host acquires the exclusive OS fence,
   verifies trust and lease and replays current registry/checkpoint history.
   Expose no mutation route while `recovery_required()` is present.
5. Recovery may accept only the exact blocked operation, authenticated separately,
   with the original admission and payload. A replay failure must retain the
   recovery fence. Never delete checkpoints to make readiness pass.
6. A product transport must authenticate principal, authorize the specific action,
   bind registry/scope/operation/admission/payload/predecessor/epoch, and use a
   host-owned clock. It must bound frame size, concurrency, queue length and
   request duration. The native library is not itself that transport.

Readiness is not just process liveness. It requires a held writer fence, valid
current lease/trust, authenticated withdrawal and CURRENT frontiers, successful
recovery, available capacity and a healthy durable audit sink. A pending recovery
blocks mutation readiness; a health endpoint must not provide write authority.

## Publication, failure and retry

The durable phases are `Prepared -> PayloadDurable -> RegistryDurable ->
WitnessDurable -> Acknowledged`. A phase is durable only after its checkpoint and
required directory synchronization succeed under the same writer fence.
Acknowledgement cannot precede witness durability. A historical terminal receipt
is not a new eligibility witness or permission to reactivate a revoked artifact.

Even a terminal retry must validate the complete caller-constructible V3
admission, exact payload size/digest and historical signed-head binding. Changed
bytes or metadata under an existing operation must conflict. An error reading the
checkpoint after a failed operation must leave the service recovery-fenced.

Do not promise that *every* failed API call leaves CURRENT unchanged: an
indeterminate failure after witness publication can leave durable newer state
without a delivered acknowledgement. The correct invariant is that recovery
reconciles the exact operation and never acknowledges a state whose required
writes have not become durable. Record this distinction in callers and tests.

On shutdown, stop accepting new requests, finish the current bounded operation
or persist its recovery requirement, flush audit output and then drop the owner.
Do not force-unlock another process. Lease/trust rotation requires draining and
reopening under the new authority-approved configuration; retain historical
verification material needed to interpret committed records.

## Durability and fault qualification

File `sync_all` alone is not a complete directory durability claim. Inventory
actual create/link/rename/unlink paths. After each namespace mutation, synchronize
all affected parent directories before acknowledgement. Reject unsupported
platforms/filesystems explicitly rather than silently using a no-op success.
The existing `_beneath` APIs assume stable trusted ancestors; dirfd/openat2-style
hardening remains an implementation/target qualification item, not a claim here.

Run process kill/restart tests at payload write/sync, registry write/sync, witness
write/sync, each phase checkpoint, CURRENT publication and acknowledgement loss.
For every boundary retain source SHA, seed, failpoint, filesystem/mount profile,
pre/post digests, recovered phase and result. Also inject ENOSPC, short writes,
EIO, fsync failure and rename failure. A SIGKILL test does not simulate power loss;
VM/block-device crash qualification must independently test lost directory and
write-cache persistence on the target profile. Never use an old snapshot as an
automatic fallback to bypass a revocation or restart anchor.

## Backup, restore and schema migration

Quiesce the writer or use a qualified consistent snapshot mechanism; copy immutable
payloads, registry history, phase checkpoints, withdrawal/lifecycle records and
required public trust history as one manifest-addressed backup set. Retain its
manifest separately. Verify it in a clean root before restoring. Startup must
still compare it with the independently retained latest anchor; restore is never
an override of revocation or freshness.

Track logical withdrawal, local physical deletion, replica deletion and backup
expiry as separate statuses. Keep tombstones and lineage evidence required to
prevent resurrection. Encrypted backup key retirement must cover all replicas and
be separately approved and evidenced; do not claim erasure from a logical notice.
Never include authority signing secrets in artifact backups.

Reject unknown schema versions. Migrate into a new root with deterministic input
and output manifests, fixture tests, full verification and an independently
approved cutover. Preserve original records until rollback/retention policy
allows removal. A migration must not rewrite identities, backdate evidence,
reduce epochs or convert an expired historical receipt into current authority.

## Metrics and structured events contract

Host events should include schema, source commit, registry/scope digest, operation,
phase, before/after head digests, error category, elapsed time and recovery status.
Do not log payloads, credentials or signing keys. IDs are trace attributes, not
unbounded metric labels. Required bounded-label metric families:

| Family | Labels | Meaning |
| --- | --- | --- |
| artifact_publication_total | outcome, phase | terminal successes, conflicts and indeterminate writes |
| artifact_recovery_required | none/pending/corrupt | mutation readiness fence |
| artifact_replay_seconds | checkpoint kind | recovery duration histogram |
| artifact_io_failure_total | create/write/sync/rename/read, errno class | host durability failures |
| artifact_current_rejection_total | signature/scope/epoch/expiry/rollback | current-view rejection |
| artifact_ranker_abstention_total | unsupported_cell/current_rejected/cache_empty | whole-ranking abstention or unavailable cache |

The actual ranker abstains for the whole action set on an unsupported cell and
invalidates its cache on failed current-view revalidation. Monitoring must preserve
that behavior; never silently invent scores or restore an invalid cache. Metrics
export and concrete target-host alarm thresholds require implementation and
operator configuration; this contract does not assert that exporters exist.

## API stability and remaining acceptance work

Keep publication recovery helpers private under `owner/`; do not export a raw
writer or arbitrary verified-handle constructor as an admin shortcut. The crate
remains version `0.1.0` until public API inventory, all caller migration, durable
format compatibility fixtures and independent review support a stable facade.
Version bumps must not erase the ability to interpret historical durable records.

Still required before production: authenticated executable host/transport,
durable withdrawal frontier provisioning, directory-capability integration,
full injected storage backend and model/concurrency/fuzz testing, target-host
power-loss evidence, measured capacity/latency profiles, operational metric
exporters, and server-side merge/release enforcement. No benchmark numbers or
production activation are claimed by this runbook.
