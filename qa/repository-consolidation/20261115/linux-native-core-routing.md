# Linux core integration tests require the native kernel

The Linux GNU Bazel job `132877426547` for published commit `8576cdb3`
failed the core integration target. Its final failed shard includes the
two-environment workspace isolation test, the read-only approval case and the
secondary workspace root test. The isolation test reports that Bubblewrap
cannot create a user namespace in the generic remote execution container.
The same job successfully runs the existing dedicated Linux sandbox targets
on the native runner kernel.

The complete `core-all-test` target now uses that existing required native
Linux test step. The generic remote test invocation excludes this target only
because the following native step runs the complete target with
`TestRunner=linux-sandbox` and uncached results. Compilation remains remote.
The test executable, shards, assertions and failure status are unchanged; no
sandbox environment switch or test skip is added. Other host routes remain
unchanged. The wrapper's existing route-preservation test includes the added
target in both corresponding lists.

The same failed job also recorded one communication-log capture timeout which
passed on its retry. This routing change does not claim to fix that separate
issue. The new native core route still requires an actual hosted CI result.
