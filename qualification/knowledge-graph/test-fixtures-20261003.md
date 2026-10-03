# Memory test fixture lint follow-up

Exact head `8e1a542217305510851e33e648ceddcb04ad645f`, tree
`0c16f6b28bee647212ee348862d6552c265b6da5`, now passes both source and
merge qualification-writer profiles (9/9), including the repaired physical
remember/restart/correct/forget E2E. Both retain six SQL regressions, 35 KG,
55 registry, 51 optimizer, 278 Memory, crash/reopen (1) and default product (9)
passes. The current source full-capacity workload passes 256 writes, 20 queries
and five reopens in 610.870 seconds. This remains runner-specific measurement.

Run `37120419841` source artifact `11273975304` has ZIP SHA-256
`a6233e7bd0173dc9dde5728cd2ef3199195f04803d8270d5ae3ce9ce68c4d498`;
merge artifact `11273630741` has ZIP SHA-256
`72c36dc1add550b6f22c41b729bac36c088c65e40ee519c8a968d17727d9a74d`.
All 25 source and 23 merge checksum entries, exact command identities, log byte
lengths/hashes and terminal test counts were verified. The recomputed merge tree
matches source; merge `80dabdd0747c6212bc3ac5c3eff1bb4533e51ef3` retains ordered
base `ad0ff102422a64f947763156ca68935f218010c4` and source `8e1a5422...`.

Only strict lint fails. The two production private-argument findings are gone.
The next 17 diagnostics are in test setup: one raw in-memory SQLite connection
in `cognitive_schema_tests.rs`, plus 16 `expect` calls in non-test helper
functions inside `production_writer.rs::final_use_dispatch_tests`.

The schema oracle now opens an isolated file-backed temporary database through
the existing `SqliteConfig::new_for_testing` shim. Compiled migrations, complete
schema inventory, owner verification, weakened-trigger rejection and close are
unchanged. The paused state shim is not edited. The signed-dispatch fixture
helpers propagate typed `Result` values to assertions at their actual test call
sites. No assertion, grant, nonce, clock computation or protocol call is removed;
the production writer bytes preceding the test module are exactly unchanged.

Existing tests still exercise complete schema/tamper behavior and the three
signed dispatch/binding mismatch, idempotent dispatch claim and queued owner
handoff cases. Scoped formatting, parsing and exact source-boundary comparison
pass locally; no heavy local build was run. New-source native behavior/lint
results remain pending. No lint allowance, production authority, host trust,
sourceBase, SQL migration or positive acceptance flag is introduced.
