# Five additional original-owner caller seams: source-bound audit

## Scope and decision

This read-only audit covers five exact omissions observed by the running original caller collector over its full Rust source set. All five are real calls to the declared original receiver or factory. They are legitimate existing custody-composition/readback seams, not typed-analysis ambiguity. The recommended eventual registration correction is **one exact additional product caller in each of five existing boundaries**, with source protection for the unprotected host code and the explicitly authorized Model dependencies. No Rust capability, owner, wire, verifier, ref, or currently running source tree was changed.

The audit uses fixed upstream `b29869e856d08db1bfb066116a9c443376ccc57d`, the root's immutable 25-file projection over `e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`, and frozen v3.1 CALLERS blob `155282ec6dd93e2637659a73da10eb2f3936a7b3`. The projection has no frozen final source tree and is not a substitute for final gates. All 29 focused source inputs (309,914 bytes) were independently checked against Git blob identity, exact byte length, and SHA-256.

The original all-boundary diagnostic continues to use **v2** CALLERS and its original source inputs. It is not an execution of v3/v3.1 or of the recommendations in this report. This report does not assert that the remaining scan has passed or reached its terminal state.

## Actual recorded observations

The first four failures are from archived SDK blob `e4df702591ee2945faceaf2151764ecf8102b527`. Its decoded 38,866-byte JSONL chunk has SHA-256 `782063461d8db596eb82210ac3326d8012d433629d3898820d7f7d27f713b076` and 122 events. The fifth is from SDK blob `5dd2ba33760b952decd6757c1b091ae494f53748`; decoded 15,219 bytes, SHA-256 `3d68bfc095bf7a2720b5ab37d2e5b9f0145b0a6d311523026991d7325e702ff4`, 50 events. Both decoded chunks were independently hash-checked.

All five completed events have status `failed`, `missing=[]`, and exactly the unexpected path shown below. Positions are the original zero-based event positions.

| Position / exact boundary ID | Unexpected existing source | Actual target |
| --- | --- | --- |
| 335 — `learning_original_selector_command_context` | `circuit_selection_command_readback.rs` | `OriginalCircuitSelectionCommandContextV1::from_original_training` |
| 337 — `learning_original_selector_command_owner_profile` | `circuit_evaluated_selection_readback_owner.rs` | `OriginalCircuitSelectionReceiptOwnerV1::original_command_profile` |
| 338 — `learning_original_selector_command_owner_factory` | `circuit_selection_readback_host.rs` | `OriginalCircuitSelectionCommandOwnerV1::from_original_receipt_owner` |
| 347 — `learning_original_dataset_readback_current` | `cell_q24_model_command_host.rs` | `OriginalCellQ24DatasetCommandReadbackV1::readback` |
| 365 — `learning_original_next_use_command_owner_factory` | `circuit_next_use_readback_host.rs` | `OriginalCircuitNextUseCommandOwnerV1::from_original_receipt_owner` |

All paths in this table are under `codex-rs/hepta-agentd/src/`.

The later SDK chunk also repeats positions 360/361 for `learning_original_material_initial_context_check` and `learning_original_material_dataset_context_check`, both naming `circuit_selection_command_readback.rs`. Those are already part of the separately audited v3 Selection additions and must not be added again.

## 335: the retained Selector readback connection constructs its exact legacy context

Source identity: `circuit_selection_command_readback.rs` blob `5a69cc5f3bbfbb58b4050cc1e51c552cacb7e75f`. Its complete bytes are identical at e8 and fixed b298.

[`OriginalCircuitSelectionReadbackConnectionV1::bind_original_selection`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs) consumes `self`, takes an opaque original Dataset result, a borrowed opaque Training result, and the opaque completed Selection result. The call is explicit, not a same-named unknown receiver:

`OriginalCircuitSelectionCommandContextV1::from_original_training(dataset.snapshot().clone(), self.material.scope.clone(), self.material.verifier.clone(), training)`.

