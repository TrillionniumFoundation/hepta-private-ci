# Ordinary evaluated-retention integration map

Status: read-only feasibility assessment. The changes proposed below are NOT IMPLEMENTED and have NO ordinary-chain acceptance result.

Intended future evidence path: qa/evidence/utility-evaluation-20261112-36fa/ORDINARY_INTEGRATION_MAP.md

## Source basis and execution boundary

The production audit read immutable source at commit 91d0e10e002d285aec720e9f2b2f3a1d854b4707, tree 8cd35e01cc02146606457a8481ecc1d8dda22158. The subsequent commit 6d0da9fe0cae414975288f23a3779d7bf86e3638 changes only two Python QA expectation files. GitHub commit and compare readback independently confirmed that 19aa601fa09321f1b6d1b3ff3b4d422908004e48, tree 8f7d13bd9e0b737354ea37e62edd88fcc26b8500, has parent 6d0 and changes only two journal calls to explicit trait UFCS in codex-rs/hepta-agentd/src/cell_q24_model_current_owner.rs (+8/-2). The functions mapped below are outside those three changed paths.

The existing eval-library execution evidence belongs to 91d0: original scoped fix and formatting commands passed, then 163 library tests passed with no failures or skipped tests. An isolated local counterexample retained the four new tests and restored only the two old comparator implementations; all four targeted tests failed with actual Ineligible versus expected InsufficientEvidence. Neither those runs nor this source review establish execution at 6d0 or 19aa. They also do not establish the new integration proposed here.

Exact references:

- [Executed source](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/91d0e10e002d285aec720e9f2b2f3a1d854b4707)
- [QA alignment](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/6d0da9fe0cae414975288f23a3779d7bf86e3638)
- [Final mapped source](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/19aa601fa09321f1b6d1b3ff3b4d422908004e48)

## 1. Feasibility conclusion

A separate evaluated-NoUpdate purpose can reuse the existing original Version owner, publication custody, independent FinalUse issuer and ordinary C factory. It requires no new signing authority, lease, CURRENT owner or reward definition. The existing generic learning observations and retained-task operation identity already express the required result.

A useful implementation must carry the original Evaluation through Version, live publication readback, Selector, C Observer and Root recovery. Adding a request discriminator to Version alone would leave a publication that the current read/selection path refuses. The smallest complete ordinary-path scope is therefore a vertical evaluated-retention slice, not an isolated context or DTO change.

Keep the existing strict TrainingNoUpdate purpose unchanged. Add an internally selected, closed evaluated-NoUpdate profile to the same original owners and state machines. Do not select authority from an untrusted branch tag, widen the legacy three-receipt rule, install a callback that manufactures owners, or duplicate the publication runtime.

The new slice should cover a complete negative independent evaluation retaining the original deployed model. Qualified Evaluation followed by Model proposal and adoption remains a separate path requiring its own complete original capabilities.

## 2. Actual reusable mechanisms

All paths below are relative to the repository root.

