# Lane G executable implementation

The implementation owner is `tools/hepta-engineering-control/control_engineering_v2`.
Read this document with [TECHNICAL.md](TECHNICAL.md), [SANDBOX_SECURITY.md](SANDBOX_SECURITY.md),
[COMPONENTS.json](COMPONENTS.json) and [TRACEABILITY.json](TRACEABILITY.json).
These are implementation and test mappings, not acceptance certificates.

## Implemented boundary

The Python package persists work envelopes, fenced path leases and dependency-aware
assignment generations; verifies exact local or signed canonical source identity;
performs resource-aware engineering orchestration over worker skills/capacity,
CI capacity, review topology, expected value, architecture debt and rollback cost;
persists a base-bound integration queue whose product path accepts only signed,
role-bound candidate/review/CI stage observations bound to the complete queue,
orchestration, work-envelope, source, integration-base and logical-owner context;
creates bounded atomic single- or multi-file code candidates including rename;
runs admitted checks under a bounded sandbox controller; performs evaluator-owned
mutation testing; verifies source/execution/evaluator evidence; records signed
candidate-bound review eligibility; exposes distributed-fence, external-audit-anchor
and external-key-custody admission contracts; and composes consent-bound dormant
external-system proposals. The repository CI includes a named v4 product caller over the SQLite v10 owner.
The caller executes registration → lease → capacity-reserving claim → heartbeat → worker
result → independently observed completion → fully context-bound candidate/review/CI
integration observations. It then reopens the same owner, runs the normal startup
reconciler, idempotently replays acknowledgement-loss boundaries, records a separately
signed terminal observation, and reopens once more to prove the terminal state and audit
anchor are stable. The product caller uses reference fixture identities and grants no
external independence, merge authority or deployment acceptance.
That caller fail-closed reads the canonical work-package registry from the exact
`HEAD:docs/delivery/WORK_PACKAGES.json` Git blob (not checkout-filtered worktree
bytes) and binds its blob OID plus registry/package digests to the tested tree. It
requires the unique `ECP-1-ENGINEERING-CONTROL-PLANE` row, including its owner,
state, zero authority delta, write scope and unresolved
`DOC-2-DEFAULT-BRANCH-SELECTION` predecessors; the binding is emitted by digest
and does not reinterpret that predecessor as satisfied.
On pull requests the named product caller executes independently against source-head
and the deterministic base-merge candidate. Each product lane first runs the canonical
implementation-map verifier scoped to `control.engineering`, pinned to the exact tested
commit/tree, plus the complete engineering-control Python suite. The independent global
document/map workflow remains a separate merge blocker; an unrelated module provenance
failure cannot suppress this module's execution receipt. Both source-head and deterministic
base-merge identities must also pass the separate real Bubblewrap strong-sandbox matrix.
The same per-lane runner emits a bounded host-profile artifact measuring SQLite, recovery,
backup/restore, controlled disk-full rollback and complete candidate-sandbox costs without
removing exact Git-object materialization or post-check drift detection. Unrelated Rust/workspace
failures remain merge blockers in their own jobs but do not suppress this module's
product-execution receipt. CI retains both lane receipts, then a
separate aggregation job recomputes each v5 execution-receipt digest, checks common
repository/run/source identity, ordered merge parents, canonical ECP blob/package identity,
all three startup-recovery observations and zero authority, and emits
`hepta.control-engineering-product-receipt-pair.v3`. Production-readiness
projection requires both lane digests and their canonical receipt-set digest; one lane
plus caller-supplied booleans cannot satisfy product composition. It is not a learned code
generator, merge service or autonomous release agent.

Review requests and dormant proposals do not themselves merge, activate, deploy,
enroll a host or transfer credentials. A deployment controller or production caller
must provide the separate owner authorization required by its own contract.

## Components and ownership

