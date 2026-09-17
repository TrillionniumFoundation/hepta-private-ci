# prompt.optimizer: implementation design

Parent: `docs/modules/prompt.optimizer/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: registered V1 candidate-enumeration, pricing, portfolio-selection and exercise surfaces are source-implemented alongside the legacy and strict-shadow calculators; product composition, owner-authenticated adapters and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-prompt-optimizer`.
Packages: `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`.

The operation signatures below are native source APIs in `src/policy.rs`. They remain authority-free library surfaces; source implementation does not establish a product caller, authenticated owner adapter, activation, promotion or release. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`enumerate_factors(registry_snapshot, objective, model_profile) -> PromptCandidateSetReceiptV1`; `price_factors(candidates, causal_estimates, costs) -> PromptPricingReceiptV1`; `select_portfolio(prices, interactions, budget) -> PromptPortfolioReceiptV1`; `exercise(portfolio, registered_boundary, state) -> PromptExerciseDecisionV1`. The four registered V1 receipt structs mirror the canonical protocol field shapes. Companion audit wrappers carry completeness, omitted-count, registry/model binding, pricing decomposition, solver disclosure, per-candidate disposition and exercise validation without adding unknown fields to the registered V1 wire contracts. The module is read-only over the registry and cannot rewrite factor semantics or task objectives.

## 3. State records and transaction design

No authoritative registry state. Candidate, pricing, portfolio and exercise receipts bind objective/state, model tuple, source registry snapshot, complete candidate set, utility/cost/support, interaction graph, constraint graph, solver and timing boundary. Candidate enumeration rejects a non-zero omitted count rather than treating a truncated set as complete. Estimated values carry confidence and applicable scope. Missing causal or cost support produces unavailable pricing instead of an implicit zero-cost benefit. Learning evidence remains owned by `learning.ledger`.

The registered V1 public structs intentionally contain only fields present in `docs/contracts/PROTOCOL_SCHEMAS.json`. Richer audit facts live in authority-free companion types and are digest-bound to the V1 inputs/results. This avoids violating `deny_unknown_critical_fields` while retaining implementation diagnostics.

## 4. Deterministic algorithm and scheduling

Validate compatible admitted and legal realizations; bind registry snapshot and model tuple; enumerate deterministically; price supported causal utility minus token, latency, interference and resource shadow costs; enforce conflict and transitive prerequisite relations; reject `requires` cycles and transitive requirement/conflict contradictions; and run a bounded requirement-closure greedy selector with stable tie-breaking plus deterministic drop-one restarts. The restart pass corrects the legacy highest-single-gain knapsack trap without claiming exact optimality. Every formal portfolio reports `GreedyClosureDropOneV1` with `HeuristicNoCertificate`.

Interactions are sparse by policy rather than silently incomplete. `RejectUnknown` prevents a pair with unknown interaction evidence from co-selection. `SupportedZero(support_digest)` permits omitted edges to mean zero only when the caller supplies an explicit non-zero support reference for the independence/zero-effect assumption. The strict `calculate_local_shadow` compatibility surface keeps its complete-pair fail-closed rule as a conservative oracle.

`exercise` accepts only registered decision boundaries and revalidates portfolio/audit binding, validity window, state, registry snapshot and model tuple before returning `Exercise`, `Wait` or `Abstain`. A decision receipt grants no dispatch or activation authority and does not mutate context mid-generation.

## 5. Capacity and performance profile

Registered policy ceilings are <=128 factors, <=512 explicit interaction edges, <=512 hard-constraint edges, <=16 selected factors and an explicit token budget <=1,000,000. Sparse interaction policy lets a 128-factor candidate set participate in multi-select without requiring the impossible complete graph `C(128,2)`. Unknown edges never silently become zero.

The strict local-shadow surface still requires complete pair evidence whenever more than one factor may be selected; with the 512-edge ceiling that conservative surface reaches at most 32 factor candidates in multi-select mode. That limit is now documented as a shadow-oracle property rather than the production policy capacity.

