# NoUpdate12 — candidate Training, independent B and completed acceptance

## Scope and source

This is a source and capture-metadata review prepared before reading the newly captured 635 business bodies. The tested source is `dbd6a00992b60f4b33e8f10c2defda031d123bcb`, tree `fe037f5b6617fb647d416e0523685fa4ce08ef2f`. Every source file in this directory is checked against the actual 15,812-file source inventory with canonical digest `20fe46de4b63f5a2bcce469113ebe27b7514f942c7f960a71e4dabaa4f643d0f`.

The original whole parent failed at `Feature C must drain its original Generation owner without Generation inference`. Its test elapsed time is 97.260 seconds; the original execution elapsed time is 98.319732 seconds. Independent layout readback of the separately captured C generation journal found no frames; that review is retained separately. This document does not convert the failed parent into a successful E6 result.

No host operation, native test, model forward, optimizer step, signature verification or authority recovery was performed by this review. Compilation/source-gate metadata that says `model_calls = 0` describes those owners only. It must not be applied to the original business parent.

## What the actual failure location proves about preceding execution

The following implication uses the exact parent source, its actual source inventory and the actual error location. It is stronger than inferring acceptance from a `completed-acceptance` request number in stderr, but is still a statement about the checks that this original test actually reached and returned from.

| Original parent sequence | Exact function / source | Conclusion supported by reaching the C drain assertion |
|---|---|---|
| A, original retirement and B preparation | `ordinary_q24_post_a_process_tests.rs::run_original_business_case`, lines 41–83 | The original A phase and successor preparation returned. This is not a new D task. |
| Candidate Training and independent B decision | Same file, lines 84–86 and `require_actual_business_decision`, lines 210–248 | A real `Training` receipt is required; `TrainingNoUpdateV2` is rejected. This case requires `Evaluation::NoUpdate`, no Adopt and the retained selected bundle. |
| Source completion and candidate reconstruction | Same file, lines 89–99; `ordinary_q24_post_a_progress_tests.rs::original_candidate_model` | The actual source child exited successfully. Its original report matched the Training cut and candidate bundle, and the model reconstructed from its heads differed from the baseline. |
| Actual B publication | Same file, lines 100–103; `ordinary_q24_b_publication_observer_tests.rs` | The publication observer checked the original file identities, completed publication image, original plan/trust and stable journal/witness cut. |
| Selection and C input | Same file, lines 104–151 | NoUpdate retained the original Current and baseline; the independent selection and selected C input were constructed. |
| Terminal learning checkpoint | Same file, lines 152–155 | The original terminal checkpoint was observed. Its actual receipt bytes remain to be independently decoded from the capture. |
| First Root acceptance and typed ACK | Same file, lines 156–158; `ordinary_q24_cold_acceptance_data_tests.rs::wait_for_original_terminal_acceptance`, lines 297–443 | The physical first fact, completed checkpoint, refusal pre/post observations and typed daemon ACK all matched. The first fact and refusal were read again after ACK before the function wrote `ordinary-terminal-acknowledgement.json` and returned. |
| Original process exits and terminal stability | Same file, lines 159–179 | Daemon, Root and source were checked dead after successful exits; the physical checkpoint equalled the earlier terminal. |
| C physical observation | Same file, lines 183–186; `ordinary_q24_post_a_completed_data_tests.rs::observe_after_original_exit` | This function was entered and reached the eight-condition C Generation assertion. The original boolean expression stopped at `is_drained == false`. |
| Checks after the C drain assertion | Remainder of `observe_after_original_exit` | Not reached. Do not claim the subsequent full Current / intent / predecessor / selection / NextUse / final postchecks succeeded. |
| Final acceptance after complete process retirement | Parent lines 202–205 | Not reached. The original final cold observation and comparison with the first acceptance digest remain unqualified. |

The exact first-acceptance loop requires a non-refused registration, monotonic attempts, stable Ready at attempt ≥ 2, a matching terminal checkpoint, a canonical accepted profile, original recipient identity and writer-proof binding, original signature time bounds, seven physical journal cut digests and the actual six-or-seven signature digests. It then requires the daemon ACK to match identity, initial, frozen scope, terminal head, acceptance digest and original data cut, followed by unchanged acceptance and refusal readbacks. A Ready disk record alone is insufficient.

## Physical readback plan

`PLANNED_PHYSICAL_INPUTS.json` records the exact observed paths and metadata selected from the frozen 635-file capture plan. It does not assert their bodies have already been inspected. Body readback must first match the actual capture manifest, original full stat, byte count and SHA256. No private key body is required.

