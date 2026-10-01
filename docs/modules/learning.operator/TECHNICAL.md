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
`LoadedTabularOperatorV2`, and the evaluated read-only ranker is implemented.
`coordinate_learning_operator_shadow_v1` implements the shadow coordination
contract. The real artifact-owner persistence adapter, qualified V3 read-only
loader and `AgentdIntelligenceProductRunnerV1::persist_learning_operator_candidate`
entry exist. The configured default caller and complete owner-port composition,
including a distinct-process shadow load and exact predecessor rollback, remain
integration work. Coordinator state-machine tests still use fixture ports;
component loading or persistence does not prove the entire runtime lifecycle.
Those facts do not establish
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

The product composition boundary additionally includes Agentd ranker admission,
the shadow coordinator, artifact-owner persistence, qualified V3 shadow loading
and the contracts crate's three untrusted transport codecs. The generated implementation
projection binds each source, document, workflow and qualification-control
object to the exact candidate SHA and tree. The checked-in
`IMPLEMENTATION_MAP.json` is navigation metadata, not a substitute for an
executed exact-source projection.

`existing_bound` means the source root exists. It does not grant production
writer authority, independent scientific acceptance, promotion, activation or
release. The sources are mapped to checks; only current exact-candidate execution
receipts establish that those checks passed. A source, workflow, test or document
change creates a new exact candidate and invalidates prior readiness evidence.

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

The implemented coordinator contract sequences the following stages when a host
supplies the owner ports:

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
still ends rolled back. Failure to reopen the exact predecessor is terminal. Unknown persistence retains
run, candidate and selection recovery identity; it cannot safely load, clean an
unverified object or restart blindly. A verified persisted object is cleaned up
when later work expires, and unverified cleanup remains a recovery error. Host
clock and receipt expiry are checked at each port; terminal audit binds selection
reason, storage and rollback evidence.
The current coordinator has fixture-port state-machine tests. Its real
`LearningOperatorArtifactOwnerV1` adapter uses the existing fenced owner service
for exact create-only publication, retry and read-only status reconciliation.
`EvaluatedTabularShadowConsumerV3` loads admitted bytes with distinct training and
evaluation sources and checks current owner, selection, trust and deadline before
and after each prediction. The ProductRunner exposes a bounded persistence entry.
These are implemented components, not a configured implementation of every
`LearningOperatorShadowPortsV1` stage. Distinct-process loading, complete runtime
invocation and verified predecessor rollback still require one composed test.

### 4.1 Final-use capability model

`FinalUseFenceV1` binds ledger head, dataset generation, candidate generation,
authority epoch, stop epoch and an exclusive absolute deadline. Opaque tabular
and world-model capabilities borrow the durable owner, are non-`Clone`, retain
their issuance time and are consumed once.

Owner/currentness is checked at issue, immediately before fit, after fit and at
selected/pinned use. The immutable V2 predictor validates payload/pin identity
once. `SelectedTabularOperatorV1` and selected world-model prediction also enforce
the retained selection window; later owner events require fresh host witnesses
at every final use. Training trust is bound into tabular selection. A witness
before capability issuance is a clock regression.
Issue, use or publication handoff observed exactly at the deadline fails closed.
Cancellation, operation, estimated-memory and elapsed-time limits are enforced
through the bounded work controls. One monotonic fit context survives issuance
and dispatch: issuance time plus actual elapsed work must stay strictly below the
absolute deadline, even when supplied witness times are stale. Final cancellation
is checked before returning encoded candidate bytes. World-model request trust
must match the current owner verifier.

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
and revocations before fitting. Future observation/finality timestamps and a fit
clock earlier than freeze reject. Mixed state/objective/action sets, unit drift,
incomplete outcomes and insufficient per-action support reject.

The terminal-cell baseline uses the existing artifact owner and pinned loader.
`hepta-agentd/tests/terminal_cell_owner.rs` exercises evidence, freeze, fit,
persistence, reload, a later generation and withdrawal, including exact shared
source support. It is not a general Bellman solver, causal policy-improvement
proof, Laya backend or deployment selection.

