# kernel.evidence runtime-boundary follow-up — 2026-09-27

This change extends PR #1050 at parent
`3bf66ef902936a40a530cd3d101af01dd04a8e06`. It is not an acceptance,
activation, or release receipt. The canonical qualification status remains the
workflow-generated `STATUS.json`; this document does not create another status
source or copy historical green flags onto a new commit.

## Delivered in this follow-up

### Restricted product SQLite connections

`HeptaEvidenceStore::open_runtime` retires the migration pool, opens an existing
file through a new restricted pool, and revalidates the migration ledger, schema,
rows, and integrity through that pool. Agentd's `EvidenceHost::open` now uses this
entrypoint in development as well as in any future admitted production mode.

`SqliteConfig::open_durable_evidence_runtime_pool` uses WAL, FULL synchronous
writes, foreign keys, recursive triggers, a bounded busy timeout, and no implicit
file creation. Its `after_connect` hook installs a SQLite authorizer before each
connection enters the pool, including newly opened/replacement connections.
Installation failure fails the connection instead of publishing it unprotected.
The SQLite handle is accessed only while holding SQLx's native-handle lock.

The runtime authorizer denies DDL, ATTACH/DETACH, extension loading, constraint
or durability overrides, migration-ledger writes, direct sequence manipulation,
and update/delete of core immutable evidence tables. Existing immutable triggers
remain in force, including for `INSERT OR REPLACE`. Read-only schema introspection,
legitimate AUTOINCREMENT inserts, idempotent inserts, transactions, savepoints,
and necessary mutable outbox transitions remain permitted. The no-column
SQLITE_READ event used for COUNT(*)/rowid scans is handled explicitly.

The legacy migration-capable `HeptaEvidenceStore::open` and low-level migration
pool are retained for controlled migration/fixture callers and other existing
consumers. They are **not** claimed to be a sealed, repository-wide migration
capability. This is a concrete separation of product connection privileges, not
an OS-user boundary or protection against arbitrary code owning the file/handle.
All other product consumers must be inventoried before claiming a closed-world
writer capability boundary across the whole repository.

### Fail-closed production activation

Syntax-valid identity/build/status/backup files do not establish a live external
authority. The existing implementation did not call an authenticated latest
frontier service, verify a live durable acknowledgement, or fence every append
through publication. `EvidenceRuntimePolicy::validate_startup` now rejects that
file-only production configuration, both at process policy installation and at
EvidenceHost entry before opening or migrating a database. The requested process policy is latched before startup validation. Even a caller
that ignores a production admission error cannot obtain the default development
policy or install a development replacement. EvidenceHost independently rejects
the latched production policy before database I/O.

Production therefore remains deliberately unavailable in this revision. There
is no boolean, environment, or force override. Replacing this guard requires a
real authenticated backend and durable append/publication path, with negative
replay/rollback/epoch tests and native qualification. An interface plus an
in-memory backend, or matching JSON hashes, is not a production implementation.

## Validation and limits

The common fixture is `SQLITE_RUNTIME_CASES.json`: 29 forbidden and 9 allowed
SQL cases. The new native SQLx integration suite (`runtime_authorizer`) exercises
all five simultaneous pool connections, pool reopen, immutable writes, pragma
changes, real migration/schema validation, identity recovery, AUTOINCREMENT,
idempotence, transactions, and missing-file refusal. Three production guard tests
were added to the existing `kernel_evidence_production_policy` test target so the
qualification lane already names the target that contains them.

Local execution during this follow-up:

- `python -m unittest discover -s scripts/tests -p test_kernel_evidence_sqlite_authorizer.py -v`
  passed 8 policy-model tests against SQLite. The first run exposed and led to
  fixing the legal no-column SQLITE_READ case and a test transaction issue.
- Original contents of all modified source files were checked against their
  Git blob hashes before editing, preventing accidental reconstruction drift.

The Python model executes SQLite SQL but does **not** compile or execute Rust,
validate SQLx's FFI installation, or prove native reconnect behavior. Cargo and
rustc were absent from this working environment. Native tests are submitted for
CI, not represented as passed. At the last observation of the parent candidate,
the hardening job was queued. A subsequent commit requires its own source and
merge qualification; the parent's status cannot qualify this change.

The branch-protection status-check endpoint returned HTTP 403 (`Resource not
accessible by integration`). No branch-protection setting was changed, and the
existence of the stable workflow job `Kernel evidence qualification required`
is not reported as proof that it has become a protected required check.

## Still required for production completion

A deployed external monotonic backend, live authenticated reads/CAS/history,
actual durable acknowledgements and audit retention, key distribution/rotation,
a crash-reconciled named writer and backup publisher, rollback-resistant trust
state, an independent restore drill, performance baselines, sustained fuzzing,
independent acceptance, and canary/release approval are still open. The CI
artifact should keep those lifecycle claims false until evidence actually
exists. This follow-up must not be used to raise the production-completion claim.
