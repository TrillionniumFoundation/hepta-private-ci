# Retention-guard Rust regression feasibility at the fixed original provider

## Status and exact scope

This is a source-bound feasibility audit, not another Rust test execution. It examines the fixed upstream source `b29869e856d08db1bfb066116a9c443376ccc57d` and the two already reviewed retention-guard preparation postimages listed below. The existing published integration source discussed by the task is `e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`; this report neither republishes it nor transfers any execution result to a later candidate.

**Conclusion:** the current original B provider and the examined frozen strict-superiority plan cannot honestly produce the requested primary Eligible / retention Ineligible panel fixture. The obstacle is the provider's deterministic support contract, not merely the small sample size. There is no existing lower-level production combination entry point, among the inspected layers, that accepts independently authenticated qualifications without the original panel/cohort or complete material custody and could cover the two guards using the existing synthetic positive fixture. No Rust regression patch is submitted: duplicating the predicate, transplanting an incompatible qualification, exposing an opaque seal, or changing the genuine negative fixture would give misleading coverage.

The two new positive-primary rejection branches remain **runtime uncovered by this preparation**. Existing complete-negative and insufficient-evidence tests remain legitimate regression targets; they have not been run by this audit. The independent source-mutation QA protects the presence and direction of the guards but does not establish execution of those Rust branches.

All 27 source inputs used for the conclusions below were retrieved as immutable GitHub blob objects and independently checked against their exact Git blob identity, UTF-8 byte length, and SHA-256. The companion manifest records every path and hash. No production source modification, ref update, Cargo invocation, or desktop operation was performed.

## Prepared production guards remain unchanged

| Boundary | Original blob at fixed b298 | Reviewed preparation postimage | Behavior |
| --- | --- | --- | --- |
| `codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_binding.rs`, `OriginalCellEvaluationPanelOwnerV1::require_observed_panel` | `a3be9f7b415d4783886b346d273296ae8ecb32e5` | `8a779085dd02536a646415406abcaa471b097c10` | After the existing actual-member, Unknown, task, run, and exact retention-digest checks, reject primary Eligible if any retention member is not Eligible. |
| `codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs`, `material` | `c9b8a264cbf51fbf4c405042e1252e931717524a` | `aea0027ad5f6e51825469b5d8fb8b14d202da575` | After the complete original member/signature/material checks and exact E/panel binding, reject qualified primary if any checked retention member is not qualified. |

Both return the existing binding-error type with `qualified original B requires eligible retention`. They do not change a member's decision, relabel a complete negative as missing data, synthesize a composite NoUpdate, or assert fraud. In particular, primary Ineligible is not rejected by the new conditional merely because retention is also Ineligible. Earlier missing/invalid evidence checks still apply.

The already approved changes add 14 and 8 lines respectively. This audit does not change their condition, error semantics, wire format, digest domains, contract, or visibility.

## Why the present original chain cannot supply the desired positive primary

### 1. The behavior policy has deterministic support

In [`circuit_original_evaluation_provider_records.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_records.rs), `Episode::read_episode` requires the authenticated Decision to match the original Source publication, selected action, objective, policy digest, support digest, and canonical complete action set. It also requires `decision.selected_propensity == ProbabilityQ32::ONE` (lines 278–299).

The same file's `probability` accepts only 0 or 1,000,000 ppm (lines 423–428). Intermediate probabilities return `Binding("original deterministic policy profile")`. `observation` takes behavior and evaluated probabilities from the actual original policies, checks their same complete action support, and uses the same independently observed terminal Outcome for both arms (lines 388–420). It does not accept caller-supplied OPE rows.

These are current production input restrictions. Extending them would be an original-provider/provenance protocol change, not a test-fixture repair.

### 2. A valid evaluated policy cannot switch to an unsupported action

In [`hepta-intelligence-eval/src/ope.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-intelligence-eval/src/ope.rs), the OPE row validator rejects `evaluation > 0 && behavior == 0` as `UnsupportedAction` (lines 238–242), also checks valid complete distributions, and rejects zero support for the chosen action.

Consequently, for a row admitted by this deterministic original provider, a supported deterministic candidate and supported deterministic baseline put their unit probability on the same supported action as behavior. IPS and SNIPS use the same outcome and unit weight. DR's model term and correction cancel to that same outcome; changing a critic cannot create a supported policy gain in this case. Both arms also share the same actual target rows and principal-cluster assignments created by `records::assemble`.

This is a source-level deduction under the current provider and plan, not a fresh measured experiment or a general statement about all off-policy evaluation.

### 3. The current frozen primary contract requires strict improvement

