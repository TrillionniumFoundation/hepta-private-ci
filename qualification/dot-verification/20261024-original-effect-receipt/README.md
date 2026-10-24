# Original AutomationStore receipt readback qualification

Exact parent: `103bb2011629d12c658b7004d3a4a163a548df02` (tree `79619c42ccd81e8c1d41f19664e53f5cbf10eb9b`), the newer #3649 Responses/token-accounting source. This is a test-only addition to its existing `hepta-automation` integration fixture. No production owner, runner, public API, Cargo manifest/lock, workflow or security configuration changed. It is not a combination or requalification of the separate #3652/#3653 cancellation patch.

## Useful result

The actual Agentd replay entry `AutomationStore::read_authorized_taskflow_effect_receipt` had no direct callers in tests. Three new tests exercise that API against the existing SQLite store, original final-use fixture and controlled driver, not the simplified #3654 file owner:

- Successful and failed terminal effects survive `close`, drop and reopen with the **complete original TaskFlowStepReceipt** unchanged over repeated reads; no driver redispatch.
- Six changes under the same run/step/attempt (operation ID, payload, destination, subject, scope, policy generation), and a changed command ID, each reject with `TaskFlowError::Conflict`. The original receipt stays readable afterward.
- An absent provider attempt and a persisted indeterminate observation return `None`, not a fabricated terminal result. The latter remains in the original pending recovery scan.

Original target baseline: **10/10 passed, 0 skipped**, 0.704s. After adding the three tests: **13/13 passed, 0 skipped**, 1.075s. Original provider-contact task panic, actual SQLite reopen/no-redispatch, binding, revocation and compensation cases remain in the target. No new implementation defect was observed; #3654 missing-receipt negative control is not treated as a product vulnerability.

## Validation limits and failures

`just fmt` and `git diff --check` exit0. Tests precede formatting according to repository AGENTS instructions. Both pre-format source files and hashes are retained for independent before/after review; only formatting changed after the green run.

**Strict scoped Clippy FAILED, exit101**, even with `--no-deps`, in unchanged library code:
1. `authorized_effect.rs:540`: large_enum_variant.
2. `authorized_effect.rs:644`: too_many_arguments, synchronous authorized dispatch.
3. `authorized_effect.rs:866`: too_many_arguments, asynchronous authorized dispatch.
4. `neural_circuit.rs:125`: too_many_arguments.

The separately recorded default-warning Clippy run is supplementary, not a strict pass. No allow/expect/macro suppression or public signature changes were added. Hosted exact-head CI, entire-package/workspace tests and Bazel execution are not established by this scoped target. `defs.bzl` already includes `tests/**` as integration compile_data; the new child module uses that existing source rule.

## Environment recovery, not source defects

The first command mistakenly carried Rust1.95 from the older dot task. This exact repository's rust-toolchain.toml requires **1.96.0**. Missing offline package and subsequent MSRV logs remain unchanged. Official isolated rustup1.96 fixed that mismatch without ignoring rust-version or editing lockfiles.

Next, aws-lc-sys lacked CMake and libclang could not find builtin stddef headers. Isolated PyPI cmake3.31.6 (27.8MB wheel), followed by supported BINDGEN_EXTRA_CLANG_ARGS pointing at the existing GCC14 include directory, allowed compilation. All earlier failure logs and exact commands are retained. No privileged/system/network-policy changes were needed. nextest's pre-existing profile.local.inherits and metadata warnings, and a dependency AsyncFd deprecation warning, remain in raw output.

## Still not a native durable adapter

See integration-findings.md. The original owner has a durable attempt-before-dispatch barrier and recovery, but the loop needs three explicit original-owner contracts before integration:
- durable immutable mapping of its generation-bound operation key to the existing authorized TaskFlow/provider identity, without manufacturing new dispatch/grant on recovery;
- exact original tool-result bytes bound to the terminal receipt, which currently stores status/digest only;
- real provider/owner stop evidence for the cancellation double ACK, not a local task/cursor flag.

Existing tests use a controlled provider and test-only signing identity; they do not establish production authority, live provider behavior, network-traffic attestation, SIGKILL/power-loss recovery, tool-result persistence, physical exactly-once effects or completed native adapter integration. No socket retry or denied execution route was used. No merge/deployment; SHADOW/DENY_ALL unchanged.