The constructor in [`circuit_selection_command.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_selection_command.rs) requires the actual two-receipt Dataset prefix at Training, records the actual Training receipt at its original observed time, and authenticates the resulting exact three-receipt `TrainingNoUpdateV2` Selection predecessor. It verifies the original Generator signature, actor, trust, objective, scope, and time. This remains the legacy three-cut contract; it does not admit the evaluated four-cut profile.

Back at the consuming readback connection, the constructor result must have the same initial snapshot. The code derives the full context binding, checks the original peer lifetime, revalidates initial material and Dataset contexts, requires a nondecreasing clock and the same initial binding, authenticates the actual completed Selection, and compares the complete opaque result and binding. Only then does it create the existing `OriginalCommandEvidenceV1::Selection` reader in a `LearningIterationEvidenceClientV1` whose ordinary channel is None.

The reader retains the same channel. Its request has the dedicated readback purpose and `Action::Readback`; the response is correlated to the request and reauthenticated after peer I/O. Missing, Pending, changed signatures, expired evidence, or failed current checks do not create work. No connection, signer, replacement owner, Execute surface, or recovery constructor is obtained from this call.

**Registration recommendation:** append only this path to the existing context boundary. The caller is already covered by v3.1 protected row index 390, including the complete consuming binding order; the actual context constructor/authentication are covered by row 293. No new production interface or new protection row is required for this seam.

## 337: evaluated Selector readback reads the same owner's fixed private profile

Source identity: `circuit_evaluated_selection_readback_owner.rs` blob `c1e11662921a5b869d060dad3a9a2d53a53668fb`. It is newly present in fixed b298 and in the root's exact 25-file overlay; e8 has no such file.

[`OriginalCircuitEvaluatedSelectionReadbackOwnerV1::from_original_receipt_owner`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_owner.rs) receives the actual `OriginalCircuitSelectionReceiptOwnerV1<W>` by value. `owner.original_command_profile()` is therefore a real call on the declared receiver. The getter in `circuit_selection_receipt_owner.rs` returns only a borrowed fixed config and the owner's private Recovered brand. It returns no key, journal, mutable owner field, or caller-selected authority tag.

The consuming caller in [`circuit_evaluated_selection_receipt.rs::into_evaluated_readback_owner`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_evaluated_selection_receipt.rs) requires the owner's real `Profile::Evaluated`, matching original receipt-context binding, matching decision snapshot, and matching Selector actor before moving that same owner. The readback-owner constructor revalidates original T/E/S predecessors and compares config decision, scope, trust/scope/objective digests, full Training signature, and Selector identity. It retains the same original Cell, Trainer and Evaluator capabilities.

Ignoring the returned Recovered boolean is not an elevation here: this host exposes only the existing evidence readback purpose. `evidence_response` calls `readback_evaluated_selection`, never attestation, creation, or recovery. It validates request correlation, acquires the same owner's mutex, reads actual current T/E/Cell and journal evidence, revalidates predecessors after I/O, and requires exact snapshot/receipt/signature/binding equality. The 500 ms evidence-exchange limit, original channel lifetime, and bounded 128-request sequence remain.

**Registration recommendation:** append only this path to the original profile boundary. Row 384 already protects the actual constructor and readback flow; row 266 protects the original profile getter; row 381 protects the evaluated receipt lineage. Its consuming generic factory uses the existing file-level full-signature/stripped-body order fallback. That fallback is narrower than the verifier's unique-function check and is not represented here as an equivalent formal proof. No new row or permission is needed for this additional getter caller.

## 338: the original Selector host consumes deep readback predecessors

Source identity: `circuit_selection_readback_host.rs` blob `4a46b73bb8200bd61a6eb43a6338f3695d80ee04`, 2,169 bytes; e8 and b298 are byte-identical.

[`OriginalCircuitSelectionReceiptOwnerV1::into_command_owner_from_original_readbacks`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_selection_readback_host.rs) consumes the existing Selector receipt owner, its original task-read client, the purpose-fixed original Trainer readback connection, and the opaque D/T results. It reconstructs the actual D→T snapshot at the original observed time, compares the full snapshot against `self.config.decision`, and compares the complete original Training attestation.

It then consumes the existing Trainer readback connection through `bind_original_training`. That binding preserves the initial process/channel/deadline, validates original initial and Dataset context, authenticates the actual Training signature, and returns only the purpose-fixed Training evidence client. Finally the exact `self`, `live`, and bound Trainer client move into `OriginalCircuitSelectionCommandOwnerV1::from_original_receipt_owner`.

The callee in `circuit_selection_command_service.rs` reads the same owner's private original profile, authenticates its strict TrainingNoUpdate context, validates the original task-read client, and compares Trainer initial cut, actor and verifier bindings. It initializes `execution_requested` from the original `readback_only` brand. A recovered owner cannot be promoted by a caller boolean.

**The resulting host is an original Selector command owner, not an entirely read-only actor.** A fresh original owner retains its existing, once-admitted Selector attestation behavior; a recovered original owner remains readback-only. This constructor does not execute that work, create a signer, reopen custody, or grant Version/FinalUse authority.

**Registration/protection recommendation:** append this one path to the factory boundary and add one protected row for this currently unprotected source file. Protect the consuming signature, actual D→T reconstruction, both equality checks, irreversible Trainer connection binding, and the final move into the original factory. Row 270 already protects the callee's private-brand and fixed-context behavior.

## 347: Model host reads the retained attenuated Dataset capability

Source identity: `cell_q24_model_command_host.rs` blob `0418a532daa7460954bec6d421d608c7aa1f16ee`, 9,119 bytes; e8 and b298 are byte-identical.

The exact call in [`OriginalCellQ24ModelCommandHostV1::original_inputs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs) is `OriginalCellQ24DatasetCommandReadbackV1::readback(&self.bootstrap.dataset)`. The field belongs to the same retained `Arc<Bootstrap>`; this is not a path reopen or a caller-supplied snapshot.

