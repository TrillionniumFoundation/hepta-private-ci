# prompt.optimizer canonical policy pipeline

This addendum describes the **active** implementation in
`codex-rs/hepta-prompt-optimizer/src/canonical.rs`. The former unreferenced
`policy*.rs` implementation has been removed. Historical score-only and
local-shadow calculators are isolated under
`codex_hepta_prompt_optimizer::compat`; they are not registered product policy.

The module remains read-only and authority-free. Every output is a proposal or
evidence receipt with `AuthorityPosture::DENY_ALL`; provider, tool, mutation,
promotion and release authority remain outside this crate.

## 1. Unique active operations

The canonical source owns exactly four policy operations:

1. `enumerate_factors_v1`
2. `price_factors_v1`
3. `select_portfolio_v1`
4. `exercise_v1`

`docs/modules/prompt.optimizer/IMPLEMENTATION_MAP.json` records these native
symbols, their source tests and product callsites. The read-only verifier
`scripts/verify_prompt_optimizer_map.py` compares that map with the Rust module
tree and rejects reintroduction of orphan `policy*.rs` files.

## 2. Compatibility surface

The following APIs are retained only to avoid breaking existing qualification
fixtures:

- `compat::optimize`
- `compat::optimize_with_factor_graph`
- `compat::local_shadow::calculate_local_shadow`

Temporary crate-root re-exports preserve source compatibility. New code must
name `compat` explicitly. None of these APIs authenticates registry, graph or
learning evidence, and none may be presented as the canonical product pipeline.

## 3. Canonical candidate enumeration

`enumerate_factors_v1` reads one exact prompt-registry V2 snapshot and model
tuple, fails closed on an incomplete owner read, chooses one compatible
realization per factor deterministically, binds canonical ordering and omitted
count, and emits a deny-all candidate receipt.

The production rule is **complete-owner-read first, deterministic caller cap
second**. A registry projection truncated at its owner boundary is an error; a
smaller caller-requested cap is recorded in the canonical candidate receipt.

## 4. Evidence-qualified pricing

`price_factors_v1` consumes generator completeness evidence plus evaluator
pricing evidence. It subtracts downside and all registered prompt costs from
incremental utility. Missing, stale, scope-mismatched or unauthenticated evidence
is not converted into zero-cost benefit.

The canonical type-state hardening work requires every pricing row to bind the
exact objective, candidate set, registry snapshot, generation vector, model
tuple, realization identity/binding and pricing policy. Generator and evaluator
controllers must be independent.

## 5. Constraint-aware portfolio selection

`select_portfolio_v1` consumes a complete generation-bound knowledge projection.
Prerequisites are closed transitively and evaluated as bundles; conflicts are
non-tradable; numeric complement/substitute terms require authenticated pair
support. Incomplete projections and unsatisfiable required closures fail closed.

The bounded solver reports the actual method, rounds, termination reason,
incumbent value, resource use and either a certificate/gap or
`HeuristicNoCertificate`. Compatibility heuristics do not determine canonical
capacity or semantics.

### Graph visibility is time-dependent

The public selector enters through `canonical_temporal.rs` before invoking the
existing private solver. A graph digest freezes its facts, but does not freeze
temporal visibility: a future conflict or prerequisite can become active in the
same graph generation. Inspecting only currently returned relation edges misses
that transition.

Selection therefore caps the requested portfolio deadline at the earliest
strictly future `valid_from_unix_seconds` or `valid_to_unix_seconds` of every
non-tombstoned node/edge support in the immutable generation. Seconds convert to
milliseconds with checked arithmetic. Invalid clocks and unrepresentable
boundaries fail closed. The graph owner defines start-inclusive/end-exclusive
visibility; a portfolio must be selected again at the transition itself.

This conservative whole-generation fence can force reselection for an unrelated
support change. It deliberately favors rejection over accepting a stale hard
constraint. It neither invents missing-edge utility nor adds another solver.
The existing solver can shorten the deadline further for evidence, realization
and active relation expiry; it cannot extend the temporal cap. That final
deadline is included in the portfolio receipt and audit digests.

Native regression sources in `canonical_temporal.rs` cover a future conflict
whose query result changes without a generation-digest change, future
prerequisites, exact millisecond boundaries, node/multiple-support transitions,
tombstones, past boundaries, invalid clocks and conversion overflow. These are
test identities, not assertions that current CI has executed successfully.

## 6. Exercise and delivery revalidation

`exercise_v1` revalidates the exact selected realization set against the current
registry immediately before delivery. The hardened boundary also revalidates the
knowledge generation, evidence trust digest/epoch and the minimum validity
window inherited from registry, evidence and graph support.

Stale, revoked, unavailable, incomplete, corrupt, indeterminate and quarantined
conditions remain distinct audit reasons even though all unsafe conditions fail
closed.

## 7. Product composition

The required named product path is:

```text
prompt.registry owner snapshot
→ enumerate_factors_v1
→ price_factors_v1
→ select_portfolio_v1
→ exercise_v1
→ context.compiler
→ Agentd/Codex physical provider boundary
→ terminal PromptDeliveryObservationV1
→ learning.ledger admission
```

A caller may not hand-construct an intermediate verified stage. Raw wire values
must be revalidated into private verified type-state at every cross-crate
boundary. `build_canonical_prompt_plan_v1` calls the same time-admitted public
selector as other consumers. It rejects a use time before enumeration, zero
clocks, and state/model/generation substitution between those stages. This is a
single-plan chronology check, not a claim of a persistent monotonic host clock.

## 8. Claim boundary

Source implementation, source composition and tests do not establish deployed
activation, target-host capacity, causal efficacy, independent acceptance,
canary, promotion or release. `productionImplementation` remains false until the
current exact-head and deterministic merge candidate pass required CI and the
named product callsite has executable end-to-end evidence.