[`neuron_cell_evaluation_test_observations.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/neuron_cell_evaluation_test_observations.rs) registers `task-success` as `PrimarySuperiority { minimum_improvement: ZERO }`, with `ProductMetricSourceV1::DoublyRobust` (lines 86–98). `ProviderPlanFixture::for_panel` and `with_original_fixture` bind that registration to the real cohort, Training receipt, candidate and baseline manifests, task, run, and original plan before final-holdout consumption. They do not replace that primary role.

[`metric_roles.rs::decide_independently_v2`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-intelligence-eval/src/metric_roles.rs) requires the direction-adjusted conservative improvement to be strictly greater than the nonnegative margin (lines 63–81); the freeze rejects negative superiority margins and requires a primary objective (lines 135–170). For Maximize this is candidate lower bound minus baseline upper bound. Equal supported arm outcomes cannot satisfy strict superiority, even if a larger sample narrows the intervals.

`product_runner.rs::derive_metric_gates` derives the registered primary interval from the temporal estimates; the available metric sources here are IPS, SNIPS, and DR. Cell cost declarations and actual cost journals are separately bound and checked. Lower declared costs cannot turn an equal DR primary metric into strict task-success superiority in this frozen contract. Changing the role to noninferiority, removing the primary role, changing its source, or changing its margin to evade this result would change the contract.

### 4. Existing tests express that limitation honestly

[`PanelMemberFixture::complete`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_original_evaluation_panel_member_support_tests.rs) runs the actual original execution/Qualification owners and signed product evidence over the two actual Source/Ledger target episodes. It explicitly checks that candidate and baseline DR estimates agree, then checks the computed qualification is `Ineligible`. Those assertions remain correct and unchanged.

[`original_evaluation_provider_refuses_missing_outcomes_renewal_and_zero_support`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_tests.rs) already constructs the changed-candidate-action case. The real evaluation returns the nested `OpeError::UnsupportedAction`, consumes the holdout once, and refuses reuse (lines 332–362). That input cannot honestly be relabeled as Eligible, complete NoUpdate, or fraud.

## Why the existing synthetic positive does not close this gap

`LearningFixture::from_original_training` in [`neuron_cell_learning_evaluation_tests.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/neuron_cell_learning_evaluation_tests.rs) has a useful genuine computed positive mechanism fixture: 8,192 explicitly synthetic clusters, real evaluation, actual signed execution/evidence, and the original strict-superiority contract. It deliberately labels these cohorts as synthetic. Its Ineligible variant replaces the candidate observations with the baseline observations; its InsufficientEvidence variant removes the future-window evidence before the actual evaluator computes the result (lines 287–438).

`EvaluationFixture::new` in `circuit_model_selection_evaluation_support_tests.rs` likewise uses real original execution/Qualification owners over explicit synthetic cohort inputs.

Neither fixture supplies the original B provider's opaque `OriginalCircuitEvaluationCohortReadbackV1`. That capability owns the same original Source views and independent ledger after consumption. Its private `retaining` constructor, exact frozen-plan binding, repeated physical current reads, original training/signature pins, and fenced last-observation checks prevent substituting arbitrary positive OPE rows while retaining an unrelated actual cohort. See [`circuit_original_evaluation_cohort_readback.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/circuit_original_evaluation_cohort_readback.rs), especially `read_current_with_clock`, `require_original_member`, and `authenticate_current`.

Therefore the synthetic positive is a valid single-member/adapter test input, but transplanting it into this actual panel would not be a same-Training, same-plan, same-dataset, same-cohort signed regression. Merely possessing test signing keys does not repair the missing original provenance.

## Lower-level production entry-point assessment

| Existing entry | What it actually requires | Feasibility without forging or broadening access |
| --- | --- | --- |
| `OriginalCellEvaluationPanelOwnerV1::require_observed_panel` | A real owner containing its original primary and retention capabilities; observed member values with task/cohort/prepared qualification context and exact retention digest bindings. The method is private to the panel implementation boundary. | This is the real combination predicate, but the existing public/test fixture route can only obtain the genuine negative original cohort described above. It is not a detached validator of signed qualification pairs. Moving a synthetic positive qualification into an unrelated observed cohort would test an artificial internal value, not the required original binding chain. No new test helper or visibility change is proposed. |
| `OriginalCellEvaluationPanelMemberOwnersV1::read_original` / `authenticate` | Actual current cohort reads before and after, original Cell cuts, completed Qualification bytes, original Training peer, actual execution evidence, and product revalidation against the fixed original config. | A useful real per-member boundary; it rejects incompatible transplanted qualification/evidence before producing a valid panel readback. It does not provide an independent aggregate check. |
| `model_material_verify::material` | Complete original T/E snapshots and signatures, serialized member commitment chains, actual cohort/material proofs, full panel binding, and exact current E. | This is the second real combination boundary. A new boolean or changed decision tag in the body fails earlier authentication/binding and would not exercise the new guard. A valid original positive primary material member with the matching cohort is still unavailable. |
| `model_material_member::verify` | One complete authenticated member commitment chain, including original request, roles, decision, Qualification, and execution. | It checks a member and produces checked fields; it does not implement the retention aggregate. Its output is not an existing public aggregate-validation input. |
| `CellEvaluationRunnerV1::qualify_and_persist` / `OriginalCellEvaluationQualificationOwnerV1::qualify_or_readback` | A real individual computed comparison and its original evidence/publication. | These can evaluate synthetic supported positives honestly at their own scope, but do not accept the whole actual retention panel and do not exercise either new aggregate guard. |

