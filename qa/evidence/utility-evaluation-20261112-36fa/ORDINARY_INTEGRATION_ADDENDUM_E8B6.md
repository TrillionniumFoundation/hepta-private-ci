# Hepta utility closure: exact-source addendum at e8b6

## 1. Scope, source identity and conclusion

This is a read-only source audit of commit **e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd**, tree **b607ff5f50812c5e0f932d7dae18d4c74f1269cb**, with ordered parents **19aa601fa09321f1b6d1b3ff3b4d422908004e48** and **726af8f4a345a2ffb148b971f3fa16c71436862d**. It updates the earlier ORDINARY_INTEGRATION_MAP.md audit (immutable Git blob 2059d041fd450c99a04b657eb7d9d04afc2a85db). Every source link below is pinned to e8b6, rather than to a moving branch.

**Two previously proposed pieces are now implemented:** strict Root authentication of the evaluated-retention four-, five- and six-receipt metadata prefixes, and consuming publication that returns the same original Trainer and Evaluator connections. Those are meaningful source changes. They do not complete ordinary authorized A → original Training → independent B → Adopt or complete NoUpdate → new consumer C → daemon and Root cold recovery. The original Version/Selector/C profiles and ordinary startup composition still leave concrete, fail-closed gaps.

This audit also identified an additional composition defect: a complete primary Eligible result is not currently vetoed by a complete Ineligible retention member at two inspected aggregation boundaries. The ordinary Candidate Selection/C route remains blocked; this report does **not** claim an observed erroneous production adoption. A two-file, authority-preserving refusal patch has been prepared separately and is **not part of e8b6**. Section 5 records its exact identities and limits.

No source file, ref or running test worktree was changed for this audit. No new compilation, behavioral test or actual counterexample was run by this audit. Current canonical-head test results must be taken from the separately preserved native/source-gate records.

## 2. What 726 has actually added

### 2.1 Root authenticates the distinct evaluated-retention metadata profile

In [authority_host_learning_resident_auth.rs][rootauth], verify_non_model_attestations recognizes an Evaluation::NoUpdate at index 3 and reconstructs the learning coordinator before accepting the profile. It requires:

- Exactly a four-, five- or six-receipt prefix of Experience, Dataset, Training, Evaluation, Selection, NextUse.
- Actual Training at index 2, an existing changed candidate, and the baseline as next_task_bundle.
- RetainedModelNextUse at the sixth position if it is present.
- Exact request, owner and trust bindings; one complete role-appropriate signature for each non-Proposal receipt.
- Six signatures only for this exact evaluated-retention profile. The legacy TrainingNoUpdate and Model profiles retain their separate limits.
- Full payload verification, matching actor/owner identity, current trust/objective, original signature windows and receipt-observation ordering.
- Pairwise authenticated separation among Trainer, Evaluator, Selector and C Observer: T/E, T/S, E/S, T/C, E/C and S/C. The separation includes the host-pinned controller identity, not merely different keys.

[authority_host_learning_resident_wire.rs::decode_current][rootwire] permits at most six wire signatures and then obligatorily calls verify_original_evidence. Increasing the wire bound alone cannot bypass the exact profile or Model-proof rules.

This is **authentication of observations**. [ResidentOriginalStageOwnersV3::require_stage][rootstages] still refuses Selection and NextUse for a Candidate snapshot without TrainingNoUpdateV2. The concrete [Candidate stage owner][candidateowners] independently keeps the same refusal. The new metadata branch issues no signer, dispatch permission, publication grant or product owner.

The new [retention-auth tests][rootfixtures] explicitly describe signed metadata fixtures, construct no opaque original Selector/C result or actual publication, and require the protected Root checkpoint to stay vacant. Their four named tests use an explicit actual-Root/pre-existing-bind qualification ignore marker. Source presence or an independently run mechanism test is not evidence that ordinary A/B/C deployment or cold recovery has executed.

### 2.2 Evaluated publication preserves the same original T/E custody

