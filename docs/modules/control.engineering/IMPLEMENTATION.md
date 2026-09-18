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
creates bounded atomic single- or multi-file code candidates including rename;
runs admitted checks under a bounded sandbox controller; performs evaluator-owned
mutation testing; verifies source/execution/evaluator evidence; records signed
candidate-bound review eligibility; exposes distributed-fence, external-audit-anchor
and external-key-custody admission contracts; and composes consent-bound dormant
external-system proposals. The repository CI includes a named v2 product caller.
It is not a learned code generator, merge service or autonomous release agent.

Review requests and dormant proposals do not themselves merge, activate, deploy,
enroll a host or transfer credentials. A deployment controller or production caller
must provide the separate owner authorization required by its own contract.

## Components and ownership

| Owner | Responsibility | Main callers |
| --- | --- | --- |
| `path_policy.py` | Canonical POSIX paths and cross-platform alias rejection | Store, candidate generator and sandbox |
| `control_plane.py` | SQLite schema, transactions, envelopes, leases, base scheduling and audit anchor head | Public facade, orchestrator and CLI |
| `orchestration.py` | Exact source admission, signed completion receipts, skills/capacity scheduling, integration order and merge-queue proposals | Product caller and public package |
| `candidate.py` | Deterministic single/multi-file/rename grammar, exact Git materialization and immutable oracle paths | Public facade and CLI |
| `sandbox_control.py` | <=8 process-local sandbox admission and <=2 infrastructure-only retries | Mutation testing and production qualification |
| `mutation_testing.py` | Baseline-pass / mutant-kill evaluator gate | Qualification |
| `evidence.py` | Exact Git objects, source/merge execution receipts, pluggable signing port and independent identities | Candidate evidence binder |
| `hardening.py` | Active-state frontier and authenticated evidence/consent primitives | Store, closure and seal |
| `closure.py` | Source-tree and freshness-window binding, dormant assimilation | Seal and public facade |
| `seal.py` | Signed evidence seals, replay prevention, review and durable eligibility | Public package and facade |
| `external_controls.py` | Distributed fencing, external audit anchor and HSM/KMS custody receipt admission | Production worker/deployment composition |
| `product_gate.py` | Named repository CI product caller over the v2 durable owner/orchestrator | `hepta-consolidated-source.yml` |
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
Encoded semantic records also have a 256 KiB bound; hitting a byte bound may reject input below the
item-count limit. Graph validation is iterative, so valid deep DAGs do not depend
on Python's recursion limit. Base scheduling applies verified completed predecessors, active lease exclusion,
intra-batch path exclusion, stable priority and envelope capacity. The higher
orchestration layer then matches required skills, worker capacity, CI units and
review-role slots and orders admitted work by expected value minus architecture
debt and rollback cost. A generation binds the exact source/envelope/active-lease
frontier; the orchestration plan additionally binds the authenticated completion
frontier. A changed frontier requires a new generation ID. An assignment is still
a proposal; workers must acquire the exact local lease, and multi-host production
writes must additionally present a signed distributed fence matching epoch/token,
paths, source and revocation frontier. Fence verification re-reads the current
SQLite lease row and requires the same envelope, holder, revision, epoch, token,
paths and expiry to still be active; a previously signed active receipt fails
immediately after local release/revocation. External fence and audit-anchor validity
windows may not outlive their owning local lease/envelope.

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

The Linux strong profile requires an actual successful Bubblewrap admission probe.
It mounts the candidate workspace read-only, isolates network and namespaces and
provides private writable temporary/home paths. The portable profile is for trusted
fixtures and reports `fixture_tested`; it cannot produce strong review evidence.
See [SANDBOX_SECURITY.md](SANDBOX_SECURITY.md) for platform and mount policy.

Checks use argument vectors without shell expansion, at most 64 checks, 256 arguments
per check, 8192 characters per argument and 65536 characters per argument vector.
One elapsed time budget covers all checks. `SandboxCoordinator` admits at most
eight process-local sandboxes and retries only the explicitly classified
infrastructure failures, at most twice; semantic rejection is never retried.
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
Production admission additionally requires a signed `KeyCustodyReceipt` proving
hardware-backed custody outside the engineering process. Fixture signers establish
protocol behavior only; they do not establish organizational independence or
production key custody.

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
