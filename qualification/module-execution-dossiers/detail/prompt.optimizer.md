# prompt.optimizer: implementation design

Parent: `docs/modules/prompt.optimizer/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: canonical candidate enumeration, evidence-qualified pricing, constraint-aware portfolio selection and delivery-boundary exercise are implemented at source level alongside the compatibility and local-shadow paths. Cross-owner context/delivery/ledger adapters are source-composed; the real Codex dispatch callsite and independent causal acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented optimizer entrypoints:** compatibility `optimize` in [codex-rs/hepta-prompt-optimizer/src/lib.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib.rs); strict `calculate_local_shadow` in [local_shadow.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow.rs); canonical `enumerate_factors_v1`, `price_factors_v1`, `select_portfolio_v1` and `exercise_v1` in [canonical.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical.rs).
- **Candidate and pricing evidence:** the canonical path reads an exact prompt-registry V2 snapshot/model tuple, deterministically selects one compatible realization per factor, binds completeness, requires generator/evaluator-role signed evidence, and subtracts downside plus token, latency, interference, crowding, privacy, instability and future-context-option costs before selection.
- **Constraint semantics:** knowledge-graph relations bind the generation vector and interaction projection. Required factors are closed transitively and evaluated as bundles, cycles fail closed, conflicts are non-tradable, complement/substitute utility requires independently authenticated pair evidence, and incomplete relation projections are rejected. The solver discloses `HeuristicNoCertificate` rather than claiming global optimality.
- **Delivery-boundary revalidation:** `exercise_v1` rechecks state, generation vector, exact model tuple, expiry, factor revocation and the exact selected realization binding. [hepta-intelligence/src/prompt_pipeline.rs](../../../codex-rs/hepta-intelligence/src/prompt_pipeline.rs) performs a second exercise check before attachment preparation, materializes exact registry payload bytes and binds their occurrence in the serialized provider payload.
- **Delivery and learning handoff:** [hepta-codex-adapter/src/lib.rs](../../../codex-rs/hepta-codex-adapter/src/lib.rs) can emit a typed terminal delivery observation only when caller-supplied bytes equal the expected payload digest and terminal disposition is explicit. [hepta-learning-ledger/src/ledger.rs](../../../codex-rs/hepta-learning-ledger/src/ledger.rs) admits prompt-delivery evidence into the durable owner chain and rejects policy self-observation. Neither adapter fabricates provider execution or outcome/credit.
- **State and recovery:** `prompt.optimizer` remains stateless and owns no registry/graph/ledger mutation. Every canonical optimizer result retains `AuthorityPosture::DENY_ALL`; no receipt grants model/provider/tool/effect authority.
- **Source tests:** [canonical_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_tests.rs), [local_shadow_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs), [lib_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib_tests.rs), [hepta-intelligence/src/prompt_pipeline_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_pipeline_tests.rs), [hepta-codex-adapter/src/lib_tests.rs](../../../codex-rs/hepta-codex-adapter/src/lib_tests.rs), and learning-ledger prompt-delivery/durable tests. These are source test identities, not independent acceptance receipts.
- **Remaining repository-controlled work:** wire the prepared prompt attachment and runtime observation contract into the named real Codex model/provider dispatch callsite and cover that exact callsite with executable product tests. Until then `production_implementation=false` and `productCallerState=not_composed` remain truthful.
- **Remaining external evidence:** independently observed outcomes, conserved credit, longitudinal causal efficacy, operator acceptance, canary, selection, promotion and release remain outside this source package. Signed provenance proves identity/scope, not causal truth. No source change here self-accepts, self-merges or self-releases.
