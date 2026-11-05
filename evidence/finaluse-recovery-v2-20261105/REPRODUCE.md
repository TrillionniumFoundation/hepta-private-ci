# Provider-effect recovery frontier V2 verification

The baseline is `5cb4ee7b63dc91e3c3023f0687f0ea7d2b0a8497` in
`TrillionniumFoundation/hepta-private-ci`, existing Draft PR #4729. The candidate
changes the evidence recovery snapshot and its signed wire record to V2.
`manifest.json` records actual results, source hashes, toolchain and remaining
gates. A build interruption is not a passed or executed test.

## Recorded outcome on 2026-11-05

The complete source and all eight new test cases are preserved in
`ff280f268f4f2d2287109b7af7f8c22ba790df6c`
(tree `7f26786ed3dc94f4d47d2c1a46b686b9f616295b`).
Native qualification remains incomplete: **no native test execution was
observed, and RED/GREEN has not been established**. Four test commands were
attempted; the fifth native command was scoped `just fix`.

| Observed command attempt | Result | Exit |
| --- | --- | --- |
| Initial candidate evidence suite | Interrupted during dependency compilation | 130 |
| Single-job candidate evidence suite | `RUNNER_LOST`; no observed completion | unknown |
| First old-source regression command | Duplicate `--no-fail-fast` rejected before execution | 2 |
| Corrected old-source regression command | Dependency compilation failed with `ENOSPC` | 101 |
| Scoped `just fix` for evidence and Agentd | Dependency metadata write failed with `ENOSPC` | 101 |

The shared overlay reported 63 GB used of 63 GB and zero available space.
Reclaiming this task's completed build caches did not restore available space;
other sessions' files were left alone. The final candidate owner suite,
signature-verifier units and Agentd product tests are
`NOT_RUN_UNAVAILABLE_STORAGE`. A separate AF_UNIX capability probe returned
`EPERM`; it is not an executed Agentd product test or a substitute for one.

After the final Clippy failure, the nine changed Rust files passed a read-only
Rust 1.96 `rustfmt --check`. All 13 frozen source/document SHA-256 values still
matched. An independent index, refreshed from the published tree, showed no
tracked differences across 11,253 entries. The original index and source were
unchanged. These integrity and formatting checks do not establish a successful
compile or test run. The final full `just fmt` was not run because rewriting
source on the full filesystem was unsafe.

The original lane-A `verify` and `self-test` gates both remain failed. The
initial module-order mismatch also existed in the original HEAD. Correcting
only the existing row order preserved all seven module rows, 42 capability
rows and qualification states; the next unchanged `platform.types` contract
check still failed. The gate was not weakened and those unrelated source
anchors were not rewritten to obtain a green result.

The manifest records the actual versions, exit states, source hashes and log
digests. Raw logs and binaries are not packaged by this evidence commit.
Historical PR test counts do not qualify V2, and no hosted CI result is claimed.

## Scope

The signed recovery input now commits the `hepta-evidence` facade's intent,
uncertainty and ACK history, including ACK provenance and cross-table ordering.
The same SQLite snapshot rechecks actual JSON bytes against their record
digests. It does not require canonical JSON reserialization. The snapshot
scan limit is not an overall startup-memory bound: the existing cold-open
`verify_provider_effect_rows` still uses `fetch_all` and validates types/column
projections separately. This does not compose the AutomationStore runtime owner with
FinalUse consumption or a budget owner. It supplies neither a fresh remote
witness nor an exactly-once guarantee for arbitrary external effects.

V1 recovery files are refused. An authorized checkpoint publisher must review
and sign a new V2 checkpoint; recovering local data does not authorize an
automatic upgrade. The existing trust-file schema remains V1, and its key is
still Ed25519. A file outside Agent home alone does not establish an independent
failure domain.

## Candidate owner tests

Use the repository's pinned Rust toolchain and `just test` entry point. Limit
build concurrency when sharing an 8 GB container with other builds:

