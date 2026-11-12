# Actual B/retention eligibility obstruction

Fixed source: [ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c). This is a source proof for the current original Circuit provider. It is not an ordinary acceptance or native test result.

## Finding

The current actual B provider cannot produce a successful superiority qualification from its deterministic original policies. This is independent of fixture size, wall-clock freshness, network budgeting and signature correctness. No result has been re-signed, relabelled or promoted to Qualified.

## Exact chain

| Fixed source | Enforced rule |
| --- | --- |
| [circuit_task_source_policy.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c/codex-rs/hepta-agentd/src/circuit_task_source_policy.rs), read | deterministic original policy, not a fixture-only restriction |
| [circuit_original_evaluation_provider_records.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c/codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_records.rs), observation / probability / assemble | the original exact propensities reach both OPE arms |
| [ope.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c/codex-rs/hepta-intelligence-eval/src/ope.rs), estimate_row | nonzero target support at a zero behavior probability fails closed |
| [product_runner.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c/codex-rs/hepta-intelligence-eval/src/product_runner.rs), validate_comparable_observations / derive_metric_gates / ProductMetricSourceV1 | current plan compares policies on one actual behavior/outcome cohort; no separate arm outcome import |
| [metric_roles.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c/codex-rs/hepta-intelligence-eval/src/metric_roles.rs), decide_independently_v2 / role_contract_commitment_bytes | at least one preregistered primary requires strict nonnegative-margin superiority |
| [closure.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c/codex-rs/hepta-intelligence-eval/src/closure.rs), decide_with_metric_contract | a failed primary cannot become Eligible |
| [circuit_original_evaluation_provider_contract.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c/codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_contract.rs), OriginalCircuitEvaluationTargetV1 / validate | one behavior episode and outcome per paired target; finite original cohort membership |
| [neuron_cell_evaluation_model_material.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae8a0b52770e9edd4d0a7938bc3f3c2ea1cce16c/codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material.rs), require_original_model_input | unqualified full E material cannot become original Model input |

The original behavior policy for each row has one action with probability 1. Both the candidate and baseline projected policies have the same deterministic form. The unchanged OPE estimator rejects any evaluation action whose probability is positive while its original behavior probability is zero.

Therefore, whenever both arms evaluate successfully, each must choose that row's unique behavior action. Its importance weight is 1. If the authenticated Outcome is y and the historical outcome-model prediction is m, the per-row contributions are:

- IPS: y.
- DR: m + 1 × (y − m) = y.
- SNIPS: the same mean, because all successful weights are 1.

The common Outcome and its evidence are required to match between arms. All three point estimates are consequently identical. Different interval widths do not help: each conservative interval contains that same point. The direction-adjusted lower confidence improvement is nonpositive. Every valid role plan contains at least one PrimarySuperiority with a nonnegative margin and a strict comparison. It cannot pass.

If the candidate selects a different action on even one row, the original support check rejects that row. Neither more independent rows nor waiting for a live clock changes this alternative.

## Existing actual mechanisms and their limits

The original provider tests already construct actual source publications, independent signed terminal Outcomes, Consumption and physical files. Their equal-policy case produces equal estimates. Their changed-candidate-action case consumes the holdout once and fails with UnsupportedAction. The actual nonempty B/retention panel then computes Ineligible for the equal-policy case. These are useful mechanism controls, not a positive donor fixture.

The pre-existing positive local Model/Selection fixture uses explicit synthetic comparison cohorts. It does not supply the complete original nonempty panel demanded by the new Model material/Version path. The retained Version issuer fixture exercises actual Prepared/Root protocol/FinalUse/C factory for the parent model. It does not cover the new positive Version path.

Accordingly, the new Version publish and post-effect Finish-failure/cancellation branches remain unverified by a full valid original E/Model native fixture. Earlier 150/174 native inventories are not attributed to those branches.

## Minimal legitimate on-policy extension

The requested approach—each arm supplies its own actual on-policy execution and Outcome, while OPE remains unchanged—is statistically compatible with deterministic probabilities and weight 1. **It is not accepted by the existing comparison data contract.**

The legacy Product validator requires the same decision ID, chosen action, Outcome value, Outcome evidence, observation time and behavior distribution. The current producer accepts one original behavior episode/Outcome per paired target, and the temporal input type has one shared target/assignment set. Replacing IDs or Outcomes to fit those equalities would erase original data identity.

A legitimate extension needs a separate typed comparison profile, frozen before Training:

1. Freeze the complete pair membership, exact input/protocol/objective/unit/delay/window and original arm run/episode identities.
2. Retain each arm's own authenticated Decision, Outcome, Source publication, original ledger domain and freeze. Preserve actual record IDs.
3. Verify comparability against the frozen pair contract, including actual principal lineage for clusters. Only the declared bundle, arm and run may differ.
4. Build arm-specific temporal targets/assignments and run the existing OPE/interval estimators unchanged with each arm's original behavior=evaluated policy.
5. Bind the new comparability profile into plan, cohort, raw execution and qualification digests. Keep the old shared-behavior mode unchanged.
6. Obtain candidate evaluation execution only through existing concrete evaluator custody. A LoadedModel or Candidate getter is not production activation or RunStart authority.
7. Only after a real qualified primary and nonempty retention panel exists can the original Model and Version success/Finish-failure fixture execute.

This audit does not implement or authorize a new production grant, change the inference policy, reduce a metric threshold, smooth a zero propensity, or construct a Qualified receipt.

