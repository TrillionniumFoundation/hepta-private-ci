# prompt.optimizer V1 policy pipeline

Status: source implementation design for `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`.
Owner: `intelligence-platform`. Deputy: `performance`.
Primary source: `codex-rs/hepta-prompt-optimizer/src/pipeline.rs`.
Tests: `codex-rs/hepta-prompt-optimizer/src/pipeline_tests.rs`.

This document is the detailed development reference for the native prompt-selection policy pipeline. It complements `TECHNICAL.md` and the module execution dossier. Canonical JSON registries remain authoritative for contract names and field shapes; this document describes the Rust semantic implementation and its bounded audit sidecars.

## 1. Scope and non-claims

The source implements the deterministic, authority-free pipeline:

`registry snapshot -> candidate enumeration -> causal pricing -> portfolio selection -> registered-boundary exercise`

It does not:

- mutate `prompt.registry`, task objectives, the knowledge graph, or the learning ledger;
- estimate causal effects from raw episodes; it consumes supported causal estimates from the learning-owner boundary;
- authenticate a production transport or owner signature by itself;
- compile or deliver prompt text to a model/provider;
- establish a production caller, activation, promotion, release, or independent acceptance;
- claim global optimality.

Every native receipt/proposal exposes `AuthorityPosture::DENY_ALL`. The public policy library is a deterministic calculator and verifier, not an authority issuer.

## 2. Compatibility strategy

The crate now has three intentionally different surfaces.

### 2.1 Registered V1 semantic contracts

The following Rust structs mirror the semantic fields registered in `docs/contracts/PROTOCOL_SCHEMAS.json` without adding unregistered fields:

| Contract | Native type | Canonical semantic fields represented |
| --- | --- | --- |
| `PromptCandidateSetReceiptV1` | `PromptCandidateSetReceiptV1` | set id, objective/state/registry digests, candidate factor ids, selection grammar digest |
| `PromptPricingReceiptV1` | `PromptPricingReceiptV1` | factor id, state digest, expected utility, downside, token cost, latency cost, interference, confidence interval |
| `PromptPortfolioReceiptV1` | `PromptPortfolioReceiptV1` | portfolio id, candidate-set digest, selected factor ids, interaction digest, expected utility, token upper bound, validity |
| `PromptExerciseDecisionV1` | `PromptExerciseDecisionV1` | factor/portfolio id, registered boundary, exercise-now value, wait value, decision, policy digest |

`PromptPricingReceiptV1` is canonically a single-factor record. Therefore the plural native operation `price_factors` returns a bounded `Vec<PromptPricingReceiptV1>`. The composable audited variant returns `PromptPricingBatchV1`, which contains the exact registered receipts plus provenance and decomposition sidecars. The registered V1 type is not redefined into a batch.

The source-level semantic types are not a claim that canonical JSON codecs are complete. Canonical JSON serialization, unknown-critical-field rejection at a wire boundary, and round-trip codec qualification remain separate repository work.

### 2.2 Audited native pipeline surfaces

The complete in-process pipeline uses audit-preserving variants:

```text
enumerate_factors_with_audit(...) -> PromptCandidateEnumerationV1
price_factors_with_audit(...)     -> PromptPricingBatchV1
select_portfolio_with_audit(...)  -> PromptPortfolioDecisionV1
exercise_with_audit(...)          -> PromptExerciseOutcomeV1
```

The exact contract-returning wrappers are:

```text
enumerate_factors(...) -> PromptCandidateSetReceiptV1
price_factors(...)     -> Vec<PromptPricingReceiptV1>
select_portfolio(...)  -> PromptPortfolioReceiptV1
exercise(...)          -> PromptExerciseDecisionV1
```

### 2.3 Legacy compatibility surface

`optimize(OptimizationRequest) -> PromptPortfolioReceipt` remains source-compatible. It is explicitly a legacy gain-first caller-score heuristic. It is not the registered V1 portfolio selector and does not claim an optimality certificate.

`calculate_local_shadow` also remains available as an authority-free local calculator. It still consumes caller-supplied gains/costs/support and is not a registered prompt receipt schema. Its solver semantics are upgraded to sparse interactions, prerequisite packages, explicit constraint-graph validation, and richer audit disclosure.

