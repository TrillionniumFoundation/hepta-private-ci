# prompt.optimizer: implementation design

Parent: `docs/modules/prompt.optimizer/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
The active API is the verified canonical pipeline. Source implementation,
compiled tests, product execution and independent causal acceptance are separate
facts. Compatibility calculators are not substitutes for evidence admission.

## 1. Source and work envelope

Exclusive root: `codex-rs/hepta-prompt-optimizer`. Bootstrap package:
`PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`. Registry, graph, runtime, context and learning
owners retain their existing write domains. No new authority or execution spine
is introduced. Removed `policy*.rs` files were outside the Rust module tree;
Git history retains their provenance without a competing current API.

## 2. Public operations and contract details

`canonical::enumerate_factors_v1` returns a sealed candidate phase from the
registry. `canonical::price_factors_v1` requires independently signed exact-context
pricing. `canonical::select_portfolio_v1` accepts sealed pricing and signed graph
admission. `canonical::exercise_v1` accepts only a sealed selection and rechecks
current owners and the host exercise policy. `build_verified_prompt_portfolio_v1`
composes the first three phases through a host-installed evidence source.

Raw DTOs have no conversion into verified phases; their fields do not establish
provenance. The arithmetic engine is private. Compatibility entrypoints remain
under `compat` with temporary root forwarding. Registered V1 wire schemas remain
in `docs/contracts/PROTOCOL_SCHEMAS.json`; no rich DTO or debug representation is
a substitute for canonical wire codecs and golden conformance.

## 3. State records and transaction design

The optimizer owns no durable state. Verified phases retain immutable signed
inputs and a host evidence-source capability. Candidate structure and digests
are recomputed; pricing is replayed before selection and exercise; selected
bindings, costs, utility and receipt digests are rechecked. Persisted raw receipts
cannot recreate verified phases. Pricing batch signatures bind the exact registry,
candidate, objective/state/scope, model, generation, grammar, pricing policy,
realization and individual evidence. Interaction admission additionally binds
graph identity and missing-pair semantics. Evaluators must be actor/controller
independent of the generator.

## 4. Deterministic algorithm and scheduling

The arithmetic selector remains greedy prerequisite-bundle selection with stable
utility/token/identity ties and `HeuristicNoCertificate`. Cycles fail closed;
a requires closure with a hard conflict is diagnosed as unsatisfiable. Selected
pairs require explicit support or an independently signed zero-interaction
assumption. Empty verified selection means no intervention, not a fabricated
learning treatment assignment. Directional dominance/supersession pruning,
required-factor preservation through final truncation and detailed exclusion
reasons still need implementation and qualification.

## 5. Capacity and performance profile

Limits: 128 factors, 512 queried edges, 16 selected factors, token budget at most
1,000,000. The upstream realization read must be complete; truncation there is
rejected. A smaller final candidate limit records omitted count. The audit bounds
utility by summing positive factor and pair terms while relaxing budget and
constraints. It reports an absent bound on overflow, not a false certificate.
These source bounds do not establish target-host latency or capacity.

## 6. Concrete verification cases

POPT-01: exact bindings, hard conflicts and prerequisite bundles. POPT-02: invalid
pricing never creates zero-cost benefit. POPT-03: no-intervention and independent
causal assignment remain distinct. POPT-04: revocation or model/evidence/trust/
graph/policy drift invalidates use at the corresponding boundary.

The verified tests exercise real signatures and tamper/expiry/controller cases.
The orchestration test calls the actual builder. A downstream compiler test first
compiles a positive control, then rejects raw substitution, mutation, construction
and access to the private engine. Compatibility graph tests are part of the
module tree. Intelligence and Agentd fixtures use real signature admission rather
than constructing a selected portfolio. Runtime recovery tests remain separate
from scientific or provider evidence. Exact candidate logs own pass/fail/skip
facts; test names and compiling source do not certify execution.

## 7. Integration, rollback and capability ceiling

`AgentdPromptOptimizerV1::optimize_and_stage` is the named source consumer through
enumeration, pricing, selection and existing context/runtime staging. Concrete
current owner readers, default daemon invocation, final-send proof retention,
physical provider-terminal-to-ledger qualification, wire conformance and host
fault/load evidence remain gaps. No stage acknowledgement is reported as provider
delivery. Unknown outcomes remain indeterminate; the optimizer never self-writes
observed causal outcomes or credit. Existing App Server/Core ownership is retained.

## 8. Current native implementation

Active: `canonical.rs`, `canonical_body.rs`, `canonical_admission.rs`,
`canonical_integrity.rs`, `canonical_audit.rs`. Private arithmetic:
`canonical_engine.rs`. Compatibility: `compat.rs`, `graph.rs`, `graph_impl.rs`,
`local_shadow.rs`. Consumers: Agentd `prompt_optimizer_product.rs` and
`prompt_runtime.rs`, intelligence `prompt_delivery.rs` and `prompt_pipeline.rs`.

`productionImplementation`, `productExecutionProved`, `independentAcceptance`,
`activation` and `release` remain false until their separate evidence exists.
