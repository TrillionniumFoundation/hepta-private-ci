# prompt.optimizer technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `prompt.optimizer`  
**Owner / deputy:** `intelligence-platform` / `performance`  
**Lifecycle:** target  
**Source root:** `codex-rs/hepta-prompt-optimizer`  
**Production implementation:** false until current exact-head and product execution evidence pass

This guide describes the current canonical source candidate. It is not an
activation, causal-efficacy, operator-acceptance, promotion or release record.
Machine-readable operation, test and caller facts are in
`IMPLEMENTATION_MAP.json` and are checked against the Rust module tree by
`scripts/verify_prompt_optimizer_map.py`.

## 1. Mission and authority ceiling

`prompt.optimizer` selects a bounded prompt-intervention portfolio for one exact
objective, state, prompt-registry snapshot, model tuple, evidence trust snapshot
and knowledge generation. It owns no prompt registry, knowledge graph, learning
fact, context store or provider execution state.

Every canonical result is authority-free. A candidate set, price, portfolio or
exercise decision is evidence consumed by another owner; it is never permission
to call a model, invoke a tool, mutate a store, promote an artifact or release a
configuration. `AuthorityPosture::DENY_ALL` is rechecked at each verified stage.

## 2. Unique implementation surface

The only active product pipeline is
`codex_hepta_prompt_optimizer::canonical`:

```text
enumerate_factors_v1
→ price_factors_v1
→ select_portfolio_v1
→ exercise_v1
```

The historical score-only optimizer, graph adapter and local shadow calculator
are isolated under `codex_hepta_prompt_optimizer::compat`. Temporary crate-root
re-exports preserve source compatibility, but new code must name `compat`
explicitly. The former unreferenced `policy*.rs` implementation family has been
removed; Git history retains it.

Canonical source decomposition:

| Source | Responsibility |
| --- | --- |
| `canonical_raw.rs` | internal/raw V1 domain and receipt structures; never exported as an active operation |
| `canonical_verified.rs` | verified enumeration and pricing type-state, evidence binding and receipt recomputation |
| `canonical_solver.rs` | graph admission, exact/heuristic selection, validity propagation, audits and secure exercise core |
| `canonical_runtime.rs` | product-compatible exercise request and end-to-end plan orchestrator |
| `canonical_digest.rs` | semantic digest recomputation for every stage |
| `canonical_codec.rs` | strict registered V1 JSON transport DTOs |

## 3. Raw versus verified type-state

Raw receipt structures exist for wire compatibility and persistence. They do not
establish trust. Product operations return private-field wrappers:

- `EnumeratedPromptCandidatesV1`;
- `PricedPromptCandidatesV1`;
- `SelectedPromptPortfolioV1`;
- `VerifiedPromptExerciseDecisionV1`.

The wrappers can be created only by canonical validators. At every stage the
implementation recomputes and checks:

- exact IDs and canonical ordering;
- factor-to-realization identity;
- realization binding digest;
- prompt-registry snapshot and model tuple;
- candidate, order, pricing-set, portfolio and audit digests;
- counts, token accounting and authority posture;
- objective, state, generation and policy context.

The selector accepts only `PricedPromptCandidatesV1`. Exercise accepts only
`SelectedPromptPortfolioV1`. A caller-constructed raw receipt cannot cross these
boundaries.

## 4. Candidate enumeration

`enumerate_factors_v1` consumes the authoritative prompt-registry V2 view and
binds:

- set, objective and state identities;
- evidence scope;
- generation vector;
- exact model/tokenizer/template/tool/context/locale tuple;
- selection grammar;
- generator code, hard-filter and truncation policy digests;
- required factor IDs and caller candidate cap.

The owner registry must return a complete compatible view at its own 128-factor
bound. Owner-side truncation is an error. After the complete read, the optimizer
deterministically chooses the lowest-token compatible realization per factor,
using realization ID as the stable tie-breaker, then applies the caller cap and
records the omitted count. This is the normative truncation rule.

No-intervention is represented by an empty selected portfolio, not by a
fabricated prompt factor. Learning systems that require an explicit `abstain`
arm map it through their owner-bound assignment protocol.

## 5. Evidence-qualified pricing

Pricing requires both:

1. generator-signed `CandidateSetCompletenessReceiptV1` evidence; and
2. evaluator-signed `PromptPricingEvidenceV1` for each priced factor.

