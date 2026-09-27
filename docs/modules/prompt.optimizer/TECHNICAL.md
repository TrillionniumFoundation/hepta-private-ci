# prompt.optimizer technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `prompt.optimizer`
**Owner / deputy:** `intelligence-platform` / `performance`
**Lifecycle:** `target`
**Source status:** `existing_bound`
**Bootstrap work package:** `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`

This guide describes the active source, its trust assumptions and its remaining
implementation work. Git and exact-candidate CI own current execution facts;
a source link, test name or completed documentation section is not a pass receipt.
Canonical JSON registries continue to own module, contract and authority facts.

## 1. Identity, mission and ownership

Price and select a bounded prompt intervention portfolio without mutating the
prompt registry, objective, knowledge graph or learning ledger. The module is a
`domain`-plane `optimizer` with `stateless_runtime` state and the architectural
role `intervention_policy`. Its outputs are proposals, not effect capabilities.

The primary owner maintains algorithm correctness, receipt semantics and source
compatibility. The deputy independently reviews trust boundaries, bounds,
qualification and performance. Cross-owner composition uses the existing
intelligence, registry, runtime and ledger owners. It must not create another
model execution loop, registry writer, authority issuer or learning store.

## 2. Source binding and implementation status

The exclusive root is `codex-rs/hepta-prompt-optimizer`.

The only supported policy API is `codex_hepta_prompt_optimizer::canonical`.
[canonical.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical.rs) exports
[canonical_body.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_body.rs).
The previous arithmetic implementation is private in
[canonical_engine.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_engine.rs);
no external consumer may invoke its raw selector or exercise function.

Compatibility calculators are grouped under `compat`. Temporary root re-exports
preserve existing caller source and receipt semantics. They are not equivalent
to the verified pipeline. The unreachable `policy*.rs` implementation has been
removed; its former tests must not be counted as current coverage.

`existing_bound` means that the root exists. `productionImplementation` and
`productExecutionProved` remain false. The named Agentd consumer is source-level
composition, not proof of default daemon activation or a completed physical
provider-to-ledger product run. Read the exact operation and test inventory in
[IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json).

## 3. Boundary, responsibilities and non-goals

Declared domain dependencies remain `platform.types`, `prompt.registry`,
`utility.ndu`, `memory.retrieval` and `learning.artifacts`. The current native
arithmetic implementation additionally consumes `hepta-kg` and learning-ledger
signed evidence. These source dependencies do not transfer domain ownership;
registry/port reconciliation remains necessary before production qualification.

Authoritative write domains: none. Explicitly forbidden: `registry_write`,
`objective_rewrite`, `authority_issuance`. The module never directly performs
provider, tool, network, filesystem-effect, acceptance, promotion or release
operations. Host-supplied evidence is not permitted to install its own trust
root or redefine the current objective.

A cryptographic signature authenticates an assertion and its scope; it does not
prove causal efficacy. Likewise, a graph content digest is not an independent
attestation that a graph is complete. The embedding is responsible for supplying
current authenticated owner views, while the optimizer enforces their binding.

## 4. Internal architecture and component decomposition

The native phase sequence is:

```text
PromptRegistry + PromptEnumerationRequestV1
  -> enumerate_factors_v1
  -> EnumeratedPromptCandidatesV1
  -> signed completeness + exact-context pricing batch
  -> price_factors_v1
  -> PricedPromptCandidatesV1
  -> signed exact-context graph/pair batch
  -> select_portfolio_v1
  -> SelectedPromptPortfolioV1
  -> current owner views + exercise_v1
  -> PromptExerciseDecisionV1
```

`build_verified_prompt_portfolio_v1` sequences enumeration, evidence production,
pricing and selection. `AgentdPromptOptimizerV1::optimize_and_stage` is the named
consumer that uses the existing `AgentdPromptPipelineOwner`, then invokes context
compilation and runtime staging. It is implemented in
[prompt_optimizer_product.rs](../../../codex-rs/hepta-agentd/src/prompt_optimizer_product.rs).
No request accepts a preconstructed raw portfolio instead of those phases.

Verified phase fields are private. Immutable `Deref` permits reading existing
field names but supplies neither `DerefMut` nor a raw-to-verified constructor.
The `Raw*` aliases are explicitly untrusted inspection/transport values. Cloning
an inspected raw DTO cannot recreate a verified phase. Only a successful native
admission/selection operation constructs the corresponding verified object.

Admission and integrity helpers are split into
[canonical_admission.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_admission.rs)
and [canonical_integrity.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_integrity.rs).
Candidate bindings, IDs, ordering, counts and receipt digests are recomputed.
Pricing is replayed against retained signed evidence before selection and exercise.
Selection accounting and the portfolio receipt digest are recomputed before use.