```bash
cd codex-rs
CARGO_BUILD_JOBS=1 just test -p codex-hepta-evidence --locked
```

The five authored owner tests are intended to exercise:

1. Intent, unknown result and reconciliation with the original operation ID.
2. A structurally valid old database image that loses only effect records.
3. ACK provenance and timestamp changes without changing its record digest.
4. The effect row after the first 256-row page.
5. Replaced JSON with retained record digests, for all three effect tables.

Existing evidence tests are retained, including cold-open row validation and
the original provider-effect transition cases.

## Old-source RED without modifying the candidate

Run from the candidate repository root. Only the new test module and its test
declaration are added to the detached baseline; production code stays at the
exact original commit. Sharing the target directory reuses dependency builds.
The expected failure must be a regression assertion, not a compile or fixture
failure. Preserve the nonzero command result and inspect every case.

```bash
candidate_root="$(git rev-parse --show-toplevel)"
baseline_root="$(mktemp -d)"
git worktree add --detach "$baseline_root" 5cb4ee7b63dc91e3c3023f0687f0ea7d2b0a8497
cp "$candidate_root/codex-rs/hepta-evidence/src/recovery_effect_frontier_tests.rs" \
   "$baseline_root/codex-rs/hepta-evidence/src/recovery_effect_frontier_tests.rs"
cat >> "$baseline_root/codex-rs/hepta-evidence/src/lib.rs" <<'RUST'

#[cfg(test)]
#[path = "recovery_effect_frontier_tests.rs"]
mod recovery_effect_frontier_tests;
RUST
(
    cd "$baseline_root/codex-rs"
    CARGO_BUILD_JOBS=1 CARGO_TARGET_DIR="$candidate_root/codex-rs/target" \
        just test -p codex-hepta-evidence --locked --lib --retries 0 \
        -E 'test(recovery_snapshot_)'
)
```

## Signed-file verifier and product integration

The authored verifier tests generate a real legacy V1 signature with the enrolled key
and require the actual verifier to refuse it. They also admit an unmodified V2
checkpoint and then independently modify each new effect field, requiring a
signature-verification rejection.

The product tests retain the original exact-current and old-qualification
database cases and add an effect-only rollback through Agentd startup.

```bash
cd codex-rs
CARGO_BUILD_JOBS=1 just test -p codex-hepta-agentd --locked --lib \
    --test kernel_evidence_product --retries 0 \
    -E 'test(recovery_frontier_)'
```

The repository wrapper already injects `--no-fail-fast`; passing it again is a
nextest argument error and does not execute tests.

Product fixtures need real process and socket support. A bind/permission error
before recovery admission is an environment-blocked product test, not recovery
coverage. The manifest keeps such outcomes separate from verifier unit results.

## Final source hygiene

On an executor where the native tests can finish, follow the repository instructions:

```bash
cd codex-rs
CARGO_BUILD_JOBS=1 just fix -p codex-hepta-evidence -p codex-hepta-agentd --locked
just fmt
```

Do not repeat tests solely after fix/format. Compare source hashes and record
any changes rather than claiming an unexecuted result for different source.

The read-only scoped format check used after the failed final Clippy command
is equivalent to the following from `codex-rs`; this does not replace the full
`just fmt` gate:

```bash
rustfmt --edition 2024 --config imports_granularity=Item,skip_children=true \
    --config-path rustfmt.toml --check -- \
    hepta-evidence/src/lib.rs \
    hepta-evidence/src/recovery_frontier.rs \
    hepta-evidence/src/recovery_effect_frontier.rs \
    hepta-evidence/src/recovery_effect_frontier_tests.rs \
    hepta-evidence/src/provider_effect_store.rs \
    hepta-agentd/src/lib.rs \
    hepta-agentd/src/evidence_frontier.rs \
    hepta-agentd/src/evidence_frontier_tests.rs \
    hepta-agentd/tests/kernel_evidence_product.rs
```
