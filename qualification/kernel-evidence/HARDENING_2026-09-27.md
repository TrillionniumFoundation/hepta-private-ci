# kernel.evidence hardening: 2026-09-27

## Scope and delivery status

This change set belongs to PR #1050, branch
`codex/kernel-evidence-production-hardening-20260927`. It is a development
hardening candidate, not a production activation, independent acceptance,
backup-restore certification, or release approval. Changes are not merged into
`main` merely because their source files exist.

The reviewed main candidate was commit
`a126987b84737dbc2ee2592442a314117bddb4a2`, tree
`a22fd0074c45ae6f3cef2092cd6e273bf9c26c30`.
Its evidence command failed with 121 tests passed, one failed, and one ignored
subprocess helper. The failing test was
`authbus_outbox_tests::bounded_capacity_prunes_only_terminal_history_and_keeps_replay_consumed`.
The enqueue helper unwrapped `Capacity`.

## 1. Exact-source qualification and retained diagnostics

The original failure was an invalid test fixture, not a reason to weaken the
per-issuer quota. The global-capacity fixture copied 4,095 active messages with
the same issuer. After acknowledging one message it still exceeded the separate
per-issuer active limit. The fixture now fills global capacity using independent
issuer identities, asserts the original issuer has exactly one active message,
and checks unrelated active messages survive terminal pruning. The separate
per-issuer-across-epochs quota test is retained unchanged.

The qualification workflow now delegates each candidate to
`.github/workflows/hepta-kernel-evidence-lane.yml`. Source and deterministic merge
lanes run independently. Each has separately recorded checks for candidate
identity, environment setup, Rust toolchain setup, evidence crate tests, Agentd
product tests, production policy tests, status-generator tests, Lane-A truth,
technical documentation, and implementation maps.

Each real command is executed through `scripts/hepta_ci_exec.py`. Cargo commands
use `--locked`; test commands require at least one observed passing test. Command
records bind source/tested/base SHAs, tree, parent identities, clean checkout
before and after execution, run ID, attempt, exit status, and log hashes.

Uploads and diagnostic aggregation run with `if: always()`. Individual failures
are allowed to reach the diagnostic steps but not to turn the final result green.
Records and lane receipts have source/run/attempt-qualified artifact names. The
aggregate downloads these artifacts from the same run, rejects digest mismatches,
rechecks record manifests and logs, and recomputes the deterministic merge tree.
A boolean output alone is not sufficient qualification evidence.

The stable aggregate check is `Kernel evidence qualification required`. It is
scheduled for every PR rather than being hidden behind a path filter. Adding
that check to repository branch protection is a separate administrative action.
The connected GitHub integration returned HTTP 403, `Resource not accessible by
integration`, when reading the main branch's required-status-check protection.
No branch-protection mutation or removal of existing required checks is claimed.
An administrator must add this context while retaining existing protections.

## 2. Frontier backend and production admission

`EvidenceFrontierBackend` defines latest-frontier reads, compare-and-swap,
bounded history, and backend identity verification. The in-memory implementation
is explicitly ephemeral and cannot satisfy production durability validation.
Its first-generation CAS retry now works with `expected_generation=None`.
Replay compares the entire stored record, not just the frontier digest; changing
audit identity, commit time, or other metadata cannot produce a fictitious replay
receipt. Zero expected generation, generation overflow, key-epoch substitution,
invalid JSON objects, digest mismatch, and oversized payloads are rejected.

The schema-v2 Agentd frontier binds the evidence trust registry, recovery-signer
trust, build identity, qualification status, backend identity, source commit/tree,
and ledger root. The build identity checks the running binary and migration-set
digests. Signer trust supports bounded, non-revoked generation windows for key
rotation. Development and production policies are distinct and cannot be replaced
within one process after configuration.

**Important remaining implementation boundary:** the current backend identity
and backup publication admission files are not a live authenticated read from an
external monotonic service. No remotely deployed CAS service, production network
adapter, remote durable-ack verification, backup publisher, or continuously fenced
production writer is delivered by the in-memory backend. A signed local identity
file must not be treated as proof that the external service is latest, reachable,
or durably committed. Production activation remains blocked pending those
implementations and independent deployment evidence.

Required next integration is a real backend outside the local rollback domain,
with authenticated latest reads, durable CAS/audit receipts, trust-root and key
rotation, explicit outage behavior, and recovery plus write/publication fencing.
It must reject old database + old frontier + old trust-registry bundles even when
all local signatures still validate. Fault tests must cover response loss after
remote commit, stale generation, revoked backend keys, network partitions, and
local-write/remote-publication crash boundaries.

## 3. SQLite and runtime hardening

The runtime migration is
`codex-rs/hepta-evidence/migrations/0011_qualification_evidence.sql`, not a schema
mirror. It already contains `qualification_evidence_no_update`,
`qualification_evidence_no_delete`, and immutable recovery-identity triggers.
The earlier review's statement that these triggers were absent was incorrect.
Existing append-only protections and their schema checks are retained.

`SqliteConfig::open_durable_evidence_pool` now explicitly enables
`recursive_triggers=ON` for every new pooled connection. SQLite REPLACE can
implicitly delete a conflicting row; its DELETE trigger protection must not
depend on a compile-time/default recursive-trigger setting. This is a narrow
change to the durable evidence pool. Ordinary rebuildable Codex databases keep
their existing configuration.

`codex-rs/hepta-evidence/tests/sqlite_hardening.rs` adds real SQLx regressions for:

- all five pool connections and reopened pools retaining recursive triggers,
  foreign keys, and FULL synchronous durability;
- replacement, direct update, and deletion failing to change the enrolled store
  identity, while exact `ON CONFLICT DO NOTHING` remains idempotent;
- `SQLITE_FULL` leaving no partial committed transaction;
- corrupted database headers being rejected rather than silently rebuilt;
- abrupt process exit before and after commit preserving the commit boundary.

The ignored child helper is explicitly invoked by the parent crash test. It is
not counted as an independently executed green test. Abrupt process exit is not
a physical power-cut test, and `max_page_count` is not a host disk-full or fsync
fault injector. Runtime SQLite authorizer installation, separate migration and
runtime database authority, a complete corruption/fsync/rename/power-loss fault
matrix, sustained fuzzing, and a multi-process performance baseline remain open.

The branch also includes bounded qualification cursor pagination and frontier
contention/contract tests. Thread-contention tests must not be reported as a
multi-process throughput benchmark or as external quorum qualification.

## 4. Canonical status and generated documentation

`scripts/kernel_evidence_status.py` is the status engine. Its `lane` command
validates command/log records and durable artifact evidence. Its `aggregate`
command revalidates downloaded lane receipts, identities, manifests, and merge
trees. Its `verify` command performs structural consistency checks; it does not
independently authenticate an arbitrary JSON file or establish external service
trust. Provenance comes from the qualified workflow and the verified artifacts.

The authoritative candidate object is the `STATUS.json` inside the immutable
`kernel-evidence-canonical-status-<source>-<run>-<attempt>` artifact. It contains
source commit/tree, run ID/attempt, exact-source and applicable merge outcomes,
artifact digests, receipt digests, and validation errors. CI always leaves
independent acceptance, external frontier activation, backup-restore drilling,
canary acceptance, and release approval false; it cannot self-issue those claims.

The `render` command preserves technical prose and generates a managed current
status section in five views:

- `docs/modules/kernel.evidence/TECHNICAL.md`;
- `docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md`;
- `qualification/kernel-evidence/TRACEABILITY.md`;
- `qualification/module-execution-dossiers/detail/kernel.evidence.md`;
- `qualification/kernel-evidence/RELEASE_DASHBOARD.md`.

These generated views are stored in the same candidate artifact, under `views/`.
They all reference the same canonical JSON hash. `render --check` rejects drift.
Generated files are deliberately outside the qualified checkout: committing a
status claiming its own current source SHA would change that SHA and invalidate
the claim. An optional documentation/status publication branch must be a separate
projection of the immutable candidate artifact, not a new qualification claim.
Historic status prose outside the managed block is design/history context, not
a replacement for the block's candidate-bound values.

Local execution completed 44 Python regression tests covering false-green
prevention, missing records, wrong commands, log tampering, wrong run/attempt,
source drift, JSON type confusion, merge-parent/tree mismatches, unsafe paths,
external lifecycle self-approval, and five-view generation/drift. Workflow YAML
and shell blocks were parsed locally. Local SQLite experiments reproduced the
REPLACE trigger boundary and SQLITE_FULL rollback behavior. These are not Rust,
Agentd, hosted exact-source, or hosted merge qualification results. Hosted results
must be read from the final candidate's actual Actions run.

## Acceptance checklist

Do not close this work as production-ready until the final source and merge
candidate receipts are green; branch protection is actually configured; the real
external monotonic backend and production caller are integrated and deployed;
old-state recovery is rejected against a live authority; database/runtime
permissions and fault/performance testing are complete; and independent
acceptance, disaster-recovery, canary, and release receipts exist for the exact
candidate. Missing or queued evidence remains unqualified.