The verifier is a host-owned immutable trust snapshot. Remote evidence cannot
supply or replace its scope, objective or epoch. Generator and evaluator must
have distinct principals and distinct `controller_id` values; key rotation alone
does not establish independence.

Each pricing attestation binds:

```text
objective + evidence scope
candidate-set digest
registry snapshot digest
generation-vector digest
model-tuple digest
factor ID + realization ID + realization-binding digest
pricing-policy digest + state digest
utility/downside/confidence/support
latency/interference/crowding/privacy/instability/future-option costs
```

Net utility is computed in checked fixed-point arithmetic as incremental utility
minus downside and all registered costs. Missing, expired or revoked evidence is
recorded as unavailable pricing; it is never converted into a zero-cost benefit.
The minimum evidence expiry is propagated to the portfolio validity frontier.

## 6. Knowledge relations and portfolio semantics

`select_portfolio_v1` requires a validated complete `KnowledgeGenerationV2`
whose generation vector, source snapshot and graph profile match the portfolio
request. Relation queries fail closed on omitted edges.

Relation semantics are:

- `PromptRequires`: directed transitive prerequisite closure;
- `PromptConflicts`: symmetric non-tradable exclusion;
- `PromptRedundant`: symmetric exclusion in V1;
- `PromptDominates`: directed pre-selection pruning of the dominated target;
- `PromptSupersedes`: directed pre-selection pruning of the superseded target;
- `PromptComplements` / `PromptSubstitutes`: numeric marginal terms requiring
  evaluator-signed pair evidence bound to both exact realization bindings and the
  exact graph edge validity digest.

A requires cycle, unavailable prerequisite, internal conflict, dominated or
superseded member inside a required closure is a structural error rather than a
silent no-intervention result.

## 7. Solver and optimality disclosure

Limits are fixed at:

- at most 128 enumerated factors;
- at most 16 selected factors;
- at most 512 queried interaction edges;
- token budget at most 1,000,000;
- exact oracle at most 20 factors;
- local-improvement rounds at most 128.

For small candidate sets the implementation enumerates all subsets under token,
selection, prerequisite, direction and conflict constraints and emits
`ExactCertificate`.

For larger sets it runs deterministic prerequisite-bundle greedy selection,
then bounded one-swap local improvement. It reports an optimistic positive-term
upper bound and the resulting gap; it does not claim a global optimum. Stable
tie-breaking is utility, lower token cost and lexical factor order.

The solver precomputes prerequisite closures and dense lookup maps rather than
repeating graph traversal for every marginal evaluation. The bounded audit
contains solver rounds, local-improvement rounds, termination reason, incumbent,
token use, upper-bound gap and one disposition for every candidate.

## 8. Validity and exercise-time revalidation

Portfolio validity is the minimum of:

- requested portfolio validity;
- selected realization expiry;
- generator/evaluator evidence expiry;
- pair-evidence expiry;
- relation-support validity.

`PromptExercisePolicyV1` is a checked, digest-bound policy value containing the
objective, evidence scope, allowed decision boundaries and validity window. A
nonzero arbitrary digest is not accepted as policy.

Immediately before context compilation or provider delivery, `exercise_v1`
revalidates:

- verified portfolio integrity;
- current exercise policy and boundary;
- current evidence trust digest, scope, objective and authority epoch;
- current knowledge generation, source snapshot and graph profile;
- current state, generation vector and exact model tuple;
- current prompt-registry snapshot and each selected realization binding;
- the inherited validity frontier.

Unsafe conditions all fail closed but retain typed reasons: state, generation,
model, registry, revocation/unavailability, evidence expiry, trust drift, graph
drift, policy expiry/boundary denial, dependency unavailable, corrupt,
indeterminate or quarantined.

## 9. Registered V1 codecs

`canonical_codec.rs` implements strict canonical JSON DTOs for:

- `PromptCandidateSetReceiptV1`;
- `PromptPricingReceiptV1`;
- `PromptPortfolioReceiptV1`;
- `PromptExerciseDecisionV1`.

Only fields registered in `docs/contracts/PROTOCOL_SCHEMAS.json` are encoded.
Internal receipt digests, verified handles, audits and authority posture are not
silently added to V1. Struct declaration order defines canonical JSON field
order. Decode rejects unknown, missing or duplicate fields, invalid IDs/digests,
noncanonical factor ordering, invalid enums, numeric bounds and payloads larger
than 262,144 bytes.

