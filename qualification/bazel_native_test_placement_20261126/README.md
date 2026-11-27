# Native placement for namespace integration tests

This candidate corrects test execution placement. It does not change a Rust
test, permission check, namespace configuration, runner, timeout, retry count,
shard count, or compilation target.

## Observed input

The source is `be271ddfa2a2d519a44112e4f176d2d8c3499c25`. The normal PR
checkout `9ee5f862b0e8a8a4d3fdd9d29c75b8cadb152e15` has the same complete tree.
GNU job `139664083803` contains three actual remote attempts of the app-server
integration shard with these two failures:

- `command_exec_permission_profile_does_not_reuse_default_network_proxy`
- `command_exec_permission_profile_project_roots_use_command_cwd`

All three complete logs report 54 passed and two failed. The child errors
explicitly report that bubblewrap cannot create the namespace. The execution
records distinguish these failing TestRunner spawns from their successful XML
report actions. They share action digest
`2f871786989c1e5f46ea7104471d2d667e2bdcbd954566ede27ebe6eb43419ad`.
The musl job `139664083857` subsequently executes this action remotely and
passes. These observations do not establish that every remote worker lacks
namespace support. Both jobs already prepare namespaces on the hosted Linux
runner before invoking Bazel.

The existing Core regular-expression rule also did not establish native
execution: the GNU job's 16 actual Core integration spawns remain remote;
the musl job uses cached results for those spawns.

## Bazel 9 contract and change

Bazel `9.0.0`, source commit
`93f38093f8e24875c1d015e67311853756bdb27e`, explicitly excludes `TestRunner`
from `strategy_regexp` matching in `SpawnStrategyRegistry.getStrategies`.
Matching the progress text therefore cannot select a test executor.

The generated native sharded wrappers for `core-all-test` and
`app-server-all-test` now carry `no-remote-exec`. The macro's new map defaults
to empty and is read only by those native integration launchers. Their manual
Rust compilation helpers do not receive the tag. Unit tests, unsharded tests,
Wine wrappers, and Windows cross wrappers retain their original definitions.
The operator wrapper already has this tag. The two ineffective regular
expression settings are removed.

Tags are not configurable attributes in Bazel, so the two native wrappers
carry this tag on every platform. The existing macOS and Windows execution
strategies are unchanged. On Linux, `BazelStrategyModule` retains the default
remote, worker, sandboxed, local strategy chain. `Spawns` rejects remote
execution for a tagged action, allowing the existing local strategy to handle
these tests. Their existing `no-sandbox` tag is unchanged. Remote compilation
and all original test assertions remain in place.

`no-remote-exec` does not prohibit remote cache reads or writes. A cached pass
must remain identified as cached; it is not evidence of fresh native execution.
New qualification must inspect the actual TestRunner execution records.

## Qualification boundary

This is a source candidate. No new Rust build or native test has run for this
change. Static formatting, target expansion, and source comparisons are
recorded separately; none substitutes for the next normal CI execution.
The original failures and later musl pass remain attached to their original
source and invocation identities.