[PreparedOriginalCircuitEvaluatedRetentionV1::publish_and_retain_original_evidence][evaluatedpublish] is a crate-private method consuming self. It returns PublishedCircuitFeatureTaskV1 together with the original OriginalCellQ24TrainingCommandClientV1 and OriginalCellEvaluationCommandClientV1.

It performs the existing original T/E CURRENT reads, fixed-context authentication, exact FinalUse publication, cancellation fence and actual published-decision checks. Only after the post-publication checks does it move the same connections into the return value. It does not clone, reconnect, renew signatures, manufacture a new issuer or turn uncertain publication into another prepare. The existing public publish_original_retained_task delegates to it and discards the returned connections as before.

The [four-receipt context][evaluatedcontext] continues to require actual opaque original T/E command receipts, their exact predecessor/signature binding, a changed candidate and a complete evaluated NoUpdate. Its recovered brand is permanently read-only. [recover_original_circuit_evaluated_retention_v1][evaluatedrecover] reads the original Control intent, actual Artifact selection and original Source/Cell state; it has no fresh writer factory, prepare call or replacement FinalUse grant.

These components can be reused by an eventual evaluated Version continuation. They do not yet install that continuation.

## 3. Remaining ordinary-path blockers, by actual boundary

Receipt counts include Experience. The existing TrainingNoUpdate profile is 3 → 4 → 5 receipts. The evaluated-retention profile must remain 4 → 5 → 6. A baseline next_task_bundle does not distinguish them.

| Boundary | Implemented source mechanism | Remaining blocker or external input |
| --- | --- | --- |
| Completed authorized A | [require_circuit_learning_source / require_resident_learning_source_candidate][objective] bind the original Objective RunStart, actual Circuit completion, outbox intent, current generation/admission and owner rereads. | A real admitted task, authenticated objective and actual completion must exist. A profile, fixture or caller-supplied receipt cannot create them. |
| Original Training and independent B | [Evaluated context][evaluatedcontext] requires original T/E outputs. [Original cohort read][cohortread] consumes original independent ledger/source capabilities and checks original training and evaluator evidence. | Real original Trainer custody, independent B/retention runs, current full outcomes and their signed evidence must be supplied. This audit has not deployed or run them. |
| Complete comparison | [prepare_cell_learning_evaluation_v1][learningdecision] revalidates the original signed product qualification and binds exact candidate, baseline, objective, trust and Training predecessor. | Eligibility is still not adoption. The newly found positive-primary/negative-retention composition defect also needs refusal before any positive continuation. |
| Evaluated Version | [OriginalVersionCut][versioncontext] stores the old OriginalCircuitRetainedPublicationContextV1 and original Dataset/Trainer binding; [Version effect][versioneffect] publishes through the old same-model preparation and retains only its Trainer. | No closed evaluated purpose retains and rereads the original Evaluator throughout Version state, wire, current read, installation and recovery. The new T/E-returning helper is available but not wired here. |
| Live read and Selector | [circuit_learning_read_wire::mode][readwire] requires TrainingNoUpdateV2 at index 2 and exactly 3/4 receipts. [Selector authenticate][selector] requires exactly 3 and the same old variant. | The evaluated four-cut input cannot be silently passed through the old reader/Selector. It needs its own exact profile, T/E bindings, original-current dependencies and correct Selection index. |
| New C | [NextUse authenticate][nextuse] expects exactly four receipts, T at 2 and S at 3. [C readback composition][chost] records Dataset → Training → Selection with no Evaluation. | A real evaluated five-cut predecessor, retained original T/E/S custody, all actor separation and actual C completion/readback are absent from this command path. |
| Actual C runtime | [run_original_c][versioneffect] waits for separately authorized publication and consumes the original ordinary factory config once. [install_original][versionc] supplies real Source/Cell configuration. | Starting this runtime does not synthesize authenticated RunStart, deployment permission or completion. It still needs a distinct real consumer task and admission. |
| Candidate stage dispatch | [Candidate execute_stage][candidateowners] and [Root require_stage][rootstages] reject Candidate Selection/C without the old TrainingNoUpdate brand. | Those refusals must remain until actual new original owner capabilities are assembled. Deleting the guards would grant a route without its owner evidence. |
| Cold Candidate recovery | [Candidate validate_recovery][candidateowners] treats any candidate snapshot of length five as the original Model path; longer post-Evaluation snapshots are otherwise refused. | An evaluated Selection at length five needs an explicit semantic discriminator and original readback capabilities. Six-signature metadata acceptance does not repair this routing. |
| Ordinary startup | [main][main] calls startup.receive; [receive][launcher] retains Root learning inputs. [require_root_learning_assembled][assembly] rejects startup while actual stage assembly is missing. | Receiving a descriptor is not assembling original owners. CALLERS still registers no product caller for with_root_learning_stage_owners or into_candidate_runtime. |
| Positive Adopt | [OriginalCircuitModelSelectionReceiptOwnerV1][modelselection] can authenticate and attest an already authorized original Model publication. | Its own source states that ordinary Root Model routing and cross-process custody handoff remain separate. It cannot mint publication/FinalUse or convert eligibility into adoption. The concrete Candidate path still refuses the remaining adoption route. |