A decoded DTO is transport data. It must still be reconciled with owner snapshots
and converted into verified type-state before product use.

## 10. Named product composition

The named product caller is the Agentd Cargo target:

`codex-rs/hepta-agentd/src/bin/prompt_optimizer_product.rs`.

It performs:

```text
DurablePromptRegistry owner
→ enumerate_factors_v1
→ verify generator/evaluator evidence
→ price_factors_v1
→ validate KnowledgeGenerationV2 and pair evidence
→ select_portfolio_v1
→ AgentdPromptPipelineOwner::compile_and_stage
→ exercise_v1 inside context compilation
→ ContextAttachmentV2
→ Agentd PromptRuntimeHost
→ Codex physical provider terminal
→ append_agentd_prompt_terminal_to_ledger_v1
→ learning.ledger
```

Only `Delivered` and explicit `Rejected` terminal records carry a bound
`PromptDeliveryObservationV1` into the ledger. `NotDispatched` creates no causal
exposure. `Indeterminate` remains open and is not converted into success,
rejection or retry permission.

The target is source composition. Production remains false until executable
product tests and current exact-candidate checks pass.

## 11. State, concurrency and recovery

The optimizer crate is stateless and owns no writer. Durable state remains with:

- `prompt.registry` for factors, realizations, payloads, lifecycle and revocation;
- `knowledge.graph` for complete relation generations;
- `learning.ledger` for evidence, delivery and causal facts;
- `runtime.agentd` for staged attachments, dispatch claims and terminal records.

The Agentd runtime records the physical dispatch claim before the effect boundary.
A crash after that claim but before terminal observation is indeterminate and
blocks blind retry. Optimizer recomputation does not close or overwrite that
state.

## 12. Security and privacy controls

The canonical path rejects:

- caller-selected trust configuration;
- objective/scope/epoch substitution;
- same-controller generator/evaluator evidence;
- evidence replay across candidate sets, snapshots, models or realizations;
- utility, receipt, ordering or binding tampering;
- stale or revoked realizations;
- incomplete graph projections;
- unsupported pair interactions;
- unknown critical wire fields;
- authority-bearing receipts.

Prompt payload bytes are dereferenced only by the prompt-registry owner after
exercise. General optimizer audits contain IDs, digests, costs and dispositions,
not credentials or secrets.

## 13. Observability

`PromptPortfolioAuditV1` records:

- every candidate disposition;
- unavailable pricing reasons;
- graph source/profile/generation;
- evidence trust digest and epoch;
- inherited validity frontier;
- solver and local-improvement rounds;
- incumbent and token utilization;
- exact certificate or upper-bound gap;
- deterministic audit digest.

`PromptExerciseAuditV1` records the typed rejection reason and current graph,
trust and portfolio verification identities. Operators can distinguish normal
wait/no-intervention from stale, revoked, unavailable, corrupt and indeterminate
conditions without granting the optimizer execution authority.

## 14. Verification matrix

Focused owner tests include:

- exact durable-registry enumeration;
- incomplete candidate-set rejection;
- negative prerequisite in a positive bundle;
- hard conflict enforcement;
- controller-collision rejection;
- objective/scope mismatch;
- realization-binding replay rejection;
- evidence expiry as unavailable pricing;
- utility and candidate-binding tamper detection;
- graph and trust drift at exercise;
- exercise-policy context mismatch;
- strict codec round trips, unknown/missing fields, enums, ordering, bounds and
  maximum encoded size;
- compatibility optimizer and graph regressions.

The focused workflow runs:

```text
python3 scripts/verify_prompt_optimizer_map.py
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-prompt-optimizer
cargo check --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd --all-targets
```

A source test identity or queued workflow is not a pass receipt.

## 15. Completion and remaining gates

Repository-controlled completion requires:

1. current focused package tests and all-target Agentd compilation pass;
2. current exact-head and deterministic merge candidate pass required CI;
3. executable Agentd product tests traverse staging, physical provider terminal
   and learning-ledger admission;
4. target-host capacity and fault measurements establish operational ceilings;
5. implementation map and docs remain synchronized with source.

External gates remain independent causal review, operator acceptance, canary,
promotion and release. Until those conditions are evidenced,
`productionImplementation`, `productExecutionProved`, `activation` and `release`
remain false.
