# Lane G executable implementation

The implementation owner is `tools/hepta-engineering-control/control_engineering_v2`.
Read this document with [TECHNICAL.md](TECHNICAL.md), [SANDBOX_SECURITY.md](SANDBOX_SECURITY.md),
[COMPONENTS.json](COMPONENTS.json) and [TRACEABILITY.json](TRACEABILITY.json).
These are implementation and test mappings, not acceptance certificates.

## Implemented boundary

The Python package persists work envelopes, fenced path leases and dependency-aware
assignment generations; creates bounded code candidates; runs admitted checks;
verifies source, execution and evaluator evidence; records signed candidate-bound
review eligibility; and composes consent-bound dormant external-system proposals.
Its CLI exposes local scheduling, candidate generation and sandbox execution.
The pilot mutation grammar is deterministic (`no_change`, `add_file`, `replace_text`,
`delete_file`). It is not a learned code generator or an autonomous development agent.

Review requests and dormant proposals do not themselves merge, activate, deploy,
enroll a host or transfer credentials. A deployment controller or production caller
must provide the separate owner authorization required by its own contract.

## Components and ownership

| Owner | Responsibility | Main callers |
| --- | --- | --- |
| `path_policy.py` | Canonical POSIX paths and cross-platform alias rejection | Store, candidate generator and sandbox |
| `control_plane.py` | SQLite schema, transactions, envelopes, leases, scheduling and audit | Public facade and CLI |
| `candidate.py` | Deterministic candidate grammar, exact Git materialization and isolation | Public facade and CLI |
| `evidence.py` | Exact Git objects, source/merge execution receipts and independent identities | Candidate evidence binder |
| `hardening.py` | Active-state frontier and authenticated evidence/consent primitives | Store, closure and seal |
| `closure.py` | Source-tree and freshness-window binding, dormant assimilation | Seal and public facade |
| `seal.py` | Signed evidence seals, replay prevention, review and durable eligibility | Public package and facade |
| `cli.py` | Bounded JSON ingress and local operations | `python -m control_engineering_v2`, installed CLI |

There are no import-time store patches or alternate clone sandbox owners. The
public package, direct facade and historical public `hardened_*` aliases use the
current authenticated composition. Lower-layer composition helpers do not replace
that public boundary. SQLite file access and the Python process are trusted owner
boundaries: this library does not isolate a caller that can directly rewrite its
connection, modules or database.

## Durable state and migration

`EngineeringStore` uses SQLite foreign keys, WAL, `synchronous=FULL` and one outer
`BEGIN IMMEDIATE` per mutation. Nested owner operations share that transaction.
`SCHEMA.sql` is the single schema source, currently version 5. Tables are:

- `work_envelopes`: immutable source/objective/contract/owner/path/capacity facts;
- `path_leases`: state, revision, authority epoch, monotonically increasing fence and expiry;
- `assignment_generations`: immutable assigned and blocked projections;
- `assignment_generation_frontiers`: exact envelope revision, source and active-lease frontier;
- `integration_decisions`: immutable eligibility and rejection projection;
- `integration_decision_bindings`: candidate, sandbox and evidence identity;
- `integration_decision_seals`: authenticated seal identity, freshness and replay uniqueness;
- `audit_events`: ordered hash-linked event projection;
- `engineering_schema_meta`: schema version mirrored in `PRAGMA user_version`.

An owner mutation, its binding/frontier and audit event either commit together or
roll back together. Equal identity and semantics replay idempotently; different
semantics conflict. Startup checks the audit chain. Additive v2/v3/v4 stores migrate
transactionally to v5; historical generations without a bound frontier remain
unusable and require a new generation. A future version is rejected before any
schema or journal-mode write. A database claiming v5 but missing a required table
is rejected. A corrupted store must be quarantined and restored from a verified
backup; startup does not silently reconstruct acceptance or change owner facts.

