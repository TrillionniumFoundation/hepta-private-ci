# Current-main integration follow-up

This increment integrates main `c6f90d48c40f7b5267db587bb3c3f4934f1414a8`
into the existing platform.types audit branch. It preserves public DTO,
serialization and rejection boundaries and does not promote qualification or
acceptance claims. Source identity is the actual candidate commit, rather than
a self-referential value embedded in this document.

## Operation-owner integration regression

The generic durable evidence profile has a five-connection bound. Selecting it
while resolving the current-main conflict accidentally changed the original
operation and destination owners' four-connection bound. Two regressions invoke
the real `DurableOperationStore::open` and
`DestinationDedupeStore::open_standalone` constructors. On this branch with its
pinned Rust 1.96 toolchain, both compiled and failed with actual `5 != 4` before
the correction; both passed afterward.

The fix adds an explicit central operation-owner profile and retains the
canonical-parent path adapter. The existing generic evidence profile, including
its five-connection limit, is unchanged. The regression checks WAL, FULL
synchronous mode, foreign keys and a 5000 ms busy timeout on four simultaneous
leases, and verifies that no fifth lease can be acquired.

After removal of the production adapter's absolute-path wrapper, the existing
workspace dependency remains only in the destination recovery integration test.
It is therefore moved to dev-dependencies without changing its version or
Cargo.lock. Locked Cargo metadata confirms the sole dependency kind is `dev`.

## Bounded validation

The repair's local Operations suite passed 50 tests. One child-process helper
is excluded from direct nextest execution and is invoked by the passing parent
crash-recovery tests. All-target Clippy with `-D warnings`, scoped `just fix` and
`just fmt` passed under Rust 1.96. This is scoped source validation, not a complete
platform.types, prospective-merge or host-matrix qualification receipt.

An earlier platform test session has no recoverable completion result and is
not counted as passed. At that earlier Operations-only snapshot, platform.types/NDU
package tests had not yet run; their subsequent result is recorded below. Current-source
hosted qualification, Windows and Bazel lock validation remain separate
requirements. No result from the cognitive.types branch is transferred here.

## NDU post-step residual domain

The independent consumer run exposed a genuine merge mismatch: original audit
commit `cd233594120d03044c9eb87fe75b12cdf8782b58` deliberately defines the local
termination maximum over emitted post-step iteration receipts, while the main
branch's test included the pre-iteration residual. The algorithm retains the
original audit's post-step domain. The regression now independently distinguishes
initial residual 1 from the first damped residual 3/4, requires the termination
maximum to match the emitted-receipt maximum, and requires it to be below the
initial residual. This local solver result is not a learning.eval convergence
certificate. No algorithm, public field or serialized receipt changed here.

The first actual combined run executed 195 tests: 194 passed and this domain
mismatch failed. After the explicit test-domain repair and removal of four
unfulfilled test-only lint expectations, platform.types (96) and NDU (99) passed
all 195 tests with zero skips. All-target strict Clippy and scoped just fix passed
under Rust 1.96. Formatting changed no behavior. These results do not supply
missing hosted exact-head/prospective-merge or target-host acceptance evidence.
