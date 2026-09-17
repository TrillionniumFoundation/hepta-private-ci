# prompt.optimizer: implementation design

Parent: `docs/modules/prompt.optimizer/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: bounded shadow calculators and the authority-free V1 candidate/pricing/portfolio/exercise policy surface are source-implemented; authenticated owner adapters, product composition and independent acceptance remain open. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-prompt-optimizer`.
Packages: `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`.

The operations below are native source APIs under `codex_hepta_prompt_optimizer::policy`. Registered V1 receipt structs preserve the exact field shapes in `docs/contracts/PROTOCOL_SCHEMAS.json`; richer completeness, support, rejection and authority diagnostics are carried only by separate `*AuditV1` wrappers. Source implementation is not production composition.

## 2. Public operations and contract details

`enumerate_factors(...) -> PromptCandidateSetReceiptV1`; `price_factors(...) -> Vec<PromptPricingReceiptV1>` because the canonical pricing schema prices one factor per receipt; `select_portfolio(...) -> PromptPortfolioReceiptV1`; `exercise(...) -> PromptExerciseDecisionV1`. Audited counterparts (`*_with_audit`) return the richer local lineage required for optimization and qualification. The module is read-only over registry, graph and ledger facts and cannot rewrite factor semantics or task objectives.

The legacy `optimize` entrypoint is retained for compatibility and is not the V1 policy surface. `calculate_local_shadow` remains an in-process structural calculator whose output is explicitly not a registered receipt.

## 3. State records and transaction design

No authoritative registry state. The canonical receipts bind their registered contract fields only. Audit wrappers additionally bind model profile, complete or deterministically truncated candidate set, omitted count, causal support/scope, normalized pricing decomposition, hard constraints, interaction policy, heuristic disclosure, candidate dispositions and exercise-time drift checks. Learning evidence remains owned by `learning.ledger`.

## 4. Deterministic algorithm and scheduling

Validate compatible admitted factors and deterministically truncate candidate enumeration. Pricing computes supported expected utility minus downside plus normalized token, latency, interference and resource penalties while preserving canonical raw token/latency/interference fields and confidence interval. Portfolio selection enforces conflict and transitive prerequisite relations, evaluates prerequisite closures as bundles, and compares deterministic gain-first and gain-density heuristics with stable tie breaking. Audit output explicitly reports `HeuristicBestOfGainAndDensityNoCertificate` rather than claiming optimality.

Sparse interaction graphs use an explicit policy: `AssumeZero` permits omitted edges to contribute zero marginal gain, while `RequireExplicit` fails closed when a needed edge is absent. Requires cycles and prerequisite closures that conflict with themselves are rejected before selection. Exercise revalidates the registered boundary, registry snapshot and model profile and compares exercise-now value with wait value. Never use unsupported estimated uplift as proof of utility or mutate context mid-generation.

## 5. Capacity and performance profile

The V1 policy surface enforces <=128 candidate factors, <=512 supplied interaction edges, <=512 hard-constraint edges, <=16 selected factors and an explicit <=1,000,000 token budget. Unlike the legacy local-shadow complete-pair rule, multi-factor V1 selection can use all 128 candidate slots with sparse interactions when the caller explicitly selects `AssumeZero`; callers requiring measured pair support use `RequireExplicit` and fail closed on missing edges.

These ceilings are source-enforced bounds, not host latency or throughput measurements. Bind the selected host and performance evidence before composition.

## 6. Concrete verification cases

- POPT-01: mutually conflicting factors, requires cycles and self-conflicting prerequisite closures are rejected structurally.
- POPT-02: missing estimate/cost/support or invalid confidence yields an error, not zero-cost benefit.
- POPT-03: candidate completeness, omitted count, pricing decomposition, per-candidate disposition and heuristic disclosure remain visible in audit wrappers without widening canonical V1 receipts.
- POPT-04: registry or model-profile drift and an unregistered exercise boundary produce a wait/reject audit result.
- POPT-05: a lower-cost portfolio can beat the legacy highest-gain-first counterexample.
- POPT-06: a negative-gain prerequisite may be selected as part of a positive-gain prerequisite closure.
- POPT-07: 128 supplied factors can participate in bounded multi-select without requiring a complete 8,128-edge pair graph.

These source tests prove deterministic local behavior only. Product delivery, causal efficacy and independent oracle evidence remain separate gates.

## 7. Integration, rollback and capability ceiling

C1 records actual delivery through Codex before assigning intervention credit. Cross-factor interactions still require the support semantics selected by the caller; `AssumeZero` is an explicit modeling policy, not evidence that an unmeasured interaction is truly zero. Rollback uses compatible non-revoked factor/realization snapshots and a deterministic no-intervention fallback.

Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** legacy `optimize` in [codex-rs/hepta-prompt-optimizer/src/lib.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib.rs); structural `calculate_local_shadow` in [codex-rs/hepta-prompt-optimizer/src/local_shadow.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow.rs); canonical V1 `enumerate_factors`, `price_factors`, `select_portfolio`, and `exercise`, plus audited variants, in [codex-rs/hepta-prompt-optimizer/src/policy.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy.rs).
- **Canonical contracts:** `PromptCandidateSetReceiptV1`, `PromptPricingReceiptV1`, `PromptPortfolioReceiptV1`, and `PromptExerciseDecisionV1` mirror the registered protocol-schema fields. Extra diagnostics are not added to those structs.
- **Audit receipts:** `PromptCandidateSetAuditV1`, `PromptPricingSetAuditV1`, `PromptPortfolioAuditV1`, and `PromptExerciseAuditV1` bind local lineage and always expose `AuthorityPosture::DENY_ALL`.
- **Selection semantics:** transitive prerequisite bundles, satisfiability rejection, sparse interaction policy, gain/density heuristic comparison and explicit no-certificate disclosure are source-implemented.
- **State and recovery:** all current policy outputs are pure local receipts/proposals. The module owns no durable state and does not mutate registry, graph, ledger, context or runtime authority.
- **Source tests:** [codex-rs/hepta-prompt-optimizer/src/policy_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/policy_tests.rs), [codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs), and [codex-rs/hepta-prompt-optimizer/src/lib_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib_tests.rs). These are test identities; current CI is the execution evidence for the exact PR head.
- **Remaining work:** bind registry/graph/ledger inputs to authenticated owner adapters; prove realization-context compatibility and actual Codex delivery; compose a named product caller; obtain target-host qualification, independent semantic review and operator acceptance. Source implementation alone does not qualify activation.