The store is a local coordination database, not a replicated consensus service.
One connection belongs to one execution thread; concurrent callers use separate
connections and serialize writes in SQLite. WAL disk growth, backups, external
audit anchoring, archival retention and production availability remain operational
work. The in-file hash chain detects accidental mutation; it is not protection
against an administrator who can rewrite the complete database and chain.

## Leases and scheduling

Paths are NFC UTF-8 relative paths. Absolute/drive/UNC paths, traversal, alternate
separators, reserved aliases, unsupported globs and protected roots are rejected.
Envelope trailing `/**` denotes a canonical prefix. Leases check current envelope,
expiry, declared scope, active conflicts and revisions in the owner transaction.
Renewal, release and revocation require the exact revision and epoch.

At most 4096 packages, 4096 completed IDs, 256 predecessors per package, 4096 active
leases, 256 paths per record and 128 assignments are admitted. Encoded semantic
records also have a 256 KiB bound; hitting a byte bound may reject input below the
item-count limit. Graph validation is iterative, so valid deep DAGs do not depend
on Python's recursion limit. Scheduling applies completed predecessors, active
lease exclusion, intra-batch path exclusion, stable priority and envelope capacity.
A generation binds the exact source/envelope/active-lease frontier. A changed
frontier requires a new generation ID. An assignment is a proposal; workers still
need to acquire leases before writing their declared paths.

## Candidate qualification

Candidates bind exact base commit, allowed/protected paths and file/diff/resource
budgets. No-change is first and candidate identity is content-derived. The executor
requires the clean caller HEAD to match the envelope. It reads exact Git tree and
blob records into a metadata-free temporary workspace, without checkout filters,
Git archive attributes, hooks, repository remotes or credential files.

The Linux strong profile requires an actual successful Bubblewrap admission probe.
It mounts the candidate workspace read-only, isolates network and namespaces and
provides private writable temporary/home paths. The portable profile is for trusted
fixtures and reports `fixture_tested`; it cannot produce strong review evidence.
See [SANDBOX_SECURITY.md](SANDBOX_SECURITY.md) for platform and mount policy.

Checks use argument vectors without shell expansion, at most 64 checks, 256 arguments
per check, 8192 characters per argument and 65536 characters per argument vector.
One elapsed time budget covers all checks. Source HEAD/tree/refs/worktree and
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

`HmacTrustStore` is the deterministic reference/test signing adapter. Production
composition needs independent registered signing identities and protected verifier
keys. Tests using fixture signers establish protocol behavior; they do not establish
organizational evaluator independence or production key custody.

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
`packages.json` and `mutations.json` are arrays of `WorkPackage` and `Mutation`
objects. `checks.json` is an array of string argument arrays. Candidate IDs come from
the `candidates` output, including its no-change entry. Schedule optionally accepts
`--completed completed.json`, a JSON array of completed package IDs. Each input
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
| Missing/tampered/stale binding, seal or replay | Obtain fresh independent execution evidence; never set eligibility manually |
| Consent/parity mismatch or widened effect scope | Obtain exact owner consent and evaluator evidence for the declared target |

Run all current engineering-control tests from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tools/hepta-engineering-control -p 'test_*.py'
HEPTA_REQUIRE_STRONG_SANDBOX=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tools/hepta-engineering-control -p 'test_candidate_sandbox_hardening.py'
```

The second command belongs on a Linux runner that can admit Bubblewrap namespaces.
The default portable suite explicitly skips strong positive execution tests when
the real admission probe fails; strict mode turns that into failure. Never count a
skip as strong sandbox evidence. `test_consolidated_engineering.py` adds concurrent
SQLite lease races, rollback fault injection, migration/downgrade protection, deep
DAG and lease capacity behavior, forged evidence rejection, per-command source/state
mutation detection and real CLI subprocess round trips. Historical registries that
merely asserted maturity or counted source symbols have been retired in favor of
these behavior tests and this single implementation map. CI definitions remain in
the repository's current workflow; this document does not certify an unobserved run.
