# Completed checkpoint DATA reader: bounded capacity and terminal semantics

## Decision and scope

At exact source `bfea526e1cb9a2da718d835cd617e87c67181fe9` (tree `e047b5fc72284e25a98c0ebb4f2e69a2f6338e56`), `MAX_RECEIPTS = 8` is a capacity ceiling. It is not the number of receipts required for every completed iteration. `read_original_completed_scoped` incorrectly combines the correct semantic completion checks with an equality to that ceiling.

The isolated candidate removes only `snapshot.receipts.len() != codec::MAX_RECEIPTS` from that method. It keeps the scope check, bounded canonical decoding, full coordinator replay, refusal of unfinished histories, the explicit exclusion of TrainingNoUpdate for this completed-history purpose, and the final NextUse requirement. No `8 → 6` substitution, relaxed replay, new public entry point, new authority, changed wire format, or expanded budget is introduced.

This is a necessary DATA-layer correction, not a complete Root acceptance repair. The independent outer-Root review found another existing fixed physical-journal/signature shape. The actual six-receipt EvaluationNoUpdate route remains blocked there. This candidate does not change or synthesize that evidence and does not claim Root acceptance. Hia owns integration and the precise CALLERS protection update; Chain owns the independent outer-route review.

The NoUpdate9 original failure remains the observer's old namespace and resulting ENOENT. Its trace stopped before completed-history acceptance; this DATA condition was not reached. Neither this patch nor the later signature issue replaces the recorded first cause.

## Exact source evidence

The read-only audit source resides in `../e6_checkpoint_terminal_contract_review/source/`. Its `SOURCE_PINS.json` binds all 23 Rust files to exact Git blobs at bfea. The complete agentd source Git tree has 1,160 entries and `truncated: false`; the earlier Contents directory result capped at 1,000 entries is preserved and is not used as a complete inventory.

| Source | Relevant contract |
|---|---|
| `codex-rs/hepta-agentd/src/learning_iteration_checkpoint_codec.rs` | `MAX_RECEIPTS` is eight. Encoding and decoding reject counts above eight only for LocalDecision; older histories retain their seven-slot capacity. `HEPLCP02`, `HEPLCP03`, and `HEPLCP04` stay distinct. Decode consumes all bytes and invokes coordinator replay. |
| `codex-rs/hepta-agentd/src/learning_iteration_checkpoint.rs` | The write path already uses `len > MAX_RECEIPTS` as a capacity check. The completed DATA read uses `len != MAX_RECEIPTS`, causing the mismatch. The candidate changes only that equality, plus registering a dedicated Linux-only test module. |
| `codex-rs/hepta-learning-artifacts/src/learning_iteration.rs` | `from_snapshot` starts from the original request/owners, records every receipt, and compares the entire reconstructed snapshot. `next_stage` branches on actual observations; NextUse and RetainedModelNextUse are terminal. Selection remains mandatory after each NoUpdate route. |
| `codex-rs/hepta-learning-artifacts/src/learning_iteration_types.rs` | LocalDecision is a distinct observation at the Selection stage. Both ordinary and retained use map to NextUse. TrainingNoUpdate remains a separately versioned outcome. |
| `codex-rs/hepta-learning-artifacts/src/learning_iteration_scope.rs` | The frozen scope binds original request, owners, update rule and component boundary, and validates every candidate even if evaluation returned NoUpdate. |

`SOURCE_ANCHORS.json` provides exact line spans, source hashes and excerpts. The candidate's `MANIFEST.json` binds original/new product bytes, test bytes, full test names, and the absence of execution.

## Stage routes

Every row below is a complete core coordinator history. This table does not assert that all of these routes satisfy the outer completed-history authority protocol.

| Route | Receipts, in order | Count | Existing codec | Candidate DATA API |
|---|---|---:|---|---|
| TrainingNoUpdate | Experience, Dataset, TrainingNoUpdate, Selection, RetainedModelNextUse | 5 | HEPLCP03 | Refused by the existing explicit purpose exclusion |
| EvaluationNoUpdate | Experience, Dataset, Training, Evaluation(NoUpdate), Selection, RetainedModelNextUse | 6 | HEPLCP02 | Readable after exact semantic replay and scope checks |
| ProposalNoAdmissible | Experience, Dataset, Training, Evaluation(Qualified), Proposal(NoAdmissibleUpdate), Selection, RetainedModelNextUse | 7 | HEPLCP02 | Readable after exact semantic replay and scope checks |
| Historical proposal update | Experience, Dataset, Training, Evaluation(Qualified), Proposal(UpdateCandidates), Selection, NextUse | 7 | HEPLCP02 | Readable after exact semantic replay and scope checks |
| Local Adopt | Experience, Dataset, Training, Evaluation(Qualified), Proposal(UpdateCandidates), LocalDecision(Adopt), Selection, NextUse | 8 | HEPLCP04 | Readable after exact semantic replay and scope checks |
| Local Defer / Retain | Experience, Dataset, Training, Evaluation(Qualified), Proposal(UpdateCandidates), LocalDecision(Defer / Retain), Selection, RetainedModelNextUse | 8 | HEPLCP04 | Readable after exact semantic replay and scope checks |

