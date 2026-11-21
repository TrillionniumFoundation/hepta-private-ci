# Wait for the committed local decision in the ordinary Q24 fixture

## Observed failure

The original warm Adopt parent on source `84721f3da92ffaac3e7c7e2e39de2df985834370` failed once with `actual local decision or original NoUpdate cut required`. Its canonical JUnit contains one failed case (65.719 seconds); the outer command took 66.54169046785682 seconds. Both planned cold parents had zero attempts under the original stop-on-first-failure protocol. The old source, original result, and retained executable remain frozen.

The original checkpoint is 3,907 bytes with SHA256 `b086e9c3270b8d9ac457d01dd5fa0daa981925848806736b3d67bf1d1757c5a0`. A read-only structural translation of the pinned Rust codec consumes all 2,743 inner `HEPLCP02` bytes and finds five receipts: Experience, Dataset, Training, Evaluation(Qualified), and Proposal(UpdateCandidates). It finds no LocalDecisionV2, artifact Selection, or NextUse. The actual Training observation records `steps=2`, `milliseconds=2`, and `artifact_bytes=172`; it contains no `optimizer_steps`, `parameter_updates`, or `examples_seen` fields. These receipt values do not independently measure physical optimizer work. Independent Rust receipt-chain verification was not rerun by the decoder.

The failure result SHA256 is `36e30576f6e36dfc2109e8a7de134e9f796314a0c263ab1b5c475799c32cd6ff`; the canonical JUnit SHA256 is `6087c475ab4844be675fb39671aa97372fe80632807da8fd59575e64d7270421`. The complete failure archive has SHA256 `3bb02ef7c446777e23101d556f1aa138d697ab8ccb34971de4d3489a5b06cdfb`. It is preserved separately from the earlier NoUpdate16 PASS evidence.

## Why this is a fixture observation error

At the pinned source, `learning_iteration.rs` maps both Proposal and LocalDecisionV2 to next stage Selection. The fixture `ordinary_q24_post_a_progress_tests.rs` currently treats that stage alone as a complete decision. In contrast, `cell_q24_publication_validation.rs` correctly requires the last observation to be LocalDecisionV2 or an original NoUpdate cut. Its existing bare-Proposal negative control expressly rejects publication at this prefix.

The candidate adds one enum import and waits only when the validated checkpoint is at Selection with a last Proposal whose disposition is UpdateCandidates. Every other state follows the original Decision construction and error propagation. It preserves the TrainingNoUpdate refusal, monotonic checkpoint observation, independent-B requirement, liveness checks, 10-millisecond polling interval, original deadlines, Root read budget of 64, and publication guards. It does not convert arbitrary Decision errors into polling and does not relax the NoAdmissibleUpdate path.

This wait does not depend on a later fixture action. In the pinned product source:

- `learning_iteration_successor.rs` and `learning_iteration_historical_context.rs` do not require a successor generation for Selection immediately after Proposal.
- `cell_q24_learning_historical_operation.rs` dispatches `CommitDecision` for that prefix, authenticates the receipt, records it, and commits the checkpoint. Only the later Selection/NextUse handoff requires generation ownership.
- `cell_q24_local_decision_owner.rs` uses the already available trainer, dataset, proposal, factory, and local policy to attest/read back the decision. It does not consume the future fixture artifact-writer input.
- `ordinary_q24_post_a_process_tests.rs` writes the candidate/artifact handoff after observing the actual decision.

The real successor parent still must establish that this correction works. This source reasoning is not an Adopt result.

## Two inherited source-QA locator repairs

The publication-frame mutation tests are updated to locate the real `exchange_inner` arguments and diagnostic header-write call, including the original deadline and error propagation. The material-recovery mutation tests locate the complete existing `inspect_err(...)?` calls. Both original starting-record reads remain separate negative controls, as do both pinned-process checks and all three peer-owner checks. The verifier, CALLERS policy, production source, assertions, and test names are unchanged. The repair has received static source/AST review; the full QA execution remains pending on the published successor.

## Formatting already executed

An initial preparation attempt cloned an incomplete local donor but could not read the 84721 tree. It exited before changing a source file or running a formatter. That failure is retained. A different donor was then read-only verified at the exact 84721 tree with all 16,557 tracked objects present. A new independent checkout copied Git objects without hardlinks or alternates and did not copy the donor's dirty CGen test file.