Two easy-to-miss interactions require preserving the profile distinction:

1. [RetainedVersionHostStateV1::install_original_selection_reader][versionstate] immediately constructs the old live-read context after installation. Passing an evaluated context through a superficial Version adapter would fail here even if publication had already occurred. [require_cut_current][versionstate] also rereads Dataset and Trainer only.
2. [cell_q24_no_update_stage_auth::stage_index][oldauth] fixes Selection at index 3 and NextUse at index 4, rejects Evaluation/Proposal, and caps the snapshot at five. It is not a general evaluated-retention authenticator.

The [CALLERS registry][callers] has product_callers = [] for the evaluated context creation/recovery, evaluated publication preservation boundary, evaluated recovery, retained Version serve_original_ordinary, Root stage assembly and Candidate resident-runtime consumption. Existing internal delegations are real; these empty registered product-call sets mean the cited public mechanisms cannot be presented as a deployed ordinary integration.

## 4. Four outcomes remain distinct

| Outcome | Exact-source meaning and boundary |
| --- | --- |
| Adopt | A positive evaluation is EligibleForIndependentSelection, then Qualified in the learning observation. It is not an Adopt grant. Original Model, Artifact/Version, independent FinalUse, actual Selector and consumer readback remain separate. |
| Complete Ineligible / NoUpdate | [closure::decide_with_metric_contract][closure] preserves failed_metrics and returns Ineligible only after required evidence is complete. [prepare_cell_learning_evaluation_v1][learningdecision] maps that exact revalidated original result to NoUpdate, without inventing another observation time. |
| InsufficientEvidence / Unknown | Missing required evidence takes priority over a known failed metric in both the main [closure][closure] and the explicitly gated [legacy evaluator][legacyeval]. The learning adapter returns its typed InsufficientEvidence error without an Evaluation receipt. [Panel admission][panelbinding] refuses unknown members. |
| Objective Fraud | Missing, late, revoked, unsupported or incomplete evidence is not made into a deterministic fraud finding by the inspected mappings. No fraud challenge, adjudication or settlement completion is established by this audit. |

[revalidate_product_qualification_v1][qualificationuse] recomputes the exact signed decision under current trust/time and requires full decision equality; matching disposition alone is insufficient. [model_failure][modelfailure] maps Missing, Pending, cancellation and uncertain Model outcomes to refusal/uncertainty, not to a successful NoUpdate.

The bounded mapping review covered these comparison, qualification, panel, learning-adapter and Model-error paths. It did not find another failed-metric-before-insufficient branch in those inspected production paths. This is not a whole-repository proof.

The new retention-combination refusal below is a different issue. Its member comparisons can be complete. Rejecting an incompatible Qualified combination must not relabel those complete comparisons as missing evidence, invent a new aggregate NoUpdate or accuse an actor of fraud.

## 5. Additional concrete finding and separately prepared refusal

### 5.1 The source-level composition gap at e8b6