| Owner | Responsibility | Main callers |
| --- | --- | --- |
| `path_policy.py` | Canonical POSIX paths and cross-platform alias rejection | Store, candidate generator and sandbox |
| `control_plane.py` | SQLite schema, transactions, envelopes, leases, base scheduling and audit anchor head | Public facade, orchestrator and CLI |
| `orchestration.py` | Exact source admission, signed completion receipts, skills/capacity scheduling, integration order and merge-queue proposals | Product caller and public package |
| `worker_lifecycle.py` | Durable worker registration, cross-generation capacity reservations, fenced claims, signed heartbeats/results, startup reconciliation, bounded requeue and independently observed completion | Named product owner |
| `integration_controller.py` | Durable integration-queue generations, complete-context signed candidate/review/CI observations, base-drift invalidation and separately authenticated terminal observations | Named product owner / external merge observer |
| `product_runtime.py` | Named `EngineeringControlProduct` composition over repository identity, SQLite owner, verifier port, planner, startup reconciler and worker lifecycle | Repository product caller / production composition target |
| `candidate.py` | Deterministic single/multi-file/rename grammar, exact Git materialization and immutable oracle paths | Public facade and CLI |
| `sandbox_control.py` | <=8 host-wide POSIX sandbox admission (process-local fallback on non-POSIX fixtures) and <=2 infrastructure-only retries | Mutation testing and production qualification |
| `mutation_testing.py` | Baseline-pass / mutant-kill evaluator gate | Qualification |
| `evidence.py` | Exact Git objects, source/merge execution receipts, pluggable signing port and independent identities | Candidate evidence binder |
| `hardening.py` | Active-state frontier and authenticated evidence/consent primitives | Store, closure and seal |
| `closure.py` | Source-tree and freshness-window binding, dormant assimilation | Seal and public facade |
| `seal.py` | Signed evidence seals, replay prevention, review and durable eligibility | Public package and facade |
| `external_controls.py` | Distributed fencing, external audit anchor over both audit head and durable owner-state snapshot, and subject-bound HSM/KMS custody receipt admission | Production worker/deployment composition |
| `product_gate.py` | Named repository CI product caller over the SQLite v10 durable owner/orchestrator, startup recovery, worker lifecycle and terminal integration reconciler; PR qualification emits separate source-head and base-merge execution receipts | `hepta-consolidated-source.yml` |
| `qualification_profile.py` | Bounded target-host measurements for database, recovery, backup/restore, disk-full rollback and the unchanged complete sandbox boundary | Strong-sandbox source/merge lanes |
| `cli.py` | Bounded JSON ingress and local operations | `python -m control_engineering_v2`, installed CLI |

There are no import-time store patches or alternate clone sandbox owners. The
public package and historical public `hardened_*` aliases use the current
authenticated composition. The historical direct-facade wrappers
`issue_work_envelope` and `schedule_ready_packages` fail closed unless a caller
explicitly sets `compatibility_only=True`; they are retained only for local legacy
fixtures and are not supported product admission paths. Lower-layer store helpers
do not replace the authenticated orchestration boundary. SQLite file access and
the Python process are trusted owner boundaries: this library does not isolate a
caller that can directly rewrite its connection, modules or database.

## Durable state and migration

`EngineeringStore` uses SQLite foreign keys, WAL, `synchronous=FULL` and one outer
`BEGIN IMMEDIATE` per mutation. Nested owner operations share that transaction.
`SCHEMA.sql` is the single schema source, currently version 10. Tables are:

- `work_envelopes`: immutable source/objective/contract/owner/path/capacity facts;
- `path_leases`: state, revision, authority epoch, monotonically increasing fence and expiry;
- `assignment_generations`: immutable assigned and blocked projections;
- `assignment_generation_frontiers`: exact envelope revision, source and active-lease frontier;
- `orchestration_generations`: immutable normalized resource-aware plan and semantic digest;
- `worker_registrations`: authenticated worker profile, signing identity, scope, expiry and revision;
- `worker_claims`: fenced assignment claims, heartbeat/result state, bounded attempts and observed completion;
- `worker_capacity_reservations`: claim-bound active/released capacity records whose release is idempotent across retry, terminal result, revocation and recovery;
- `worker_heartbeat_observations`: immutable signed heartbeat receipt digests and prior/resulting revisions for acknowledgement-loss replay;
- `worker_result_observations`: immutable signed worker-result receipt digests, outcome and result binding for acknowledgement-loss replay;
- `worker_completion_observations`: immutable accepted CI completion receipt digests used for acknowledgement-loss replay after reopen;
- `integration_queue_generations`: durable orchestration/base-bound integration queue generation and invalidation state;
- `integration_queue_items`: revisioned candidate/review/CI observations, ready-external-merge state and terminal outcome;
- `distributed_cluster_frontiers`: cluster-global highest admitted leader term and revocation frontier, shared across all holders;
- `distributed_fence_frontiers`: highest admitted holder-local fence/token/revision bound to the current cluster frontier, retained across restart;
- `integration_decisions`: immutable eligibility and rejection projection;
- `integration_decision_bindings`: candidate, sandbox and evidence identity;
- `integration_decision_seals`: authenticated seal identity, freshness and replay uniqueness;
- `audit_events`: ordered hash-linked event projection;
- `engineering_schema_meta`: schema version mirrored in `PRAGMA user_version`.