### Dataset authorization and currentness

The Bootstrap was constructed from original custody, an actual consumed `OriginalCellQ24DatasetCommandReadbackV1`, an original material-source connection, fixed baseline, original Generator custody, and fixed initial material config. `bind_original_custody` checks the Dataset's initial context, the original material-source context, baseline, signer identity/key binding, and lifetime. It stores the Dataset as an internal Arc. `ready` returns only an Arc clone of the existing ready Trainer; Awaiting, Starting and Fenced are not converted into an owner.

In `cell_q24_material_dataset_readback.rs`, `into_original_dataset_readback` consumes the original Dataset command client, requires its fixed Dataset role and original context binding, checks the actual peer lifetime, rechecks context/time, and permanently sets its existing execution-requested bit before wrapping it. Its field is private and it exposes no Execute or inner-owner extraction. `readback` delegates explicitly to the original client's Readback action.

The original material client correlates request/response, retains the same channel, checks peer lifetime, freshly verifies original signatures/context after I/O, and rejects changed completed signatures. The service Readback branch calls original Experience/Dataset readback only, rereads the original Dataset and Experience and requires full signature equality. The wire enforces the complete two-stage prefix, original Observer actor/principal/controller, exact evidence timestamps, and fixed expiry formula. Missing, Pending and Uncertain remain distinct original states.

### Why the Model host itself must not be called read-only

The host owns an original Model file/witness and one already bound Evaluator material connection. Its fresh constructor requires the Bootstrap's real Fresh origin. `bind` validates initial material and the preregistered panel, then consumes the Bootstrap-wide `model_host_bound.compare_exchange(false,true,...)` once. Recovery has an explicit separate deployment constructor and initializes execution as already requested.

After the Dataset read, `original_inputs` reads actual original Training through `read_original_model_training`, which compares the same Dataset and invokes the SourceBound stage's original readback. It binds the single material connection at most once, obtains fresh Evaluator material outside the Trainer lane, builds the actual D/T/E `Context`, rejects a changed retained context, and authenticates context and material again before returning.

The inspected dependencies preserve the following existing effects and restrictions:

