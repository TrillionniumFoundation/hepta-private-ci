# Core Wine test execution placement

## Observed failure

The fixed source at `2bd2df402f8fd025ab9c78d77e29a8aef278867d` produced
three uncached remote TestRunner failures for shard 6 of 16 of
`//codex-rs/core:core-all-wine-exec-test`. Each complete archived attempt
reported 89 passed cases and one failure in the existing multi-exec-server
workspace-write isolation test. Its first output assertion expected
`cross-write-denied`; the tool output instead contained a bubblewrap
user-namespace permission error.

This fixture starts two native host exec-server children even when its
integration test binary runs behind the Wine test wrapper. The Core BUILD
already requests local execution for its native outer launcher, but the
separate Wine launcher had no such placement tag.

## Change

Set the existing `wine_test_launcher_tags` entry for
`core-all-wine-exec-test` to `no-remote-exec`. The unchanged macro consumes
this map only in the Wine outer `workspace_root_test` rule. Rust compilation
helpers, the native launcher, the Windows cross wrapper, and other Wine
targets retain their original configuration. The app-server already uses
this same separate launcher mechanism.

The original Rust sources, isolation assertions, 30-second case deadlines,
16 shards, long 900-second test timeout, and existing flaky-attempt policy
are unchanged. The change adds no timeout, retry, permission, dependency,
host setting, or manual test invocation. Remote cache eligibility remains.

## Evidence and qualification limit

The original compact execution records distinguish the three remote,
uncached TestRunner failures from their separate XML-generation actions.
The three complete logs are associated through their archive paths,
source-path records, target, and shard; the compact outputs do not provide
the test-log content digest.

The later `f902c2fac20ee3e0526f4ff21686f98d1d070406` run reports all
16 Core Wine shards through remote cache hits. Its matching shard also
has a different action digest from the three failures. These cached results
do not establish a fresh local execution or resolve the observed placement
failure. The shared macro and its prior recorded rule comparison support
the narrow source change; this candidate does not claim a new generated
rule query or a native test pass.

Normal CI must establish the resulting execution placement and behavior.
The tag alone does not prove that every local runner requirement is met.
