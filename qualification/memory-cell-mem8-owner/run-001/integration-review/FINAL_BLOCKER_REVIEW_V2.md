# MEM8 final blocker review — v2

Review time: `2026-11-11T06:28:52.941093+00:00`. Local read-only review draft; the original frozen ledger and v1 review files are unchanged.

**All ten original blockers remain open.** Scientific acceptance stays `HOLD`, adoption action stays `NoUpdate`, and production adoption is false. New scored memory actor episodes remain zero.

## Evidence corrections and completed automatic work

Provider evidence now uses the explicitly derived redacted v3 projection and its privacy erratum. Both earlier projections incorrectly copied `world_state.state` despite a false privacy flag. Those original projections and the unattached unsafe v2 archive are excluded. The 64-member replacement was checked independently, including all member hashes, exact scalar derivation, retained `ready` recovery state, and original native log/JUnit identity. The original failed provider attempt remains failed and its physical outcome remains `UNKNOWN`.

The separate full f1fd RMCP execution is now adjudicated: 268 unique passes, zero failures, zero retries, seven unselected cases, equal raw/JUnit/frozen-expected case sets, and unchanged source and CLI. Its original dc96 predecessor remains a 265/3 execution followed by a separate 3/0 recheck; those historical executions are not rewritten or summed into a synthetic result.