- `cell_q24_model_command_context.rs`: exact two-receipt D and three-receipt Candidate T prefixes; original full T/E signatures and actor separation; exact four-receipt E extension; original panel/objective/trust/scope; Qualified and Proposal-stage prerequisite; full context binding.
- `cell_q24_model_command_effect.rs`: no Execute after the shared admission bit; Readback without an existing Model returns ReadbackRequired; full request/context/Qualified/material checks before the one-time custody take; actual create+commit only in Execute; actual read only in Readback; after-work material re-read, T/Model re-read, equality and final current checks; uncertain admitted errors fence.
- `cell_q24_model_command_lane.rs`: exact Dataset and SourceBound context, original stage readback, then direct delegation to the same original lane for create/recover/commit/read. No Evaluator RPC occurs inside this adapter's lane operations.
- `cell_q24_model_current_admission.rs`: actual original Trainer observation must match the exact Training extension; fresh sealed material input must name the trained Candidate and actual Qualified Evaluation before admission.
- `cell_q24_model_current_owner.rs`: no writer before actual Native/witness I/O and fresh material authorization; explicit deployment recovery may reconcile the old minimum anchor; current read never claims or creates; commit reads an existing result first and otherwise delegates to the original claim/completion algorithm, fencing late uncertainty.
- Already protected `cell_q24_training_model_lane.rs` and `cell_q24_model_proposal.rs`: same original lane and owners locks, original completion/current checks around work, original journal/witness CURRENT and claim/completion behavior.

The Model service separately binds its fixed purpose, nonce, initial context and actual D/T/E context. It maps transport/current/source/owner failures to Uncertain, not a proven missing Model. This audit read that behavior; it does not claim every Model service/wire function is newly source-fenced by the proposed narrow addition.

The independently prepared two retention guards remain necessary and unchanged. This caller audit does not solve the documented inability of the current deterministic original provider to furnish a positive primary experiment, and does not claim an actual Qualified Model publication or a completed ordinary loop.

### Proposed bounded protection

The direct host file currently has zero protected rows. The five Model dependency files listed above also have zero protected rows. The Dataset attenuation/client/service/wire already have protected rows 278/294/276/277; Bootstrap current ready/custody is covered by 273/275; existing Model proposal current/claim rules are in rows 217/223.

The authorized minimal preparation is one new host row plus one row for each of the five directly reviewed Model dependencies, covering only these already-read functions and invariants. Do not replace their genuine Fresh/Recovered/Execute distinctions with a global read-only prohibition. Preserve allowed original recovery reconciliation. No re-keying, new owner, callback, reconnect, or broad caller category is introduced.

The five generic methods in current-owner and the generic `validate_current_material` method cannot use the original verifier's `required_function_order`, whose accepted marker is exactly `fn name(`. They will need the existing full-signature/stripped-body file-order fallback, documented as such, with effective deletion/reordering/upgrade source mutations. The verifier will not be changed, and a fallback will not be advertised as a unique-function or formal safety proof. Nongeneric reviewed functions can use the original function-local checks.

## 365: original C Observer host consumes both distinct readback predecessors

Source identity: `circuit_next_use_readback_host.rs` blob `f8cb73a2b9f87e1c866e74771ba10678ef168f90`, 3,072 bytes; e8 and b298 are byte-identical.

[`OriginalCircuitNextUseReceiptOwnerV1::into_command_owner_from_original_readbacks`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_next_use_readback_host.rs) consumes its original C Observer owner and the original live-task, Trainer-readback and Selector-readback capabilities. It reconstructs D→T→S using each original observed timestamp, then requires:

1. the reconstructed snapshot equals the owner's fixed Selection snapshot;
2. the opaque Selection snapshot equals that same fixed snapshot;
3. the passed Training attestation and the Selection's retained Training attestation both equal the owner's original Training evidence;
4. the Selection attestation equals the owner's original Selection evidence.

The two predecessor connections are separately consumed by their purpose-fixed binders. The exact same `self`, `live`, bound Trainer reader and bound Selector reader then move into the original NextUse command factory. No new evidence is signed by this composition.

The callee in `circuit_next_use_command_service.rs` uses the owner's private Fresh/Recovered profile, verifies the actual task-read context and both predecessor reader initial/actor/trust/scope/objective bindings, and initializes the execution-requested bit from the original readback-only brand. Its strict legacy context requires four receipts, TrainingNoUpdate, retained-baseline Selection, actual T/S signatures and actor separation. It does not route an evaluated five-cut through that legacy profile.