## 5. Contracts, ports and compatibility

The four registered output contract names remain `PromptCandidateSetReceiptV1`,
`PromptPricingReceiptV1`, `PromptPortfolioReceiptV1` and `PromptExerciseDecisionV1`.
Their public registered field shapes are specified by
[PROTOCOL_SCHEMAS.json](../../contracts/PROTOCOL_SCHEMAS.json), not inferred from
the richer in-process arithmetic DTOs or audit structures.

The verified pipeline currently operates through in-process Rust types. This
candidate does not claim that the richer DTOs already implement the registered
canonical JSON wire format. Canonical encoding, duplicate/unknown-field
rejection, maximum encoded sizes, round trips and golden conformance vectors
remain explicit work. Do not serialize a debug representation as a wire receipt
or silently widen a V1 schema with the wrapper's provenance fields.

The `PromptPricingAdmissionV1` batch evaluator signature binds the candidate
receipt, registry snapshot, objective, state, generation, model tuple, grammar,
scope, pricing policy, exact realization bindings and individual evidence bytes.
Individual evaluator signatures are retained and verified as well. The independent
Generator and every relevant Evaluator must have distinct authenticated actors
and controllers, using the learning-ledger actor-separation validator.

`PromptInteractionAdmissionV1` binds candidate/pricing identity, objective and
scope, exact model/generation, graph source/generation, ordered pair evidence,
and the missing-pair policy. Missing interaction values are never silently
upgraded into measured zero effects: `AssumeZeroWithWitness` is an explicitly
signed assumption; `RequireExplicit` rejects any selected unsupported pair.

`PromptExercisePolicyV1` contains actual allowed boundaries and wait valuation,
objective/scope/state/generation/model bindings and a half-open validity window.
The request's policy digest and wait value must match this host-owned policy.

## 6. Data authority, persistence and migrations

The optimizer owns no durable state or schema. Database migration, writer locks,
fsync, outboxes and backup restoration are not implemented here. They belong to
the registry, graph, runtime and learning owners. In-process verified handles
retain immutable admitted evidence and a host-installed evidence-source handle;
raw bytes on disk cannot independently restore verified state.

The caller must reconstruct a verified phase from current authenticated owner
inputs after restart. An old receipt digest, debug dump or copied registry
snapshot is not sufficient. Historical learning facts and scientific support
remain the responsibility of `learning.ledger` and its authenticated readers.
No optimizer adapter may grant itself registry write or observation authority.

## 7. Runtime, concurrency and transaction model

`PromptEvidenceSourceV1: Send + Sync` is installed by the trusted embedding. Its
`current` operation must reread the relevant authority, graph and policy owners;
it must not indefinitely replay an untrusted request-supplied snapshot. Pricing
and interaction methods return signed owner evidence rather than anonymous
numeric scores. Source identity, trust digest and scope are pinned during pricing.

Selection and exercise reread the source and reject trust rotation, source drift,
objective/scope mismatch or pricing-policy drift. Exercise also rejects graph
and exercise-policy replacement. These are synchronous bounded source calls;
blocking I/O requires owner-side deadline and cancellation enforcement. The trait
alone does not establish a production input adapter or timing guarantee.

The Agentd consumer uses the existing registry owner and context compiler. Default
daemon wiring, final physical-send validation after staging, and a coherent
provider-terminal-to-ledger execution receipt must be qualified at those owners.
A sequence of successful pure functions is not a substitute for that boundary.

## 8. Failure semantics, recovery and rollback

The verified API distinguishes integrity, evidence, objective, scope, source,
trust, graph and policy failures. It has explicit variants for expired evidence,
unsatisfiable constraints, missing pair support, unavailable, timed out, corrupt,
indeterminate and quarantined inputs. Do not turn these conditions into positive
zero-cost utility or silently select an unverified compatibility result.

The private arithmetic engine still maps some registry-read failures into
`RejectStale`. Complete owner-error classification is remaining work; the new
variants alone do not prove that every dependency error is mapped precisely.

No-intervention is represented by an empty verified selection. It is not a
canonical learning-ledger `abstain` assignment or evidence of randomized treatment.
Agentd returns `NoIntervention` without fabricating delivery. Rollback rebuilds a
selection using compatible, non-revoked registry bytes and current evidence.
A runtime dispatch with unknown outcome remains indeterminate until its owner
reconciles it; the optimizer never fabricates terminal delivery or negative proof.

## 9. Security, privacy and threat controls

Owned threats: `prompt_candidate_selection_bias`, `prompt_factor_interference`.
Every generated proposal remains `AuthorityPosture::DENY_ALL`.

Candidate integrity checks bind factor ID, realization ID, exact realization
content digest and the full model/tokenizer/template/tool/context/locale tuple.
Pricing batch signatures prevent individually signed estimates from being moved
to another candidate realization, registry cut or pricing policy. The host
verifier's objective and scope must match the current candidate context.

