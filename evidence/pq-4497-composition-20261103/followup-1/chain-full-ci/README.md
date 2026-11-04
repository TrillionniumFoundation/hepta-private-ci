# Chain full regression evidence — HOLD

These are the original full Node-library and strict Clippy command results from
GitHub Actions run **41594378689**, attempt **1**. Retention did not rerun tests,
change thresholds, or change Chain source or references. The combined result
remains **HOLD**; this evidence does not grant whole-chain PQ qualification.

## Actual results

| Lane | Passed | Failed | Ignored | Full Node suite | Clippy |
| --- | ---: | ---: | ---: | --- | --- |
| x64 head | 895 | 0 | 22 | PASS | PASS |
| x64 prospective merge | 894 | 1 | 22 | HOLD | PASS |
| ARM64 head | 893 | 2 | 22 | HOLD | PASS |
| ARM64 prospective merge | 893 | 2 | 22 | HOLD | PASS |

Totals come from the unique terminal summary with zero filtered tests in each
log: 917 total cases. Nested child-process summaries with 916 filtered cases
remain in the original logs and are excluded from these totals. Exact summaries,
failure excerpts and source identities are in [review.json](review.json).

The full-suite x64 prospective-merge failure is
`pq_rollback_witness::tests::cancellation_after_signing_before_send_preserves_same_client`.
It reports `PQ_WITNESS_DEADLINE` at
`crates/trnm-pon-node/src/pq_rollback_witness/tests.rs:98:35`.
This is distinct from the earlier 43-control stage failure,
`store::pq_rollback_witness::tests::committed_expiry_retirement_publishes_epoch_even_when_live_callback_refuses`.
The two stages and their different failed cases must remain separate.

Both ARM64 lanes fail these cases with `PUBLIC_MUTATION_CPU_BUDGET` at
`crates/trnm-pon-node/src/store/detached_admission/tests.rs:724:31`:

- `store::detached_admission::tests::admitted_custom_genesis_over_eight_mib_keeps_original_held_schedule_and_cpu_owner`
- `store::detached_admission::tests::authenticated_large_parent_original_schedule_supplementary_denominator`

These remain actual deadline and CPU-budget gate failures. Identical source
trees across lanes do not establish an environmental cause for different
results. No retry, exemption or relaxed budget replaces a failed result.

## Source and original commands

| Identity | Value |
| --- | --- |
| Candidate/head | `1c7e8ab7cd6a321cad4e6c7f7e8a197d7b3be14c` |
| Prospective merge | `39f9195a2bf192ac93e28fbfc1bd4e9ef7388cf9` |
| Base | `2e72a989d001cf51bd0aed0e1401526e45db31f1` |
| Tested tree, all lanes | `535660af742d62b6578b5e4334e0f2d2c17527e0` |

Each receipt preserves the complete original `before` and `after` identity
objects; they are equal. Each reports `tracked_worktree_verified: true`, 6,831
tracked entries and 782,153,776 tracked bytes.
`tests_executed_by_identity_check: false` remains unchanged: the identity check
does not itself execute the tests.

Original Node command:

```text
cargo +1.95.0 test --locked --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib --all-features -- --show-output --test-threads=1
```

Original strict Clippy command:

```text
cargo +1.95.0 clippy --locked --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib --tests --all-features -- -D warnings
```

Each retained JSON is byte-for-byte identical to the ZIP member. Its original
argv, environment, source identities, exit code, log length and log hash remain
intact.

## Log mapping and integrity

Within each lane directory:

| Original receipt `log_file` | Retained complete original log |
| --- | --- |
| `node-lib.log` | `node-lib.log.xz` |
| `clippy.log` | `clippy.log.xz` |

The receipts were not edited to rename `log_file`. `review.json` records each
full relative mapping, original and compressed SHA-256 and length, and the
original ZIP SHA-256. All four ZIP digests and sizes match a fresh independent
GitHub artifact-metadata read, preserved without temporary download URLs in
[official-artifact-metadata.json](official-artifact-metadata.json).

Each XZ contains one complete original log, compressed with preset 6. The
written file was decompressed and compared byte for byte with its ZIP member;
the decoded SHA-256 and length also match the original receipt. No log was
split, truncated or edited. Every retained file meets the existing 512,000-byte
blob gate. The larger original ZIPs remain in task scratch, and their
authenticated identities are recorded here.

[file-inventory.json](file-inventory.json) records hashes and lengths of the
retained evidence files other than the inventory itself.
