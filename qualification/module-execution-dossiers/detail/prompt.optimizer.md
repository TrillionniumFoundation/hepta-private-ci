# prompt.optimizer: implementation design

Parent: `docs/modules/prompt.optimizer/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: bounded portfolio optimization and pair-interaction shadow calculator implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-prompt-optimizer`.
Packages: `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`enumerate_factors(registry_snapshot, objective, model_profile) -> PromptCandidateSetReceiptV1`; `price_factors(candidates, causal_estimates, costs) -> PromptPricingReceiptV1`; `select_portfolio(prices, interactions, budget) -> PromptPortfolioReceiptV1`; `exercise(portfolio, registered_boundary, state) -> PromptExerciseDecisionV1`. It is read-only over the registry and cannot rewrite factor semantics or task objectives.

## 3. State records and transaction design

No authoritative registry state. Candidate, pricing, portfolio and exercise receipts bind objective/NDU, model/tokenizer/template, source registry revisions, complete enumerated/truncated set, utility/cost/support, interaction graph, solver and timing boundary. Estimated values carry confidence and applicable task/model scope. Learning evidence is stored by learning.ledger.

## 4. Deterministic algorithm and scheduling

Validate compatible admitted factors; retain no-intervention; deterministically truncate before assignment; price supported causal utility minus token, latency, interference and resource costs; enforce conflict/prerequisite relations; run a bounded greedy marginal-gain selector with registered stable tie-breaking; compare no-change and fixed portfolios; exercise only at registered boundaries. Report the heuristic/optimality gap or absence of a certificate. Never use unsupported estimated uplift as proof of utility or mutate context mid-generation.

## 5. Capacity and performance profile

Pilot <=128 factors, <=512 interaction edges, <=16 selected factors and explicit token budget; <=128 marginal selection steps. Complete set and omitted-count bounds are recorded. Measure optimization/packing separately from provider latency and report context crowding.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- POPT-01: mutually conflicting factors or missing prerequisites cannot co-occur.
- POPT-02: unknown support/units yields unavailable pricing, not zero-cost benefit.
- POPT-03: no-intervention, single-factor, pairwise, full-portfolio and fixed/learned timing arms remain independently evaluable.
- POPT-04: registry revocation or model-template drift between selection and delivery invalidates the portfolio.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 records actual delivery through Codex before assigning intervention credit. Cross-factor interactions need adequate support, not unmeasured additive claims. Rollback uses compatible non-revoked factor/realization snapshots and a deterministic no-intervention fallback.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Canonical registered policy:** [codex-rs/hepta-prompt-optimizer/src/policy.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy.rs) implements exact-field `PromptCandidateSetReceiptV1`, `PromptPricingReceiptV1`, `PromptPortfolioReceiptV1` and `PromptExerciseDecisionV1` outputs matching the registered V1 schemas. Rich completeness, pricing, solver, registry/model and exercise diagnostics are kept in separate `*AuditV1` wrappers rather than widening the registered contracts.
- **Exact-registry audit pipeline:** [canonical_v1.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_v1.rs), [pricing_v1.rs](../../../codex-rs/hepta-prompt-optimizer/src/pricing_v1.rs), [relations_v1.rs](../../../codex-rs/hepta-prompt-optimizer/src/relations_v1.rs), [portfolio_v1.rs](../../../codex-rs/hepta-prompt-optimizer/src/portfolio_v1.rs) and [exercise_v1.rs](../../../codex-rs/hepta-prompt-optimizer/src/exercise_v1.rs) retain authenticated owner-source, causal/cost evidence, relation, portfolio and delivery-boundary revalidation facts as authority-free audit receipts.
- **Source composition:** [codex-rs/hepta-intelligence/src/prompt_registry_adapter_v1.rs](../../../codex-rs/hepta-intelligence/src/prompt_registry_adapter_v1.rs) derives the candidate source directly from the durable prompt-registry owner. [prompt_delivery.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery.rs) accepts only a validated exercise audit for that exact owner view, dereferences exactly the selected realization IDs/bindings/payloads, and compiles them as one mandatory context group. No substitute compatible realization is allowed.
- **Compatibility:** legacy `optimize` and `local_shadow` remain available but do not define the canonical V1 wire meaning.
- **Source tests:** `policy_tests.rs`, the `*_v1_tests.rs` policy/audit suites, legacy tests and the cross-crate `hepta-intelligence/src/prompt_delivery_tests.rs` are source test identities. Exact-head CI is still required for this candidate; test presence is not a pass receipt.
- **Remaining work:** obtain exact-head/synthetic-merge execution evidence; bind the source-composed path into an activated named runtime host; obtain terminal provider-delivery observation and target-host resource/fault qualification; preserve independent causal/evaluator evidence and operator acceptance. No optimizer receipt grants model/provider authority.
