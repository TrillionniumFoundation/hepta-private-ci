# Agentd fixture paths and recovery qualification selection

## Observed blockers

At exact source `793c2053c8921df479ebded068b5ce31f59d31fe`, Agentd process
run 37082235877 source Linux job 111085060522 passed 500 owner/library tests,
10 retirement/shutdown tests and seven automation process tests. Its next
`destination_recovery_binding` memory selector selected zero tests and failed;
later plasticity, real daemon and strict owner-lint steps did not execute.

The same run's source macOS job 111085060535 passed 476 and failed 23 library
tests. Three HNMF tests explicitly rejected noncanonical cognitive roots; one
run-start test rejected a noncanonical external replay-checkpoint parent.
Nineteen supervisor release-install tests reported Registry PermissionDenied;
their root cause remains unverified. This change does not claim to fix them.

## Bounded repairs

The HNMF fixture now canonicalizes its newly created fleet directory before
constructing the owner layout. The replay fixture canonicalizes its existing
temporary parent before naming the new checkpoint file. These use the same
physical paths already required by production checks, including on Darwin where
`/tmp` is an alias. No production validation, permissions or trust input changes.

The nonexistent memory selector is replaced by two separately executed groups:

- `test(production_writer::)`: bound lease reopen/replay, changed-grant rejection,
  crash-after-send remaining indeterminate without redispatch, unresolved peer
  obligations, and final-use destination mismatch preventing target entry.
- `test(production_cognitive_source_target::tests::)`: exact destination dedupe,
  predecessor mismatch producing deterministic NotApplied, and real SQLite
  destination lost-ACK reconciliation without redispatch.

Both commands retain locked dependencies, the repository just/nextest entrypoint,
serial test execution and nextest's fatal zero-test behavior. Neither is wrapped
in a success override. Later owner/plasticity/daemon/lint gates and final fan-in
remain unchanged. The selector inventory regression names the eight required
contract tests and executes the real workflow shell with a bounded fake runner;
each absent selected group fails the step. This is wiring validation, not a Rust
qualification receipt. The old selector named no test at this source, so no
previous executable recovery contract is being removed or relabeled.

These groups do not establish whole-process power-loss recovery, hosted writer
bootstrap, cross-process generation transfer or production trust installation.
In particular, the separate cognitive_store_product_writer exact-cut case on
context source 8b9f4b7b has its own asynchronous-close investigation. That result
is not replaced by either of these library groups.

## Executed local validation and pending qualification

The actual workflow-shell regression failed against the old selector (zero-test
exit 4), then passed after the repair. The recovery scope, Agentd terminal-gate
and exact-candidate planner suites passed 25 tests. Scoped Ruff checks/formatting,
changed-file Rust formatting and diff whitespace checks passed. No local Rust
build or test was attempted, and no shared build cache was restored. Formatting
was limited to owned files so paused paths could not be modified.

Actual repaired Linux/macOS execution remains pending the existing hosted
workflow. This change does not establish aggregate CI, product qualification,
independent acceptance, activation or release. Historical source anchors and
unrelated ancestry failures are not repaired by this fixture/selector change.