| Evidence group | Required original bytes / fields | Readback purpose and limit |
|---|---|---|
| Source identity and profile | Initial/profile, source/service/ledger configuration, post-A deployment, trust mapping, signed trust and writer proof | Bind actual run, owner, objective, candidate request, deadline, recipients and physical paths. Do not turn data-only decoding into a live authority capability. |
| Baseline and trained heads | Runtime `model/{base,encoder,heads}`; Root `independent-b/original-candidate.data`; `post-a-data/training.journal` and witness; training-receipt journal and witness | Compare exact baseline and candidate matrix bytes. Decode the recorded `HQ24TRES` result, metrics and heads; require candidate heads agree with the Root candidate data and signed Training receipt. Do not rerun the optimizer to generate replacement evidence. |
| Original Training contract | Frozen Dataset receipt, one-row declaration, original Training result header and lineage | The fixture declares one frozen A row, `Drive { index: 0 }`, two SGD epochs and learning rate `2^23` in Q24. Actual metrics, payload hashes and changed coordinates must be obtained from retained bytes before reporting measured values. |
| Independent B registration and source | Protocol, preregistered protocol, Generator statement, realized plan, Observer statement, original source data, candidate / fixed / execution / qualification / publication / receipt journals with witnesses | Match protocol, initial, Training head, candidate and retained bundle; bind signed policy before outcomes and independent observation afterwards. Validate the recorded completed state and exact payload relation. |
| B business outcomes | All 405 actual B business files including 16 earlier rows, 256 heldout row evidence and any actual `.requested` files | Match each evidence digest and action outcome to the actual persisted file or recorded absence. These rows are an independent file-contract fixture; they are not a real external agent trajectory corpus. |
| B control computation | `original-fixed-control.data`, candidate declaration, forecasts, retained-training / retention / removal records | Distinguish the fixed-arm fresh bounded self-distillation control from candidate Training and from pretraining history. No total forward/MAC count is inferred merely from optimizer-step metadata. |
| Completed terminal and delivery | Original checkpoint frontier/lock; actual seven physical input pairs; delivery journal/witness | Decode the actual receipt sequence and terminal head. Seven physical pairs remain required even when the LocalDecision journal has zero completed records. This NoUpdate route should have no LocalDecision receipt; confirm from originals, not from filename. |
| First acceptance and ACK | Actual Root acceptance/refusal frontiers and locks; `ordinary-terminal-acknowledgement.json` | Cross-bind accepted checkpoint, terminal head, scope, recipient, actual six-or-seven signatures, seven cut digests and ACK. The parent precondition proves its original successful observation, not a new post-expiry verification. |
| Current, selection and next use | Original publication / withdrawal / registry / Current files, independent selection, Selection and NextUse journals/witnesses, C cell/source and five separately captured C files | Check the retained model route and identity. C's failed drain prevents claiming that the complete later physical acceptance block passed. |
| FinalUse and side effects | All original device and notes claims, corresponding Current/intent/authority records, cognitive state DB/WAL/SHM as captured | Attribute each effect to its actual A or C owner and operation. The device 80-byte and notes zero-byte metadata alone do not demonstrate C/D FinalUse or settlement. |

## Training scope and counting

`cell_q24_training_fit.rs` performs actual bounded fixed-point SGD: it computes original hidden features, updates only one selected head row, checks cancellation and the minimum of original envelope time and training milliseconds before/during/after compute, and validates the original source again before returning. `cell_composed_q24_training_owner.rs` claims and witnesses the operation before compute, encodes the actual candidate and metrics, validates those exact bytes, completes the journal and reads the result back. Existing Pending is not permission to rerun.

The recorded result contains bundle, batch, optimizer and update-rule digests; optimizer steps; before/after squared error in Q48; elapsed microseconds; and candidate head bytes. The product's work contract counts gradient-coordinate updates, including zero deltas. It expressly excludes forward costs and historic pretraining. Total parameters, trainable row width, optimizer steps and coordinate updates must stay separate from whole-parent CPU/wall/physical costs.

`ordinary_q24_b_evaluation_fixed_tests.rs` prospectively declares the actual three-matrix baseline and one frozen row. Its fixed-arm control independently performs two native forwards and self-distillation steps while requiring unchanged fixed weights. `ordinary_q24_b_evaluation_producer_tests.rs::actual_policy` performs a real native forward for each baseline/candidate arm, then uses a preregistered threshold to select `persist` or `skip`. These source call sites are not a measured total for all Root evaluation, A/C execution, retries or recovery; a complete actual call total remains unset unless original records provide it.

## Retained bytes versus the anonymous report

The original source report was written to `tempfile::tempfile()`, an unnamed inherited descriptor. It was successfully read by the original parent before this failure, but is not guaranteed to survive parent exit as a named file. It is not stdout. The sealed source input descriptor includes private keys and must not be captured.

This does not mean the trained heads are lost. `root_independent_b_candidate_data.rs::write_original_candidate_data` writes the actual Training evidence's head bytes once to the existing Root-owned `independent-b/original-candidate.data`, and rereads them under the original custody checks. The frozen capture plan includes that file at 172 bytes and the Training journal at 673 bytes, which independently embeds the candidate heads and metrics. The baseline head file is also 172 bytes. These will permit a three-way byte comparison after actual capture delivery. A reconstructed report must never be labelled the missing original report.

## Fail-closed readback and storage rules

1. Preserve all failed captures, failed parents and frozen source plans. Read actual capture manifest and RESULT as separate authority inputs; require exact path/size/SHA matches before decoding a body.
2. Read journals with a standalone bounded layout parser tied to exact source. Consume all bytes, verify frame/chaining hashes and witness binding where the codec permits. Record that this is offline DATA validation, not the original Rust authority verifier or a fresh signature/current check.
3. Do not write source files, original DB/WAL/SHM, key files, journals or host state. If SQLite queries become necessary, copy each complete original group to a new analysis-only directory and verify all archived inputs remain unchanged. Do not open archived inputs with SQLite, even in a nominal read-only mode.
4. Keep the 12 excluded key bodies, four unexpanded environment subtrees, two nonregular endpoints and unrecoverable anonymous descriptor explicitly outside the captured-body claim. A non-atomic capture cannot establish a simultaneous host snapshot.
5. A new current/expiry check, model forward, signature operation or Rust observer would be new execution and is outside this review. Missing or ambiguous evidence remains unknown; it is not repaired by rerunning a business action.

The original E6 whole-parent result remains FAIL. This preparation supports a precise explanation of the actual work before the failed C drain, not a new qualification for cold D, Adopt, FinalUse, useful-work reward or production deployment.
