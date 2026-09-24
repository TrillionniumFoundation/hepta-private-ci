# memory.federation local qualification record

- module: `memory.federation`
- source candidate: `2f2d84401369f2223bf20716e09719ed6ccd6ab3`
- source tree: `b69e5249f363497051e27654d555f9780e78d589`
- product-convergence parent: `9d7147f7d745a8edad99fb892751da536ef1e009`
- current main used by the PR: `7ddbfac88525196e7a4b31387ceae194958275f5`
- local host class: shared Linux development workstation; concurrent unrelated builds were active
- status: focused local regressions passed; this file is not target-host qualification, independent acceptance, activation or release evidence

## Scope

This record covers the local in-process federation profile only:

- the memory owner controls the active cognitive database generation;
- recovery publication fences predecessor federation readers;
- a missing active pointer cannot revive `cognitive_1.sqlite3` after a recovered generation exists;
- recovered-owner revoke, correction and forget operations dominate predecessor state;
- discovery retains completed healthy owners while bad or unresolved owners become explicit bounded failure coverage;
- the canonical V2 engine remains one-attempt/read-only and the product orchestrator remains bounded.

It does not cover an authenticated cross-process or cross-host wire protocol. No second real authenticated host, registered wire schema, remote credential exchange or remote cut witness was available in this session.

## Commands and observations

All Cargo commands used the repository Rust 1.95 toolchain, `--locked`, offline dependency resolution after the local cache was populated, and a dedicated target directory.

| Check | Candidate observation |
| --- | --- |
| `cargo metadata --offline --locked --format-version 1 --no-deps` | passed after rebasing onto the current product-convergence parent, which already contained the required lockfile refresh |
| `cargo test --offline --locked -p codex-hepta-memory --lib cognitive_federation_tests -- --nocapture` | development slice: 6 passed, including recovered-owner revoke and recovered-owner correction/forget; the later active-pointer no-fallback assertion was then rerun on the frozen source candidate as the focused check below |
| `cargo test --offline --locked -p codex-hepta-memory --lib cognitive_federation_tests::recovered_owner_revocation_fences_predecessor_readers -- --exact --nocapture` | passed on the frozen source content: 1 passed, 0 failed; includes real writable recovery, recovered-generation revoke, predecessor-reader rejection, product empty result and missing-active-pointer fail-closed behavior |
| `cargo test --offline --locked -p codex-hepta-memory --lib cognitive_runtime_tests -- --nocapture` | diagnostic run with the initial 1-second discovery horizon: 9 passed and the existing 17-owner ceiling test observed only 8/16 healthy owners before the horizon; this result was treated as a defect, not waived |
| focused stalled-owner and bad-owner runtime regressions | passed in the diagnostic runtime run: completed healthy outcomes were retained and bad/unresolved owners remained typed failed discovery coverage |
| corrected budget | source changed to one 3-second total product horizon with at most 2 seconds for discovery, retaining a bounded remainder for admitted reads; final full runtime execution is delegated to the isolated exact-head and synthetic-merge workflow |
| `rustfmt --edition 2024 --check` on changed Rust sources | passed; stable rustfmt reports only the repository's existing warning about unstable `imports_granularity` configuration |
| `git diff --check` | passed before source freeze |

The shared workstation was heavily contended by unrelated Rust builds. Individual SQLite-heavy tests therefore took tens of seconds to minutes. These timings are recorded only to explain the local environment and are not p95/p99, capacity, latency or deployment-SLO evidence.

## Failure matrix covered by source tests

| Boundary | Expected result |
| --- | --- |
| recovered owner revokes an old grant | current discovery returns no enrolled reader; a deliberately rebound predecessor reader is denied before evidence use |
| recovered owner corrects one memory and forgets another | predecessor bindings are denied; fresh and product reads expose only the current corrected revision |
| active pointer is deleted after recovery | discovery fails closed as corrupt while recovered generations exist; it does not fall back to the legacy database |
| one owner database is corrupt/unobservable | healthy owner result remains available; coverage reports one completed and one failed discovery slot |
| one discovery future does not complete before the discovery horizon | completed healthy outcomes are returned; unresolved count is explicit and bounded |
| legacy V1 compatibility runtime reaches product API | rejected; it cannot replace `AvailableFederatedV2` |
| provider final-use guard rejects | physical HTTP dispatch must remain uncalled; the hosted workflow executes the existing Core regression on exact and synthetic-merge trees |

## Remaining qualification gates

The final metadata head must pass both jobs in `.github/workflows/memory-federation-v2-final-verify.yml`:

1. exact-head locked tests, product composition checks, physical-send regression and strict no-deps lint;
2. deterministic synthetic merge against the current `main` resolved at execution time, running the same suite.

Even after those repository-controlled checks pass, `productionImplementation`, `productExecutionProved`, independent acceptance, activation and release remain false until the governing claim policy and external gates explicitly permit promotion. Authenticated cross-host work remains a separate profile, not an implied extension of this local result.
