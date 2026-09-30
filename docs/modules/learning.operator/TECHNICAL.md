# learning.operator technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `learning.operator`  
**Owner:** `learning-platform`  
**Deputy:** `qualification-plane`  
**Lifecycle:** `target`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `HBO-0-BELLMAN-OPERATOR-CONTRACTS`

## Canonical status source

[`STATUS.json`](STATUS.json) is the single machine-readable source for current
implementation, product composition and external-gate state. This document
explains the design but does not independently restate mutable status facts.
Exact source, base, deterministic-merge, workflow, runner, toolchain, test-set,
implementation-map, documentation and artifact identities are emitted by the
qualification-generated `readiness-manifest.json`; they are not hand-maintained
in Markdown.

At the current contract boundary the default loader is
`LoadedTabularOperatorV2`, the read-only consumer and
`coordinate_learning_operator_shadow_v1` loop are wired, and fresh-process load
plus protocol E2E are required repository gates. Those facts do not establish
longitudinal product benefit: `productExecutionProved`, production writer
authority, independent acceptance, target-host acceptance, canary, promotion,
activation and release remain false.

Canonical admission semantics are in [ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).
Compatibility and capacity policy are in
[COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md](COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md).
Operations and recovery are in [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md).

## 1. Identity, mission and ownership

`learning.operator` trains bounded Bellman/operator candidates in qualification
space without online production mutation. The primary owner controls changes in
`codex-rs/hepta-bellman-operator`; the deputy independently reviews contracts,
authority checks, persistence boundaries, compatibility, concurrency, resource
limits and activation posture.

The module is a qualification-plane, stateful-shadow, slow-learner component. It
may optimize a bounded local objective but cannot claim global optimality,
absorb another owner's durable facts, self-select a candidate, or convert
repository evidence into deployment authority.

## 2. Source binding and implementation status

The declared and resolved source root is:

- `codex-rs/hepta-bellman-operator`

The product composition boundary additionally includes the explicitly mapped
Agentd ranker admission and shadow coordinator. The generated implementation
projection binds each source, document, workflow and qualification-control
object to the exact candidate SHA and tree. The checked-in
`IMPLEMENTATION_MAP.json` is navigation metadata, not a substitute for an
executed exact-source projection.

`existing_bound` means the source root exists. It does not grant production
writer authority, independent scientific acceptance, promotion, activation or
release. A source, workflow, test or document change creates a new exact
candidate and invalidates prior readiness evidence.

## 3. Boundary, responsibilities and non-goals

Direct dependencies are:

- `platform.types`
- `learning.ledger`
- `learning.artifacts`
- `kernel.evidence`

The module owns no authoritative write domain. Explicitly denied capabilities
are `online_current_artifact_mutation` and `production_write`.

Inputs must be registered, bounded, versioned and digest-bound. Missing
authority, stale revision, scope mismatch, unknown critical fields and digest
mismatch fail closed. The module does not mint authority consumed by itself,
interpret model prose as authority, bypass the Codex execution spine, or become
a general state store.

## 4. Internal architecture

The bounded implementation consists of:

- owner-authenticated dataset snapshot and row verification;
- deterministic feature, target and sensor-core construction;
- bounded tabular and action-conditioned world-model fitters;
- canonical training and runtime profiles with internally derived identities;
- single-use final-use capabilities;
- independent evaluation and selection handoff;
- create-only artifact persistence and V2 pinned loading;
- Agentd shadow observation, currentness/revocation checks and exact rollback.

The default product loop is:

```text
freeze training
→ derive canonical profile
→ issue and consume final-use capability
→ freeze an independent future window
→ independent evaluation
→ independent selection
→ create-only persistence
→ fresh-process V2 load
→ read-only shadow observation
→ currentness/revocation check
→ exact predecessor rollback
```

The coordinator exposes no publish, canary or activate port. A healthy candidate
still ends rolled back. Failure to reopen the exact predecessor is terminal.

### 4.1 Final-use capability model

