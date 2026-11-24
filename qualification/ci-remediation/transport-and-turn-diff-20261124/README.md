# Transport and turn-diff regression repairs

Baseline: `304aad85f2803c49daafa84dad1f3f6d18b701dd` on the dependency remediation branch.
Failure source: the normal GNU CI run `45104012523`, original head
`07c8994f2402a58f6b59eb648c801fc40c6e2b96`.
The recovered GNU job log has 14,029,539 bytes and SHA-256
`5a3b134bdc475713a8975dd4f8d47d81ba8f158b793fdd93bcfc8f952f0ff955`.
Retry attempts in that log are repeated observations, not independent test cases.

## Current working directory diff paths

`turn_diff_display_roots` searched for `.git` unconditionally after the environment
snapshot refactor. `CwdRelativeTurnDiffs` remained in configuration and behavioral
tests but had no production reader. The repair reads the exact step's turn
configuration and chooses each selected environment's own current directory when
enabled. Repository-root discovery remains the disabled-feature behavior.

The existing `apply_patch_turn_diff_skips_git_root_when_feature_is_enabled` integration
test exercises seven originator/feature combinations through actual patch requests.
Its expected paths and the separate repository-relative path checks are retained.

## WebSocket prewarm reuse

Connection identity used the recoverable-request compatibility projection directly.
That projection intentionally distinguishes `prewarm` from `turn`, so an otherwise
identical turn discarded the warmed connection and attempted a second handshake.
The recorded failing prewarm test received and completed the first request, then
timed out before a follow-up request reached that connection.

Socket identity now uses a separately tagged projection. Only the prewarm request
purpose is normalized to the turn's existing representation. Provider URL, query
parameters, configured headers, beta features, sandbox, workspace, tool metadata,
and other stable behavior fields retain their prior binding. Recoverable-request
fingerprints use the original projection unchanged.

The identity unit test now checks prewarm/turn reuse, distinct recovery projections,
and a distinct Memory purpose, alongside the existing provider/sandbox/beta changes.
The existing real-socket client prewarm, agent WebSocket, and managed-residency
integration tests remain the behavioral gates; their assertions are not relaxed.

## Executor MCP publication

The initial installation and ordinary refresh paths published their base projection
without calling the existing executor-local MCP configuration projector. Read-side
configuration inspection and the special Apps refresh did call it. Consequently an
initial thread without selected plugin roots could advertise no executor browser
tool even when that executor configured it as required.

The shared publication boundary now projects the selected executors' configuration
from the same desired session source, configuration, and environment snapshot before
building the runtime input. This reuses all existing requirement, environment
authority, unsupported-header, legacy-capability, and Guardian filtering. The runtime
is still published before required-server startup validation so elicitation can run.

The `executor_mcp` integration suite retains the authenticated first-request discovery,
legacy-executor behavior, Guardian isolation, executor selection, and policy rejection
checks. The discovery fixture's deliberate two-second startup delay and ten-second
server timeout remain intact.

## Validation boundary

Actual Rust 1.96 `just fmt` and `git diff --check` pass for this source change. No
dependency manifest or lockfile changed. Core/app-server behavioral tests and Clippy
must pass on the published combined head in normal CI. A previous local core test
build was terminated by SIGKILL before executing tests; that is not a test pass and
does not qualify these repairs. Source inspection is not a substitute for those
native executions.
