# V26: Exact-source Rust syntax and Python dependency P0 repair

**Status: research-only, DRAFT / SHADOW_ONLY / DENY_ALL.** Parent PR #2364 frozen at `48eaf00329d65589de546043b67f9e934440b91c` before the V26 patch. No inference worker owner, original input material, Q24 output, NDU, CAS, CNS, Final-use, original experimental numbers or production routes changed.

## Real failures observed

| Exact parent run / job | Failure | Minimum remediation |
| --- | --- | --- |
| PR V24 [38932051233](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38932051233), job 117078220783 | `rustc` rejects three `pcentile(&..., .99)` float literals (missing integer part) at original `native_v24_packed_head.rs` lines 316–317; exit 1 *before* running any Rust tests or original physical model | Replace only each `,.99)` with `,0.99)` |
| PR V25 [38932051070](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38932051070), job 117078215482 | Same three Rust parser errors in `native_v25_stack_tile.rs`; cross-order V24/V25 original benchmark not reached | Same three literal replacements |
| [38932051279](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38932051279), job 117078222364 | Seven original source-test modules fail import with `ModuleNotFoundError: No module named 'cryptography'` in the matrix's execution-regressions job | Install pinned `cryptography==46.0.4` in the **existing** focused dependency step |
| Global [38932051329](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38932051329), repo-checks | Exact Prettier 3 workflow check flags `hepta-group-reasoning-research.yml`, `hepta-stem-v13-cheap-retrieval.yml`, `hepta-stem-v13-original-reader-negative.yml` | Separate precise format repair; do not disable formatting |
| Global 38932051329 cargo-deny | Advisories FAILED | Independently update affected dependencies in a qualified security branch; do **not** ignore advisories |

## Source-invariant patch and strict acceptance

Exactly **three** tracked paths are patched by the P0 step: two research-only Rust binaries, one original next-round matrix. No scientific weights/sources or reported measurement is revised, and no new capability is asserted.

For the exact new commit SHA, require all of:

1. Original V24 and V25 `rustc --edition=2021 --test` compile and test **success** on a hosted Rust runner. The three parser errors must be gone in each.
2. Separate push-source jobs **actually compile optimized Rust binaries**, reload hash-pinned original pretrained artifact, reproduce native Rust outputs and pass the independent NumPy reviewer for all 64/256/1024/4096-Head sizes.
3. The next-round matrix must run the original `test_*.py` suite with `cryptography` installed. Passing import only is not a full test pass.
4. Other formatting, security, Rust workspace, architecture and global blocking checks require their own exact-HEAD completed verdicts. No predecessor green result is inherited.

Rust throughput/p99, RSS, Q24 parity, Worker dispatch, signed model publisher custody, trusted hardware attestation, new source families and prospective utility **remain unverified until their separate original executions succeed**. Production promotion and physical Cell Split stay `DENY_ALL`.