| Existing source and function | Actual reusable behavior |
| --- | --- |
| codex-rs/hepta-agentd/src/circuit_evaluated_retention_context.rs: OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation, recover_original_evaluation, authenticate, require_current | Accepts original opaque Trainer and Evaluator results. Requires the exact four-receipt cut, changed Candidate, Evaluation::NoUpdate, original T/E signature and actor separation, frozen scope, and actual current T/E owner readback. Recovered context stays read-only. |
| codex-rs/hepta-agentd/src/circuit_evaluated_retention_publication.rs: prepare_original_circuit_evaluated_retention_v1 and PreparedOriginalCircuitEvaluatedRetentionV1::publish_original_retained_task | Consumes real original publication inputs, independently selected Artifact, CURRENT and exact signed FinalUse. It calls the existing same-model generation preparation/publication and returns an actual PublishedCircuitFeatureTaskV1. |
| codex-rs/hepta-agentd/src/circuit_evaluated_retention_recovery.rs: recover_original_circuit_evaluated_retention_v1 | Resolves the original intent through actual retained owners. It performs readback, with no prepare operation, fresh writer or new grant. |
| codex-rs/hepta-agentd/src/neuron_generation_update_learning.rs: learning_retained_task_operation_id_v1 | Commits the complete authenticated decision head into the retained-task operation. The four-receipt decision therefore gets its own exact operation while using the existing CURRENT wire. It also resolves the same predecessor from completed retained-use snapshots. |
| codex-rs/hepta-agentd/src/circuit_retained_version_effect.rs: prepare_original, publish_original_final_use, run_original_c | Provides consumed-phase ownership, one-time preparation/publication/runtime bits, uncertain-effect handling and the ordinary C runtime entry. |
| codex-rs/hepta-agentd/src/root_retained_version_issuer.rs: AgentdUnixFinalUseGrantProvider::into_original_retained_version_issuer and OriginalRootRetainedVersionIssuerV1::request_for_original_retained_version | Attenuates an already held protected Root issuer connection. The exact prepared binding uses destination agentd.cell-generation.next-task-same-model. This wrapper creates no replacement policy or signer and does not restore an already requested/denied operation. |
| codex-rs/hepta-agentd/src/circuit_retained_version_c_task.rs: OriginalCircuitRetainedTaskInputsV1::install_original | Consumes existing C files/configuration and calls AgentdConfig::with_q24_circuit_task_profile. It creates actual original Source/Cell owners and ordinary driver configuration; authenticated C RunStart still arrives separately. |
| codex-rs/hepta-agentd/src/circuit_retained_version_service.rs: serve_original_ordinary | Joins the real command service, original FinalUse worker and ordinary C runtime. This is a real mechanism, but its current CALLERS entry has no product caller. |
| codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs: OriginalCellEvaluationCommandConnectionV1::recover_from_original_stream, bind_original_training, bind_recovered_training; OriginalCellEvaluationCommandClientV1::readback | Provides an already held, peer/pidfd-bound original E channel and explicit readback-only attenuation. Late binding preserves its original lifetime; no new Evaluation needs to be executed by Version, Selector or C. |

One concrete ownership adjustment is necessary: evaluated publish currently returns only the published task and consumes its T/E clients. The Version state must retain those original clients for subsequent current reads. Add a private consuming transfer analogous to the existing strict publication's publish_and_retain_original_trainer, returning the task and original T/E handles after successful publication. It must not expose keys, recreate a client, reconnect, or restore an execution bit.

## 3. Receipt shapes must remain distinct

| Profile | Decision cut | After original Selection | After actual retained C use |
| --- | --- | --- | --- |
| Existing TrainingNoUpdate | Experience, Dataset, TrainingNoUpdate: 3 receipts | 4 receipts | 5 receipts |
| Proposed evaluated NoUpdate | Experience, Dataset, Training, Evaluation::NoUpdate: 4 receipts | 5 receipts | 6 receipts |
| Qualified / Model proposal path | Evaluation::Qualified precedes its actual Model proposal | Separate proposal/adoption contract | Outside this proposed negative-result slice |

The evaluated branch must retain the original trained Candidate and complete negative B evidence even though the next task uses the original baseline. A baseline next_task_bundle alone is insufficient to distinguish these profiles: a different Model proposal disposition may also retain the baseline.

## 4. Minimum complete change boundary

### Version command and state

Extend the existing Version host with a private closed profile carrying either the existing strict original context or the original evaluated context. Preserve fresh versus recovered origin independently of the profile. New admission must consume the original D/T/E capabilities and initial host pins; arbitrary future snapshots or booleans cannot create the evaluated branch.

Add a distinct fixed wire purpose and commitment domain. A possible name is runtime.learning.original-evaluated-retained-version.command.v1; this is a proposal, not an existing operation. Bind the original initial context, operation, full four-receipt head, complete original signatures and action. The request still carries no uploaded observation, publication permission, files, key or FinalUse grant.

Relevant existing files are circuit_retained_version_context.rs, circuit_retained_version_host.rs, circuit_retained_version_state.rs, circuit_retained_version_wire.rs, circuit_retained_version_client.rs, circuit_retained_version_effect.rs and circuit_retained_version_service.rs under codex-rs/hepta-agentd/src/.

Use the same prepared/installed state machine, Artifact/CURRENT observations, issuer and C factory. Preserve phase.take(), one-time bits, original deadlines, dropped-queued-request handling and same-operation readback after uncertain effects. Recovery must construct only a read-only original evaluated context and verify the exact original intent.

### Live publication readback

The current circuit_learning_read_wire.rs::mode accepts only TrainingNoUpdateV2 at receipt index 2, with lengths 3 for Selection and 4 for NextUse. context_binding authenticates T and optional S, and decode uses Selection index 3. OriginalCircuitLearningReadContextV1 has no Evaluation evidence field.

The evaluated purpose needs explicit 4-receipt Selection and 5-receipt NextUse profiles, retaining and verifying T/E and then T/E/S. Preserve the legacy mode and commitments. Derive the accepted profile from the concrete original context, not a widened length interval.

