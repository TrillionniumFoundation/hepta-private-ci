# Exact-head CI API diagnosis

At `94252595fa741ed331b9946d7a910b28c96e44cf`, the method exists at
`codex-rs/hepta-learning-ledger/src/durable.rs:210`, guarded by the feature
`qualification-legacy-write` at line 208. The raw production append is
crate-private. Agentd's Cargo dev-dependency enables that feature, while its
Bazel unit-test map selects the qualification ledger only for unit tests.

The root `defs.bzl` integration rules at lines 575, 615 and 690 bypass that
replacement helper and link the ordinary host library. This establishes the
source-level feature-profile mismatch behind the reported E0599. It does not
establish a hosted repair.

A separate candidate is prepared under
`tools/hcsn/ci_qualification_profile_r22_20261102/`, with exact baselines,
verified primary-source evidence, candidate copies, patch and static checks.
It introduces a private test-only host dependency graph and leaves production
library/binary calls unchanged. No repository source or research evidence was
modified. Hosted integration execution, transitive crate identity and release
sweep remain required; no CI-green claim is made.