[require_observed_panel][panelbinding] currently rejects InsufficientEvidence but permits a known Ineligible retention member. It binds the complete retention evidence-digest set. [Owners::read_original_completion][evalhost] then passes only before.primary().qualification() to the original Evaluation receipt owner.

The corresponding current-material verifier [material][materialverify] authenticates every member and the complete panel binding, but lines deriving the learning disposition and returning Checked.qualified use only primary.qualified. [member::verify][materialmember] permits the known eligible and ineligible tags; retention members are not required to be eligible in that aggregation.

Therefore these composition layers do not themselves veto the combination “primary Eligible plus one complete retention Ineligible.” This is a concrete missing comparison condition, not proof of an actually reachable ordinary wrong Adopt. The stricter original provider and the still-closed downstream owner routes limit current execution. No signed positive-primary/negative-retention end-to-end counterexample was executed.

### 5.2 Minimal preparation, not yet this source

**Preparation status: independently reviewed, not executed and not applied.** The coordinating source owner has independently fetched both full postimages and the patch, verified their object/content hashes, and confirmed the exact +14/+8-line-only diff. No maintenance, compile, behavioral test or source-gate success is claimed for this preparation. It remains separate from the e8b6 source under test.

Two existing private boundaries have separate immutable postimages:

| File | Exact e8b6 base blob | Prepared postimage blob |
| --- | --- | --- |
| neuron_cell_evaluation_panel_binding.rs | a3be9f7b415d4783886b346d273296ae8ecb32e5 | 8a779085dd02536a646415406abcaa471b097c10 |
| neuron_cell_evaluation_model_material_verify.rs | c9b8a264cbf51fbf4c405042e1252e931717524a | aea0027ad5f6e51825469b5d8fb8b14d202da575 |

Exact patch: Git blob **91fdfbe4f9e6f9db60d51c2cb93a7b7daeb26425**, 1,903 bytes, SHA-256 **318ca3573e04317d26843e21500845122ec6ad8f667f8c62b3ff9e4471d115e1**. Preparation manifest: Git blob **62aadcb673bed4833bf3c363792d6275b4bfb6a8**, 8,131 bytes, SHA-256 **3a97d3208e57e503501600308cab67f098027f0927cbf4829e1855f2c1166379**. Both full postimages, patch and manifest were fetched back and compared in full.

The proposed conditions are deliberately narrow:

- After existing complete-member/digest/unknown checks, primary Eligible plus any non-Eligible retention returns the existing PanelError::Binding.
- After complete material authentication, primary.qualified plus any retained !qualified returns the existing CommandError::Binding.
- Primary Ineligible with known complete retention continues through the original honest NoUpdate path.
- Unknown remains refused by the existing prior check.
- No wire, digest, frozen plan, role, signature, visibility or registered caller set changes.

The host already calls the guarded panel reader both before receipt production/readback and again before returning it. Material export, current revalidation and original Model-input extraction call the guarded verifier. This is why the preparation requires two production files, not a new owner or a host authority shortcut.

The refusal does **not** re-sign or reinterpret the primary result. Every member result remains unchanged. Current frozen member plans require at least one PrimarySuperiority role; an Ineligible result can mean lack of required superiority rather than an actual regression. The patch does not silently reinterpret that failure as a passed noninferiority contract. Producing a new, complete aggregate NoUpdate from a positive primary plus failed retention would require an explicit aggregation contract accepted by the original receipt owner; that protocol remains separate work.

### 5.3 Honest test coverage boundary

The [actual original panel-member fixture][panelfixture] obtains rows from the original B provider, computes equal supported policies, and explicitly asserts Ineligible. Its assertion and original signature/owner mechanisms were not changed to fabricate a positive qualification. The [material fixture][materialfixture] checks the original negative material and rejects Model input.

The preparation manifest lists existing actual panel, host, material, withdrawal, renewal, missing-outcome and zero-support regressions for a future frozen successor. It contains no claimed execution results. No test-only qualification forging entry, opaque-seal exposure or visibility expansion was added. A valid complete-signature positive-primary/negative-retention execution remains uncovered. Independent source review of the two simple refusal conditions has been completed, but that review does not supply missing execution coverage or replace the existing actual negative/unknown regressions. No end-to-end PASS is inferred.