In that independent checkout, the original `just fmt` recipe ran once for the Rust candidate and again after adding the two approved QA locator files. Both invocations succeeded and left all three candidate files byte-identical to the reviewed payload. The recipe actually selected Rust's file formatter; it was not a registry no-op. The two QA paths are outside this formatter registry's Python scope and were not formatted by it.

An additional read-only check invoked Rust 1.96.0's rustfmt with edition 2024 and CI's `imports_granularity=Item` setting, scoped to the candidate file with `skip_children=true`. It succeeded with the stable-toolchain warning that `imports_granularity` is a nightly-only feature. The actual formatter was `rustfmt 1.9.0-stable (ac68faa20c 2026-05-25)` under Rust 1.96.0, matching the pinned CI toolchain. This is a single-file check, not a whole-workspace cargo-fmt result. The separate CI format failures in `ordinary_q24_source_keeper_tests.rs` and `production_initial_q24_writer.rs` are retained; this candidate does not alter those paths.

The Rust file remains SHA256 `4b0d98a11085203161646d177d0af079254e8d4fe5e2dbcb3adae41141202462` (8,651 bytes). The original-format receipt is SHA256 `467d616b85e4a569b012a0ba851ececf71b1289e25abd51b503488ebf5bcfbd1`; the three-file receipt is `d25c061b9f065a4c559cedf8b941d6343d7e4af577c12d1908ec79af8509fa45`. Zero source tests, Rust builds, or native parents were executed for this candidate during preparation.

## Proposed qualification after immutable publication

The exact three-file successor must be published before any qualification execution. A new ai395 owner will bind its real HEAD/tree, source inventory, raw receipts, copied tooling, dependency inputs, target, and fresh JUnit paths. The old 84721 source, NoUpdate16 result, failed lifecycle owner, and retained 0555 executable will remain untouched.

The source gate will run the original CI commands in order from the repository root: `python3 scripts/verify_hepta_callers.py self-test`, `python3 scripts/verify_hepta_callers.py verify`, and `python3 -m unittest discover -s qa/b4-no-bypass -p 'test_*.py'`. The separate #6858 CI b4 check (job 136735663569, its own merge-source identity) discovered 1,014 tests and reported two failures plus four errors; the prior 474-case selected gate cannot stand in for this full suite. The successor will retain its actual discovered roster and count. No preliminary ten-case rerun is proposed. The later fault-matrix, performance, and vertical-slice CI suites are separate and must not be claimed passed by these commands.

If the frozen source gate succeeds, a new private target may be populated by read-only copy or reflink from the terminal 84721 target. Before compilation, every copied regular file must have a distinct inode from its donor; external symlinks and any path that could write into the original owner must be refused. Capacity, copy time, original/copy inventories, and both ELF identities will be recorded. Only copied files may have their mode changed. Cache reuse is a real preparation cost, not a fresh cold build or free computation.

Rust qualification will retain the original Rust 1.96.0 tool identities, two build jobs, `--offline`, `--locked`, and disabled incrementals. Cumulative compilation is already 736.5254642539658 / 1,800 seconds, leaving 1,063.4745357460342 seconds. Cumulative lint is already 523.7743974500336 / 1,800 seconds, leaving 1,276.2256025499664 seconds; this small fixture correction does not require a repeated unrelated `just fix`. Additional actual build time must be charged to the remaining compilation allowance. Native preparation remains a separately identified original scope with its actual costs retained, never a reset of compilation allowance.

The existing bare-Proposal and NoUpdate/retention/Defer publication controls are the focused Rust checks. Exact compiled test identities must be frozen from the real list. A separately reviewed new native driver will then preserve the complete helper/product/seven-package preparation, original guards and read limits, exact parent order, original 360/480/120/60/300-second scopes, and one attempt per branch with stop on first failure. No ordinary/native dispatch is authorized by this planning file. No result is borrowed from 84721, #6858, or an earlier owner.

Even a future successful lifecycle fixture would demonstrate an engineering adoption/recovery path. It would not establish external E2 child weights, scientific model gain, fresh D after recovering C, FinalUse, settlement eligibility, or production deployment.
