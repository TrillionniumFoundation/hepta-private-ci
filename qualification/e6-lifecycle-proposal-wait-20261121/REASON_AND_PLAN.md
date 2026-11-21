# Five-file lifecycle successor prepared on the readback-reconciliation base

The proposed parent is immutable commit `72fb96148a3d12db0d3482f46ab0653f7353d532`. It includes the separately reviewed Cell-generation readback test repair. The five new source edits comprise the ordinary Q24 fixture waiter, two source-QA mutation locators, and two mechanical Rust-format corrections. Publication and qualification of this successor are separate from the prior 84721 native executions and the parent commit's official CI.

## Retained failure and bounded correction

The original warm Adopt parent on `84721f3da92ffaac3e7c7e2e39de2df985834370` failed once because the fixture treated a Proposal(UpdateCandidates) prefix as an already committed local decision. The actual checkpoint contains Experience, Dataset, Training, Evaluation(Qualified), and Proposal, followed by no LocalDecisionV2, Selection, or NextUse. Its Training observation records `steps=2`, `milliseconds=2`, and `artifact_bytes=172`; it does not contain optimizer-step or parameter-update fields. Both cold parents had zero attempts. The complete failed execution, checkpoint, original codec, structural-decoder limitation, and retained 0555 ELF remain preserved.

The waiter correction delays only that specific validated Proposal(UpdateCandidates) prefix under the existing deadline, liveness, monotonic-history, and 10-millisecond poll loop. All original Decision guards, independent-B checks, TrainingNoUpdate refusal, error propagation, and the Root 64-read limit remain unchanged. Production can commit LocalDecision before the later generation/artifact handoff, so this wait does not depend on a future fixture write. The detailed source analysis and the original 84721 formatting receipts remain in the preliminary evidence; they are not relabeled as 72fb execution.

The two Python QA changes locate the actual existing diagnostic-call expressions. They preserve all tests and assertions, the two independent starting-record negative controls, two pinned-process controls, and three peer-owner checks. They do not change protected predicates, the verifier, CALLERS, or product behavior.

The two mechanical format edits exactly match the observed source-format differences: a `seals` declaration becomes one line; the existing single-expression `map_err` closure receives a formatting block around that same expression. The latter adds braces as well as whitespace, while preserving the call, arguments, and `?`. No deadline, permission, or product guard changes.

## Actual formatter scope

The independent preparation checkout first ran the original `just fmt` and a Rust 1.96.0 single-file check at 84721. Its first incomplete-donor preparation failure and subsequent successful preparation are retained. The checkout then fetched and selected the exact published 72fb parent, verified the original three preimages, added only the two approved format corrections, and ran the original `just fmt` again successfully. The five reviewed file byte streams remained unchanged by formatting. The new receipt SHA256 is `8f92f0f2f65301b01e5f47db38337a5608698f53c3585b1c0eb7337c991e64d7`.

The recipe selects the three changed Rust files. The two QA files are outside this formatter registry's Python coverage. The additional pinned rustfmt check covers only those three Rust files, using edition 2024, `imports_granularity=Item`, and `skip_children=true`. The stable-toolchain warning about nightly-only import grouping is retained. Neither operation is represented as a full-workspace `cargo fmt` or full CI pass.

The separate daemon-CI formatting behavior involving historical evidence Rust files and a merge-base formatting scope remains a separate issue. These two source-format corrections do not claim to repair or clear that entire CI gate. Each original CI run retains its actual merge/source identity and outcome.

## Qualification planned for the newly published SHA

No source tests, Rust builds, or native parents have run for the new successor during preparation. After publication, a new ai395 owner will bind the exact public HEAD/tree, changed-file hashes, complete source inventory, tooling, fresh receipts, and an independent target. From the repository root it will run the actual original CI commands in order:

```sh
python3 scripts/verify_hepta_callers.py self-test
python3 scripts/verify_hepta_callers.py verify
python3 -m unittest discover -s qa/b4-no-bypass -p 'test_*.py'
```

The full b4 suite previously discovered 1,014 tests under its separate CI identity. Its prior two failures plus four errors are retained; the selected 474-case result on 84721 cannot replace the complete new gate. The actual new roster/count and all errors will be retained. No preliminary ten-case rerun is planned. Fault-matrix, performance, vertical-slice, formatting, and official ordinary/Root CI outcomes remain separate checks.

The old 84721 target is 18,191,298,801 apparent bytes across 19,544 regular files, with no symlinks at the read-only preflight. Capacity was sufficient for a full private copy. These are preflight observations, not a launch-time guarantee. Copy/reflink preparation must recheck terminal ownership, donor bytes, inode separation, file types, capacity, source identity, and the original ELF SHA. No hardlink may share a writable inode with the old target; the original 0555 executable is never chmodded. Any copied historical nextest reports must be preserved as inherited copies outside the new report destinations; the new commands must begin with no prior report at their fresh JUnit paths. Copy time and cache reuse are recorded as real preparation costs.

The Rust toolchain remains 1.96.0, with two build jobs, `--offline`, `--locked`, and disabled incrementals. The cumulative compilation ledger remains 736.5254642539658 / 1,800 seconds, leaving 1,063.4745357460342 seconds. The lint ledger remains 523.7743974500336 / 1,800 seconds, leaving 1,276.2256025499664 seconds. Prior failed, preparation, native, and cache-copy costs remain visible. This small fixture repair does not automatically require a repeated unrelated `just fix`; no allowance is reset.

Existing bare-Proposal and NoUpdate/retention/Defer publication controls will use their actual compiled identities. Any subsequent native scope requires its separately reviewed exact driver and source binding. It must preserve original helper/product/seven-package preparation, component gates, original case order, 360/480/120/60/300-second scopes, one attempt per branch, and stop on first failure. This document does not itself launch a native scope.

A future successful tiny Q24 lifecycle fixture would establish only its measured engineering path. It would not establish learned E2 child weights, scientific model gain, fresh D after recovering C, FinalUse, settlement eligibility, or deployment.