Pilot ceilings are design/enforcement limits, not latency measurements. Bind target-host measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- POPT-01: conflicts, missing prerequisites, `requires` cycles and transitive requirement/conflict contradictions cannot yield an invalid portfolio.
- POPT-02: missing or invalid causal/cost support yields unavailable pricing, not zero-cost benefit.
- POPT-03: no-intervention, single-factor, pairwise, full-portfolio and fixed/learned timing arms remain independently evaluable.
- POPT-04: registry snapshot, state, validity-window or model-tuple drift invalidates exercise.
- POPT-05: budget 10 with A=(utility 100,cost 10), B=(60,5), C=(60,5) selects B+C rather than the legacy A-only greedy outcome.
- POPT-06: a negative prerequisite may be included when the transitive requirement package has positive marginal utility.
- POPT-07: a 128-factor set can use sparse supported-zero interaction semantics while retaining the 16-selection ceiling.
- POPT-08: every formal policy decision exposes completeness/omission, solver/optimality, binding digests and per-candidate disposition through companion audit data.

Source test identities are in `src/policy_tests.rs`, `src/local_shadow_tests.rs` and `src/lib_tests.rs`. CI execution is still required for the exact candidate; this document is not a pass receipt or independent oracle.

## 7. Integration, rollback and capability ceiling

C1 records actual delivery through Codex before assigning intervention credit. Cross-factor interactions need adequate support: explicit edges carry their own support digests, while sparse zero semantics require a separate support digest and never arise from absence alone. Rollback uses compatible non-revoked factor/realization snapshots and a deterministic no-intervention fallback.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release. The source library still grants `AuthorityPosture::DENY_ALL` and does not itself authenticate registry, graph or ledger ownership.

## 8. Current native implementation

- **Implemented entrypoints:** `optimize` in [codex-rs/hepta-prompt-optimizer/src/lib.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib.rs); `calculate_local_shadow` in [codex-rs/hepta-prompt-optimizer/src/local_shadow.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow.rs); `enumerate_factors` in [codex-rs/hepta-prompt-optimizer/src/policy.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy.rs); `price_factors` in [codex-rs/hepta-prompt-optimizer/src/policy.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy.rs); `select_portfolio` in [codex-rs/hepta-prompt-optimizer/src/policy.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy.rs); `exercise` in [codex-rs/hepta-prompt-optimizer/src/policy.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy.rs). The four registered policy APIs also have audited companion variants for implementation diagnostics.
- **Registered V1 source contracts:** `PromptCandidateSetReceiptV1`, `PromptPricingReceiptV1`, `PromptPortfolioReceiptV1` and `PromptExerciseDecisionV1` are implemented with the canonical registered field shapes. Extra audit data is deliberately not injected into those deny-unknown-critical-fields payloads.
- **Pricing:** `price_factors` consumes scoped causal estimates plus explicit token/latency/interference/resource shadow costs, subtracts all cost components, carries confidence/support, and leaves missing evidence unavailable.
- **Portfolio solver:** `select_portfolio` evaluates transitive prerequisite closures, supports explicit sparse interaction policy, rejects structurally unsatisfiable hard constraints, uses deterministic drop-one restarts, and discloses `HeuristicNoCertificate`.
- **Strict shadow:** `calculate_local_shadow` now evaluates prerequisite closures and explicitly rejects cycles/requirement conflicts while retaining complete-pair evidence as a conservative local oracle.
- **State and recovery:** Pure calculations own no durable receipt store or registry mutation. Registered policy outputs and strict-shadow proposals grant no runtime/effect authority.
- **Source tests:** [codex-rs/hepta-prompt-optimizer/src/policy_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy_tests.rs), [codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs), [codex-rs/hepta-prompt-optimizer/src/lib_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/modules/prompt.optimizer/TECHNICAL.md](../../../docs/modules/prompt.optimizer/TECHNICAL.md).
- **Remaining integration work:** bind these typed inputs to owner-authenticated `prompt.registry` / graph / ledger adapters and a named product caller, validate realization-context compatibility at the real composition boundary, record actual delivery through Codex, and obtain target-host/independent acceptance. None of those gates are implied by source-level API completion.