**The result is the original C command owner, not a grant or an execution of C.** New Observer attestation still requires the existing actual task completion and current original predecessors; recovered owners do not gain Execute. The separately investigated typed Trainer expression in `circuit_next_use_receipt_owner.rs` remains a different issue and must be synchronized from its actual verified postimage and row 279 evidence, not rewritten during this audit.

**Registration/protection recommendation:** append only this path to the NextUse factory boundary and add one new host protection row. Protect the consuming signature, exact D/T/S order and timestamps, all full evidence/snapshot comparisons, both distinct purpose-fixed binders, and the final original-factory move. Existing row 281 protects the factory's private brand and same-context checks; 279/295 protect existing owner/context semantics. Root's independent source review reached the same specific custody conclusion.

## Exact candidate boundary delta and preservation obligations

The eventual candidate should add only these five pairs:

| Existing boundary ID | Additional exact product caller |
| --- | --- |
| `learning_original_selector_command_context` | `codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs` |
| `learning_original_selector_command_owner_profile` | `codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_owner.rs` |
| `learning_original_selector_command_owner_factory` | `codex-rs/hepta-agentd/src/circuit_selection_readback_host.rs` |
| `learning_original_dataset_readback_current` | `codex-rs/hepta-agentd/src/cell_q24_model_command_host.rs` |
| `learning_original_next_use_command_owner_factory` | `codex-rs/hepta-agentd/src/circuit_next_use_readback_host.rs` |

All other boundary fields, existing callers, ignored/source-root rules, authority metadata, and original verifier behavior remain. The count remains 534 boundaries. No wildcard or same-prefix admission is appropriate.

Eight new protected rows are planned: three direct hosts plus the five explicitly authorized Model dependencies. If no further scan finding changes the scope, v3.1's 399 rows / 328 unique paths becomes 407 rows / 336 unique paths, preserving all repeated original rows and order. The exact typed-row-279 synchronization is separately pending. This is a preparation estimate, not a frozen v3.2 manifest.

Existing EXPECTED declarations affected by these five registrations occur in:

- `test_original_selector_command_source_closure.py` — context, owner profile, owner factory.
- `test_original_no_update_stage_source_closure.py` — the same context boundary.
- `test_original_training_bootstrap_source_closure.py` — Dataset current readback.
- `test_original_next_use_command_source_closure.py` — C owner factory.

Their existing test functions and unauthorized-caller injections must remain; only the exact expected memberships should track the reviewed source. New sibling source-mutation QA should cover deletion/inversion of each custody equality, moving current/material checks before the I/O they must follow, bypassing Qualified, resetting shared once/admission state, and switching a Readback branch into create/recover/commit. Every negative mutation must first pass the unchanged baseline through the original validator and actually fail after mutation. These are source-fence tests, not runtime execution proof.

The original complete Rust collector and full source membership gate remain mandatory on the eventual frozen source. A local protection test, subset construction, updated EXPECTED tuple, or this static audit is not a full caller-set pass.

## Source identity and limits

The four pre-existing direct host/readback files were fetched independently at e8 and b298 and compared byte-for-byte. Evaluated Selection readback is new in the fixed overlay. Model current-owner differs between e8 and b298: e8 uses the shortened trait UFCS, while fixed b298 uses the explicit concrete `<LockedFileProductEvaluationExecutionStoreV1 as ProductEvaluationExecutionStoreV1>::readback`. The root's frozen 25-file overlay explicitly selects b298 blob `d32eb1681ce8e51b823ed483955d69257a25d981`; the future protection must use those exact bytes. The other four newly protected Model dependencies are byte-identical at e8 and b298.

No recommendation above changes authorization policy or grants live authority. The audit establishes the identity and intended existing behavior of each source seam. It does not prove deployment, independent experimental validity, actual adoption, Model execution, consumer execution, or cold-recovery success. It starts no tests and reports no new gate pass. All original scan failures remain retained.
