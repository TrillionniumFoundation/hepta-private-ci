# CLI crate entrypoint compiler fix

## Actual failures

The original dependency union at `0b9da54535a7795b2433947a479e6d9e71525e0a`
fails to compile the `codex` binary with Rust 1.96: the compiler's query depth
reaches 130, above the default 128. The original SDK, Linux release, Linux Clippy
and macOS Clippy job diagnostics are preserved in `ORIGINAL_FAILURES.json`, with
the byte length and SHA-256 of each complete decoded log.

Draft [#4738](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4738)
at `e5891fffb795531f0a8887a786eeaa55995a3065` adds the compiler recursion limit
to `main.rs`. Its original SDK job `126191609776` succeeds, but the original
Linux Clippy and release jobs `126191611382` and `126191611720` fail with
`an inner attribute is not permitted in this context`: `hepta.rs` includes
`main.rs`, so the inner crate attribute is expanded inside another source file.
These are separate failures; the SDK success does not qualify the Hepta binary.

## Source change

This successor starts at that exact `e5891ff` commit. Both real crate roots,
`main.rs` and `hepta.rs`, now declare `#![recursion_limit = "256"]` and include
`main_shared.rs`. The shared body is the original 176,978-byte `main.rs` from
`0b9da54`, byte for byte (Git blob `1bd3eb0bfb183f6a436ba56220906f91b49f0679`).
The relocation is mechanical: the original CLI body, tests, assertions and
runtime limits are unchanged. Compiler diagnostics for that body will name
`main_shared.rs`.

The three sources remain in the same directory. Cargo's explicit binary paths,
the original Bazel crate roots, the existing `src/**/*.rs` source glob, all
manifests and both dependency locks are unchanged. The shared source is included
by that existing glob. This compiler setting does not change any runtime
recursion or resource budget.

## Local evidence and limits

`SOURCE.json` binds the three source files and unchanged build inputs.
`INDEPENDENT_REVIEW.json` records an independent, read-only review of module
paths, source identity and Cargo/Bazel entrypoints. It did not run the CLI.

`placement_probe.py` runs a small Rust 1.96 compiler control. The previous nested
inner attribute is rejected with the original diagnostic. Both candidate root
layouts compile as binaries and as test crates, including a sibling module.
The five exact compiler invocations, generated inputs, compiler version/hash,
exit codes and original output hashes are in `placement/RECEIPT.json`.
This control only qualifies attribute placement and module resolution; it does
not compile the CLI dependency graph or execute CLI business tests.

To reproduce that control with an existing Rust 1.96 compiler:

```sh
python3 qualification/cli-crate-entrypoint-20261103/placement_probe.py \
  --rustc /absolute/path/to/rustc \
  --output /absolute/path/to/fresh-receipt-directory
```

The repository's `just fmt` and `git diff --check` also passed locally.
The complete original SDK, Linux Clippy/release and native CLI gates must still
run on this successor. No full CLI build was attempted in the local workspace
because its remaining disk could not hold that graph. This proposal remains
Draft/HOLD until the exact successor's original gates provide their own results;
the earlier query-depth failure, the include-placement failure and unrelated
joint dependency or platform failures remain separate evidence.
