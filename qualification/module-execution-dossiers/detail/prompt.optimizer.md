# prompt.optimizer: implementation and execution dossier

Parent: `docs/modules/prompt.optimizer/TECHNICAL.md`  
Lane: `LANE-F-ADAPTIVE-POLICY`  
Package: `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`

## 1. Current claim

The canonical owner source is implemented and source-composed through a named
Agentd Cargo target. The current candidate is not yet a production
implementation because exact-head/product execution evidence is still pending.
No activation, causal acceptance, canary, promotion or release is claimed.

## 2. Unique native operations

| Operation | Native source | Current caller |
| --- | --- | --- |
| `enumerate_factors_v1` | `canonical_verified.rs` | Agentd registry owner and named product target |
| `price_factors_v1` | `canonical_verified.rs` | named Agentd product target |
| `select_portfolio_v1` | `canonical_solver.rs` | named Agentd product target |
| `exercise_v1` | `canonical_runtime.rs` / secure core in `canonical_solver.rs` | context pipeline, prompt delivery and named Agentd product target |

`canonical_raw.rs` contains internal raw V1 records only. It is not an active
product operation surface. Historical algorithms are compatibility-only under
`compat`.

## 3. Verified state machine

```text
raw registry/model request
→ verified EnumeratedPromptCandidatesV1
→ verified PricedPromptCandidatesV1
→ verified SelectedPromptPortfolioV1
→ verified PromptExerciseDecisionV1
```

Each transition recomputes semantic digests and rejects altered IDs, ordering,
counts, authority, realization bindings, prices, token accounting and lineage.
Only verified wrappers are accepted by selection and exercise.

## 4. Evidence admission

Candidate completeness is signed by a Generator. Pricing and numeric pair
marginals are signed by an Evaluator. The host supplies the immutable trust
snapshot. Evidence is bound to objective, scope, candidate set, registry
snapshot, generation vector, model tuple, realization and pricing policy.
Generator and Evaluator must have independent principals and controllers.
Evidence expiry and revocation are retained rather than converted into zero
cost or implicit support.

## 5. Constraint and solver behavior

- owner-side candidate and relation truncation fail closed;
- required factors close transitively;
- cycles and internally unsatisfiable required closures fail structurally;
- conflicts and V1 redundancy are symmetric exclusions;
- dominates and supersedes are directional pruning relations;
- complement/substitute terms require exact edge-bound pair evidence;
- up to 20 factors use an exact subset oracle;
- larger sets use deterministic prerequisite-bundle greedy selection followed by
  bounded one-swap local improvement;
- every result reports exact certificate or an optimistic upper-bound gap.

## 6. Exercise and runtime handoff

Portfolio validity is bounded by requested validity, realization expiry,
Generator/Evaluator/pair evidence expiry and graph support validity. Exercise
rechecks current policy, state, generation, model tuple, trust epoch, knowledge
generation and exact prompt-registry realization bindings.

The Agentd product target stages only a verified portfolio into the existing
PromptRuntimeHost. The PromptRuntimeHost records a durable dispatch claim before
the provider boundary. The terminal-to-ledger adapter admits only bound
Delivered/Rejected observations. NotDispatched is not exposure; Indeterminate
remains unresolved.

## 7. Registered codecs

Strict V1 canonical JSON codecs implement exactly the registered semantic field
shapes for candidate, pricing, portfolio and exercise receipts. Unknown/missing
fields, invalid enums, noncanonical IDs/order, numeric bounds and payloads over
262,144 bytes are rejected. Internal verified handles and audit fields are not
added to V1.

## 8. Source tests

Current source test identities include:

- `sealed_canonical_pipeline_reaches_exercise_with_exact_certificate`;
- `generator_and_evaluator_under_same_controller_are_rejected`;
- `objective_mismatch_is_rejected_before_evidence_use`;
- `pricing_evidence_cannot_rebind_to_another_realization`;
- `expired_pricing_is_unavailable_not_zero_cost_benefit`;
- `pricing_receipt_utility_tamper_is_detected_by_type_state`;
- `candidate_order_and_binding_tamper_are_detected`;
- `exercise_rejects_graph_and_trust_drift_with_typed_reasons`;
- `policy_context_mismatch_cannot_be_hidden_behind_a_digest`;
- registered-codec round trip and rejection tests;
- compatibility/local-shadow/graph regressions.

These names are source identities, not pass receipts.

## 9. Remaining repository work

- obtain a successful current focused package/all-target run;
- repair every exact-head or deterministic-merge failure attributable to this
  candidate;
- add executable product tests over Agentd staging, PromptRuntime physical
  terminal and learning-ledger admission;
- record bounded target-host performance/fault measurements;
- keep machine map and docs synchronized.

## 10. External gates

Independently observed causal outcomes, conserved credit, longitudinal efficacy,
operator acceptance, canary, selection, promotion and release remain outside
this owner source package. Signed provenance authenticates who attested to a
claim; it does not prove scientific truth.
