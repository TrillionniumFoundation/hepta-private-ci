# VERIFY-1 native integration qualification

This capsule records a real Linux native engineering run on base commit
`6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5` plus the eight source files in
`SOURCE_BINDING.json`. It is not a qualification of a future Git commit or an
automatic production caller. The publisher must retain the exact source binding.

## Executed result

The final substantive source passed 131 evidence-crate tests with one existing
ignored subprocess crash fixture, and four tests across the two selected Agentd
integration targets. The new Agentd test starts the actual daemon with ephemeral
fixture trust, signs envelopes, appends them, reads retained references, and
checks current trust. Exact replay is idempotent; changed replay, expired claims,
tampered signed bytes and revoked writers are rejected. A different candidate
tree does not match. Revoking the key also changes verification of retained
evidence. These checks do not register a production signer or caller.

The frozen Python worker ran 18 physical effects in separate step subprocesses
across six cases. The native checker examined their actual SQLite states, and
Python decoded the seven resulting native receipts. Clean state was proved;
stale read, semantic error, partial success and common misjudgment were refuted.
Missing ACK was unknown, then proved after the existing owner performed a fresh
readback without replaying effects. Every database retained zero acceptance rows.
The common-misjudgment case is an injected fixture fault, not a model ensemble.

## What is implemented

The `hepta.verify1.report` namespace now validates three distinct typed records:
risk prediction, calibration report and verification receipt. The wrapper binds
the original inner JSON bytes and digest. Rust does not reserialize floating-point
numbers to infer Python canonical equivalence. Nullable fields remain required,
and malformed scopes, fields, probabilities and report semantics are rejected.
The actual Python receipt producer/decoder interoperation is separately exercised.

`check_verify1_sqlite(path, trusted_goal, expected_scope)` uses the repository's
read-only SQLite shim. It recomputes the initialized goal, current epoch,
frontier, resource values, finished intents and ACK/readback obligations in one
snapshot. Imported claims are not checker inputs. A foreign `proved` receipt
cannot make wrong current values pass. The checker returns an unsigned typed
receipt and never accepts a task or grants an effect.

The property is `fixture_prefix_goal_and_owner_readback_at_snapshot`, in domain
`sqlite_two_field_engineering_fixture_v1`. `horizon_start` pins the prefix:
step 1 checks only the left target, and later prefixes check both fields. Only
frontier 4 is a terminal acceptance candidate. A step-1 proof cannot be promoted
to terminal success; that counterexample is exercised. This remains a snapshot
property under a trusted controller goal, trusted host-selected fixture database,
consistent SQLite read transaction, and trusted owner/epoch-bound readbacks.
It does not isolate a malicious process that can write the same database.

`Supported` from kernel evidence verification means that retained evidence has
chain support under current trust. It may correctly support a report whose
property verdict is `refuted`. The CLI and test harness invoke the checker;
generic append validates the namespace but does not automatically run it.
No model inference, calibrated trajectory guarantee, production adoption,
whole-workspace pass, Bazel pass or other-platform pass is claimed here.

## Source and logs

`RESULT.json` is the bounded result. `SOURCE_BINDING.json` retains both tested and
formatted hashes. `COMMANDS.json` has exact argv, exit status, full-log hashes and
wall times. Wall times are build/test measurements, not agent cost comparisons.
`CROSS_LANGUAGE.json` gives the six-case result. `native-execution-logs.tar.gz`
contains every recorded native build/test/fix/fmt stdout and stderr, both source
cycles, failed attempts, the actual interoperation databases and driver scripts.
`LOG_MANIFEST.json` binds every archive member before and after packaging.

Repository `just fix` ran for both changed crates, followed by `just fmt` and
`git diff --check`. Clippy left tested source bytes unchanged. The prohibited raw
SQLite connect calls were replaced through the existing shim in a new substantive
test cycle. The final format diff is retained, and tests were not rerun afterward,
as required by the repository's AGENTS instructions. The only final lint warnings
are two pre-existing lifetime warnings in the vendored i18n-config dependency.

The command environment used a task-owned Cargo target, two build jobs, a 200%
CPU cap, 4 GiB memory cap and nice 10; observed cgroup values are retained. No
pre-existing worktree, production binary or user ref was changed. Cargo dependencies
and lockfiles are unchanged.

## Review stages and build registration

The delivery root has `STAGE_PLAN.json`, three patches, a source manifest and the
necessary report-only intermediate `lib.rs`. Stages contain 600, 568 and 383
changed Rust lines respectively. Only their composed final overlay was tested;
the stages are reviewable dependency boundaries, not separate test receipts.

The existing `codex_rust_crate` Bazel macro includes `src/**/*.rs`, generates
integration targets from `tests/*.rs`, and supplies `tests/**` as compile/runtime
data. The new target is
`//codex-rs/hepta-agentd:hepta-agentd-verify1_kernel_evidence_product-test`.
No new compile-time file resource or dependency requires a BUILD change. Cargo
autodiscovers the new integration file, and the repository's selected-package CI
uses `just test --locked -p ...` without filtering individual test targets.
This registration was inspected read-only; Bazel was not executed.