This is mandatory at publication time: circuit_retained_version_state.rs::install_original_selection_reader immediately builds OriginalCircuitLearningReadOwnerV1. Feeding it a four-receipt evaluated cut under the old mode would fail after publication. The physical task owner read itself is reusable; the strict context and wire binding must be extended coherently.

### Original Selector

circuit_selection_command.rs::OriginalCircuitSelectionCommandContextV1::authenticate requires exactly three receipts and a TrainingNoUpdateV2 last observation. circuit_selection_receipt_owner.rs::training_receipt has the same strict requirement. circuit_selection_readback_host.rs::into_command_owner_from_original_readbacks reconstructs D/T only.

Add evaluated-purpose admission to the existing original Selector owner, with actual D/T/E readback, original E evidence retained in its context, command response and journal binding, and appropriate original role/controller separation. Use its existing key, journal and witness. Its actual Selection becomes receipt 5. Current owner reads must verify E as well as T and the actual publication; a cached E result cannot substitute for a later read.

The command, wire, evidence/readback service and durable receipt configuration must agree. Preserve the existing strict constructor and rejection paths.

### Original C Observer

circuit_next_use_command.rs::authenticate requires four receipts, with T at index 2 and S at index 3. Its command wire also reads Selection index 3. circuit_next_use_receipt_owner.rs::authenticate_predecessors currently accepts a two-element T/S array. circuit_next_use_readback_host.rs::into_command_owner_from_original_readbacks reconstructs D/T/S and has no E.

Add the evaluated T/E/S profile throughout the existing C Observer owner, command/wire and readback composition. Actual C still requires the separate new run, original Source/Cell observations, committed-step receipt and task publication. The resulting RetainedModelNextUse is receipt 6. Publishing or starting a daemon is not evidence of C completion.

### Candidate adapter and Root

The existing cell_q24_candidate_stage_owners.rs::execute_stage refuses Selection/NextUse when TrainingNoUpdateV2 is absent. Keep that refusal for unsupported profiles. Add a positively authenticated evaluated-NoUpdate branch only when the concrete Version, Selector and C capabilities are installed.

Do not delegate the new shape directly to common NoUpdate handling: cell_q24_no_update_stage_auth.rs::stage_index fixes Selection index 3 and NextUse index 4; require_snapshot also caps the original profile at five receipts.

The Candidate adapter's receipt_attestation and recovery routing must retain original E/S/C evidence. Root's purpose admission, full signature validation, protected checkpoint and recovery joins must use the same closed profile.

### Actual production assembly and caller proof

At the inspected source, CALLERS.toml records product_callers = [] for the evaluated context/prepare/publish/recover boundaries, OriginalCircuitRetainedVersionHostV1::serve_original_ordinary, RootResidentLearningRegistrationV3::into_candidate_runtime and AgentdConfig::with_root_learning_stage_owners.

A complete integration needs an actual ordinary startup or original Root host caller consuming the supplied original capabilities, not just another public factory. The startup receive path retains the Root learning capability; run still requires actual assembly via require_root_learning_assembled. Register the real new callers and their exact source guards. Existing authorization and old-purpose refusal checks must stay enforced.

## 5. Two additional Root integration traps

1. **A future five-receipt evaluated Selection would be routed as Model.** In cell_q24_candidate_stage_owners.rs::validate_recovery, candidate().is_some() plus receipts.len() == 5 immediately invokes read_original_model. The proposed evaluated Selection also has five receipts. Dispatch must inspect the actual authenticated observation/profile, not length alone. This is a blocking integration collision, not an already admitted five-receipt evaluated path.

2. **A completed evaluated-retention chain has six original signatures.** authority_host_learning_resident_auth.rs::verify_non_model_attestations currently rejects signatures.len() > 5 and separately requires training_no_update_v2().is_some() for Selection independence checks. The new explicit evaluated profile needs its full six signatures and T/E/S/C predecessor separation. Blindly increasing the global maximum or deleting the Selection guard would admit shapes whose owners are still absent.

authority_host_learning_resident_stages.rs::ResidentOriginalStageOwnersV3::require_stage also refuses Candidate Selection/NextUse without TrainingNoUpdateV2. Its new admission must depend on the installed concrete evaluated-retention branch and original capability checks. Qualified/Model adoption remains independently gated.

## 6. Real external inputs required

The source implementation cannot supply these merely by constructing records:

