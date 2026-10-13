# Hepta Stem + Matrix SDK 0.19.1 / Safe YAML combined qualification

**Draft-only, shadow-only, no model selection or release authority.**

This branch deliberately composes the existing [signed Stem Worker PR
#1517](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1517)
and [P0 CI recovery PR
#1728](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1728)
with the *complete dependency-bearing source subgraph* previously reviewed
in `integration/matrix-safe-yaml-reviewed-20261013`, pinned to Git SHA
`93b94440b28f0779e2dfa75df01d9cf47c1800db`.

## Proven separately, NOT yet proved in combination

At the reviewed Matrix/YAML SHA the following **actual** GitHub CI jobs
concluded successfully:

- [Matrix SDK compatibility workflow
  38334384670](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38334384670):
  crypto migration, Synapse send/sync, full `cargo-deny` without advisory
  ignores, and strict Matrix owner checks.
- [Safe YAML RustSec
  38334384638](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38334384638):
  locked resolver, real consumer tests and Bazel source proposal.
- [Global CI 38334384936](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38334384936):
  `cargo-deny` and repo-checks passed but **entire CI failed** in
  platform-specific Bazel jobs.

A preexisting green **security** run cannot qualify the Hepta Stem/Worker
combination at this different Git SHA. The combined source must undergo
fresh `cargo --locked`, full advisory, Bazel, Rust fmt, CI, and later the
genuine product/target-machine checks.

## Intentionally selected source, no forced merge

The reviewed security branch is built from a different root tree and
contains many concurrent changes to unrelated application runtimes. Blind
`merge` or replacing its whole root would overwrite newer Stem/Worker
code. We therefore **cherry-picked exact reviewed Git blob and subtree
object IDs**, without modifying unrelated product runtime code:

- exact `codex-rs/Cargo.toml`, `Cargo.lock`, and `rust-toolchain.toml`;
- exact Bzlmod `MODULE.bazel`, `MODULE.bazel.lock` dependency graph;
- the entire actual `hepta-matrix-sdk`, `hepta-matrixd`,
  `hepta-matrix-store` trees, including real Matrix crypto/transport/store
  compatibility fixtures, copied as complete immutable Git trees;
- complete reviewed `third_party/matrix-sdk-0.19.1`,
  `third_party/sqlx-sqlite-0.9.0`, and
  `third_party/starlark-0.14.2` patch trees;
- reviewed safe-YAML command parser and adversarial tests;
- matching `skills` and `cli` manifests plus original safe-YAML and
  Matrix qualification workflows;
- all Stem, Head, signed Final-use, Neuron native Worker, independent NDU
  and no-change route remains inherited from #1728; neither the security
  source nor this shadow composition changes production active weights.

Rust 1.96.0 is intentionally used for this combined trial, matching the
reviewed SDK's actual toolchain and the copied lockfile. The stacked Neuron
owner CI is also tested with this same version, rather than asserting that
the Rust 1.95.0 results automatically carry over.

The workspace has the same 187 members and 330 dependency keys in both
source variants. The reviewed dependency graph updates SQLite/SQLx, Matrix
SDK to exactly 0.19.1, the cryptographic backend and the `serde_yaml` API
alias to `serde-saphyr` 1.3.0. It cannot be replicated by replacing only
`matrix-sdk-crypto` or editing `deny.toml`.

## Mandatory strict new-git-sha gates

Workflow `hepta-stem-matrix-security-convergence.yml` must verify:

1. Full exact-source Git SHA and clean tracked files.
2. `cargo +1.96.0 metadata --locked` and complete workspace `cargo fmt`.
3. Whole locked `cargo-deny`, with **no** ignored RUSTSEC IDs.
4. Actual `codex-hepta-matrix-sdk`, `codex-hepta-matrixd`,
   `codex-core-plugins`, `codex-skills`,
   `codex-external-agent-migration`, `codex-hepta-infer-core` and
   signed `codex-hepta-infer-worker-host` native tests.
5. Strict native Clippy for these independent owners.
6. Original Matrix crypto migration, Matrix Synapse / encrypted reopen,
   safe-YAML, Stem Worker, Neuron Stem and full Blocking CI all succeed
   on exactly the eventual merged SHA.
7. Actual Windows Bazel shards, macOS release, generator output and all
   cross-platform tests succeed. The previously identified `git_process`,
   supervisor, ledger and provider-stream failures remain blocking.

**No green result is presumed.** The archive of independent prior success
only proves this subgraph has passed in isolation; compatibility with
the newer Stem/Worker source must be established with genuine exact-head
retesting. If lockfile or crypto compilation differs, hold all production
routing unchanged and resolve conflicts in the independent test branch.

## Still not authorized

No Jina pretrained weights have been verified or executed for real
future-window learning in this branch, and no claim of 4096 actually ticked
Cell throughput, signed production Artifact CAS load, actual independent
Final-use authority/clock/frontier, NDU positive causal benefit, or
unclean crash-recovery receipts exists. All remain mandatory separate
production gates. There is no private signing key in this code change.
