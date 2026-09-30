# secrets.heptabao adversarial audit and remediation

Audit date: 2026-10-01 (Asia/Shanghai).
Source baseline: `a57ffe266efc1fa9f7028eb22b77094c7ea6c443`,
`codex/secrets-heptabao-frozen-closure-20260930`.
Remediation branch: `codex/secrets-heptabao-adversarial-audit-20261001`.

## Scope and documentation assessment

The latest module branch contains detailed development documentation. The
principal contracts are `TECHNICAL.md`, `CONSUMPTION_SAGA_V4.md`,
`LEASE_OWNER_V3.md`, `OPERATIONS_AND_CAPACITY_V1.md`, the canonical manifest,
product-caller specifications and readiness/target-storage policies. This
audit additionally supplies `SQLITE_OWNER_RUNTIME_V1.md` to make the actual
SQLite API, table layout, resource limits and recovery behavior explicit.

The baseline main branch is older than the module candidate. This remediation
preserves that candidate and reviews only its delta; it does not replace main
with the complete development-branch tree.

Parallel reviews covered transport and secret buffers, SQLite storage and
recovery, reference-owner durability and revocation, product composition,
native qualification and adversarial evidence inputs. Reviewers then checked
their fixes, with an independent review of the qualification trust boundary.

## Position in the project

| Owner | Authoritative responsibility | Bao interaction |
|---|---|---|
| HeptaBao provider | Secret value and provider contract | Read one exact KV-v2 version over pinned-CA TLS |
| `kernel.authority` | Grants, approvals, revocation and final-use authority | Verify exact request and recheck immediately before consumer entry |
| `auth.authbus` | Policy, quota, reservation and settlement | Reserve once, fence dispatch, settle original immutable outcome |
| `secrets.heptabao` | Secret metadata, lease history and consumption state | Persist exact identity and recovery facts without raw secret values |
| Selected product host | Enrolled consumer effect and original-effect observer | Compose dependencies, enforce execution budgets and operate recovery |

The appropriate optimization boundary is a transactional metadata owner and
registered, evidence-preserving consumer ingress. The module must not become
another authority issuer, an AuthBus ledger or a generic secret-value store.

## Findings and implemented remedies

| Priority | Baseline defect | Remedy and regression boundary |
|---|---|---|
| P0 | SQLite runtime contains `Box::new(_)` in a match pattern and cannot compile | Correct boxed variant pattern; make build-contract checks distinguish patterns from constructors |
| P0 | External storage/provider receipts self-certify signatures with a boolean | Separate structural completeness from authentication; unverified declarations cannot satisfy `--require-qualified`; reject zero identities and normalized unsupported storage profiles |
| P1 | Native qualifier emits v2 and nine gates while attestation expects v1/four gates | Validate current schema, exact commands, every retained log digest and nonzero native test execution |
| P1 | Historical or mismatched source/merge evidence can be combined | Bind commit trees, merge parents, lock/manifest object hashes, workflow run/attempt and toolchain; require native evidence before a qualified readiness claim |
| P1 | Build-contract gate rejects an existing constructor helper and requires removed development machinery | Register the actual lexical caller; preserve `productComposed=false`; permit retired materializers to remain absent |
| P1 | Evidence outages after dispatch replace recovery context with generic errors | Preserve `Indeterminate` or `SettlementPending`, original reservation and validated receipt across time/signing failures |
| P1 | Reference-owner idempotent retries bypass an uncertain-commit fence | Check writer eligibility before every consumption mutation; inject post-rename parent-sync failures across nine transitions |
| P1 | Concurrent revocation publication can overwrite a new head's deadline with an older deadline | Serialize durable head and freshness publication; reject unavailable freshness owner before advancing authority |
| P1 | SQLite lease result and independent projection can disagree | Bind result, provider observation, operation kind, generation, scope, reference and consumer; reject denied-result mutations and future observations |
| P1 | SQLite accesses unsafe sidecars before checking them | Validate database/WAL/SHM/journal paths before connection setup; reject symbolic/hard links and establish private modes |
| P1 | Checkpoint publication or COMMIT cancellation can leave an unfenced uncertain owner | Fence on uncertain outcome/drop, recheck after writer-lock acquisition, and compute the published checkpoint within the same transaction |
| P1 | Decoded SQLite JSON can disagree with immutable/indexed SQL projections | Validate consumption, lease and lease-operation keys, semantic identity, state, generation and terminal digests on reads; add actual database-corruption/API regressions |
| P1 | Serial recovery preclaims a whole batch and expires later work behind the first operation | Claim one row immediately before execution using fresh time; actual SQLite runtime regression reproduces the old second-row expiry |
| P2 | Checkpoint/metrics scans and archive batches load extensive history into memory | Stream rows and SHA-256; archive by bounded identities; preserve checkpoint framing and bound reference import |
| P2 | Duplicate or escaped-alias KV fields silently overwrite values | Reject duplicate decoded keys before accepting their values |
| P2 | Response-buffer growth and token-validation temporaries create unnecessary unzeroized copies | Preallocate the bounded body and validate token bytes by borrowing; exercise chunked cap and injection boundaries |
| P2 | Supply-chain receipt combines dirty worktree hashes with an older HEAD and accepts empty inputs | Require clean stable source and valid metadata/artifacts; select and hash exact Git objects; distinguish unsigned digests from authenticated build provenance |
| P2 | Bazel library lacks compile-time SQL migration resources | Declare migration compile data; keep the Cargo dependency graph unchanged |
| P2 | Composition/deadline helpers live only inside a binary and cannot be imported by a product host | Move unchanged behavior to an exported library surface; retain source-bound caller evidence without claiming daemon activation |
| P1 | Composition normalizes the inner batch to one before validating the original sweep limit | Validate the original configuration first; reject zero and over-limit sweeps; preserve valid configured bounds |

The low-level transport remains direct HTTPS with supplied CA only, hostname
validation, no ambient proxy, no redirects/retries or trace propagation, and a
one-MiB response cap. Provider mutation remains fail-closed. Local zeroization
covers controlled buffers; dependency/OS transient copies remain outside that
guarantee. Secret digests remain sensitive metadata.

Repeat review found that a denied renewal could still carry a generation-two
lease projection. It also reproduced a valid JSON lease-operation semantic
substitution against an unchanged SQL identity. Both require explicit rejection
at the owner boundary. The composition review additionally checks compiled
module/public-export reachability, rather than treating an unreferenced Rust
source file as an importable library API.

The pre-existing SQLite owner is large. These repairs keep its transaction and
validation invariants together and avoid combining a security fix with a broad
storage rewrite. Response parsing and product composition live in separate
modules; review commits separate ownership, transport, evidence and docs.

## Verification

Verification results are recorded after the final source freeze. Native checks
cover the adapter, Hepta primitives, AuthBus and SQLite infrastructure. Python
checks cover candidate immutability, manifests, receipts, SQL admission fences,
external-gate declarations and supply-chain evidence. The ignored
`saga_crash_tests::child_process` is a subprocess fixture: the passing
`registered_saga_sigkill_matrix` invokes it at 26 distinct crash cuts.

| Local verification | Result |
|---|---|
| `just test -p codex-hepta-bao-adapter -p codex-hepta-types -p codex-hepta-authbus -p codex-state-sqlite --locked --test-threads=2` | 200 passed; one ignored subprocess fixture; includes all three compiled bootstrap tests and denied/corrupt lease-operation regressions |
| Scoped `cargo clippy` for the same four packages, `--locked --all-targets -- -D warnings` | Passed with no warnings |
| Module Python QA discovery | 86 tests passed |
| Independent evidence-review regression subset | 58 tests passed |
| Scoped formatting, canonical projection verification and `git diff --check` | Passed |

The repository-wide caller inventory separately reports five existing
unclassified cognitive/learning boundaries outside this module. The newly
registered Bao runtime constructor matches its source caller; this audit does
not label the entire repository caller inventory green.

The shared execution filesystem exhausted space during earlier attempts. A
complete rerun uses an isolated `TMPDIR` under `/dev/shm` and two test threads;
this is source-fixture verification, not target-device durability evidence.
Failed/interrupted attempts are not counted as passes. Source and synthetic-merge
CI must retain their own exact-run evidence; a local report is not an independent
operator attestation.

## Completion assessment and remaining boundaries

| Dimension | Assessment |
|---|---|
| Detailed technical development documents | Present; concrete SQLite implementation guide added |
| Exact KV-v2 transport and registered durable consumption | Implemented; adversarial failure and parsing fixes included |
| Reference JSON owner | Bounded reference implementation; synchronous snapshots unsuitable for production throughput |
| SQLite metadata owner/runtime | Implemented; schema, CAS, history, claims, archive and checkpoint hooks present |
| Product source caller | Exported constructor helper present and inventoried |
| Selected running product composition | Open: binary `main` currently describes/validates config and does not run a consuming product |
| Independent time/settlement/revocation/checkpoint operation | Open: interfaces and checks do not provision independently governed services |
| Dynamic provider lease effects | Blocked by the fixed provider's qualified contract |
| Storage-device power-loss, restore and long-history qualification | Open: process termination and runner-local tests do not supply these observations |
| Activation, operator acceptance, promotion and release | Remain false and independently governed |

Concrete follow-on product work is to select a consuming host, provision its
independent trust services, enroll its exact consumer/observer configuration,
enforce callback and shutdown budgets, export bounded metrics, and retain
target-host qualification evidence. These are explicit remaining work items;
they cannot be fulfilled by changing claim booleans or generating unsigned
receipts. This audit does not label the entire product 100% complete.

A finite adversarial review establishes tested fixes within its stated scope.
It does not prove the absence of every future optimization or vulnerability.