- An actually authorized task A, its original completed Source publication, correct drained predecessor and original training custody.
- Actual complete independent B and registered retention results under the frozen objective, evaluation/cost profile and trust contract; their original current owners and original T/E signatures.
- The original Artifact owner, independently signed selection and withdrawal state, accessible authorized baseline model material, CURRENT owner, original intent and target files/witnesses.
- The independently delivered original protected Root FinalUse issuer and authorization for the exact prepared same-model binding. The resident learning grant does not supply this permission.
- The original Selector and C Observer keys/journals/witnesses, with the relevant frozen role/controller separation and actual readback sources.
- Pre-held original process/UID/pidfd-bound channels for each command/readback purpose, including E. Waiting for D/T/E readiness must not create a new absolute lifetime or reconnect a spent channel.
- Actual C configuration and files, a distinct run/session, loaded original baseline model, and C's separately authorized deployment and authenticated RunStart. Completion requires real committed work.
- Original daemon and Root recovery custody, protected checkpoint/lease state and the same operation/intent. Cold evidence cannot re-grant work or reopen a consumed phase.

The current Candidate initial constructor also requires its original Model descriptor. This assessment does not remove that requirement or treat a negative Evaluation as an adoption grant.

## 7. Proposed acceptance, not executed acceptance

A reviewable implementation should demonstrate a complete original-owner negative-result path using real physical Source/Cell/CURRENT observations, independent FinalUse and actual C completion, then read-only daemon and Root recovery on the same frozen source. Keep raw execution records and exact before/after identities.

Required adverse cases include:

- Old three-receipt purpose rejects evaluated cuts; the new purpose rejects old cuts, missing E, Unknown evidence, Qualified E and unrelated Model proposal shapes.
- Changed T/E/signature windows, mismatched predecessor, revoked/expired evidence or swapped original peers cannot create a Version preparation or a successful completed NoUpdate.
- Original E is checked at publication, Selector, C observation and recovery boundaries; stale stored bytes alone are insufficient.
- Lost ACK, cancellation or failure after prepare/publication cannot cause a second prepare, reissued FinalUse, regenerated E or fresh C factory. Recovery reports the original state or remains uncertain.
- Evaluated Selection at receipt 5 takes its actual Selector route; six-receipt completion authenticates all required signatures while unsupported seven-receipt/adoption shapes remain rejected.
- An actually committed new C run is required; publication, daemon startup, a content root and a supplied future receipt are insufficient.
- Original caller restrictions and legacy rejection tests remain effective, with exact-source verification for all changed production boundaries.

No proposed code, ordinary A/B/C execution, new owner purpose, deployment or cold-recovery acceptance was performed in this audit.

## 8. Focused four-outcome follow-up audit

The follow-up searched the actual production mappings in the two eval comparators, signed admission/product revalidation, panel aggregation, learning bridge, learning-iteration coordinator, evaluated-retention context/recovery and Candidate Model error mapping.

No additional branch was found in that reviewed scope where a known failed metric takes precedence over missing required evidence and produces a complete Ineligible/NoUpdate result.

Specific observations:

- hepta-intelligence-eval/src/closure.rs::decide_with_metric_contract and the explicitly gated legacy lib.rs::evaluate now choose InsufficientEvidence before failed_metrics. Known failed_metrics remain retained.
- hepta-intelligence-eval/src/product_qualification_use.rs::revalidate_product_qualification_v1 recomputes and compares the complete signed decision, not just its disposition.
- hepta-agentd/src/neuron_cell_evaluation_panel_binding.rs::require_observed_panel rejects an InsufficientEvidence member before sealing the complete panel.
- hepta-agentd/src/neuron_cell_learning_evaluation.rs maps complete Ineligible to LearningEvaluationDispositionV1::NoUpdate; InsufficientEvidence returns a typed error before an Evaluation receipt is prepared.
- hepta-learning-artifacts/src/learning_iteration.rs retains distinct TrainingNoUpdate, evaluated NoUpdate and Model proposal observations; a NoUpdate decision still requires Selection and actual next-task use.
- hepta-agentd/src/cell_q24_candidate_stage_model.rs::model_failure maps missing/pending/uncertain owner state to errors, not a successful NoUpdate.
- No automatic conversion of missing evidence into objective fraud was found in these reviewed paths.

This is a bounded read-only finding, not a proof that all repository code is defect-free. It adds no fraud verdict, scientific effectiveness claim, committee independence guarantee or complete deployment-cost acceptance.
