# prompt.optimizer registered policy pipeline

This document describes the native registered-policy surface implemented in `codex-rs/hepta-prompt-optimizer/src/policy.rs`. It is an implementation addendum to `TECHNICAL.md` and the module execution dossier. The module remains read-only and authority-free: a returned receipt or decision is evidence for a caller, not permission to mutate context, dispatch a provider, or activate an intervention.

## 1. Native operations

The target operation names are now native Rust entrypoints:

- `enumerate_factors(registry_snapshot, objective, model_profile)` -> `PromptCandidateSetReceiptV1`
- `price_factors(candidates, causal_estimates, costs)` -> `Vec<PromptPricingReceiptV1>`
- `select_portfolio(prices, interactions, budget)` -> `PromptPortfolioReceiptV1`
- `exercise(portfolio, registered_boundary, state)` -> `PromptExerciseDecisionV1`

Each public V1 type carries the semantic fields registered in `docs/contracts/PROTOCOL_SCHEMAS.json`. Rich diagnostics are emitted by the corresponding `*_audited` operation into companion audit types instead of widening the registered public schema.

`optimize` and `local_shadow::calculate_local_shadow` remain compatibility/shadow primitives. They must not be presented as the registered policy pipeline or as globally optimal portfolio solvers.

## 2. Candidate enumeration and completeness

`enumerate_factors_audited` validates bounded registry/objective/model inputs, rejects duplicate factor or realization identities, filters admission/legal/scope/model incompatibilities, sorts by stable factor identity, and deterministically truncates to 128 retained factors. The audit binds:

- complete eligible-set digest before truncation;
- eligible, retained, and omitted counts;
- per-factor enumeration disposition;
- factor-to-realization binding;
- registered token upper bound;
- realization-context and model-profile digests;
- registry source-evidence digest.

This makes truncation explicit rather than silently treating the retained set as complete.

## 3. Causal pricing

Pricing is no longer just `expected_gain + cost` supplied by the caller. For each supported factor the native pricing path computes:

`net expected utility = causal incremental recursive utility - token cost - latency cost - context crowding - instruction interference - privacy - instability - future-context option value - resource cost`.

The public `PromptPricingReceiptV1` contains the registered expected utility, downside, token cost, latency cost, interference, and confidence interval. The audit companion binds the full pricing decomposition, causal-support digest, cost-support digest, model profile, and realization context.

Missing causal evidence or cost data is unavailable pricing, never a zero-cost benefit. The audited batch preserves an explicit unavailability reason. Model/realization binding drift and token estimates beyond the registered realization bound also make pricing unavailable.

The optimizer validates and digest-binds caller-supplied evidence but does not itself authenticate remote owner signatures. Authentication of `prompt.registry`, `knowledge.graph`, and `learning.ledger` remains an owner-bound composition adapter requirement and is not claimed by this source-only change.

## 4. Portfolio solver and heuristic disclosure

The registered selector is a bounded deterministic heuristic and says so explicitly through `PromptOptimalityDisclosureV1::HeuristicNoCertificate`. It does not claim a global knapsack or combinatorial optimum.

The selector evaluates the transitive prerequisite closure of a root factor as one package. Therefore a prerequisite with negative standalone utility can still be selected when the dependent package has positive marginal utility. Hard conflicts are non-tradable and cannot be outweighed by numeric utility.

Selection is bounded by:

- at most 128 candidate factors;
- at most 512 explicit interaction edges;
- at most 512 hard constraints;
- at most 16 selected factors;
- token budget at most 1,000,000;
- at most 128 selection rounds.

Stable tie-breaking is: greater package marginal utility, then lower package token cost, then lower root factor identity.

## 5. Sparse interactions

The formal policy graph has an explicit missing-edge policy:

- `AssumeZero`: a missing pair is an explicit zero marginal interaction assumption;
- `RejectMissing`: every unordered pair must be present.

`AssumeZero` is the sparse-graph path and allows the full 128-factor candidate capacity while still capping explicit supported interactions at 512 edges. The older local shadow calculator keeps its historical complete-pair semantics for compatibility and must not be used to infer the capacity of the registered policy path.

## 6. Constraint satisfiability

Before selection, the registered policy path validates constraint endpoints, uniqueness, canonical ordering and support references, then performs structural checks for:

- directed `Requires` cycles;
- a conflict inside any factor's transitive prerequisite closure.

These fail with `RequiresCycle` or `UnsatisfiableConstraintGraph` instead of silently collapsing to an empty selection. Unknown endpoints and non-canonical/duplicate constraints remain hard errors.

## 7. Decision audit

`PromptPortfolioAuditV1` is a companion audit record, not an extension of the registered `PromptPortfolioReceiptV1` wire shape. It records:

- complete eligible-set digest and omitted count;
- priced and unavailable-pricing counts;
- pricing-batch, interaction, and hard-constraint digests;
- model-profile digest;
- one disposition for every candidate in the selection graph;
- selection method and explicit absence of an optimality certificate;
- the requirement for a registered exercise boundary;
- an audit digest over the above semantics.

Per-candidate dispositions distinguish selected, unavailable pricing, non-positive package utility, token-budget exclusion, selection-limit exclusion, hard conflict, and heuristic exclusion.

## 8. Exercise boundary and drift invalidation

`exercise` only evaluates a portfolio against a `RegisteredPromptBoundaryV1`. It rejects:

- portfolio/candidate-set digest mismatch;
- state drift;
- registry drift;
- model-profile drift;
- expiry.

The decision compares exercise-now value with wait value and emits `Exercise`, `Wait`, or `NoChange`. The result remains `AuthorityPosture::DENY_ALL`; an owner-bound adapter is still required before any runtime effect.

## 9. Compatibility and remaining gates

This source change closes the native API/contract/pricing/solver/audit gaps without deleting the two existing compatibility paths. It does **not** claim production composition, authenticated remote owner attestations, product execution, independent acceptance, activation, promotion, or release. Those remain separate qualification and delivery gates.