## 6. Utility, objective, deployment, cost and independence limits

### 6.1 The external objective is represented separately

The [Objective compiler artifact][objectivefunction] preserves admitted objective identity, source and semantic digest, hard constraints, legal action classes, soft dimensions and resource meaning. [Original learning-source authentication][objective] rereads the compiled RunStart and actual completed task under the original source objective. Candidate/B joins require that same objective; [require_arm][records] also compares objective semantic and ObjectiveFunction bytes.

[NduAuthenticatedOwnerV1][ndu] freezes its policy/profile for its lifetime. Evaluation reads contributions under those policies; durable projection mutations consume independently issued, exact FinalUse grants. NDU does not mint those grants. The [NDU specification][nduspec] explicitly separates read-only composition, authenticated production activation and external acceptance.

Predictions, policy choices, posterior Outcomes and evaluation judgments are separately represented in the inspected ledger/evaluation path. This prevents an evaluation receipt from being mistaken for permission to rewrite the target. It does not prove that a real admitted objective is the right user/task objective, that all important hard constraints were registered, or that an external reward/payment contract was correctly chosen. Those are still inputs and governance facts.

### 6.2 A model bundle is more than an adapter, but full deployment comparison is not established

[CellBundleComponentsV1][bundle] binds the base, organ/cell adapters, heads, composition, encoder, tokenizer, normalizer, calibration, numeric profile, schemas and state semantics. [Original retained publication binding][retainedbinding] checks actual A completion, full Q24 manifests and a distinct C source/run rather than accepting a content root alone. [Current material verification][materialverify] checks original generation manifests, complete snapshot preimages, original journal cuts and actual B/retention run distinction.

These are real identity/readback mechanisms. They do not by themselves establish the strongest deployable baseline, a representative real task distribution, the full router/tool/runtime deployment configuration, legal material authorization, sustained model availability or actual new-consumer adoption. A full-system claim must bind those inputs and evaluate the complete deployment. Content identity is not continuous availability or licensing proof.

The [registered panel][panelcontract] fixes nonempty bounded retention membership before training, with distinct plan/task identities. It does not automatically discover old, rare or safety-critical tasks missing from the registration. [Metric roles][roles] freeze primary superiority, noninferiority margins and absolute limits, require a primary objective, and apply each registered gate independently. Selecting the right complete task/constraint set remains external, and the retention-combination defect in Section 5 must be closed before a positive aggregate can rely on it.

### 6.3 The current cost scope is explicitly narrower than full lifecycle net utility

[CellTaskCostV2][cost] retains exclusive charges and separate inclusive envelopes, supports Succeeded/Failed/Cancelled/Rejected/Unknown outcomes, and keeps missing measurements as None. Failed and cancelled work does not disappear from the totals. Its own contract says that digest bindings do not authenticate meters or prove coverage.

[CellComparisonContractV1][cellcontract] freezes common metering/allocation semantics and matched declared capacity, cumulative budgets and selective-update schedules. It reads actual drained Cell task-cost journals, rejects missing stages/Unknown outcomes, and requires known wall/CPU plus any additional preregistered required metrics. The source explicitly says host training counters and receipt references are declarations, not independent proof of all training history.

The decisive limitation is [CellEvaluationCostScopeV1][celleval]: its only value is **TaskLedgersBeforeFinalHoldout**. CellEvaluationRecordV1 explicitly excludes the new holdout estimator, signature verification and publication overhead occurring after the cut. The existence of an Evaluation stage enum in the cost ledger does not expand that actual cut.

In addition, [ProductMetricSourceV1 / derive_metric_gates][runner] derive the registered comparison metrics from IPS, SNIPS or doubly robust outcome intervals. Merely committing a cost record into the estimand is not itself a complete download/activation/search/service/maintenance budget test or payment settlement rule.