There are no two missing stages on the legitimate six-receipt EvaluationNoUpdate path. Its state machine goes directly from the evaluation decision to independent Selection. Adding a proposal or LocalDecision there would contradict the existing stage and observation checks. A valid unfinished prefix can also have six or seven receipts, so a different numeric completion threshold would be incorrect.

## Existing tests and their evidentiary limits

The existing artifact tests explicitly cover evaluated and proposed NoUpdate, actual next-task use, all three local decisions, and the five-receipt TrainingNoUpdate route. The existing checkpoint tests cover codec persistence and frozen-scope reopening for these routes. They are retained as source evidence; this audit did not execute them.

The complete original Root process tests separately name Adopt and EvaluatedNoUpdate. Their process flow waits for the actual first Root acceptance and daemon acknowledgment before successful retirement; the cold tests call that complete business case first. These are ignored tests requiring the actual privileged deployment, not synthetic proof of acceptance. Merely reading their definitions does not establish a passing run. Existing protocol JSON tests and negative missing-ACK tests are also not equivalent to an accepted physical Root history.

## New direct API controls

The 414-line dedicated test module contains eight test functions. Its helpers reuse the existing authority-free synthetic receipt fixtures and the actual coordinator, codec and `read_original_completed_scoped` method. The complete returned snapshot is compared with the expected snapshot in positive cases.

| Control | What must remain true |
|---|---|
| Evaluated/proposed completed histories | Complete six- and seven-receipt histories are readable without padding them to eight. |
| All LocalDecision outcomes | Adopt, Defer and Retain eight-receipt histories remain readable only after Selection and actual use. |
| TrainingNoUpdate | Its five-receipt history is semantically complete and codec-valid, but this specific completed-history DATA API still refuses it. |
| Every unfinished prefix and vacant record | All seven route variants reject every proper prefix, including numerically six- or seven-receipt prefixes; an unstarted owner is refused. |
| Scope/request/owner/record binding | A different scope, update rule, budget, trust set, schema, binding or outer predecessor remains refused. |
| Missing/duplicate/reordered/tampered chain | Interior removal, exact receipt duplication, reordering, false predecessor/head/actor/operation/evidence and a receipt at expiry remain refused. |
| Actual retained use | A substituted candidate, reuse of the source run, a missing committed step, or a missing publication remains refused with the exact ContextMismatch error, so a later head mismatch cannot satisfy this assertion. |
| Encoded payload integrity | Truncation, trailing bytes and noncanonical base64 remain refused. |

The receipt timestamp test preserves the original boundary: new receipts at or beyond envelope expiry are invalid. Historical replay is still permitted after expiry because it replays original receipt timestamps; a separate outer authority must enforce current acceptance authorization. No new wall-clock admission rule is invented in this DATA helper.

## Execution and next gate

All runtime counts for this candidate are zero: formatter, Rust compilation, Rust tests, native parents, model calls, training and host execution. The only completed checks were local source/Git-object identity checks and verification that the product delta is exactly the approved removal plus test-module registration. These are not test passes.

Hia must integrate the frozen files, migrate only the erroneous CALLERS required-order literal to a corresponding forbidden pattern, preserve the other protected sequence and caller boundaries, and run the original formatter/source/project gates under the parent-coordinated owner. Root has paused deployment and NoUpdate10 while the independent outer journal/signature contract is resolved. No native retry is justified solely by this DATA candidate.

## Revision 2 peer correction

The first candidate is retained unchanged. Hia and Root identified that generic error assertions could pass because a later whole-snapshot/head mismatch caught an edited receipt. Revision 2 requires `Snapshot(ContextMismatch)` for each of the four actual-use mutations and exact `WrongOwner`, `WrongOperation`, `EmptyEvidence`, and `DeadlineExceeded` Snapshot errors for the corresponding receipt mutations. These errors occur before final snapshot comparison, so a stale-head fallback cannot satisfy the assertions. It does not recompute heads, copy a digest implementation, or create any signature. The product bytes remain identical to candidate 1, and the eight test functions remain unexecuted.

An earlier, unpublished revision-2 draft had used canonical payload bytes to recompute the last head. That draft and its metadata-builder failure (an excerpt range ending beyond the source file) are preserved under `retained-pre-root-feedback/`. The final source follows Root's smaller exact-error approach. The range correction affects source annotations only. No Rust or native command was involved in either preparation attempt.