The portfolio lifetime is capped by requested validity, realization expiry,
completeness/pricing/pair/batch evidence expiry, host exercise-policy expiry and
retained graph support end times. Exercise rechecks current trust and graph;
a valid old signature cannot override current revocation configuration.

The host must authenticate the evidence-source implementation and supply reliable
clock values. Generator code, hard-filter and truncation-policy expected identities
still require stronger host pinning; nonzero digests alone are not qualification.
Final-send freshness, caller authentication and concrete trust distribution are
not self-certified by the presence of the generic source trait.

Audit output uses IDs and digests rather than raw prompt text, credentials or
private training examples. The runtime and registry still own retention/deletion.

## 10. Performance, capacity and hot-path policy

Canonical bounds are 128 retained factors, 16 selected factors, 512 queried
interaction edges and a token budget of at most 1,000,000. The legacy compatibility
limits differ and must not be used to describe canonical capacity.

Enumeration presently demands a complete registry realization read within its
128-entry read bound before selecting one lowest-token compatible realization
per factor. An upstream truncated registry read returns `RegistryReadIncomplete`.
A smaller requested candidate limit may subsequently truncate the per-factor
set and records omitted count. This is not the retired policy path's 4096-to-128
streaming enumeration. Pagination/completeness and required-factor preservation
across final truncation still need dedicated capacity qualification.

The selector remains deterministic greedy prerequisite-bundle search with
`HeuristicNoCertificate`. It closes prerequisites atomically, detects requires
cycles and rejects a requires closure containing a hard conflict. Some directed
relations still use the engine's conservative symmetric exclusion semantics;
directional pruning, richer reasons and an explicit semantic migration remain
work rather than an undocumented change of contract.

The audit reports a valid relaxed upper bound: sum of all positive priced factor
utilities plus all positive supplied pair terms, ignoring budget and constraints.
The gap is that bound minus the incumbent. Checked wide arithmetic yields no
bound rather than a false finite certificate if the registered range overflows.
This bound may be loose. Solver rounds are currently unavailable (`None`), not
inferred from selected-factor count. Swap/beam/exact-oracle improvements,
precomputed closures, incremental marginals, bitsets and target-host benchmarks
are not yet claimed.

## 11. Observability and operations

[canonical_audit.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_audit.rs)
records candidate/completeness/omission, source/trust/scope, pricing and interaction
attestations, pricing policy, graph generation, portfolio identity, oldest evidence
age, validity, token allocation, incumbent and relaxed upper bound/gap. Its digest
is recomputable and is separate from registered V1 wire receipt shape.

Per-candidate diagnostics currently distinguish `Selected` and `HeuristicExcluded`.
They must not be described as a complete causal rejection taxonomy. Unavailable
pricing currently fails admission; a persisted per-factor unavailable-pricing
report, detailed conflict/budget/revocation reasons and exact solver termination
telemetry remain outstanding. No operation claims observed causal uplift.

## 12. Verification and qualification

Use `just test` from the repository. Native qualification includes:

```sh
just test --locked --lib -p codex-hepta-prompt-optimizer
just test --locked --lib -p codex-hepta-intelligence -E 'test(prompt_)'
just test --locked --lib -p codex-hepta-agentd -E 'test(prompt_runtime)'
```

Compile relevant all-target consumers and run strict Clippy and changed-source
format checks separately. The workflow
[Hepta architecture convergence](../../../.github/workflows/hepta-architecture-convergence.yml)
uses exact source and deterministic synthetic-merge lanes, retains command logs
and binds their Git identity. It is read-only and never pushes formatter output.
Zero executed tests, failed commands and missing evidence are not passes.

[canonical_verified_tests.rs](../../../codex-rs/hepta-prompt-optimizer/src/canonical_verified_tests.rs)
contains actual signed admission and negative cases for candidate/realization,
batch signature, individual estimate substitution, objective/scope, shared
controller, pricing replay, expiry, missing-pair assumption, graph/policy drift
and altered portfolio utility. Private engine unit tests remain arithmetic-only.

Intelligence and Agentd prompt fixtures now obtain sealed portfolios through the
real generator/evaluator signature checks rather than public struct literals.
They use deterministic test keys and are not production trust configuration.
The runtime crash, retry and indeterminate-outcome tests remain separate from
scientific evidence and real provider execution. Wire goldens, external compile-
fail API tests, default daemon ingress, final-send freshness and end-to-end ledger
qualification remain necessary. Source inventories must distinguish compiled
files and listed test binaries from merely present files.

## 13. Implementation sequence and work packages

