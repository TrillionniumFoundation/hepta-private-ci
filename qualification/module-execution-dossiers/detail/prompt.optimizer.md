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

- **Implemented entrypoints:** compatibility `optimize` in [codex-rs/hepta-prompt-optimizer/src/lib.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib.rs); `calculate_local_shadow` in [codex-rs/hepta-prompt-optimizer/src/local_shadow.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow.rs); canonical `enumerate_factors`, `price_factors`, `select_portfolio` and `exercise` in [codex-rs/hepta-prompt-optimizer/src/canonical.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical.rs). The canonical path consumes the authenticated prompt-registry V2 snapshot/model tuple, requires evidence for every priced candidate, evaluates prerequisite closures as bundles, and revalidates registry/model/realization compatibility immediately before the registered delivery boundary.
- **State and recovery:** Legacy local proposals remain authority-free. The canonical path emits digest-bound candidate, pricing, portfolio and exercise receipts with `AuthorityPosture::DENY_ALL`; stale registry revisions, revocation/model drift and missing realization compatibility fail closed. `hepta-intelligence::run_canonical_prompt_context_v1` composes an exercised portfolio into the owner-native context compiler without transferring ownership.
- **Source tests:** [codex-rs/hepta-prompt-optimizer/src/canonical_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_tests.rs), [codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs), [codex-rs/hepta-prompt-optimizer/src/lib_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib_tests.rs), and the composition regression in [codex-rs/hepta-intelligence/src/prompt_pipeline_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_pipeline_tests.rs). These are test identities, not independent acceptance receipts.
- **Implementation and operating references:** [docs/modules/prompt.optimizer/TECHNICAL.md](../../../docs/modules/prompt.optimizer/TECHNICAL.md).
- **Remaining work:** Runtime-owned terminal delivery observation still has to be wired at the real Codex dispatch boundary; the learning ledger now owns a prompt-portfolio exposure validation receipt but durable exposure persistence and independently observed outcome/credit remain separate owner work. Pricing evidence digests are mandatory and structurally bound, but an authenticated evidence-provider adapter is still required before causal-support claims can advance. No source change in this package self-qualifies activation or causal efficacy.
