# V23 — Exact V22 global blocking-CI repair and security non-waiver

**2026-10-16 UTC/2026-10-17 CI · DRAFT · RESEARCH_ONLY · SHADOW_ONLY · DENY_ALL.** Parent: the real **V22 #2557 exact HEAD** `209f9c1964adea91c0b198e96d512d9b31b19c5f`. The parent passed all four original physical experimental workflows V18–V21, V22 source integrity, Neuron Matrix, architecture convergence, and V8 canary **at that exact parent SHA**. Its global `blocking-ci` run `38986001548` failed; those successes do **not** transfer automatically to V23.

## Genuine full-workflow failures read from completed hosted logs

| Job / exact original ID | Observed error | V23 bounded action |
| --- | --- | --- |
| `repo-checks/build-test` `117261400009` | Pinned Ruff reports one offending source: `scripts/tests/test_hepta_ci_dependencies.py`; `just fmt-check` fails before remaining checks | Add formatter-required fixture class blank lines only; original three bounded ENOTEMPTY/EACCES negative cases and all Git/Cargo scope tests remain |
| `Bazel clippy macOS` `117261400517` | Fleet fixture `authority_port.rs:197` uses disallowed `unwrap()`; production code did not fail this diagnostic | Transfer reviewed test-only helper and stricter assertions from Matrix security candidate #1507 |
| `Bazel clippy Windows` `117261400551` | Disallowed `sqlx::PoolOptions::connect("sqlite::memory:")` in Automation historical migration and Memory schema tests | Transfer pre-reviewed isolated SQLite fixture calls to `codex-state::SqliteConfig::open_durable_evidence_pool`; preserve all schema/migration/rollback assertions and SQLite shim requirement |
| `Bazel test Windows shards` `117261400470`/`117261400536` | Original AuthBus global/per-issuer capacity fixture, Fleet canonical workspace bindings, Supervisor restart budget, Git descendant wrapper checks fail among other Windows tests | Transfer bounded **test-only** fixes exactly from independent Matrix PR #1507 where possible; no owner behavior, permission, test waiver or CI removal |
| `cargo-deny` `117261400066` | Live unresolved advisories listed below in actual `Cargo.lock` | **No ignore/allowlisting.** Requires independently reviewed secure dependency graph and live lock/Bazel/SDK validation; not marked fixed by this test-only PR |

### Exact advisory blocker census (all kept blocking)

- `RUSTSEC-2026-0319`: `anymap2 0.13.0` via `matrix-sdk 0.18.0` (unmaintained).
- `RUSTSEC-2026-0318`: `matrix-sdk-crypto 0.18.0` (to-device panic; safe compatible SDK migration required).
- `RUSTSEC-2026-0346/0347/0348/0349`: `rustls 0.23.45` (TLS session Debug exposure, ECH rejection, Brotli decompression, unauthenticated ServerHello group choice). Do not call this resolved by disabling TLS checking.
- `RUSTSEC-2024-0449`: `unsafe-libyaml 0.2.11` transitively via deprecated YAML parser; move to compatible audited safe-Rust implementation, not an ignore.
- `RUSTSEC-2026-0367/0368/0369`: `zip 2.4.2` in `codex-core-plugins`; archive extraction permission/symlink safety defects. Requires reviewed compatible extractor/API upgrade. Live `cargo-deny` requires full workspace lock and consumers to qualify.

The **independent unmerged** [Matrix/Neuron security candidate #1507](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1507) has some prior scoped Matrix SDK tests and reviewed fixture sources, but its own last observed exact HEAD global, architecture, Windows and parser qualification were not fully green. **Do not copy a giant unreviewed migration into V23 or assert the old advisory graph is solved.** This draft cherry-picks only individually inspected test corrections; complete secure resolved graph remains a separate prerequisite.

## Source closure and preserving original scientific controls

V23 changes no real V18–V21 pretrained model/Head/Encoder/Reader bytes, model-source artifact SHA, feature snapshot source, test labels, NDU selector, original Worker/Control/CNS/CAS or FinalUse implementation. All four real original physical workflows remain mandatory. No model promotion or automatic Cell division can be inferred from global source checks.

The new `hepta-v23-global-gate-targeted-regressions` CI runs source-head Ruff, Git impact-selector tests, canonical DB migration/schema and original Windows/Linux fixture tests on the **same V23 event HEAD**. Successful local source inspection and a queued workflow are NOT completion evidence.

## Remaining strict gates

1. Confirm current V23 exact-head targeted scope tests, Ruff and audit, all four original physical trials, Neuron Matrix, architecture and canary.
2. Fix any true source/API errors from hosted logs; never silence failed tests.
3. Merge reviewed secure Matrix/AnyMap/YAML/TLS/ZIP dependency upgrades with actual Cargo lock and Bazel lock, then demand exact-SHA `cargo-deny` (advisories, bans, licenses, sources) all green.
4. Rerun all Windows/macOS/Linux Bazel and native tests, crate-owned durability, private ACL, signed authorization, crash/reopen.
5. Only after *independent learning and NDU future gains* and 64/256/1024/4096 target host CPU/RSS/p95/p99/WAL/energy proofs consider CellSplit; until then **DRAFT / DENY_ALL / no production cutover**.
