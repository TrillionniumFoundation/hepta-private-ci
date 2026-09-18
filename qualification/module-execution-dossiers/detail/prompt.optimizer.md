# prompt.optimizer: implementation design

Parent: `docs/modules/prompt.optimizer/TECHNICAL.md`. Implementation addendum: `docs/modules/prompt.optimizer/POLICY_PIPELINE.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: the four target policy operation names and registered V1 receipt semantics are implemented in native Rust; legacy `optimize` and `calculate_local_shadow` remain compatibility/shadow primitives. Product composition, authenticated owner adapters and independent acceptance remain open. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-prompt-optimizer`.
Packages: `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`.

The operation signatures in section 2 now have native Rust entrypoints in `src/policy.rs`. Public registered V1 structs retain only the fields registered by `docs/contracts/PROTOCOL_SCHEMAS.json`; richer completeness, pricing and decision diagnostics are companion audit records and do not silently widen the wire contract. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`enumerate_factors(registry_snapshot, objective, model_profile) -> PromptCandidateSetReceiptV1`; `price_factors(candidates, causal_estimates, costs) -> Vec<PromptPricingReceiptV1>`; `select_portfolio(prices, interactions, budget) -> PromptPortfolioReceiptV1`; `exercise(portfolio, registered_boundary, state) -> PromptExerciseDecisionV1`.

Audited variants retain complete-set/omitted-count evidence, pricing decomposition, model/realization compatibility, per-candidate dispositions, heuristic disclosure and registered-boundary evidence without changing the registered public receipt field shapes. The module is read-only over the registry and cannot rewrite factor semantics or task objectives.

## 3. State records and transaction design

No authoritative registry state. Candidate, pricing, portfolio and exercise receipts bind objective/state, model/tokenizer/template, source registry revisions, complete enumerated/truncated set, utility/cost/support, interaction graph, solver and timing boundary through registered fields plus companion semantic digests. Estimated values carry confidence and applicable model/realization scope. Learning evidence remains owned by `learning.ledger`.

The native source validates and binds caller-supplied source-evidence digests but does not authenticate remote owner signatures. Owner authentication for `prompt.registry`, `knowledge.graph` and `learning.ledger` is a composition-adapter requirement and is not source-complete in this crate.

## 4. Deterministic algorithm and scheduling

Validate compatible admitted factors; retain no-intervention outside the factor set; deterministically sort and truncate before assignment; price supported causal incremental recursive utility minus token, latency, context-crowding, instruction-interference, privacy, instability, future-context-option-value and resource costs; enforce conflict/prerequisite relations; run a bounded greedy marginal-gain selector with stable tie-breaking; compare against no-change through the positive-marginal rule; exercise only at registered boundaries.

The selector evaluates a factor's transitive prerequisite closure as one package, so a negative standalone prerequisite can be selected when the dependent package is net positive. `Requires` cycles and conflicts inside a transitive prerequisite closure fail structurally before selection. Selection always reports `HeuristicNoCertificate`; neither the registered path nor legacy `optimize` claims global knapsack/combinatorial optimality.

Interaction graphs expose an explicit missing-edge policy. `AssumeZero` is the sparse-graph path and allows 128 candidate factors with at most 512 explicitly supported interaction edges. `RejectMissing` preserves fail-closed complete-pair semantics when a caller explicitly requires it. Never use unsupported estimated uplift as proof of utility or mutate context mid-generation.

## 5. Capacity and performance profile

Registered policy ceilings are <=128 factors, <=512 interaction edges, <=512 hard-constraint edges, <=16 selected factors, explicit token budget <=1,000,000 and <=128 selection rounds. Complete eligible-set digest and omitted-count bounds are recorded by the audited enumeration path. Sparse interaction semantics remove the previous accidental 32-factor multi-select ceiling from the registered policy path.

The legacy local shadow calculator keeps its historical complete-pair semantics for compatibility; its capacity must not be reported as the capacity of `policy::select_portfolio`.