Root has published review PR [#5935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5935), commit `2ae5215beaf8d7b7df111a090b82134beae2683d`, tree `12159640adcf073b51f3837e75575e11f5c20233`. All 112 original postimages, the common base and three parent heads match the independently reconstructed Git objects. The original 73 directory trees and four branch roots were recomputed. The source composition is therefore an accomplished action, not a missing external input.

The frozen CI review identifies actual policies: the common review base has no enforced contexts; main names `CI required` and `Architecture required`; the unchanged repository selector chooses `full_repo=true` for these 112 changes. Existing PR CI has been observed scheduling. The initial 11-workflow/20-check snapshot is partial and is not a terminal result. Inspect the combined-head Bazel evidence for existing F2 controls before running only missing bounded checks. Neither ignored provider diagnostic is enabled by the reviewed command selections.

## Protocol and counting boundaries

- At least 69 source groups are hard exclusions. The remaining 16 catalog groups, seven development and nine retention validation, are only an upper bound; complete exposure and verified unseen capacity remain unknown.
- W retains its original minimum of 20 source groups and at least four per role. The historical MEM6 allocation was 16 development plus four retention-validation groups. E requires a separate pre-execution protocol and has no frozen numeric source minimum; W thresholds are not transferred to E.
- G has six passing engineering regression cases and zero executions of its ignored provider case. This is not a scored memory-benefit result.
- The original ordinary provider smoke admitted one logical turn and failed its 20-second completion wait. It remains zero passed/one failed with 12 unselected cases, zero observed provider terminals and unknown physical request count.
- Complete raw archive recovery, logical read fences, fixture owner tests, independent authority, and original owner/effect cold recovery remain distinct milestones.

## 1. WORKING-STATE-SCIENTIFIC-GATE

**Status:** `NOT_MET_SOURCE_CAPACITY_INSUFFICIENT_FOR_EXISTING_W_GATE`. Original blocker closed: **no**.

Historical fixed-selector retention remains 30/84 versus 28/84, with 16 initial no-ops per arm and source-level one-sided 95% lower bound 0.0. The existing W positive-benefit gate is not met. The newly audited released-catalog remainder has only 16 possibly eligible groups (7 development, 9 retention_validation), not enough for W's unchanged minimum 20 even under optimistic exposure assumptions.

### Verified or retained progress

- 69 known source groups are now explicitly excluded; 16 residual groups are an upper bound, with current exposure UNKNOWN.
- W minimum 20 and minimum 4 each role are distinct from the prior campaign allocation of 16 development plus 4 retention_validation.

### Minimum missing inputs

- Current, complete exposure coverage and justified source-group independence for any proposed successor W cohort.
- Additional authorized released-role inventory: at least 4 more total under the optimistic 16-group bound; at least 9 additional development groups if retaining the historical 16/4 allocation.
- A new request with fixed selector/model/OCR/control/budget and source allocation frozen before reference access; preserve the original engineering thresholds and missingness rule.

### Minimum executable next action

First admit a sufficient, independently justified and unexposed cohort using the existing metadata-only freeze checks. Only after that prerequisite is satisfied, register a new paired W campaign and run its independent source-level analysis; keep the original failed gate and no-op accounting unchanged.

Existing entry or artifact: ndu_real_runtime.run_candidate_retention_public; candidate_retention_public_plan.freeze; candidate_retention_inference; ACCEPTANCE.json /prospective_benefit_gate

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- At least 20 source groups and at least 4 per original role, source mean difference at least 0.05, and original source-level one-sided 95% lower bound greater than 0, with the original independence and missingness requirements.

### Insufficient for closure

- Do not pool old exposed cohorts as independent new sources.
- Do not relabel retention_validation as development or sealed holdout.
- These W minima do not become an approved E minimum.

Evidence keys: `ledger_v6`, `source_capacity`, `source_exclusions`, `source_offline_audit`, `acceptance`.

## 2. ORDINARY-OWNER-BRIDGE

**Status:** `NATIVE_FIXTURE_BRIDGE_QUALIFIED_ORIGINAL_DEPLOYED_BINDING_OPEN`. Original blocker closed: **no**.

The bridge is implemented and native-qualified; it should no longer be described as missing bridge code. Exact 66f passed its 11 memory, 5 Agentd and 16 protocol cases on host and GitHub; F2 passed its own focused isolation groups. Exact G compiled the added fixture and passed six existing Agentd controls. The original deployed writer, source adapter and caller binding remain unauthenticated.

### Verified or retained progress

- G 9d9bdfb/07192603: 6 passed, 0 failed, 782 unselected; commit/revoke/panic markers; exact source and CLI unchanged.
- G provider case was not selected; all new G tests here are zero-model controls.

### Minimum missing inputs

- Original authority config, registration, native-profile descriptors, original agent ID/spawn generation/socket/home, and a valid original process capability where a live-owner diagnostic requires it.
- Original canonical store/current cut/recovery requirement and original authority/verifier/lease binding.
- Existing source custody adapter returning exact typed admissions and authenticated withdrawals for the configured namespace; the request must not choose its own verifier or verification level.

### Minimum executable next action

Use the existing original deployment descriptors for diagnose-native, then recover the retained writer with open_with_recovery and install the real source adapter in the original embedding. Submit the current snapshot through the ordinary UDS import and reconcile its original receipt/cut before an explicit context read.

Existing entry or artifact: hepta-authority-host diagnose-native; AgentdProductionWriterHost::open_with_recovery; with_production_writer_host; with_episodic_snapshot_import; AgentdClient::import_episodic_snapshot

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- Actual original-owner import/replay/update/withdrawal and lost-ACK reconciliation with preserved current cut and tombstones, followed by the ordinary source-aware read under the authenticated original caller.

### Insufficient for closure

- A newly created fixture owner, source digest, test-only public role or fresh registration cannot supply original deployment custody.
- V1 retired slots reject reimport, including a newer Python version; full Python rebuild semantics are not qualified.
- Normal configured startup must still receive the actual retained writer and verifier; an unused configurable hook is not deployment proof.

Evidence keys: `ledger_v6`, `g_native_audit`, `g_root_readback`, `original_owner_inputs`.

## 3. PROVIDER-RUNTIME-BINDING

**Status:** `ORIGINAL_TURN_UNSETTLED_AFTER_READONLY_RECONCILIATION_NATIVE_CONTEXT_NOT_EXECUTED`. Original blocker closed: **no**.

The original 55951 ordinary smoke remains 0 passed/1 failed after its 20-second completion wait. Readonly v2 observed the original rollout recovery binding and ready candidate but no assistant or terminal; the original DB/WAL bytes were unchanged. Those findings are now cited through the explicitly derived scalar-only v3 projection and privacy erratum. The prior whole world_state export and its false privacy flag are not accepted as safe evidence. Physical request count and remote model outcome remain UNKNOWN. G is compiled and regression-qualified, but its provider context case has zero executions.

### Verified or retained progress

- Readonly settlement-v2 completed at 2026-11-11T05:29:21.693505+00:00 without network, owner restart or model replay.
- The original thread is 01a1c8ef-125f-75ae-aaf1-0fe5a4c079f6; turn is 01a1c8ef-1fbd-75b0-bc6e-2b22a1f1f596; the ProductClient smoke has no native DurableInferenceControl journal.
- The exact 64-member redacted v3 archive was independently checked: all member hashes, two derived scalar projections, ready-event retention, exclusion of unsafe original projections/nested archives and preservation of the original failed test. This corrects the evidence artifact, not the provider outcome.

### Minimum missing inputs

- The original gateway/provider owner's retained admission, upstream request correlation and terminal/error records for this original logical turn and time window.
- A verified current route/model/native-profile binding and the original final-use authorizer before any later native memory-path call.
- A separately registered later intent only after reconciliation makes its admission unambiguous; retain the original failed request as failed/unknown.

### Minimum executable next action

Obtain existing provider-side correlation and terminal records for the original request without restarting the owner or replaying it. If those records cannot determine the outcome, retain UNKNOWN. After the route and original authority are established, a separately identified native-context smoke can test the compiled path; label any G source and signer as fixture-only.

Existing entry or artifact: Original retained rollout/state/queue/log evidence; hepta-authority-host provider-status; AppServerModelDriver/native_run_control; G ignored fixture only under a separately admitted later intent

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- Original request settlement plus an actual intended native-provider context execution with retained thread/turn/terminal and final-use/source-validation evidence.
- A fixture route smoke does not by itself establish original deployed provider or source custody.

### Insufficient for closure

- No assistant/terminal in a local rollout, zero local token counter, an empty queued binding result or a dead owner PID proves zero physical requests or remote cancellation.
- Do not invent a native journal retroactively, change the original 20-second gate, replay under a fresh key, or treat after-GET 502 as settlement.

Evidence keys: `ledger_v6`, `provider_settlement_v2`, `provider_rollout_redacted_v3`, `provider_queue_safe`, `provider_state_safe`, `g_native_audit`, `original_owner_inputs`, `provider_privacy_erratum`, `provider_redaction_independent_audit`, `provider_redacted_package_manifest`.

## 4. UNSEEN-EPISODIC-BENEFIT

**Status:** `NOT_EVALUATED_E_PROTOCOL_AND_VERIFIED_UNSEEN_COHORT_UNFROZEN`. Original blocker closed: **no**.

There is no new scored memory-benefit actor episode. G six controls and older fresh-reader tests exercise software with zero models. The ordinary admitted turn is not a memory successor comparison. The 69 exclusions and 16 residual upper bound do not admit an unseen cohort.

### Verified or retained progress

- The source inventory now has an exact hard-exclusion list and original-role residual roster.
- E acceptance already requires a separate pre-execution protocol, new sources and sessions, matched history/budget, and four primary baseline contrasts; it specifies no numeric source minimum or role allocation in the inspected E gate.

### Minimum missing inputs

- Complete current exposure history and independent source identities, plus a separately registered E source-unit/power rationale and numeric roster before references/outcomes.
- Ordered predecessor/successor tasks, rubrics and paired on/off identities with matched model, permitted tools, prompts, seeds, initial effects, history, schedule and memory budget.
- Actual actor integration of the intervention and observable delivered content, using source-aware native context and preserving fresh sessions; record failures, no-ops and unknowns in the original denominator.

### Minimum executable next action

Freeze the separate E protocol and its source requirement first, then implement/register the primary durable off/on intervention at the existing native actor boundary. Use the current source exclusions without treating the 16 unknown-exposure residual groups as unseen. Qualify actual path use before running the preregistered paired successor cohort.

Existing entry or artifact: ACCEPTANCE.json /real_successor_task_gate; native_run_control context_query None/Some; AppServerModelDriver; the existing Python episodic mechanism runner remains a control, not the actor study

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- Attributable successor advantage on independently justified, unexposed source groups and fresh sessions; actual content remove/replace/delivery counterfactuals; original four-comparison error control and matched budgets.

### Insufficient for closure

- Do not transfer W's 20/min4 or prior 16/4 as an already approved E minimum.
- A successful future random-fact G smoke would establish a synthetic path observation, not learned predecessor experience or unseen successor benefit.

Evidence keys: `ledger_v6`, `g_native_audit`, `source_capacity`, `source_exclusions`, `acceptance`, `successor_route`.

## 5. STRONG-BASELINES-AND-ASSOCIATION

**Status:** `MECHANISM_PATHS_IMPLEMENTED_MATCHED_REAL_ACTOR_COMPARISON_OPEN`. Original blocker closed: **no**.

Exact KV, BM25/RAG, chronological ICL and uniform read replay exist in Python mechanism paths. No frozen matched real-successor competition or trained association head is qualified. Native optional context query currently switches the explicit path as a whole; it does not implement all separate retrieval, delivery and association interventions.

### Verified or retained progress

- Final source/read freshness and F2 explicit-context profile are tested for the listed software paths.
- The native context limit is four items; equal authorized history and charged context budget must be specified for every baseline.

### Minimum missing inputs

- A common authorized experience/support set, exact key availability policy, baseline implementations and fixed context/token budget at the actual actor boundary.
- A real pinned association head/version and its training/tuning exposure ledger if association is to be tested; absent head stays unavailable.
- Durable intervention identity and receipts distinguishing retrieval, association and actual delivery, with the final selected support still source/owner revalidated.

### Minimum executable next action

Connect one frozen support-selection strategy and the retrieved-but-withheld delivery control to the existing native context route, then add the remaining matched baselines under the same registered E history and budget. Use the source verifier for admission, never for upgrading a ranker's output into authority.

Existing entry or artifact: episodic_retrieval.py strategy paths; native_run_control.rs; cognitive_context.rs and final revalidation; separately frozen E analysis

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- Actual same-task/model/history/budget baseline and ablation executions, including usage-path receipts and the preregistered source-level comparison for each contrast.

### Insufficient for closure

- Uniform record sampling at read time is not optimizer replay.
- Keys cannot be hidden evaluator answer IDs, and larger ICL history cannot bypass the common budget.
- A configured optional association callback without a trained, frozen artifact is not association qualification.

Evidence keys: `ledger_v6`, `successor_route`, `acceptance`, `g_native_audit`.

## 6. SOURCE-OWNERSHIP-EXPOSURE-AND-TRUST

**Status:** `KNOWN_EXCLUSION_UNION_FROZEN_COMPLETE_EXPOSURE_AND_INDEPENDENT_AUTHORITY_OPEN`. Original blocker closed: **no**.

The exact known exclusion union is now 69, with full per-group provenance; a single pinned metadata inventory established the released catalog and the 16-group upper bound. Complete current exposure, factual source custody and independently controlled authority are not established by those bytes or same-owner receipts.

### Verified or retained progress

- All 69 source IDs and the 16 residual original roles are reproducibly pinned.
- Bounded public-role observations are test_only; startup release=false has no observed timestamp. This is not a global absence proof.

### Minimum missing inputs

- A current complete exposure-event ledger with registry/source revision binding, event kinds, all relevant consumers/hosts, reservations/failed requests and an explicit coverage cutoff.
- The original source-owner custody interface and current fact/dependency/withdrawal observations with preserved verification level.
- The original independently controlled final-use issuer's public identity/socket/peer UID and retained epoch/revocation frontier, plus its independently retained rollback/recovery evidence.

### Minimum executable next action

Have the existing source authority attest the current namespace and coverage cutoff against the frozen exclusion list; bind its adapter to the original embedding. Establish the existing independent issuer descriptor/public identity and current frontier, then exercise withdrawal/rollback rejection without replacing either authority with an operator-controlled fixture.

Existing entry or artifact: EpisodicSnapshotVerifier::verify_current -> typed admission; FinalUseAuthorizerConfig/UnixFinalUseAuthorizer; existing owner/source descriptors

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- Authenticated source admission and withdrawal at the original trust boundary, complete declared exposure coverage, and independent-authority resistance to stale/rolled-back owner state.

### Insufficient for closure

- Digest equality cannot grant Verified or establish fact truth.
- The 97 train-role catalog groups are a role restriction, not proof all 97 were actually trained on.
- Source disjointness relative to inspected records is not complete exposure or source-independence certification.

Evidence keys: `source_exclusions`, `source_capacity`, `source_offline_audit`, `original_owner_inputs`, `ledger_v6`.

## 7. DELETION-AND-EXTERNAL-EFFECT

**Status:** `LOGICAL_WITHDRAWAL_AND_EXPLICIT_READ_FENCES_PASSED_PHYSICAL_AND_EFFECT_COMMIT_OPEN`. Original blocker closed: **no**.

Logical tombstones, dependency invalidation, original-owner transaction settlement and explicit context/final-read source checks are tested. Physical erasure, propagation to all actual consumers/caches and commit-time fencing at a real external effect remain unqualified.

### Verified or retained progress

- E retains the current admitted observation and rechecks the original verifier around explicit context reads/revalidation; cold missing observation fails closed.
- F2 disables specified implicit memory paths for configured episodic ingress; G preserves the six related controls.

### Minimum missing inputs

- An inventory of the actual original store/index/WAL/backup and downstream consumer/cache locations, their deletion contract and the authorized withdrawal identity.
- Registered actual effect destination/outbox/target state, effect grant provider and current revoke frontier.
- A defined acknowledgement and external readback criterion for revocation propagation and effect noncommit after the fence.

### Minimum executable next action

Using the existing authenticated owner, qualify one authorized withdrawal through ordinary import to each declared consumer acknowledgement. Inspect physical remnants under the explicit retention/deletion contract and reconcile the same original outbox/target at the actual effect boundary. Add a commit-time check where the real consumer currently lacks it; do not label a completed read check as an effect lease.

Existing entry or artifact: ordinary episodic import and CognitiveContext/Revalidate; AgentdProductionOperationRuntimeConfig/attach_target; production_writer_reconcile.rs::reconcile

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- Measured physical deletion/retention behavior at each declared location, actual downstream acknowledgement, and original-effect readback proving stale authority cannot commit after revocation.

### Insufficient for closure

- Python final-view linearization and NativeAppServer final context revalidation do not create an atomic external-effect lease.
- F2 is not global isolation of direct store callers, all ordinary tools, prompts or skills.
- A fixture outbox with no dispatched effects cannot establish recovery or fencing of the original effect destination.

Evidence keys: `ledger_v6`, `original_owner_inputs`, `successor_route`, `g_native_audit`.

## 8. FULL-OWNER-EFFECT-COLD-RECOVERY

**Status:** `RAW_BYTES_RECOVERED_ORIGINAL_OWNER_TRUST_AND_EFFECT_RECOVERY_OPEN`. Original blocker closed: **no**.

The original raw-copy blocker is closed separately: the complete archive is published, independently reconstructed and restored as files. The ten current blockers do not reopen that copy task. The archive explicitly omits external runtime inputs and does not restore original source custody, live authority, pending inference or real effect state.

### Verified or retained progress

- Complete 61,412,948-byte CAS and 10,365 logical files remain recoverable.
- This source audit reverified the full archive and selected metadata without invoking its runtime.

### Minimum missing inputs

- The original canonical store plus committed cut/recovery requirement, tombstones, retained import receipts and uncertain commit identities, and required external runtime/material inputs.
- The original authority/lease lineage and independent issuer state needed to authorize a successor owner generation; descriptors cannot be newly invented for a different owner.
- The original pending request IDs/journal where one existed, actual outbox/target/destination state and externally observable effect receipts.

### Minimum executable next action

Assemble an owner-authorized recovery manifest for those exact original components, recover them under the existing recovery interfaces into an authorized successor generation, and reconcile original pending requests/effects by identity before any new operation. Verify both memory behavior and actual external effect state after cold restart.

Existing entry or artifact: AgentdProductionWriterHost::open_with_recovery; original lease/recovery requirements; DurableInferenceControl only when originally present; production_writer_reconcile.rs::reconcile

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- A cold-start run using the same original canonical/authority/effect state and authorized lineage, with original pending-operation reconciliation, preserved revocations and external readback.

### Insufficient for closure

- Second-host file restoration is not full-owner recovery.
- A fresh test owner/grant or replacement successful request does not recover the original deployment.
- The ordinary provider smoke has no native durable journal; one must not be invented retrospectively.

Evidence keys: `ledger_v6`, `source_offline_audit`, `original_owner_inputs`, `provider_settlement_v2`.

## 9. FULL-COST-AND-SLOW-CONSOLIDATION

**Status:** `NOT_QUALIFIED_FULL_LIFECYCLE_COST_AND_SLOW_COMPONENT_UNEVALUATED`. Original blocker closed: **no**.

Existing read timing and native phase receipts are limited observations. There is no complete producer/consumer/model/failure/recovery cost account and no qualified slow semantic/skill consolidation component or successor benefit.

### Verified or retained progress

- Source, import/read and native qualification evidence now provides exact phases that a future actor-cost ledger can reference without double counting.

### Minimum missing inputs

- A preregistered lifecycle cost model and instrumentation spanning experience production, source admission, persistence/indexing, retrieval/ranking/delivery, model calls, deletion, failures/retries and cold recovery; unknown energy/prices remain explicit.
- A separately defined slow semantic/skill component with frozen update schedule, source dependencies, revision and withdrawal semantics, plus original artifact identity.
- Matched successor tasks and off/old-state/withdrawal controls with the same model/history/budget and qualified source roster.

### Minimum executable next action

Instrument the first registered actual actor campaign end to end and reconcile its nested phase costs before claiming full cost. Separately freeze and test one real slow update mechanism against no-update/old-state controls; evaluate downstream utility and deletion propagation under its registered schedule.

Existing entry or artifact: Existing episodic receipts and native phase journals; separately registered E actor harness and slow-component protocol

Execution status of this review: `NOT_EXECUTED`.

### Evidence still needed to close this original blocker

- Complete attributable lifecycle cost including failed/unknown paths, and prospective matched successor evidence for the actual slow component with correct revision/deletion behavior.

### Insufficient for closure

- Memory-file growth, store replay, synthetic source checks or native test timing do not measure consolidation benefit.
- Do not add nested evaluation time twice or substitute zero for unobserved provider cost, energy or terminal state.

Evidence keys: `ledger_v6`, `acceptance`, `successor_route`, `source_capacity`.

## 10. HOSTED-CI

**Status:** `COMPONENT_NATIVE_SUBGATES_PASSED_EXACT_COMPOSITION_PUBLISHED_EXISTING_CI_PENDING`. Original blocker closed: **no**.

Historical exact-head focused scopes remain qualified: MEM/66f owner controls, original Windows/Linux signed-credit cases, F2 groups, G six Agentd controls and f1fd full Matrix 30/0. The separately executed full f1fd RMCP run is now independently verified as 268 unique passes/0 failures/0 retries, with seven unselected cases, exact original case IDs and unchanged source/CLI. The original dc96 265/3 execution and separate 3/0 recheck remain unchanged. The actual 112-path composition is now published as PR #5935 at 2ae5215beaf8d7b7df111a090b82134beae2683d, tree 12159640adcf073b51f3837e75575e11f5c20233, with its three original parent heads and all original postimages preserved. Existing PR workflows are observed but their final exact-head outcomes are not yet adjudicated here. The frozen source/branch review is complete: the common PR base has no enforced check contexts, main names CI required and Architecture required, and the unchanged scope selector chooses the existing full_repo workflow path for these changes. This identifies runnable existing scopes without inventing an extra all-target gate.

### Verified or retained progress

- G zero-model native compilation/regression and source/binary checks are now fully audited.
- The original dc96 and f1fd source commits were published unchanged; this removes a source-publication gap without creating new test results.
- The real full f1fd 268-case run was audited independently against raw PASS identities, JUnit identities, original expected IDs, source/binary identity and scoped-fix logs.
- The source composition has been constructed automatically from 112 unchanged original Git blobs. All four branch reconstruction proofs and the resulting root tree were independently recomputed; the published integration commit matches the proof.
- The initial observed integration snapshot contains 11 PR workflow runs and 20 check records. Queued/in-progress/skipped states are not passing executions and the first-page snapshot is not a complete final matrix.
- The complete source/trigger audit read 93 YAML workflows, their README and 13 supporting sources. It confirms the actual existing full_repo selector/fan-in and both ignored provider boundaries; branch-specific skipped proposal jobs are not forced into new requirements.

### Minimum missing inputs

- Actual accepted terminal results and original artifacts for the applicable existing CI jobs on the published integration head; no additional original-owner or provider secret is required for software-only CI.
- Combined-head raw coverage for the existing F2 controls not directly named by the MEM workflow; inspect the already-scheduled Bazel evidence before running only any missing bounded focused checks. The workflow/branch-rule mapping itself is now available in the frozen CI review.
- Any real combined-head compiler/test/lint failure needs its concrete minimal source correction and new exact-head validation; unselected or waived scope remains explicit.

### Minimum executable next action

Continue the already-triggered existing CI on PR #5935 and collect exact-head job terminals/artifacts according to the frozen existing workflow and branch-rule mapping. Inspect combined-head Bazel evidence for the existing focused F2 controls before adding only missing checks. Fix concrete failures with reviewable changes if they arise; preserve previous head results and the provider unknown state. Do not replace this executable CI work with an external-input request.

Existing entry or artifact: PR #5935; 2ae5215beaf8d7b7df111a090b82134beae2683d; existing blocking-ci, architecture and MEM/Windows qualification workflows; CI5935_INITIAL_OBSERVATION.json is an initial partial snapshot, not a terminal matrix.

Execution status of this review: `NO_NEW_EXECUTION_BY_THIS_REVIEW_EXISTING_PR_CI_OBSERVED`.

### Evidence still needed to close this original blocker

- All existing required jobs for the intended integration head have actual accepted terminal results and retained evidence; any waived/unselected scope remains explicitly outside qualification.

### Insufficient for closure

- A package-level Linux/native RMCP 268/0 covers that source, package and environment only; it does not establish Windows/macOS shards or all workspace consumers.
- Bazel lock regeneration/cache cleanup is not execution of the affected Bazel build/test graph.
- Old common-source and individual signed-case passes do not transfer automatically to G plus dependency plus Windows-fix composition.
- Whole-repository checks and Matrix cross-version migration are distinct; no new mandatory test or relaxed existing gate is invented here.

Evidence keys: `ledger_v6`, `g_native_audit`, `g_root_readback`, `g_source_inventory`, `dependency_source_publication`, `full_rmcp_driver`, `full_rmcp_independent_audit`, `full_rmcp_terminal`, `full_rmcp_receipt`, `composition_tree_plan`, `composition_original_objects`, `integration_commit`, `integration_initial_ci`, `ci_required_matrix`, `ci_source_review`, `ci_frozen_source_manifest`.

## Exact active evidence inputs

Paths are workspace-relative. Hashes bind original bytes unless explicitly marked as a derived v3 projection. The old unsafe rollout projections are not active inputs.

| Evidence key | Workspace-relative path | Bytes | SHA256 |
| --- | --- | ---: | --- |
| `acceptance` | `mem-source-exclusion-20261111/inputs/protocol/ACCEPTANCE.json` | 7952 | `d77624e729b02213eec9bc808b94ee27c839a66883d63ede3455a3ca4f6f14ea` |
| `ci_frozen_source_manifest` | `mem-final-composition-readonly/CI_REVIEW_FROZEN_FILES.json` | 30701 | `e13e18d1a5dc61303c989e6e46fce0e9696059b12f84db8781eba8fc401a081c` |
| `ci_required_matrix` | `mem-final-composition-readonly/CI_REQUIRED_MATRIX.json` | 140155 | `60a534369fcdb250abcab2d14b05e1ee73c7f3c4cd198d3dc9f512c5a2227ebe` |
| `ci_source_review` | `mem-final-composition-readonly/CI_REVIEW.md` | 14363 | `a2e4afcbb7567c18da84a6b96ecac896b0cde7aee07b91f2fdf768556292cd2d` |
| `composition_original_objects` | `mem-final-composition-readonly/GIT_OBJECT_PROOF.json` | 1716972 | `ccb155ac832be78df0a3a66270880a5f41aa054a68f35b628c3ed92bc4332afa` |
| `composition_tree_plan` | `mem-final-composition-readonly/GIT_TREE_PLAN.json` | 23708 | `752ba348ffa7399ba74e5c20e29ceb153d0ec2cab7ba8aecc844275f3dd1c953` |
| `dependency_source_publication` | `mem8-dependency-closure/source-publication-readbacks/native/RESULT.json` | 1463 | `d39f2b23ffee677ff87222d78bee1de00358217945d62987a735c9f942230201` |
| `full_rmcp_driver` | `mem8-dependency-closure/run_f1fd_full_rmcp_v1.py` | 9846 | `577777dcb6648f8ab9016dfdd459dcfd4f664858be180e26a9f83c17298e0fbf` |
| `full_rmcp_independent_audit` | `mem-final-composition-readonly/RMCP_FULL_INDEPENDENT_AUDIT.json` | 5128 | `7cec66427494da3711e928c3ade168a61592e09ab2809da87d9a29c00723e5d7` |
| `full_rmcp_receipt` | `mem8-dependency-closure/f1fd-full-evidence-v1/records/full-rmcp-268.json` | 1557 | `f9eefc70b6502fa3ca722ab200b745b6bcf20fd15a65639a8d3216c25202f047` |
| `full_rmcp_terminal` | `mem8-dependency-closure/f1fd-full-evidence-v1/records/RESULT.json` | 622 | `74b09ab11a71efe94975a76320af068c4598e482098408e3f9ba6d77295cf02c` |
| `g_native_audit` | `mem-native-g-9d9bdfb-ai395/NATIVE_AUDIT.json` | 6608 | `69ca626e0dd472a899a480d16720888790bf52db1f98861664222237c9f717d6` |
| `g_root_readback` | `mem8-owner-followup-v7/ROOT_G_READBACK_AUDIT.json` | 2019 | `53f159052c8230fed086ad0c1d0c6ae0df5fffef18ea3c61794f3a749f890208` |
| `g_source_inventory` | `mem8-owner-followup-v7/CURRENT_SOURCES_G.json` | 24806 | `96c3090369cf2739c0cb2c89a178b813e96d6da093866af036b42c5f8bee0082` |
| `integration_commit` | `mem-final-composition-readonly/INTEGRATION_COMMIT.json` | 2476 | `b004e5e5109ee134c9db705a28356167814fe509344d996568ecb8a7e79708e2` |
| `integration_initial_ci` | `mem-final-composition-readonly/CI5935_INITIAL_OBSERVATION.json` | 17760 | `1cebf0e582c4a46602974ce1e3088f19e6cfe7a4e29754256fd9a6257a912d71` |
| `ledger_v6` | `mem8-owner-followup-v6/BLOCKERS.json` | 51551 | `a69108c4f3ea340c20ce54b7977f1ec95362df06a3f7fe8d18af01163d2fe071` |
| `original_owner_inputs` | `mem-stage-g-static-review/OWNER_MINIMUM_INPUTS.md` | 7545 | `fd846ff700b2d21eda9ee86c31bab8755f8ee591e221b02549ee3623266edfde` |
| `provider_privacy_erratum` | `mem8-provider-smoke-observation/provider-safe-v3-complete/PROJECTION_PRIVACY_ERRATUM.json` | 2578 | `f2d74ef113be94dbe182717fa8c42f59eeb3ef62d278bc863528ad77be4697fd` |
| `provider_queue_safe` | `mem8-provider-smoke-observation/provider-safe-v3-complete/readonly-v2/queue_1.sqlite.SAFE_QUERY.json` | 1880 | `b390324b59584653b085aa7a30e1b8470507e10dda55e3fdc41477c47e959785` |
| `provider_redacted_package_manifest` | `mem8-provider-smoke-observation/provider-safe-v3-complete/FILE_MANIFEST.json` | 10933 | `98ec3b1be43d3d949a8f77b1cd8bc97468b04b9332e140df4dd4e0b0f5ece0a8` |
| `provider_redaction_independent_audit` | `mem-final-composition-readonly/PROVIDER_REDACTION_V3_INDEPENDENT_AUDIT.json` | 2474 | `1499e4d43d7de2574b8471a24cc13589bd071a7273c2928cf8d81861edda5d06` |
| `provider_rollout_redacted_v3` | `mem8-provider-smoke-observation/provider-safe-v3-complete/readonly-v2/ROLLOUT_REDACTED_OBSERVATIONS.json` | 5886 | `a1ef90bd7d25647ad33423ca2c9adfbf03de67234f46a7c7f0ff3e9104f386f6` |
| `provider_settlement_v2` | `mem8-provider-smoke-observation/provider-safe-v3-complete/readonly-v2/RESULT.json` | 1281 | `b6b8a70ee0eeba9daeb88c28cc4417fcdcba4a019c9d506c7446c44dda7d2fae` |
| `provider_state_safe` | `mem8-provider-smoke-observation/provider-safe-v3-complete/readonly-v2/state_5.sqlite.SAFE_QUERY.json` | 2699 | `dcdcfde27c698b9508ce51efc25298fc93cf3589783313c8f63150b9838c08a5` |
| `source_capacity` | `mem-source-exclusion-20261111/CAPACITY.json` | 15453 | `b0d2ea6df03c8461024c394e53243d400f512da951ec91dac78e20777cbb714f` |
| `source_exclusions` | `mem-source-exclusion-20261111/EXCLUSIONS.json` | 70615 | `807b08e2a831bca804a3623abc096cd0d9f4053f22b7c9af6317220e7cdb5812` |
| `source_offline_audit` | `mem-source-exclusion-20261111/OFFLINE_AUDIT.json` | 1532 | `d8dd433595f5a5f16a5657bf868592c6670a8d50e4a60332cf0ecdd100d2bae2` |
| `source_report` | `mem-source-exclusion-20261111/REPORT.md` | 12139 | `5dba14d44d68004eba90308ea99b486106d78cd1051bc14152c8997a95cf0b5b` |
| `successor_route` | `mem-successor-readonly/SUCCESSOR_ROUTE_REVIEW.md` | 17200 | `a37d6557b08308d054050b55995ad0851239ffd6b52b9724c9a438eb2f5ce23d` |

## Preservation and review scope

Original v1 JSON: 37147 bytes, SHA256 `f6532abc40ac7219c4dd834c43a61da2be6e7085b08ff4fc454dafaa572139f2`; original bytes retained unchanged.
Original v1 Markdown: 27476 bytes, SHA256 `cf99c12376ddf9bea9afa6cb67322b46efdc18625bb06efb1e2ece7ac8de901a`; original bytes retained unchanged.

This v2 corrects active evidence references, records the actual f1fd package result, and records the actual integration/CI state and frozen workflow policy. All ten original IDs, acceptance thresholds, historical failures and no-op accounting are preserved. The original unsafe archive/manifest objects are named only in the exclusion/erratum record; no unsafe body or projection is included.

This review performs zero host probes, native tests, model calls, original source mutations or ref changes. Its package-level and source-review findings do not predict future CI outcomes or establish original production custody.