### 4.7 Native profile and evidence boundaries

The learner fits a complete finite sensor/action table; the world model fits
action-conditioned transition counts. The bounded V2 profile uses exact integer
moments for variance/confidence, counts owned text and input capacity before
allocation, and protects fitted statistics and prediction metadata with private
integrity commitments. The Bellman reference accepts supplied
reward and continuation cells rather than simulating a diffusion or interpolating
a continuation function. Neural/tensor fitting and continuous reconstruction
remain separate profiles.

Sensor fill distance is measured over the supplied finite candidate design.
`hull_digest` commits selected point bytes; it does not certify continuous-domain
coverage or implement geometric hull containment. Fill distance and mesh ratio
round upward, separation radius rounds downward, and the manifest commits the
full candidate design. Tabular OOD is exact sensor/action identity membership.

Generic V2 dataset verification binds frozen receipt identity and exact evidence
membership; it does not derive numeric targets from ledger events. Internal V3
admission additionally binds current owner records and independently signed row
semantics. Signed targets remain observer attestations; the owner-derived terminal
profile derives its narrower targets directly from owner facts. Applicability and
regularity signatures authenticate exact attestations rather than measuring the
claimed geometry, rank, calibration or scientific assumptions.

World-model row signatures bind the model ID, exact samples, frozen dataset and
owner-trust context. They do not attest the host-supplied train/holdout/future
window identities, calibration, OOD/drift, change-point or retention values.
Range checks and artifact commitments protect those inputs but do not measure
them or establish future-window efficacy. The Holder reference still consumes
supplied reward/continuation cells; registered local-model integration,
continuous monotone reconstruction, certified hull OOD and branch/state/action
trunk fitting remain unimplemented profiles. A simpler reference may replace a
neural profile only after meeting the same independent acceptance bounds.

## 5. Contracts, ports and compatibility

Produced contracts include Bellman/operator artifacts, regularity assessments,
canonical profiles, opaque final-use candidates and qualification receipts.
Consumed contracts include frozen dataset snapshots, authenticated decisions
and outcomes, artifact registry views, unlearning lineage, sensor-core manifests
and qualification evidence.

Canonical wire parity is a target contract requirement. The contracts crate now
implements strict bounded untrusted V1 codecs for the registered sensor,
regularity and applicability protocols. Unknown fields, duplicate keys,
noncanonical numbers/ordering, reserved serde members and unsupported versions
reject. Current native candidate structs remain owner-local profiles: applicability uses
profile digests and a scalar interval, while registered wire schemas require
profile objects, horizon and jump-policy fields; native sensor manifests contain
points rather than the wire lifecycle envelope. Lossless context-bound native
bridges and semantic owner admission remain work. `BellmanOperatorArtifactV1`
is registered without a precise field schema and dispatch explicitly rejects it.
Native ordering, digest binding and `HEPTTB01` validation have focused tests.
No existing V1 wire schema is redefined by the native profiles.

Sensor/reference/target and tabular-training commitments use V2 digest domains
to bind full source inputs or minimum-support policy. Target multiplication uses
signed nearest/ties-to-even. Existing V1 struct names remain; `train` is a
compatibility-only alias. New fits and rebuilt references need independent
admission under their new identities. Correctly pinned existing `HEPTTB01` bytes
remain readable under current selection and revocation. The legacy world-model
V2 commitments bind complete rows; its private fit-owned seal rejects modified
models. Public field reads remain, external struct literals do not. There is no
persisted world-model wire migration. Error mapping retains rejected, unavailable,
timed-out, indeterminate, quarantined and terminal outcomes.

The default crate root has an explicit export allowlist. Raw structural fitters, direct V3 owner-bound verify/fit primitives
and caller-authored V2 verification inputs exist only behind the non-default
`qualification-unverified-input` feature and under `compatibility`. Independent
consumer compile-pass/compile-fail tests prove that default callers cannot reach
raw fitters, compatibility inputs, publish or activation ports.

## 6. Data authority, persistence and migrations