An owner mutation, its binding/frontier and audit event either commit together or
roll back together. Equal identity and semantics replay idempotently; different
semantics conflict. Startup checks exact table/index definitions, schema-version
agreement, SQLite integrity, foreign keys, capacity-reservation consistency and the
audit chain. Additive v2 through v9 stores migrate transactionally to v10; active
legacy claims receive capacity reservations derived from their durable plan before
the new version is published. Historical generations without a bound frontier remain
unusable and require a new generation. A future version is rejected before any
schema or journal-mode write. A database claiming v10 but missing a table, column,
constraint or index—or carrying an unexpected schema object—is rejected before
business execution. A corrupted store must be quarantined and restored from a verified
backup; startup does not silently reconstruct acceptance or change owner facts.

The store is a local coordination database, not a replicated consensus service.
One connection belongs to one execution thread; concurrent callers use separate
connections and serialize writes in SQLite. WAL disk growth, backups, external
audit anchoring, archival retention and production availability remain operational
work. The in-file hash chain detects accidental mutation; it is not protection
against an administrator who can rewrite the complete database and chain.
Production anchor admission therefore also recomputes a deterministic digest over
the durable owner tables independently of `audit_events`; a direct owner-table
rewrite cannot continue to satisfy a previously signed external anchor.

## Leases and scheduling

Paths are NFC UTF-8 relative paths. Absolute/drive/UNC paths, traversal, alternate
separators, reserved aliases, unsupported globs and protected roots are rejected.
Envelope trailing `/**` denotes a canonical prefix. Leases check current envelope,
expiry, declared scope, active conflicts and revisions in the owner transaction.
Renewal, release and revocation require the exact revision and epoch.

At most 4096 packages, 4096 authenticated completion receipts, 256 predecessors per
package, 4096 active leases, 256 paths per record and 128 durable base assignments
are admitted. The low-level compatibility scheduler still accepts completed IDs,
but canonical resource-aware orchestration first requires the caller's `WorkEnvelope`
to be semantically identical to the already-admitted SQLite owner row, then derives
the completed set only from fresh signed `CompletionReceipt` objects bound to the
same source commit/tree and to an actually published immutable assignment generation. The receipt carries that generation's
semantic digest; verification also requires the package to have been assigned in
that generation and the stored assignment frontier to match the same envelope and
source identity. A signed arbitrary generation string cannot satisfy a predecessor.
Completion observation cannot predate the referenced generation and its
freshness window cannot outlive the owning work envelope. Encoded semantic records
also have a 256 KiB bound; hitting a byte bound may reject input below the item-count
limit. Graph validation is iterative, so valid deep DAGs do not depend on Python's
recursion limit. Canonical resource-aware scheduling runs under one `BEGIN IMMEDIATE`
owner transaction: it freezes the active-lease frontier, removes completed or
dependency-blocked work, ranks ready packages by expected value minus architecture
debt and rollback cost (priority is a deterministic tie-breaker), then admits only
packages with an eligible worker, remaining worker/CI/reviewer capacity and no path
conflict. Infeasible work does not consume the assignment limit. The exact final
assigned/blocked set—not a coarser preliminary schedule—is written to
`assignment_generations` in the same transaction as its frontier and audit event.
The generation semantic digest binds normalized package/worker/capacity inputs, the
exact active capacity-reservation frontier and the final assignments. Planning subtracts
reservations held by all prior generations, while `claim_assignment` repeats the capacity
check and inserts the reservation in the same `BEGIN IMMEDIATE` transaction as the claim;
therefore two stale plans cannot both consume one Worker slot. Release is persisted once
when execution leaves the active claim boundary, and reopen verifies reservation/claim
consistency before serving requests.