Pilot ceilings are design targets until exact-head CI and target-host measurement are attached. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- POPT-01: mutually conflicting factors cannot co-occur; missing/unknown prerequisites fail closed; `Requires` cycles and conflict-within-closure fail with structural errors.
- POPT-02: unknown/missing support or cost evidence yields unavailable pricing or a hard error, never zero-cost benefit.
- POPT-03: no-intervention, single-factor, pairwise, full-portfolio and fixed/learned timing arms remain independently evaluable.
- POPT-04: registry, state or model-profile drift between selection and exercise invalidates the portfolio decision path.
- POPT-05: a negative standalone prerequisite may be selected when its transitive dependent package is net positive.
- POPT-06: 128 canonical factor identities can be evaluated in multi-select mode with sparse `AssumeZero` interactions and <=512 explicit edges.
- POPT-07: portfolio audit records a disposition for every graph candidate plus completeness, omitted-count, pricing, interaction, constraint, model and exercise-boundary evidence.

Native source tests live inline under `#[cfg(test)]` in `src/policy.rs`, plus `src/local_shadow_tests.rs` and `src/lib_tests.rs`. These are test identities; a documentation edit is not an execution receipt.

## 7. Integration, rollback and capability ceiling

C1 records actual delivery through Codex before assigning intervention credit. Cross-factor interactions need adequate support; a sparse missing edge means zero only when the graph explicitly selects `AssumeZero`. Rollback uses compatible non-revoked factor/realization snapshots and a deterministic no-intervention fallback.

The registered policy operations and all companion audits remain `AuthorityPosture::DENY_ALL`. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Registered target entrypoints:** `policy::enumerate_factors`, `policy::price_factors`, `policy::select_portfolio`, and `policy::exercise` in [codex-rs/hepta-prompt-optimizer/src/policy.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy.rs), with operation bodies split across the included policy implementation files.
- **Registered V1 Rust semantics:** `PromptCandidateSetReceiptV1`, `PromptPricingReceiptV1`, `PromptPortfolioReceiptV1`, and `PromptExerciseDecisionV1` are native public types. Their fields mirror the registered protocol field semantics; companion audit types carry diagnostics that are not part of the registered wire shape.
- **Pricing:** Native code computes net expected utility from causal incremental utility minus the registered cost classes and binds confidence/support/model/realization evidence. Missing or incompatible evidence is unavailable, not a free benefit.
- **Portfolio:** Native selection is a bounded deterministic prerequisite-closure heuristic, supports sparse interactions, validates `Requires` cycles and contradictory prerequisite/conflict closures, and emits per-candidate decision diagnostics with `HeuristicNoCertificate`.
- **Exercise:** Native code binds a portfolio to a registered decision boundary and rejects portfolio, state, registry, model-profile and expiry drift before emitting an authority-free exercise/wait/no-change decision.
- **Compatibility entrypoints:** `optimize` in [codex-rs/hepta-prompt-optimizer/src/lib.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib.rs) and `calculate_local_shadow` in [codex-rs/hepta-prompt-optimizer/src/local_shadow.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow.rs) remain for existing callers. They are not the registered target policy pipeline and retain their historical heuristic/shadow limitations.
- **Source tests:** [codex-rs/hepta-prompt-optimizer/src/policy.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy.rs) (focused policy tests are inline), [codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs), [codex-rs/hepta-prompt-optimizer/src/lib_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib_tests.rs).
- **Implementation references:** [docs/modules/prompt.optimizer/POLICY_PIPELINE.md](../../../docs/modules/prompt.optimizer/POLICY_PIPELINE.md) and [docs/modules/prompt.optimizer/TECHNICAL.md](../../../docs/modules/prompt.optimizer/TECHNICAL.md).
- **Remaining composition work:** authenticate remote registry/graph/ledger owner evidence in owner-bound adapters; wire a named product caller; attach exact-head and merge-candidate execution evidence; complete independent review/target-host qualification. None of these gates is implied by source implementation.