`FinalUseFenceV1` binds ledger head, dataset generation, candidate generation,
authority epoch, stop epoch and an exclusive absolute deadline. Opaque tabular
and world-model capabilities borrow the durable owner, are non-`Clone`, retain
their issuance time and are consumed once.

Owner/currentness is checked at issue, immediately before fit, after fit and at
selected/pinned use. A witness before capability issuance is a clock regression.
Issue, use or publication handoff observed exactly at the deadline fails closed.
Cancellation, operation, estimated-memory and elapsed-time limits are enforced
through the bounded work controls.

### 4.2 Sensor-core qualification receipt

`build_sensor_core_qualified_v1` wraps the bounded V2 builder and emits a public
semantic receipt. The receipt identifies `selection_mode` as `exact` or
`reduced`, binds the fingerprint-stratified reduction algorithm identity and
working-set limits, and includes the underlying work receipt. Qualification
consumes this public behavior instead of scanning private Rust function names.

Exact/reduced comparison, deterministic replay and bounded geometry degradation
are executable tests. The reduced path is a bounded qualification mechanism,
not a universal geometric-optimality claim.

### 4.3 Multiscale DecisionCell integration target

Future DecisionCell work may execute bounded local tensor-training jobs for
heads/adapters and justified NDU-sensitive policy updates through existing
learning infrastructure. Reference critics and peer bundles remain frozen;
proper-prediction supervision does not disappear when utility is optimized.
Stochastic `Z` or a bounded eligibility summary is not treated as a full
Transformer gradient.

Routing, activation and termination policies are trained separately against
fixed NDU-consistent targets. Required tests include frozen-target replay,
trainable-tensor masks, bounded optimizer memory, deterministic seeds and
unsupported-estimator rejection. This is a planned profile, not current
production capability.

### 4.4 Capacity, depth and learning-evidence target

Every estimator must declare pathwise versus score/critic/distillation
semantics, gradient stops and unroll length. Local sensitivities are compared to
tractable oracles; nonlinear NDU objectives are matched explicitly. Optimizer
state and meta-adaptation rules are versioned candidates, not implicit authority.

### 4.5 Shared-experience and isolated-Agent target

Training consumes admitted frozen multi-shard replay views, never live
concatenated Agent logs. Purpose, estimator support, independent outcomes and
private/common parameter masks are explicit. Unsupported or uncertain RL rows
enter only a separately justified training class.

### 4.6 Owner-derived terminal-cell baseline

`owner_terminal.rs` freezes and fits a constant-state terminal-value table from
authenticated `LedgerWriter` decisions and terminal outcomes. It resolves the
exact frozen source set, preserves source sequence and revalidates corrections
and revocations before fitting. Mixed state/objective/action sets, unit drift,
incomplete outcomes and insufficient per-action support reject.

The terminal-cell baseline uses the existing artifact owner and pinned loader.
It is not a general Bellman solver, causal policy-improvement proof, Laya
backend or deployment selection.

## 5. Contracts, ports and compatibility

Produced contracts include Bellman/operator artifacts, regularity assessments,
canonical profiles, opaque final-use candidates and qualification receipts.
Consumed contracts include frozen dataset snapshots, authenticated decisions
and outcomes, artifact registry views, unlearning lineage, sensor-core manifests
and qualification evidence.

Rust types and canonical serialized forms carry the same semantics. Tests cover
round trips, maximum bounds, missing/unknown critical fields, invalid enums,
canonical ordering and digest stability. Error mapping preserves rejected,
unavailable, timed-out, indeterminate, quarantined and terminal outcomes.

The default crate root has an explicit export allowlist. Raw structural fitters
and caller-authored V2 verification inputs exist only behind the non-default
`qualification-unverified-input` feature and under `compatibility`. Independent
consumer compile-pass/compile-fail tests prove that default callers cannot reach
raw fitters, compatibility inputs, publish or activation ports.

## 6. Data authority, persistence and migrations