Consequently e8b6 cannot be described as proving comprehensive net deployment utility. Such a claim still needs a frozen lifecycle allocation contract, actual meters/ledger cuts for all in-scope attempts including failures/cancellations, search/evaluation/download/activation/service/maintenance coverage, the strongest eligible deployment comparison and all non-compensable authorization/privacy/task constraints. No public reward-contract payout or bonus-maturity completion is established by these inspected boundaries.

### 6.4 Independence checks exceed different keys, but do not prove absence of collusion

[LearningEvidenceVerifierV1 and verify_signed_actor_separation][trust] authenticate exact roles, scope/objective, keys, credential lineage, validity/revocation and host-pinned controller separation. The host is explicitly responsible for the controller mapping; signatures alone do not prove scientific truth or organizational independence.

[Original B readback][cohortread] rejects reuse of the training ledger domain and retains original Source and ledger capabilities. [Episode::read_episode][records] binds the Decision support to its actual Source publication while requiring a separately authenticated nonzero Outcome measurement support, terminal outcome, correct units/delay profile and chronological bounds. Outcome support is deliberately not forced to equal the Decision publication bytes.

Those checks do not inspect all model training genealogies, teacher/judge preference leakage, task-source relationships or undisclosed common operational control. A real independent B therefore still requires truthful host enrollment and evidence for those relationships. No anti-collusion committee theorem is implemented or claimed here.

### 6.5 Action-dependent outcomes have explicit support and critic limits

[AuthenticatedDecisionRecordV2][ledger] carries the run snapshot, objective, policy, selected action/propensity and candidate completeness. Original cohort records join those facts to actual prior state/policy and independent terminal Outcomes. [fit_temporal_fold][fold] fits an earlier-time empirical outcome model, rejects held-out principal/episode/window/decision leakage and unsupported actions. [evaluate_temporal_holdout][temporal] replaces caller predictions with those fitted predictions. This is an implemented temporal separation, not permission to use an arbitrary self-updated critic.

[OPE support checks][ope] reject missing finalized outcomes, unsupported actions, invalid probability distributions, weak support/ESS and excessive weights. In the concrete original adapter, [probability][records] currently accepts only 0 and 1,000,000 ppm, and the signed selected propensity must be one. A changed target action with zero behavior support is refused. This bounded deterministic profile cannot supply general changed-action causal identification.

The statistical and real-world identification conditions—correct recorded behavior policy, consistency of outcomes, adequate support, appropriate dependence/cluster design, no hidden selection leakage and the intended intervention distribution—still need external experimental evidence. Unsupported or unidentified comparisons must stay unavailable/indeterminate, not become complete NoUpdate or earned reward. This audit does not apply ordinary proper-scoring honesty guarantees to an agent that changes the outcome.

## 7. Smallest remaining coherent continuation is a vertical integration

A viable follow-on should reuse the existing original owners and preserve the old strict profile:

1. Add a distinct evaluated Version purpose that consumes the exact original four-cut context and same finite T/E connections. Its state/current read/recovery must retain both owners and the original operation, signature windows and effect-consumption rules.
2. Carry this exact evaluated profile through live-read wire, Selector and C: four-cut decision, five-cut Selection and six-cut completion. Preserve the full Evaluation evidence and all required actor/controller separation; do not simply shift indexes or increase bounds in the old TrainingNoUpdate command.
3. Route recovery by semantic receipt profile, so a five-cut evaluated Selection is not treated as Model Proposal. Recovered custody stays read-only and cannot regenerate prepare, signing or FinalUse.
4. Assemble those real capabilities in the admitted ordinary startup/resident path and register the exact product callers. Do not remove current Candidate refusals until the concrete required owners exist.
5. Independently deliver the actual distinct C admission/RunStart, original Artifact/Control/witness state and exact FinalUse grant, then observe real C readback and separately exercise daemon/Root cold recovery.

This is an implementation boundary, not a completed implementation. A positive Adopt continuation additionally needs the original Model/publication/Selector custody route; evaluated retention cannot stand in for it. The separately prepared retention guard prevents a newly discovered unsafe combination but does not supply the missing aggregate NoUpdate protocol or these owners.