The module owns no authoritative store. It reads immutable owner-issued ledger,
artifact, unlearning and qualification facts. Candidate persistence is delegated
to `learning.artifacts` through create-only identities; selection and registry
currentness remain external owner facts.

The real publication adapter binds the candidate's borrowed
`TabularCandidatePublicationViewV1` to an externally admitted V3 manifest; the
view cannot issue that manifest or a selection. It preserves known storage or
unknown-write recovery facts after late expiry. The qualified shadow loader
refreshes both ledgers, the artifact owner's CURRENT source and independent
selection; a failed refresh permanently closes that handle pending re-admission.

| Interface | Time unit and boundary |
|---|---|
| Final-use fence/witness, candidate publication and shadow-run fields | Unix microseconds; deadlines are exclusive and retained monotonic elapsed work prevents stale-clock extension. |
| Real publication adapter and qualified V3 shadow consumer | Unix microseconds sampled from the host, with monotonic elapsed checks; submitted timestamps do not supply current time. |
| Registered V1 transport `expiresUnixMs` | Unix milliseconds; conversion needs explicit owner context and checked arithmetic. |
| Registered applicability `horizonMicros` and native `control_interval_millis` | Duration microseconds and duration milliseconds respectively; neither supplies the other's complete horizon/profile semantics. |

The optional plasticity process bootstrap now requires
`hepta.agentd.plasticity-bootstrap.v2` through
`load_plasticity_process_bootstrap_v2`. Its host descriptor explicitly supplies
the retained root key/validity and root-signed distribution identity, generation,
effective/issued/expiry times and signature. Existing V1 signer-only descriptors
are rejected; they are not automatically relabeled or self-signed as V2. Host
placement and retention of that root remain external configuration obligations.

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

## 9. Security, privacy and threat controls

The posture is least authority, bounded input, typed contracts, digest binding
and independent evidence. Credentials do not enter general logs, datasets,
prompt factors or cross-module receipts. Authority is operation-bound,
final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, stale/revoked grants, replay with
payload drift, unknown fields, oversized input, scope escape, secret/provider
leakage, clock regression and deadline equality.

## 10. Performance, capacity and hot-path policy

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

Repository work still includes native-to-wire owner context, the missing
`BellmanOperatorArtifactV1` field schema, remaining coordinator owner stages and
the configured default caller, plus successful qualification of the unified source
and deterministic merge candidate. Component E2E and a generic coordinator are
necessary engineering evidence, but do not close that composition obligation.

## 14. Activation, compatibility and retirement

Candidate fitting, independent evaluation, selection and artifact publication
have separate identities and owners. Publication into a qualification store
does not activate a runtime policy. Keep `STATUS.json` acceptance fields false
until the corresponding independent owner supplies exact-candidate receipts.
The shadow experiment restores the exact predecessor rather than selecting a
newly reconstructed approximation of it.

Digest-domain, semantic-profile, training-source or runtime changes create a
new candidate identity and require new qualification. Read existing `HEPTTB01`
payloads only with their original complete pins and current owner witnesses;
do not reinterpret them as registered Bellman JSON. Compatibility-only raw APIs
cannot satisfy the default final-use contract. Withdrawal, deletion, authority
rotation or a failed currentness refresh closes the consumer; cached bytes do
not restore eligibility.

## 15. Definition of module completion

Assess implementation and acceptance separately. The bounded deterministic
reference, tabular estimation, discrete world model, owner-bound final-use
capabilities and immutable read consumers have source implementations. Those
components do not implement every algorithm in the Holder specification.
In particular, tabular cell means are not the branch/state-trunk/action-trunk
neural operator, and finite candidate coverage is not continuous-domain coverage.

| Completion requirement | Evidence needed |
|---|---|
| Bounded candidate algorithms | Current default/compatibility tests, arithmetic, resource, integrity and adversarial regressions |
| Cross-owner qualification | Estimator-derived sealed qualification, actual fenced holdout consumption, durable publication and use-time authentication |
| Artifact lifecycle | Real owner persistence/reconciliation and qualified V3 read-only loading are implemented; distinct-process loading and exact predecessor rollback still need one complete lifecycle receipt. |
| Registered wire compatibility | Three registered untrusted codecs are implemented; the Bellman field schema, precise enum/member semantics and context-bound native bridges remain required. |
| Default runtime composition | ProductRunner persistence entry exists; a configured caller exercising every owner port in one durable shadow lifecycle remains required. |
| Scientific and host acceptance | Independent applicability/calibration, future-calendar benefit and accepted-host capacity receipts |

