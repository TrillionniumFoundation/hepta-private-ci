# Clock fixture lifetime repair

The first actual focused Rust gate compiled successfully and reported 9 passing
and 6 failing tests, with retries disabled. Its retained log is
`../backend_effect_clock_stage/actual-focused-v1.log`, SHA-256
`7ca6cd12071a4ae874859eba32e006df25dc51af86eee0312203868765262cc2`.

## Source cause

Every failing case uses `spawn_dispatch`. Its `async move` closure refers only
to `Security.authority`, `Security.signed` and `Security.clock`. Under disjoint
field capture, `Security._directory` remains outside the task and its `TempDir`
is dropped when the spawning helper returns. The original authority's durable
files are consequently removed before the test releases its dispatch barrier.

The original `FinalUseAuthority::claim` samples its clock once, then calls
`Store::append_claim`. That method opens `authority.claims` relative to the
original directory descriptor on every nonce append. Directory cleanup removes
that entry; the append fails, the authority marks its state failed and returns
`FinalUseError::Unavailable` before the second clock sample or driver entry.
This matches the observed early-return, missing-barrier and zero-contact failures.
The successful actual-file cases construct the task in their caller's scope,
where the uncaptured directory remains alive until the test ends.

The precise-capture cause and original authority persistence path were reviewed
independently by `/root/runtime_source_audit`. This is a source diagnosis, not a
claim that the repair has already passed its actual Rust gate.

## Narrow repair

The task now moves the complete `Security` value into an explicit local before
borrowing any field. A statement-local Clippy allowance explains why the rebind
is required. Synthetic fixture errors are printed on early return so any future
boundary timeout has its underlying owner error in the failure log.

The new regression exercises both sync and async registered-driver paths. It
checks that the original `authority.claims` file exists while the spawned task
is paused, then requires successful original-owner dispatch, one real file
effect, exactly one consumed nonce and an Indeterminate observation. It checks
that the fixture directory is released after task completion. It does not mint
a production grant or bypass the original owner.

Only three existing test files change. Production files, clock sample order,
barriers, grants, TTLs and timeouts are unchanged. The original frozen installer
remains intact; this is a separate overlay guarded by exact installed test-file
preimages. `FREEZE.json` records those preimages, postimages and installer hash.

## Validation status

Five local Python installer tests passed: dry-run preservation, exact test-only
application with unrelated-file preservation, reapply rejection, changed final
preimage rejection before all writes, symlink protection and stale temporary
file protection (application/reapply share one test). The actual local command
was `python3 backend_effect_clock_fixture_fix_stage/test_installer.py`; it exited
0 after 5 tests in 0.848 seconds. No Rust toolchain or remote tools were used in
this local repair stage.

The required actual gate is:

```text
just test -p codex-hepta-automation effect_clock --retries 0
```

It should enumerate 16 focused tests, including the new fixture lifetime
regression. Only its actual result can establish that the repair resolves the
observed failures. Preserve the first failed gate alongside the new result.