## 8. Evidence and claims that must remain separate

The exact e8b6 intelligence-eval subtree is **3a1254868e95319776765f776eec640df26329e5**, equal to the inspected earlier 19aa/91d subtree. That is Git-object/source equivalence, not a new test execution.

Historical session notes recorded 163 eval library tests at 91d and four actual failing old-precedence controls. Their original raw logs/JUnit became unavailable with the previous transient filesystem. This addendum does not restore them, claim that they ran at e8b6, or convert the prepared replacement control into historical execution evidence.

Likewise, maintenance success, source-gate success, mechanism fixtures, current artifact availability, legal authorization, independent task outcomes, ordinary owner assembly, actual adoption, cold recovery and public reward settlement are distinct claims. This source audit establishes only the specified code facts, refusal preparation and remaining integration/evidence boundaries.

## 9. Core exact-source object index

All entries below are mode 100644. They were resolved from e8b6 Git trees; the eval entries use the identical subtree object named above. The source text was read at the pinned commit.

| Repository path | Git blob | Bytes |
| --- | --- | --- |
| codex-rs/hepta-agentd/src/authority_host_learning_resident_auth.rs | e7de9eb47047a02d56c645e5883ff443585db37d | 13882 |
| codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs | cbbe38c49e7dadcd9397a3ebb6d45ee30a82d0a2 | 7324 |
| codex-rs/hepta-agentd/src/circuit_evaluated_retention_publication.rs | 3e4b82d31a39681d85df560004e2d1d704953cd3 | 9036 |
| codex-rs/hepta-agentd/src/circuit_retained_version_context.rs | a0afe798571bd01683785236201ea2dca52fedca | 6715 |
| codex-rs/hepta-agentd/src/circuit_learning_read_wire.rs | b7a6392ceaf4929714525c6c6e109ec306275957 | 13450 |
| codex-rs/hepta-agentd/src/circuit_selection_command.rs | 15e500215e19d8ee1603535418a1be5cfbb0f353 | 18555 |
| codex-rs/hepta-agentd/src/circuit_next_use_command.rs | f3e2359b83e9b88d8a4cd2751629bda29d7ca7fa | 19782 |
| codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs | a64c659ff63cf38d6704050e633fa65a30848d62 | 11370 |
| codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs | 799af3b9beb9cd12abdad82e7bd7f8aea6cab93c | 6291 |
| codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs | 7916d8905db13c6d8d374152c79f6786781d8ecd | 17941 |
| codex-rs/hepta-agentd/src/neuron_cell_evaluation_contract.rs | 88d0786fe43f21ac82a24cd72f18bb1a530a97f5 | 9606 |
| codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_records.rs | 3f4ec659e2e28ae5c32fddd4d8c338420ce8ffa7 | 18164 |
| codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_binding.rs | a3be9f7b415d4783886b346d273296ae8ecb32e5 | 8237 |
| codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs | c9b8a264cbf51fbf4c405042e1252e931717524a | 10259 |
| codex-rs/hepta-agentd/src/neuron_cell_evaluation_host.rs | 002394b4a405abfdb51c6f80f19a203a68a62e18 | 10958 |
| codex-rs/hepta-agentd/src/config_root_learning.rs | 792703744b84ab6df841035f1e6652e3c7bd71ad | 2102 |
| codex-rs/hepta-agentd/src/production_launcher.rs | 4b615c40566ec351d53861eb2a57d8d85da1c310 | 18594 |
| codex-rs/hepta-intelligence-eval/src/closure.rs | 97d6c9cbc151cb5373ca900a7915f8f38ff941aa | 40741 |
| codex-rs/hepta-intelligence-eval/src/lib.rs | 124be43c3440b99cb9b6f6d0e30d25ffbb533352 | 16039 |
| codex-rs/hepta-intelligence-eval/src/ope.rs | 52fb8b882012f2561c65a95639a63da8e2c12ff4 | 13021 |
| codex-rs/hepta-intelligence-eval/src/temporal_fold.rs | 3447e550262f7b85223a90031620a6b95b11dc69 | 9214 |
| codex-rs/hepta-intelligence-eval/src/product_runner.rs | 3c8f28b3121936b6cf54dff190a055d72ada0a9e | 39047 |
| codex-rs/hepta-intelligence-eval/src/metric_roles.rs | 8916bbdb97f79a8a77da7b1e637b8f51f1296ec2 | 7419 |
| codex-rs/hepta-neuron/src/cell_task_cost.rs | c73cb763cbf2bd753ae44ce74e33da0a3f951772 | 14180 |
| codex-rs/hepta-learning-ledger/src/signed_evidence.rs | 214cae5c9fc4e60598a572faeca5d92c87b0be7f | 15660 |
| codex-rs/hepta-learning-ledger/src/model.rs | ebdec3db9e6c28a7abacffc332d37c0fd6e2e22d | 12595 |
| codex-rs/hepta-objective/src/objective_function_v1.rs | 9a04b17f4b18ed352bdb285f0334b00755e6866e | 18026 |
| codex-rs/hepta-ndu/src/owner.rs | b178fa45920c465d038d57569c4f6556a2dabc84 | 12890 |