The remaining algorithmic scope is concrete:

- The reference consumes supplied reward/continuation cells. Local-model
  simulation/integration, monotone interpolation and antithetic paths from the
  Holder specification are not implemented by that interface.
- Sensor qualification measures a finite candidate set. It does not establish
  continuous-domain fill, a hull/OOD certificate or anisotropic reconstruction.
- Tabular estimation implements complete cell statistics and support. Neural
  branch/state/action trunks, action-gap losses, residual amplification/support
  diagnostics and optimizer training controls are not implemented. The design
  permits a qualified simpler reference, which still needs the corresponding
  independent error and applicability evidence.
- Discrete world-model statistics and integrity are implemented. Independent
  reward/risk heads, actual one/multi-step calibration, change-point and future
  retention measurements, and prediction-error modulation remain outstanding.

Do not compute a completion percentage from the number of mapped symbols or
test passes. A missing lifecycle edge or acceptance receipt remains a missing
requirement regardless of how many component tests pass. The three implemented
untrusted transport views leave Bellman schema definition, native bridges and
semantic owner admission outstanding; `canonicalWireAdaptersImplemented`
therefore remains false.

## 16. V8.2 pre-coding implementation-readiness overlay

`learning.operator` belongs to `LANE-E-LEARNING` under
[PARALLEL_DEVELOPMENT.md](../../readiness/PARALLEL_DEVELOPMENT.md), with
`offline_worker`, immutable candidate state, `FP-LEARNING-OFFLINE` and
`PERF-OFFLINE` execution profiles. Its integration checkpoints use the
[learning evaluation specification](../../readiness/LEARNING_EVALUATION_EXECUTION.md)
and the [source/branch policy](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md).
Record the actual Git candidate, owned paths, registry versions, input digests,
deadline and rollback predecessor before qualifying a runtime composition.

The contracts crate's `learning_operator_protocol` module implements untrusted
canonical transport views for the registered sensor, regularity and
applicability V1 schemas. Its tests read the actual contract/protocol registries,
check field order and byte bounds, and reject unknown/duplicate fields,
noncanonical bytes, protocol relabeling and unsupported versions. The artifact
identity is registered without a field schema; dispatch returns
`MissingCanonicalSchema` instead of treating `HEPTTB01` as canonical JSON.
Enum values and bounded-object members are not defined by these registries;
transport preserves them without issuing native or scientific admission.

Run `just test -p codex-hepta-contracts --locked --lib -E
'test(learning_operator_protocol::tests)'` for this transport checkpoint and the
focused Bellman/operator, coordinator and real owner tests in
[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) for their separate behavior. Run
`python3 scripts/hepta-implementation-dossiers.py verify` from the repository
root after changing this overlay. Compilation and fixture success establish
the tested engineering behavior; a source harness does not establish a named
Agentd runtime, durable crash/reopen behavior or independent future-window
acceptance. The ledger, artifact owner, evaluator and selector retain their
existing writer and decision boundaries. Unknown persistence or rollback
identity stops the operation and preserves recovery facts; activation, promotion
and release still require the applicable independent owner decisions.

## 17. Source implementation receipt

The source root, mapped symbols and historical navigation observation are in
`IMPLEMENTATION_MAP.json`. Exact executed source/tree, command, test filters,
exit status and raw-log hashes belong to the generated qualification receipts.
The retained adversarial audit in
[qualification/lane-e](../../../qualification/lane-e/learning-operator-adversarial-audit-20261001.md)
records local observations and their limits. Historical observations do not
qualify later edits. Whole Agentd, Bazel, PR-head, deterministic merge and actual
post-merge builds each require their own successful evidence; a small source
harness is evidence only for the code it compiles and exercises.
