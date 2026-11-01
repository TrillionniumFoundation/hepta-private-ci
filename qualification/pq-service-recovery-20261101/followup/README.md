# PQ test-fixture CI follow-up — 2026-11-01

This follow-up is based on published commit
`7ff91a4368bc110c35da789b16916e046f79b42c`. It changes two test files and adds
failure/verification evidence. Production authorization, durable owner logic,
dependencies, resource budgets, CI gates and lint policy remain unchanged.
**The complete hosted CI and whole-chain PQ qualification have not passed.**

## Two concrete test fixes

The new FinalUse `sign_grant` helper used two `unwrap` calls outside a test
function. The hosted Linux Bazel Clippy job correctly rejected them. The helper
now returns `Result` and propagates both real errors with `?`. The existing test
still fails if signing fails; its four call sites remain inside `#[test]`, under
the repository's existing `allow-unwrap-in-tests` rule. No lint is suppressed.

The PQ exact-replay proof test read ledger/witness files using a second handle
while its writer still held exclusive ownership. Windows reported OS error 33.
The test now drops that writer before each raw-file read and recovers it from the
actual successful receipt's acknowledged anchor, with the same PQ profile,
trust, binding, external frontier and one-record limit. All four malformed or
classical proof cases still require invalid-signature rejection, zero port calls,
unchanged records and unchanged bytes after each case. The last case still
advances the external frontier **after** reopening the live writer and requires
that writer to refuse the stale authority. No production lock is released or
test-only bypass introduced.

## New local verification

| Check | Result and scope |
| --- | --- |
| `just test --locked -p codex-hepta-contracts -p codex-hepta-intelligence --lib` | **269 passed, 0 failed, 0 skipped** on Linux: Contracts 187, Intelligence 82. Both complete selected library targets ran. |
| `just clippy --locked -p codex-hepta-contracts -p codex-hepta-intelligence -- -D warnings` | **FAILED, exit 101**. The new helper has no remaining diagnostic; 38 other diagnostics remain. This is not a passing strict lint qualification. |
| `just fmt --base 7ff91a4368bc110c35da789b16916e046f79b42c` | Exit 0; neither tested source file changed. |
| Windows execution of the new lifecycle | Not run locally. The later Windows CI result must be observed independently. |

The [manifest](manifest.json) contains all 269 distinct test names, the exact two
source hashes, executable hashes, fixed tool versions, command receipts and
lossless compressed output. The 269-test run overlaps earlier Contracts results;
it is not added to prior phase totals. The pinned nextest emitted its existing
local-profile and scoped-metadata warnings, which remain in the raw log. No JUnit
file was emitted for that local profile, so none is reconstructed or claimed.

The remaining strict diagnostics are 28 `unwrap` diagnostics in
`authority_trust_unix_tests.rs`, eight in `final_use_pq_tests.rs`, and two
`cloned_ref_to_slice_refs` diagnostics in `final_use_control.rs`. Exact source comparison
against baseline `a575cf03e2bc871a2f48021859c03ace806421c8` confirms those lines
predate this change: the first and third files are unchanged, and the second
differs only by the three-line declaration of the new recovery-test module.
That source comparison does not invent a baseline execution of this strict
command. The actual failed command and every diagnostic are retained.
Intelligence checking was started, but completion of all its selected test
targets is not established by the failed command. The 38 count emitted errors;
they are not an exhaustive lint inventory of both packages.

## Hosted CI remains separate

The [CI triage record](ci/README.md) and [machine-readable snapshot](ci/triage.json)
cover the earlier published `7ff91…` source and its actual prospective-merge tree.
They retain failed jobs, successful jobs, skipped jobs and unfinished jobs, with
exact job URLs and baseline comparison evidence. They do not describe this
two-file follow-up as already passing hosted CI.

The native pair campaign used Chain
`131f673d9563e72aca7139f3239856957d118d49`, not the interrupted unpublished Chain
candidate. Its retained ARM source-head artifact reports **CONFIRMATION_TARGET**
failure under the original four-second window: the attack-free control confirmed
one transaction, while the pressure phase confirmed none and did not satisfy its
complete-state/finite-business target. Five named Rust tests passed in that job;
they do not override the failed overall campaign. Neither this follow-up nor its
269 local tests changes that result.

Other dependency-audit, caller-contract, release-build, native-link and executor
resource failures remain recorded with their actual attribution limits. No
allowlist, deadline, workload, retry count or security assertion is relaxed to
obtain a passing status. The original complete product/Chain pairing, migration,
independent rollback anchor, WAN and whole-system acceptance remain open.