[rootauth]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/authority_host_learning_resident_auth.rs
[rootwire]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/authority_host_learning_resident_wire.rs
[rootstages]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs
[rootfixtures]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/authority_host_learning_resident_retention_auth_tests.rs
[evaluatedcontext]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_evaluated_retention_context.rs
[evaluatedpublish]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_evaluated_retention_publication.rs
[evaluatedrecover]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_evaluated_retention_recovery.rs
[retainedbinding]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_learning_retained_binding.rs
[versioncontext]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_retained_version_context.rs
[versionstate]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_retained_version_state.rs
[versioneffect]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_retained_version_effect.rs
[versionservice]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_retained_version_service.rs
[versionc]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_retained_version_c_task.rs
[readwire]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_learning_read_wire.rs
[selector]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_selection_command.rs
[nextuse]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_next_use_command.rs
[chost]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_next_use_readback_host.rs
[candidateowners]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs
[oldauth]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/cell_q24_no_update_stage_auth.rs
[modelselection]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_model_selection_receipt_owner.rs
[modelfailure]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs
[assembly]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/config_root_learning.rs
[launcher]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/production_launcher.rs
[main]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/main.rs
[rootinputs]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/root_production_learning_inputs.rs
[callers]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/CALLERS.toml
[closure]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-intelligence-eval/src/closure.rs
[legacyeval]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-intelligence-eval/src/lib.rs
[qualificationuse]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-intelligence-eval/src/product_qualification_use.rs
[learningdecision]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_learning_evaluation.rs
[panelbinding]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_binding.rs
[panel]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel.rs
[panelcontract]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_contract.rs
[evalhost]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_host.rs
[materialverify]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs
[materialmember]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_member.rs
[material]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material.rs
[materialexport]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_export.rs
[panelfixture]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_original_evaluation_panel_member_support_tests.rs
[materialfixture]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection_support_tests.rs
[objective]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/objective_learning_source.rs
[objectivefunction]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-objective/src/objective_function_v1.rs
[ndu]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-ndu/src/owner.rs
[nduspec]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/docs/modules/utility.ndu/TECHNICAL.md
[ledger]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-learning-ledger/src/model.rs
[trust]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-learning-ledger/src/signed_evidence.rs
[cohort]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_contract.rs
[cohortread]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_read.rs
[records]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_records.rs
[fold]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-intelligence-eval/src/temporal_fold.rs
[temporal]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs
[ope]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-intelligence-eval/src/ope.rs
[roles]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-intelligence-eval/src/metric_roles.rs
[runner]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-intelligence-eval/src/product_runner.rs
[bundle]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-learning-artifacts/src/cell_bundle.rs
[cost]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-neuron/src/cell_task_cost.rs
[cellcontract]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation_contract.rs
[celleval]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd/codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs
