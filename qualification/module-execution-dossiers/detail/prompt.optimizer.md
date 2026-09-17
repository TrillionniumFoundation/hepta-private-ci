# prompt.optimizer: implementation design

Parent: `docs/modules/prompt.optimizer/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: registered V1 semantic contract surfaces and the bounded native candidate -> pricing -> portfolio -> exercise pipeline are implemented in source; product composition, authenticated owner adapters, canonical JSON wire codecs and independent acceptance remain outside this source claim. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-prompt-optimizer`.
Packages: `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`.

The native implementation preserves the historical `optimize` API for source compatibility and keeps `calculate_local_shadow` as an authority-free structural calculator. New policy code uses `pipeline.rs`. No source path in this package grants activation, delivery, registry mutation or production selection authority.

## 2. Public operations and contract details

The canonical protocol registry is authoritative for V1 field shape. In particular, `PromptPricingReceiptV1` is a **per-factor** protocol, so the native plural pricing operation returns a bounded `PromptPricingBatchV1` containing exact `PromptPricingReceiptV1` records rather than redefining the V1 contract as a batch.

Native operations:

- `enumerate_factors(registry_snapshot, objective, model_profile) -> PromptCandidateSetReceiptV1`.
- `enumerate_factors_with_audit(...) -> PromptCandidateEnumerationV1` for the digest-bound native completeness/provenance sidecar used by the full pipeline.
- `price_factors(candidates, causal_estimates, costs) -> Vec<PromptPricingReceiptV1>` because the canonical pricing protocol is per-factor.
- `price_factors_with_audit(...) -> PromptPricingBatchV1`, whose `receipts` are exact registered-shape pricing records and whose audit entries contain availability, provenance and cost/support decomposition.
- `select_portfolio(prices, interactions, budget) -> PromptPortfolioReceiptV1`.
- `select_portfolio_with_audit(...) -> PromptPortfolioDecisionV1` for per-factor selection/rejection evidence and solver disclosure.
- `exercise(portfolio, registered_boundary, state) -> PromptExerciseDecisionV1`.
- `exercise_with_audit(...) -> PromptExerciseOutcomeV1` for drift/no-intervention/wait reasons.

The four registered V1 Rust structs mirror the semantic fields in `docs/contracts/PROTOCOL_SCHEMAS.json`; richer native audit fields are not injected into those V1 shapes. Canonical JSON serialization/deserialization remains an adapter/wire task and is not claimed by this source implementation.

## 3. State records and transaction design

No authoritative registry state is owned here. Candidate enumeration binds objective, state, registry snapshot, selection grammar and deterministic factor IDs. The native candidate audit additionally binds registry owner/completeness, model compatibility, source/eligible/omitted counts, candidate-realization bindings and every enumeration disposition.

Pricing binds the candidate set, frozen state and selection grammar to ledger/cost-model digests. Each canonical pricing receipt carries expected utility, downside, token cost, latency, interference and confidence interval; its audit entry separately binds causal support and the token/latency/interference/resource/privacy/instability/future-context-option-value utility decomposition.

Portfolio audit binds pricing, registry completeness, model compatibility, graph owner, per-factor disposition, prerequisite closure, confidence/support references, budget accounting, sparse interaction policy, selection method and explicit `HeuristicNoCertificate` status. Exercise audit binds the registered boundary, current state and drift disposition. All native outputs expose `DENY_ALL` authority semantics.

## 4. Deterministic algorithm and scheduling

1. Validate non-zero source/owner/support digests, unique candidate/factor/realization identities, admitted/legal factors, objective scope and model compatibility.
2. Deterministically sort before truncation; retain at most 128 compatible factors and record source, eligible and omitted counts in the audit sidecar.
3. Price only supported causal evidence. Unsupported causal evidence is unavailable and cannot contribute positive utility. Net utility is causal incremental utility minus explicit utility-denominated token, latency, interference, resource, privacy, instability and future-context-option-value costs.
4. Validate graph endpoints, duplicate relations, `Requires` cycles and prerequisite closures that contain hard conflicts. Cycles and structural contradictions return explicit errors rather than silently collapsing to an empty portfolio.
5. Treat transitive prerequisite closures as atomic evaluation packages. A negative standalone prerequisite may therefore be selected when the dependent package has positive aggregate marginal utility.
6. Use a bounded marginal-utility-density greedy heuristic with stable tie-breaking by marginal utility, cost and identifier. This remains a heuristic and emits no optimality certificate.
7. Pair interactions are sparse. `MissingAsZero` treats absent pair edges as zero; `RejectMissing` fails closed when an unobserved pair is actually needed. Multi-select no longer requires a complete pair graph.
8. Exercise only at a registered decision boundary. Registry/model/objective/state/boundary drift or higher wait value yields a non-exercise decision; there is no mid-generation mutation.

The legacy `optimize` surface remains gain-first and is explicitly documented as a compatibility heuristic, not the formal portfolio policy. For budget 10 with A=(100,10), B=(60,5), C=(60,5), the formal V1 selector chooses B+C while legacy `optimize` may choose A.

## 5. Capacity and performance profile

Native V1 ceilings:

- source registry factors: <=4096 before compatibility filtering;
- compatible candidate factors: <=128;
- explicit pair-interaction edges: <=512;
- hard-constraint edges: <=512;
- selected factors: <=16;
- token budget: <=1,000,000;
- marginal selection steps: <=128.

The 128-factor multi-select ceiling is now independent of the 512 interaction-edge ceiling because interaction input is sparse. The old local-shadow complete-pair requirement and its effective 32-factor multi-select ceiling are removed. `calculate_local_shadow` still counts its local no-intervention baseline inside its 128 total-candidate ceiling, so it accepts at most 127 factor candidates by design.

Pilot ceilings are source-enforced bounds, not latency/throughput measurements. Target-host measurements remain required before product composition.

## 6. Concrete verification cases

Source tests cover at least:

- POPT-01: registered candidate receipt shape, deterministic truncation and omitted-count audit at 130 source factors;
- POPT-02: causal pricing subtracts all declared utility-cost components and unsupported evidence stays unavailable;
- POPT-03: the A/B/C gain-first counterexample selects the higher-utility B+C portfolio on the formal selector;
- POPT-04: prerequisite closure can select a -1 prerequisite with a +100 dependent as a +99 package;
- POPT-05: 128 factor candidates can multi-select 16 factors with zero explicit pair edges under `MissingAsZero`;
- POPT-06: `Requires` cycles and `Requires`+`Conflict` contradictions produce explicit structural errors;
- POPT-07: portfolio audit records rejection reason, completeness/omitted count, confidence/support and model compatibility;
- POPT-08: registered exercise receipt binds a named timing boundary while the audit sidecar records drift invalidation;
- POPT-09: legacy gain-first behavior remains source-compatible and is tested as a limitation, not an optimality claim;
- POPT-10: local shadow preserves DENY_ALL, sparse interactions, prerequisite packages and explicit audit-gap disclosures.

These source test identities are not execution receipts until exact-head CI runs them.

## 7. Integration, rollback and capability ceiling

The crate remains a pure local policy library. It does not authenticate signatures from `prompt.registry`, `knowledge.graph` or `learning.ledger`, does not invoke those owners, does not compile/deliver prompt payloads and does not observe delivery. Product integration must supply authenticated frozen snapshots/adapters, preserve registry/model/objective identity through context compilation, and record actual delivery before learning credit.

Rollback remains deterministic no-intervention plus the previous compatible prompt-factor/realization snapshot. No native receipt in this package grants runtime, provider, tool, network, filesystem, acceptance, promotion or release authority.

## 8. Current native implementation

- **Formal pipeline entrypoints:** `enumerate_factors`, `price_factors`, `select_portfolio`, `exercise` in [codex-rs/hepta-prompt-optimizer/src/pipeline.rs](../../../codex-rs/hepta-prompt-optimizer/src/pipeline.rs), with audited variants for native evidence sidecars.
- **Registered V1 semantic Rust types:** `PromptCandidateSetReceiptV1`, `PromptPricingReceiptV1`, `PromptPortfolioReceiptV1`, `PromptExerciseDecisionV1` in `pipeline.rs`, aligned to the current canonical protocol field shapes rather than the older conceptual dossier expansion.
- **Legacy compatibility entrypoint:** `optimize` in [codex-rs/hepta-prompt-optimizer/src/lib.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib.rs); gain-first, caller-score heuristic, no optimality claim.
- **Shadow calculator:** `calculate_local_shadow` in [codex-rs/hepta-prompt-optimizer/src/local_shadow.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow.rs); sparse interactions, prerequisite-package scoring, explicit cycle/unsatisfiable validation, audit-gap disclosures, still not a registered wire receipt.
- **Source tests:** [pipeline_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/pipeline_tests.rs), [local_shadow_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/local_shadow_tests.rs), [lib_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/lib_tests.rs).
- **Detailed source guide:** [docs/modules/prompt.optimizer/PIPELINE_V1.md](../../../docs/modules/prompt.optimizer/PIPELINE_V1.md).
- **Remaining repository work before a production claim:** canonical JSON wire codec/round-trip tests for the registered protocols, authenticated owner adapters/callsites, product composition, target-host performance evidence, exact-head/merge-candidate qualification and independent acceptance. None of these are implied by source implementation.