## 3. Candidate enumeration

### 3.1 Inputs

`PromptRegistrySnapshotV1` binds:

- state digest;
- registry snapshot digest;
- registry owner digest;
- completeness digest;
- bounded factor/realization entries.

Each `PromptRegistryFactorV1` binds candidate/factor/realization identities, admission and legality, objective scope, model compatibility, token bound, registry entry digest, and support reference digest.

`PromptObjectiveProfileV1` binds the objective and objective-scope digests.

`PromptModelProfileV1` binds model profile, model compatibility, and selection-grammar digests.

### 3.2 Algorithm

1. Reject more than `MAX_SOURCE_FACTORS_V1 = 4096` source entries.
2. Reject empty critical digests and duplicate candidate/factor/realization identities.
3. Deterministically sort by factor id, realization id, then candidate id.
4. Record explicit dispositions for not-admitted, illegal, objective-scope mismatch, model incompatibility, included, and truncated entries.
5. Count every compatible eligible factor before truncation.
6. Deterministically retain at most `MAX_FACTORS_V1 = 128` factor ids.
7. Emit the registered candidate-set receipt and a digest-bound audit sidecar.

### 3.3 Completeness proof

`PromptCandidateSetAuditV1` records:

- registry owner and completeness digests;
- source-factor count;
- eligible-factor count;
- omitted count;
- exact candidate/factor/realization bindings for included factors;
- every source entry's disposition;
- model profile and compatibility digests;
- candidate-set semantic digest and audit digest.

Before pricing or selection, the implementation recomputes the candidate-set and audit digests and verifies:

`source_count >= eligible_count >= included_count`

and

`omitted_count == eligible_count - included_count`.

It also verifies that included decisions and binding order exactly match the registered receipt's factor-id vector.

## 4. Causal pricing

### 4.1 Inputs and ownership boundary

`price_factors_with_audit` consumes:

- the audited candidate enumeration;
- `PromptCausalEstimateSetV1`, bound to state, selection grammar, ledger snapshot, and ledger owner;
- `PromptCostModelV1`, bound to state, selection grammar, and cost-model digest.

The optimizer does not infer causal uplift from correlations. A factor whose causal support status is `Unsupported` is emitted as unavailable with zero selectable net utility; unsupported uplift is never treated as evidence of benefit.

### 4.2 Price equation

For a supported factor:

```text
net utility
  = causal incremental recursive utility
  - token utility cost
  - latency utility cost
  - instruction/interference utility cost
  - resource utility cost
  - privacy utility cost
  - instability utility cost
  - future-context option-value cost
```

All utility arithmetic is checked `FixedQ32`. Physical token units, latency microseconds, and interference PPM remain separately represented in the registered pricing receipt.

### 4.3 Validation

Pricing rejects:

- state or selection-grammar drift;
- missing or extra causal estimate keys;
- missing or extra cost keys;
- duplicate evidence/cost records;
- invalid confidence intervals or confidence PPM;
- invalid interference PPM;
- cost token units exceeding the enumerated realization token upper bound;
- empty ledger/cost/support digests;
- candidate audit tampering.

### 4.4 Audit sidecar

`PromptPricingAuditEntryV1` records, per factor:

- availability;
- causal incremental utility;
- total utility cost;
- net utility;
- all seven utility-cost components;
- causal support reference digest;
- cost support reference digest.

`PromptPricingBatchV1.batch_digest` binds the candidate set, candidate audit, ledger identities, cost model, every registered pricing receipt, every availability decision, every cost-decomposition component, and support references.

## 5. Portfolio solver

### 5.1 Capacity

The registered/native V1 selector enforces:

- at most 128 priced factors;
- at most 512 explicit pair-interaction edges;
- at most 512 hard-constraint edges;
- at most 16 selected factors;
- at most 128 selection steps;
- token budget at most 1,000,000 units.

The interaction graph is sparse. A 128-factor candidate set no longer requires `C(128,2)` explicit pair edges.

### 5.2 Unknown interaction policy

`UnknownInteractionPolicyV1` is explicit:

- `MissingAsZero`: absence of an interaction edge means zero measured marginal interaction for this bounded policy run;
- `RejectMissing`: any pair interaction required while evaluating a candidate package fails closed with `MissingPairInteraction`.

The chosen policy is included in the relation digest and portfolio audit.

### 5.3 Hard constraints

Supported hard constraints are:

- `Conflict(A, B)`;
- `Requires(A, B)` meaning A requires B.

Validation rejects unknown endpoints, self edges, duplicate relations, empty support references, and resource-limit overflow.

Before optimization the graph is structurally checked for:

- directed `Requires` cycles;
- a prerequisite closure that contains any internal conflict.

These return explicit `RequiresCycle` or `UnsatisfiableConstraintGraph` errors instead of silently falling through to an empty selection.

### 5.4 Prerequisite closure packages

A dependent factor is never required to wait for a prerequisite to have independently positive marginal value.

For each root factor, the selector builds its transitive prerequisite closure, removes already-selected members, and evaluates the remaining package atomically. Example:

```text
prerequisite = -1
 dependent   = +100
 package     = +99
```

If budget, slot, conflict, and evidence constraints permit it, the +99 package is selectable and is emitted prerequisite-first.

### 5.5 Heuristic objective

The selector uses bounded prerequisite-closure greedy marginal utility density:

```text
package marginal utility
  = sum(standalone priced net utilities)
  + interactions(package, already selected)
  + interactions(within package)

density = package marginal utility / package token cost
```

Comparison uses cross multiplication to avoid floating-point nondeterminism. Tie-break order is:

1. higher marginal-utility density;
2. higher absolute marginal utility;
3. lower token cost;
4. lexicographically lower root factor id.

Only positive-marginal packages are added. The result explicitly reports `HeuristicNoCertificate`; the implementation does not claim global optimality.

This eliminates the legacy gain-first counterexample where budget 10 and candidates A=(100,10), B=(60,5), C=(60,5) would choose A. The V1 density selector chooses B+C=120.

## 6. Portfolio audit receipt sidecar

`PromptPortfolioAuditV1` binds:

- pricing batch digest;
- state/objective/registry digests;
- registry completeness digest;
- source/eligible/omitted counts;
- model profile and model compatibility digests;
- graph owner digest;
- per-factor decision records;
- selected total net utility and unspent token budget;
- selection step count;
- solver method and no-certificate disclosure;
- unknown-interaction policy;
- audit digest.

Each `PromptPortfolioCandidateDecisionV1` records:

- factor id;
- selected/rejected disposition;
- full transitive prerequisite closure;
- confidence PPM;
- token cost;
- standalone net utility;
- causal support reference digest;
- cost support reference digest.

Rejection classes include unavailable pricing, non-positive marginal, over budget, selection limit, hard conflict, and heuristic-not-selected.

This sidecar supplies the audit information that cannot be added to the already-registered `PromptPortfolioReceiptV1` without a contract version change.

## 7. Exercise policy

`exercise_with_audit` is called only with an explicitly registered `PromptDecisionBoundaryV1`. The enum covers the boundaries registered by `PROMPT_INTERVENTIONS.json`, including request acceptance, objective compilation, planning/generation/dispatch boundaries, observation/failure boundaries, irreversible mutation, verification, final response, and compact/handoff.

Before exercising, it recomputes the portfolio audit digest and checks:

- state digest;
- registry snapshot digest;
- model profile digest;
- model compatibility digest;
- objective digest.

Any drift produces a registered decision of `Wait` and an explicit invalidation disposition in the audit sidecar. An empty portfolio yields `NoIntervention`. Otherwise the deterministic real-option decision is:

- `Exercise` when `exercise_now_value >= wait_value`;
- `Wait` when `wait_value > exercise_now_value`.

The policy decision alone does not mutate prompt context or prove delivery.

## 8. Local shadow policy

`calculate_local_shadow` remains intentionally less authoritative than the V1 pipeline:

- caller supplies gains, costs, relations, and support references;
- registry/graph/ledger owner authentication is not established;
- model compatibility is disclosed as unverified;
- the exercise boundary is disclosed as unbound;
- candidate completeness is limited to the caller-supplied set.

The shadow calculator nevertheless shares the corrected solver properties:

- sparse interactions;
- prerequisite closure/package scoring;
- explicit cycle and unsatisfiable-constraint errors;
- bounded deterministic density heuristic;
- explicit `HeuristicNoCertificate`;
- per-candidate selection/rejection audit.

Its total-candidate ceiling remains 128 including the local no-intervention baseline, so at most 127 factor candidates are admitted to one shadow request. The formal V1 pipeline has a separate 128-factor limit and no local-baseline slot tax.

## 9. Error taxonomy

The V1 pipeline separates at least these failure classes:

- size/resource limits;
- duplicate identity/evidence/cost;
- missing/extra pricing evidence;
- state/grammar drift;
- invalid confidence/interference bounds;
- token-bound mismatch;
- unknown/duplicate relation endpoints;
- requires cycle;
- unsatisfiable constraint graph;
- missing required pair interaction;
- digest/integrity mismatch;
- arithmetic overflow;
- authority escalation;
- invalid expiry or derived identity.

Errors fail closed and do not silently convert missing support into zero-cost benefit.

## 10. Determinism and digest binding

Native semantic digests use domain-separated byte sequences. Repeated collections bind their lengths and canonical order. Receipt/audit digests bind all fields used for later decisions, including pricing decomposition and prerequisite-closure audit data.

Candidate enumeration sorts before truncation. Interaction pairs are canonicalized. `Requires` prerequisite vectors are sorted. Stable tie-breaking avoids hash-map iteration dependence and floating-point arithmetic.

The native semantic digest is an in-process integrity primitive. It is not a detached signature and does not authenticate an owner by itself.

## 11. Verification matrix

`pipeline_tests.rs` covers the following regressions:

| Case | Expected behavior |
| --- | --- |
| V1 candidate contract | 130 compatible source factors deterministically retain 128 and record omitted=2 |
| V1 pricing contract | exact per-factor V1 fields plus seven-component audit decomposition |
| unsupported causal support | unavailable pricing, selectable net utility zero |
| legacy gain-first counterexample | V1 selector chooses B+C over A |
| negative prerequisite bundle | prerequisite -1 + dependent +100 selects as +99 package |
| sparse capacity | 128 priced factors, zero explicit pair edges, select 16 |
| strict sparse policy | `RejectMissing` fails closed when a needed pair has no edge |
| requires cycle | explicit `RequiresCycle` |
| requires + conflict contradiction | explicit `UnsatisfiableConstraintGraph` |
| decision audit | rejection reason, completeness, confidence, support, model compatibility bound |
| exercise | registered boundary and drift invalidation are explicit |
| authority | all registered/native outcomes remain `DENY_ALL` |

`local_shadow_tests.rs` separately covers the local baseline identity, sparse shadow capacity, package prerequisites, constraint graph errors, hard conflicts, support/reference integrity, arithmetic overflow, canonical ordering, and authority-free disclosure.

## 12. Integration sequence after source merge

The remaining production-composition work is deliberately outside this source claim:

1. canonical JSON codecs/validators for all four V1 protocols, including unknown-critical-field rejection and round trips;
2. authenticated adapters from `prompt.registry`, knowledge graph, and learning ledger into the native input envelopes;
3. owner-approved model/realization compatibility binding at the actual product caller;
4. named product composition through the registered module ports;
5. actual context compilation and delivery observation through Codex;
6. causal exposure/outcome recording in `learning.ledger`;
7. target-host performance qualification, independent semantic review, operator acceptance, canary/promotion/release.

None of those gates is inferred from unit tests or from the existence of the source pipeline.

## 13. Migration and rollback

- Existing callers of `optimize` remain source-compatible; migrate intentionally to the V1 pipeline.
- Existing callers of `calculate_local_shadow` keep an authority-free shadow path, but sparse interaction semantics replace complete-pair requirements and prerequisite packages replace prerequisite-first positive-marginal behavior.
- If a V1 integration must be rolled back, fall back to a compatible frozen registry/model snapshot and the explicit no-intervention path. Do not reinterpret a stale portfolio against a new registry/model/template state.
- Contract field changes require a new registered version; audit sidecars may evolve only without changing the meaning of registered V1 fields.