Applicable packages are `PIM-0-PROMPT-INTERVENTION-CONTRACTS`,
`PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW` and `PIM-3-FACTOR-EVOLUTION`.
Source development and runtime activation have different predecessors. Ordinary
authorized edits use the actual Git baseline, owner scope, focused tests and
normal protected review; they do not require unrelated deployment authority.

Close trust and boundary correctness before increasing optimizer complexity.
Next priorities are final dispatch proof retention, concrete owner-source/default
daemon composition, canonical wire conformance, exact public/test inventory,
complete error/relation semantics and bounded solver/observability improvements.
`PIM-3` next-snapshot evolution and independent causal acceptance do not become
complete merely because this library compiles.

## 14. Activation, compatibility and retirement

No shadow, fixture or source-only caller is a deployed production caller.
Activation requires the named embedding, authenticated owners, final dispatch
boundary, correct terminal observation, ledger admission, resource profile and
operator acceptance. Signing evidence grants no provider or tool authority.

`compat::optimize`, `compat::optimize_with_factor_graph` and
`compat::local_shadow::calculate_local_shadow` retain historical semantics and
root forwarding exports only for migration. Do not route canonical failure through
these calculators as a trust bypass. Remove root forwarding only after all named
callers migrate and rollback/interoperability evidence has been reviewed.

## 15. Definition of module completion

Documentation completion requires accurate current API descriptions, canonical
registry references, usable local links and a verified operation/test inventory.
Source implementation requires compiling active modules and executable tests.
Product implementation additionally requires concrete current owner inputs and
the complete real invocation/dispatch/observation/learning path. Empirical causal
acceptance, activation, promotion and release remain separately governed.

This guide grants no runtime, production-writer, model, provider, tool, network,
filesystem, secret, Matrix, fleet, independent-acceptance, promotion or release
authority. `productionImplementation`, `productExecutionProved`,
`independentAcceptance`, `activation` and `release` remain false.

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `prompt.optimizer` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `ModulePort::prompt.optimizer::context.compiler`
- `ModulePort::prompt.optimizer::intelligence.control`
- `PromptCandidateSetReceiptV1`
- `PromptExerciseDecisionV1`
- `PromptPortfolioReceiptV1`
- `PromptPricingReceiptV1`

**Consumed contracts:**
- `CandidateSetCompletenessReceiptV1`
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::prompt_factor_lifecycleV1`
- `DomainRead::prompt_factor_registryV1`
- `DomainRead::prompt_realization_registryV1`
- `ModulePort::learning.artifacts::prompt.optimizer`
- `ModulePort::memory.retrieval::prompt.optimizer`
- `ModulePort::platform.types::prompt.optimizer`
- `ModulePort::prompt.registry::prompt.optimizer`
- `ModulePort::utility.ndu::prompt.optimizer`
- `NduPreferenceStateV1`
- `ObjectiveFunctionV1`
- `PromptFactorV1`
- `PromptRealizationV1`

**Typed protocols:**
- `CandidateSetCompletenessReceiptV1`
- `NduPreferenceStateV1`
- `ObjectiveFunctionV1`
- `PromptCandidateSetReceiptV1`
- `PromptExerciseDecisionV1`
- `PromptFactorV1`
- `PromptPortfolioReceiptV1`
- `PromptPricingReceiptV1`
- `PromptRealizationV1`

**Owned data domains:**
- None.

**Read data domains:**
- `candidate_set_completeness_receipt_v1`
- `learning_artifact_registry`
- `ndu_preference_projection`
- `ndu_utility_projection`
- `operator_sensor_core_registry`
- `prompt_factor_lifecycle`
- `prompt_factor_registry`
- `prompt_realization_registry`

**Work packages:**
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`
- `PIM-3-FACTOR-EVOLUTION`

**Owned threats:**
- `prompt_candidate_selection_bias`
- `prompt_factor_interference`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `prompt.optimizer` to primary lane
`LANE-F-ADAPTIVE-POLICY`. Mandatory specifications alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols: None. Consumed readiness protocols: None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned
paths, mandatory fixtures, deterministic fallback and rollback. A runtime
coordinator admitting an envelope verifies its current `CanonicalSourceReceiptV1`,
frozen contract/readiness digest, expiry and zero authority delta. This is not a
separate permission gate for ordinary repository work and changes no activation,
acceptance, selection, promotion or release facts.

## 17. Source implementation receipt

The bootstrap source-location obligation for `prompt.optimizer` is materialized
by `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW` at `codex-rs/hepta-prompt-optimizer`.
The source is subject to `.github/workflows/hepta-consolidated-source.yml` and the
focused hardening workflow described above. Exact Git identity, actual executed
test counts, all-target checks, strict lint, source inventory and failure logs
must be read from those candidate runs; this section does not cache pass claims.
It grants no production, effect, acceptance, selection, promotion, merge or
release authority.