The module owns no authoritative store. It reads immutable owner-issued ledger,
artifact, unlearning and qualification facts. Candidate persistence is delegated
to `learning.artifacts` through create-only identities; selection and registry
currentness remain external owner facts.

Projection state is rebuildable from declared sources and never becomes a new
source of truth. Retention and deletion preserve lineage and prevent resurrection
through caches, indexes, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The deterministic core is side-effect free except for explicitly supplied owner
reads. One logical mutation has one transaction boundary at the actual owner.
Configuration affecting authority, schema, compatibility, objective, model
identity or resource policy creates a new revision or generation.

Current synchronous fitters use a cloneable monotonic cancellation token. Every
worker or blocking task that performs metered work must explicitly install the
same token; thread-local installation is not treated as cross-thread propagation.
Cross-thread cancellation and deadline races are qualification obligations for
any parallel implementation.

## 8. Failure semantics, recovery and rollback

Failures are classified by stage and scope. Identity conflict, stale owner,
revocation, deadline, cancellation, resource exhaustion, payload mismatch,
shadow rejection and rollback failure remain distinct. Queue acceptance or
handler return is never interpreted as external success.

Qualification writes one receipt per stage with `passed`, `failed` or `not_run`.
A failed documentation contract does not suppress independent compile, test,
mutation, coverage or performance diagnostics. Any failed, missing, cancelled or
not-run required stage forces `mergeReady=false` and
`productionQualified=false` in the single readiness manifest.

## 9. Security and privacy

The posture is least authority, bounded input, typed contracts, digest binding
and independent evidence. Credentials do not enter general logs, datasets,
prompt factors or cross-module receipts. Authority is operation-bound,
final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, stale/revoked grants, replay with
payload drift, unknown fields, oversized input, scope escape, secret/provider
leakage, clock regression and deadline equality.

## 10. Performance and capacity

Structural maxima are source bounds, not shipping capacity claims. Regression
qualification records time, process RSS checkpoints and model-estimated bytes
for bounded sensor and tabular cases. A target-host capacity profile requires
warm-up, a statistically meaningful measured sample, fixed host identity and
separate acceptance. GitHub-hosted runner results remain regression evidence
only; `targetHostCapacityAccepted` remains false in `STATUS.json`.

The sensor builder supports exact selection up to the configured exact limit and
a deterministic bounded reduction above it. The algorithm/version and limits
are digest-bound in the semantic receipt.

## 11. Observability and operations

Events distinguish source verification, capability issue, fit, selection,
persistence, load, shadow, currentness, revocation and rollback. Diagnostics
include stage identity, source/tree, runner/toolchain, target triple, command,
log digest and terminal state. Sensitive payloads are represented by digests.

Operators use `OPERATIONS_RUNBOOK.md`; no readiness manifest grants activation.

## 12. Verification and qualification

The authoritative workflow is read-only and runs the following independent
stages:

1. source identity;
2. documentation and schema;
3. default API surface;
4. compile;
5. unit and lifecycle tests;
6. product protocol integration;
7. mutation;
8. coverage;
9. resource/performance regression;
10. static quality;
11. deterministic ordered-parent merge;
12. exact-source receipt.

The final readiness manifest binds all identities and artifact hashes from one
workflow attempt. Results from separate attempts are never spliced. The real
post-merge `main` SHA must rerun the same workflow; PR-head evidence is not
reused.

Focused source tests include learned-grid determinism and completeness,
world-model evidence uniqueness, signed admission, exact frozen-dataset binding,
V2 payload corruption/reload/rollback, final-use deadline/clock behavior,
semantic exact/reduced sensor receipts and Agentd protocol E2E.

## 13. Implementation sequence and work packages

Applicable packages are:

- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- `BIO-2-REPLAY-CONSOLIDATION`
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR`

Contract-first work may run in parallel only with non-overlapping write paths
and frozen semantics. Production writer authority, independent evaluator and
selector acceptance, real future-window efficacy, target-host capacity,
operator acceptance, canary, promotion, activation and release require external
owners and exact-candidate receipts. Repository qualification cannot issue them;
activation remains false.
