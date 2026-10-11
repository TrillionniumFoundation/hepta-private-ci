# V8.2 Value–Learning Core Implementation Wave 1

## Status

This candidate materializes four previously unmaterialized source roots on exact base
`726c4f1f548a39b6b1a679e8f2f17898a9a447bf`:

- `objective.compiler` → `codex-rs/hepta-objective`
- `utility.ndu` → `codex-rs/hepta-ndu`
- `learning.ledger` → `codex-rs/hepta-learning-ledger`
- `learning.artifacts` → `codex-rs/hepta-learning-artifacts`

The implementation is a source candidate only. It does not activate a runtime,
write production state, invoke a model or provider, execute an external effect,
select or promote a candidate, authorize a release, or enable propagation.

## Closed source gaps

### Objective compiler

The compiler consumes typed, bounded evidence and emits a deterministic immutable
objective. Constitutional and principal constraints remain non-compensable. Raw
untrusted evidence cannot mint privileged constraints or legal actions. Conflicting
hard intervals and forbidden requested actions produce deterministic conflict
receipts. Explicit abstain is always present.

### NDU evaluator

The evaluator validates objective and generation binding, required-organ
completeness, non-empty support evidence and bounded dimensions. It applies hard,
risk and resource feasibility before Pareto filtering. Missing contributions are
errors, not zeroes. Optional scalarization is complete, non-negative, normalized,
and its digest is computed from canonical inputs rather than accepted from the
caller. Receipts bind the complete evaluated set, rejection reasons, Pareto set,
profile digests and any advisory recommendation.

The preference solver uses deterministic Q32 arithmetic, staged hierarchy updates,
bounded damping, projection and a maximum of 64 iterations. Every update creates a
new immutable revision.

### Learning ledger

The append-only ledger records complete candidate sets, selected propensity,
independently observed terminal outcomes, credit and revocation. It rejects policy
self-labeling, duplicate semantic identities, zero propensity, missing abstain,
credit against non-terminal or revoked ancestry, and revocation of revocation.
Hash-chain snapshots are replayed through all invariants; decision revocation makes
outcomes and credit ineffective and they cannot be reattached afterward.

### Artifact registry

The registry records immutable prompt/policy/model/workflow/skill/parameter/topology/
code/adapter artifacts and lineage. All content, objective, support and compatibility
digests are mandatory. Candidate generators cannot evaluate their own state changes.
Quarantine or revocation of any ancestor makes every descendant ineligible, closing
the derived-artifact resurrection path. The API intentionally exposes no activation,
selection, promotion or release operation.

## Vertical qualification

`codex-hepta-shadow-qualification` adds a source-only vertical test:

1. compile a constrained objective;
2. register abstain, safe and hard-violating policy artifacts;
3. reject the unsafe high-utility candidate before Pareto selection;
4. record the full decision set, independent terminal outcome and credit;
5. replay both hash-chain snapshots;
6. revoke the decision and selected artifact;
7. prove causal descendants and revoked artifacts do not become eligible again.

## Required evidence before merge

The exact branch head must pass manifest verification, Rust formatting, `cargo
check`, Clippy with warnings denied, unit tests and the shadow vertical test. A green
source candidate still does not establish runtime activation, longitudinal efficacy,
physical safety, operator acceptance, promotion or release authority.