Integration reconciliation is replay-stable: identical candidate/review/CI or base-drift
observations are no-op retries, evidence order is candidate → review → CI, and terminal
observations are immutable under later base movement. Every signed observation binds the
persisted queue semantic digest, orchestration digest, envelope digest, source commit/tree,
integration base commit/tree and owner-context digest; a reused local queue/package ID in
another owner context is rejected. Worker execution then uses `worker_registrations`,
`worker_claims`, `worker_capacity_reservations` and `worker_completion_observations`:
acknowledgement-loss replay is revision/audit-stable, accepted CI completion digests survive
reopen, and a claim must match the scheduler-selected worker and an active fenced path
lease. Startup reconciliation expires heartbeat claims, rechecks registration/lease/envelope
frontiers, releases capacity idempotently and preserves submitted results for the independent
completion observer rather than redispatching them. The named product `claim()` fails closed
with `product_startup_reconciliation_required` until that process generation has completed
`startup_reconcile`; lower-level state-machine helpers are not the normal product admission
surface. A worker `success` result is non-terminal
until an independent CI completion receipt is observed. The generation semantic digest binds
completion frontier, assignments, integration order and merge queue. A changed
frontier or planning input requires a new generation ID. An assignment is still
a proposal; workers must acquire the exact local lease, and multi-host production
writes must additionally present a signed distributed fence matching epoch/token,
paths, source and revocation frontier. Fence verification re-reads the current
SQLite lease row and requires the same envelope, holder, revision, epoch, token,
paths and expiry to still be active. Before production admission, the verified fence
advances two transactionally persisted high-water marks together with an audit
event: a cluster-global leader-term/revocation frontier and a holder-local
fence-token/revision frontier. Production control verification requires both to
match. Thus a new leader observed by one holder immediately fences stale receipts
for every other holder, while a legitimate lease renewal may advance its local
revision under an unchanged cluster frontier. Older still-fresh signed receipts
cannot become valid again after process restart.
A previously signed active receipt also fails immediately after local release or
revocation. External fence and audit-anchor validity windows may not outlive their
owning local lease/envelope.

## Candidate qualification

Candidates bind exact base commit, allowed/protected paths and file/diff/resource
budgets. No-change is first and candidate identity is content-derived. A candidate
may be a single mutation or one atomic `MutationSet` of up to the changed-file
ceiling; rename is a first-class two-path operation. Test, tests, __tests__, fixture,
golden and common test-file forms are mandatory oracle paths and cannot be made
mutable by an envelope. Before mutation, the executor also rejects a changed source
file whose existing contents contain inline test/oracle markers (for example Rust
`#[cfg(test)]` / `#[test]`, Python unittest/pytest forms, or common JS/JUnit/Go test
forms), and rejects replacement/addition text that attempts to introduce those
markers. This closes the same-file oracle case rather than relying only on filenames.
The executor
requires the clean caller HEAD to match the envelope. It reads exact Git tree and
blob records into a metadata-free temporary workspace, without checkout filters,
Git archive attributes, hooks, repository remotes or credential files.

The Linux strong profile requires an actual successful Bubblewrap admission probe. `SandboxCoordinator` also acquires one of eight non-blocking host-wide slot locks on POSIX before entering the candidate executor, so separate cooperating worker processes on the same qualification host cannot each admit their own set of eight sandboxes. Multi-host admission still requires the separately authenticated distributed coordination/fencing boundary.
It mounts the candidate workspace read-only, isolates network and namespaces and
provides private writable temporary/home paths. The portable profile is for trusted
fixtures and reports `fixture_tested`; it cannot produce strong review evidence.
See [SANDBOX_SECURITY.md](SANDBOX_SECURITY.md) for platform and mount policy.

Checks use argument vectors without shell expansion, at most 64 checks, 256 arguments
per check, 8192 characters per argument and 65536 characters per argument vector.
One elapsed time budget covers all checks. `SandboxCoordinator` admits at most
eight host-wide sandboxes across cooperating POSIX processes (with a process-local
fallback on non-POSIX fixtures) and retries only explicitly classified infrastructure
failures, at most twice; semantic rejection is never retried.
`run_mutation_testing` first requires the no-change/baseline candidate to pass
the exact evaluator-owned check set and then requires every admitted code mutant
to fail that same set. Source HEAD/tree/refs/worktree and
candidate manifests are checked after every command, so a later check cannot hide
an earlier mutation. Resource and isolation failure rejects or produces a failing
receipt; no checks cannot pass. A production check runner must use an admitted
strong profile. This bounded executor has no autonomous merge or deployment loop.

## Evidence, review and replay