The real production guards are inline within the two complete validation paths. There is no existing detached production aggregation function to call with the genuine synthetic positive and negative qualifications alone. Adding a test that reimplements `primary && any_negative`, manufacturing an opaque cohort, extracting a fake qualification seal, or changing an existing negative assertion would not answer the requested regression question. Such a patch was intentionally not prepared.

This assessment is limited to the inspected original provider, panel, Qualification, and material layers. It is not a claim that a future authorized provider cannot supply a positive original evaluation.

## Honest regression matrix and remaining runtime coverage

The following are existing source-defined tests and intended assertions, not new successful execution results:

| Case | Existing source / test | What it can establish when actually run | What it cannot establish |
| --- | --- | --- | --- |
| Full original negative primary and negative retention | `circuit_original_evaluation_panel_tests.rs::original_panel_reads_actual_b_and_retention_with_full_original_signatures` | Actual member signatures/qualification equality, genuine primary Ineligible, repeated current reads, unchanged files, DENY_ALL. | Execution of the new positive-primary rejection branch. |
| Full negative material and no proposal | `circuit_original_evaluation_model_material_tests.rs::original_evaluation_model_material_reads_actual_panel_and_identical_local_digest`, calling `fixture_original_material_preimages` | Actual original material/current/recovery path; the helper verifies `!checked.qualified` and `Binding("NoUpdate has no model proposal")`, then verifies corrupted authenticated preimages are rejected. | A qualified primary with a genuine negative retention member passing all prior material checks. |
| Missing or unsupported original outcomes | `circuit_original_evaluation_provider_tests.rs::original_evaluation_provider_refuses_missing_outcomes_renewal_and_zero_support` | Missing/out-of-contract original observations reject; unsupported changed action rejects without reusing final holdout. | A completed comparison for the unsupported action, or a NoUpdate/fraud conclusion. |
| Complete single-member negative mapping | `neuron_cell_learning_evaluation_tests.rs::signed_decisions_map_to_original_iteration_without_new_authority` | The actual signed synthetic evaluator maps complete Ineligible to NoUpdate and Eligible to Qualified at the adapter boundary. | Actual independent B deployment, a valid positive original cohort, or aggregate retention acceptance. |
| Insufficient evidence mapping | `neuron_cell_learning_evaluation_tests.rs::insufficient_evidence_keeps_the_original_training_cut` | Actual computed InsufficientEvidence is rejected by the adapter while preserving Training; corrupt signature remains an error. | A completed negative comparison or execution of the new panel/material positive branch. |
| Guard deletion / inversion | Previously prepared source-mutation QA and exact CALLERS protected rows | Removal/reversal of the actual production condition violates the source fence, using the original validator semantics. | Rust runtime behavior or full ordinary closed-loop completion. |

Existing e8 test outcomes remain the original recorded outcomes, including failures and incomplete coverage. Neither this report nor the later source preparation converts them into passes. Future source changes require their own frozen-source validation.

## Minimum honest next coverage step

Within the current authorized two-file guard scope, the appropriate action is to retain the guards, retain the genuine negative and Unknown tests, retain the source-mutation fence, and record the uncovered positive-primary branch. There is no honest minimal Rust test patch that supplies the missing original positive cohort without changing the input/provenance protocol or assembling an incompatible internal value.

A future full signed regression requires an actually supported original B experiment whose independently observed outcomes satisfy the preregistered positive primary contract, together with at least one complete original negative retention result under its own unchanged frozen contract. The original owners must compute and sign those results, retain the same T/E/cost/cohort/current bindings, and refuse a Qualified aggregate without rewriting any member. Exercising current-material revalidation also requires authentic complete original material for that combination, rather than changing a serialized decision tag after signing. This is a missing input/protocol capability to plan separately; it is not authorization here to expand propensity support, change the critic, relax primary superiority, or change the original owner.

If a complete aggregate NoUpdate is later desired for positive-primary/negative-retention, its original receipt owner must explicitly accept an aggregate contract. The current guard is a binding rejection preserving complete member results. It does not authorize that new NoUpdate protocol.

## Execution and mutation record for this preparation

- Rust test executions started: **0**.
- Cargo, just fix, just fmt, native desktop jobs started: **0**.
- Production Rust, fixture assertions, original verifier, wire/digest contracts, and permissions changed: **0**.
- Branch/ref/PR updates: **0**.
- New detached test predicate / opaque-seal constructor / fake positive panel fixture: **0**.
- Source checks performed: immutable text retrieval and Git blob/byte/SHA-256 verification; focused source inspection and deduction.
- Prepared guard state: the two previously reviewed postimages remain unchanged; this report makes no claim they have been executed as a new frozen integration source.

The companion manifest provides exact source inputs and the prepared-guard identities. The report is deliberately a feasibility finding with an explicit coverage gap, not a substituted passing test.
