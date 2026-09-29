# Five-consumer entrypoint and diagnostic hardening — 2026-09-29

This supplement records one bounded continuation of the existing
`cognitive.types` closure candidate. It does not replace `TECHNICAL.md`,
`QUALIFICATION.md`, `IMPLEMENTATION_MAP.json`, or the fixed-candidate depth
evidence. The containing Git commit is the source identity for this increment.
No status flag is promoted by this document.

## Preserved architecture

The change keeps `codex-rs/hepta-cognitive-types` as the single canonical type
source. `Validated<T>`, canonical digests, consumer bindings and handoffs remain
authority-free structural evidence. Current owner, scope, generation,
revocation, migration and final-use checks remain the responsibility of the
existing physical owner path.

Frozen V1 and schema-bound V1 digests remain separate. No wire byte, digest
domain, canonicalization rule, payload-family matrix, migration state or
historical receipt is reinterpreted. The change adds no store, writer, runtime
owner, fallback executor or product control plane.

## Payload-free textual rejection propagation

The central `CanonicalConsumerBindingError::violation()` already preserves a
stable, payload-free `ContractViolationV1`. Several existing consumers retain
historical `String` error variants and therefore call `to_string()` while their
public error migrations remain staged.

`Display` for `CanonicalConsumerBindingError` now delegates to the structured
violation instead of `Debug`. As a result, those existing read, store,
retrieval, compaction and intelligence-control string paths receive the stable
code, field path and redacted message rather than an embedded historical
diagnostic payload. The original enum variant and owned string remain available
for compatibility and debugging by code that explicitly inspects the value;
they are not parsed or promoted into authority.

Regressions require:

- every error variant's `Display` to equal its structured violation;
- control characters, bidi controls, JSON-looking text and authority-looking
  words in a historical message not to enter `Display`;
- one-byte and one-MiB historical messages to produce identical bounded output.

This closes the ordinary textual-log leak path. It does **not** claim that every
consumer error enum has completed a source-compatible migration from `String`
to a typed variant.

## Explicit normal-entrypoint evidence

Package-wide tests remain useful but can report success after a filter silently
matches zero tests. The new read-only
`cognitive-types-entrypoint-evidence` workflow therefore binds one reviewed
normal-entrypoint test module for each existing consumer:

| Consumer | Existing package | Required Rust test module |
| --- | --- | --- |
| `cognitive.read` | `codex-hepta-cognitive-read` | `authoritative::tests` |
| `cognitive.store` | `codex-hepta-cognitive-store` | `v2::product_tests` |
| `memory.retrieval` | `codex-hepta-memory-retrieval` | `generation_bound::tests` |
| `compact.engine` | `codex-hepta-compact-engine` | `qualified::tests` |
| `intelligence.control` | `codex-hepta-intelligence` | `canonical::tests` |

For a pull request, every module executes against both the immutable exact head
and the deterministic two-parent merge candidate. The workflow first runs
Cargo's test listing, rejects zero discovered tests and rejects any listed test
outside the registered module, then executes the same filter. Build output is
kept outside the source tree.

Each artifact retains:

- source, base, candidate commit/tree and ordered parents;
- exact consumer, package and module filter;
- every discovered test name and its count;
- listing and execution exit codes, byte lengths and SHA-256 digests;
- Rust toolchain identity and an empty final source-status file;
- explicit false values for product acceptance, compatibility retirement,
  activation and release.

The aggregate verifier requires the exact ten-artifact pull-request matrix,
recomputes every inventory and digest, reparses the Cargo listing, and rejects
missing, extra, renamed, symlinked, modified or resealed evidence. Sealed
`receipt.json` and `receipt.sha256` sidecars use the same bounded no-symlink,
stable-file-identity reader as command logs and auxiliary JSON.

## Executed verifier regressions

Before the files were pushed, Python 3.13.5 compiled the verifier and executed
12 focused unit tests successfully. The fixtures cover a complete ten-artifact
matrix, exact-head-only manual behavior, zero-test success, wrong-module
listing, nonzero Rust-test exit, modified logs, missing or renamed artifacts,
resealed claim/source substitution, duplicate JSON keys, symlinked logs or
sealed receipts/checksums, and synthetic-merge parent reversal.

These are verifier-fixture results, not Rust entrypoint execution. The actual
Rust tests and their exact-head/merge artifacts must be produced by the remote
workflow for the containing source commit.

## Remaining boundary

A green entrypoint matrix proves that the named existing regression modules were
non-empty and passed on the fixed candidates. It does not prove live
credentials, production traffic, current owner observations outside the tests,
compatibility retirement, target-host capacity, independent acceptance,
activation, promotion or release. Those remain separate gates in the
implementation map and qualification policy.