Exact-source and ordered-parent synthetic-merge receipts require successful checks,
freshness, valid signatures, exact Git commit/tree identity and independent role
bindings. They are not sufficient alone. A CI executor separately signs a binding
covering the candidate, full strong sandbox receipt and exact execution digests.
The binder verifies complete sandbox evidence and source-tree/freshness containment,
then signs `SealedCandidateEvidence`. Review and durable eligible decisions reverify
that seal; caller-made booleans or unsealed `BoundEvidenceDecision` values fail.
Persisted bindings and seals commit with the decision, and seal reuse under a new
decision ID is rejected. Denied decisions can still be recorded without a seal.

`HmacTrustStore` is the deterministic reference/test signing adapter.
`SignatureTrustStore` is the production-facing signer/verifier protocol, so an
HSM/KMS-backed adapter can be injected without changing evidence semantics.
Production admission additionally requires signed `KeyCustodyReceipt` values
proving hardware-backed custody outside the engineering process. Each critical
role binds a distinct custodied subject signing identity, provider/key identifier,
algorithm, public-key digest and external attestation digest; the custody
authority's own attestation signer cannot stand in for the custodied subject key.
Fixture signers establish protocol behavior only; they do not establish
organizational independence or production key custody.

## Authorized external-system composition

The pilot explicitly targets an unprivileged, consented Debian system. It synthesizes
only `query_version`, `query_health` and `read_status`. The owner signs the normalized
consent payload and exact target identity. An independent evaluator signs manifest,
operation set, fixture/fault/rollback parity and freshness. Missing, stale or drifted
attestations reject. Successful output remains `dormant_candidate` with all effect,
activation, propagation and authority fields false. The current module does not
install an adapter into Debian, execute a production Debian lifecycle or teach an
arbitrary external application to evolve. Those require real adapter/runtime work
and its own measured acceptance evidence.

## Normal product process

`product_service.py` is a bounded POSIX control-pipe adapter around the existing
EngineeringControlProduct and SQLite v10 owner, not a second execution kernel.
The trusted launcher selects database, repository and `--verifier-factory
engineering_host:create_verifier` using `python -m control_engineering_v2 serve`.
The factory is operator-provided; missing configuration fails before database
creation. The factory/import directory and process pipes must be inaccessible to
candidate code. Verifier I/O and current trust/revocation belong to the host contract.

Each newline-delimited JSON request contains exactly `id`, `operation`, `params`.
Duplicate keys, unknown fields, nonfinite values and caller clock overrides reject.
Frames/replies are capped at 2 MiB, replies have a five-second backpressure budget,
and the request count is bounded. Correlation `id` is not a deduplication authority:
recovery reuses native generation/claim/receipt identities after unknown outcomes.

Operations cover envelope admission, registration, planning, lease, claim,
heartbeat, result, completion and integration publication/stage/terminal observation.
`plan_state` restores the persisted decision rather than recomputing it. Completion
loads the envelope through the stored claim; publication loads the persisted plan.
`context` returns the immutable binding for independently supplied signatures.

Startup and periodic scans use the existing recovery owner. Idle or partial input
does not disable scanning; recovery also precedes planning and claims. An explicit
claim can then enter bounded retry. The service never dispatches unknown physical
effects, signs observations, performs GitHub merges or deploys. EOF closes the
owner; reopening the same database preserves native replay semantics.

`test_product_service.py` exercises real CLI processes, lost result acknowledgement,
kill/reopen, original-plan recovery, completion and terminal observation, terminal
replay after a further restart, and partial-input recovery followed by bounded retry.
HMAC identities are test-only fixtures, not real organizational independence.

## Local CLI

From the repository root, use the module without installing dependencies:

```sh
PYTHONPATH=tools/hepta-engineering-control python3 -m control_engineering_v2 --help
PYTHONPATH=tools/hepta-engineering-control python3 -m control_engineering_v2 schedule \
  --database /tmp/engineering.sqlite3 --envelope work.json \
  --packages packages.json --generation-id generation-1
PYTHONPATH=tools/hepta-engineering-control python3 -m control_engineering_v2 candidates \
  --envelope candidate-envelope.json --mutations mutations.json
PYTHONPATH=tools/hepta-engineering-control python3 -m control_engineering_v2 sandbox \
  --repository /path/to/clean-checkout --envelope candidate-envelope.json \
  --mutations mutations.json --candidate-id CANDIDATE_ID --checks checks.json
```

Installation of `tools/hepta-engineering-control` provides `hepta-engineering` with
the same commands. JSON object keys match the exported dataclass field names;
`packages.json` is an array of `WorkPackage` objects. `mutations.json` accepts
single `Mutation` objects or `{"mutations": [...]}` atomic mutation sets. `checks.json` is an array of string argument arrays. Candidate IDs come from
the `candidates` output, including its no-change entry. The legacy `schedule` CLI optionally accepts `--completed completed.json` as a
local compatibility surface. Product composition must use
`plan_engineering_work` with authenticated `CompletionReceipt` objects and must
not treat caller-supplied completion strings as production evidence. Each input
file is bounded to 2 MiB; duplicate and unknown record keys reject. Machine-readable
results go to stdout; a rejected operation emits a safe error code on stderr and
exits 1. A failed sandbox check also exits 1. The CLI cannot issue signed review
receipts, self-approve changes or deploy them.

## Failure handling and verification

| Failure family | Response |
| --- | --- |
| Path/scope, mutation or input byte/count limit | Correct the envelope/input; do not retry unchanged |
| Expired envelope, lease revision/epoch or changed frontier | Obtain fresh owner state and use a new generation where required |
| Active lease conflict/capacity | Wait for or explicitly release/revoke the relevant lease |
| Future/incomplete schema or corrupt audit | Stop using the store; restore or migrate with the compatible owner |
| Isolation unavailable or workspace/source mutation | Reject qualification and repair the executor environment |
| Sandbox capacity or infrastructure retry exhausted | Stop or reschedule; never retry unchanged semantic rejection |
| Surviving mutation-test mutant | Reject the generated/evaluator test claim and strengthen the oracle |
| Missing/tampered/stale binding, seal or replay | Obtain fresh independent execution evidence; never set eligibility manually |
| Missing/stale distributed fence, external audit anchor or key-custody receipt | Block production worker/deployment admission |
| Consent/parity mismatch or widened effect scope | Obtain exact owner consent and evaluator evidence for the declared target |

Run all current engineering-control tests from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tools/hepta-engineering-control -p 'test_*.py'
HEPTA_REQUIRE_STRONG_SANDBOX=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tools/hepta-engineering-control -p 'test_candidate_sandbox_hardening.py'
PYTHONPATH=tools/hepta-engineering-control \
  python3 -m control_engineering_v2.qualification_profile \
    --repository . --iterations 7 --sandbox-mode strong \
    --output /tmp/control-engineering-host-profile.json
```

The second and third commands belong on a Linux runner that can admit Bubblewrap
namespaces. The profile records observed costs and fault behavior for the exact host and
source; it neither defines universal thresholds nor grants deployment acceptance. The
default portable suite explicitly skips strong positive execution tests when
the real admission probe fails; strict mode turns that into failure. Never count a
skip as strong sandbox evidence. `test_consolidated_engineering.py` adds concurrent
SQLite lease races, rollback fault injection, migration/downgrade protection, deep
DAG and lease capacity behavior, forged evidence rejection, per-command source/state
mutation detection and real CLI subprocess round trips. The historical `hepta_engineering_control.py` module remains a local regression
compatibility surface only. Its boolean-based `decide_integration` is permanently
fail-closed and always includes `legacy_unauthenticated_evidence`; it cannot issue
positive review eligibility even when all legacy booleans are true. Historical
registries that merely asserted maturity or counted source symbols have been
retired in favor of these behavior tests and this single implementation map. CI definitions remain in
the repository's current workflow; this document does not certify an unobserved run.


## Profile v2 and startup validation

`hepta.control-engineering-host-profile.v2` retains raw samples and nearest-rank
p95/p99. Publication-to-claim includes lease acquisition, not distributed queue
waiting. Heartbeat observation lag excludes external transport. Expiry uses actual
elapsed wall time followed by an explicitly reported 10 ms polling delay. Up to
three sequential sandbox samples preserve exact Git-object and workspace checks;
throughput is not maximum-concurrency qualification. Counts stay visible: small
samples do not establish long-run production service-level objectives.

The scratch page-limit probe must observe SQLITE_FULL and preserve both audit and
owner-state snapshots after rollback/reopen. It does not exhaust the physical host
disk. SQLite backup/restore verifies the full owner snapshot. Fixture sandbox data
never becomes strong evidence, and host qualification grants no deployment authority.

SQL structural comparison preserves quoted literals. Changing literal case or
whitespace cannot hide behind keyword normalization. Schema, version metadata,
integrity, reservation and audit checks share one serialized startup snapshot.
