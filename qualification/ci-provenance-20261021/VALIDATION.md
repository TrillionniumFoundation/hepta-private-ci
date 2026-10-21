# CI provenance and Memory test-fixture repairs

Observed 2026-10-21 UTC. Parent: `603238ba4721b2e9656c4647ce41c5f1664c1154`
(#2944, `codex/hepta-blocker-convergence-20261020`).

## Problems reproduced

1. `scripts/hepta_ci_exec.py` resolved Git replacement refs when collecting
   source identity and recomputing merge trees. A real replacement commit could
   change tested bytes or parents while the receipt named the original SHA.
   The executor now uses `git --no-replace-objects` for every identity operation.
   Three rejection cases and one original-checkout success case exercise real
   repositories, replacement refs, worktree bytes, receipts and dispatch markers.
2. Blocking CI run `39496724981`, macOS Clippy job `118912226488`, rejected the
   schema test's direct SQLite connection. The test now keeps a temporary
   directory alive around the canonical durable-evidence SQLite shim. It still
   derives the independent schema from the compiled migration chain and rejects
   the deliberately weakened trigger.
3. The same job rejected `expect` in Unix-only Final-use fixture helpers.
   With Rust/Clippy 1.95.0, `#[cfg(all(test, unix))]` did not receive the existing
   `allow-expect-in-tests` treatment. Separate `#[cfg(test)]` and `#[cfg(unix)]`
   retain exactly the same compilation condition and let Clippy recognize the
   test module. No lint level or test coverage is reduced.

## Executed verification

- Before the executor change: all four new regression cases failed against the
  exact parent executor. After it: all 49 executor, deadline and output tests
  passed, with zero skips, in the combined local run.
- Independent review reran the 19-test executor module successfully. This is a
  subset of the 49 tests, not 19 additional distinct tests.
- An actual Clippy 1.95.0 compilation with `-D clippy::expect_used` rejected a
  minimal helper under the combined cfg and accepted the same helper under the
  separate cfg attributes. The accepted binary executed its one test. This
  demonstrates the lint cause, not full package or macOS qualification.
- `just fmt`, scoped Ruff checks, and `git diff --check` passed.
- Independent source review checked the SQLite shim signature, existing
  dependencies, directory lifetime, preserved migration/trigger assertions,
  compilation-condition equivalence, and the Git replacement-ref boundaries.

## Remaining gates

The full `codex-hepta-memory` Rust package, Windows/macOS native jobs, and the
new commit's required GitHub checks remain pending. The local host has limited
free disk and is not identified as the user's dedicated cloud runner. No
historical result, metadata-only success, skipped job or local micro-test is
treated as current-head required-CI success. Other #2944 Windows failures and
the separate #2937 upstream V8 download failure remain open.

Research authority remains `SHADOW_ONLY / DENY_ALL`; these repairs do not
activate production routing, alter runtime permissions, or change branch
protection.
