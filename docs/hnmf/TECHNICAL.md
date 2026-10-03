# Hepta-Neuron Multimodal Memory Fabric technical specification

**Specification ID:** `HEPTA-HNMF-QUALIFICATION-V1`

**Parent plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Baseline:** `70ef65a90a031ce0cc08b77b5596eb0d99edaa11`

**Status:** qualification blocker-closure candidate

This specification defines a bounded multimodal event-memory and associative-engram system that preserves the current Hepta authority, durability, causal-learning, next-snapshot, and no-self-promotion invariants. It is an executable engineering specification, not a claim that production learning, biological fidelity, or autonomous production evolution already exists.

## 1. Authority, scope and non-goals

HNMF does not create a second model, tool, session, or effect-execution spine. Codex App Server remains the only model-call and tool-execution spine. HNMF may read snapshot-bound cognitive evidence, emit recall and learning candidates, and append governed learning observations through owning modules. It may not mint the authority it consumes, mutate another module's authoritative store, call providers directly, attach unverified evidence as trusted instruction, or promote its own artifacts.

The reference runtime is qualification-only. The following values are invariant and machine-checked:

```text
runtimeAuthority = false
productionCaller = false
productionWriter = false
modelInvocation = false
providerDispatch = false
toolExecution = false
networkConnect = false
externalFilesystemMutation = false
secretOperation = false
matrixSend = false
externalEffect = false
fleetMutation = false
canonicalSelection = false
merge = false
operatorAcceptance = false
promotion = false
release = false
```

Non-goals include replacing the immutable source ledger with embeddings, representing permissions as learnable weights, treating model output as a source fact, mutating the current run's memory or neural snapshot, claiming universal biological equivalence, or using online topology mutation as a shortcut around evaluation.

## 2. Closed blocker model

The V8 audit identified eighteen implementation-design blockers: first-class multimodal events, content-addressed spans, seven bounded functional populations, recurrent associative recall, sparse competition, lateral inhibition, adaptive thresholds, eligibility traces, low-dimensional modulation, replay scheduling, prediction-error input, candidate-only plasticity, bounded structural proposals, deletion non-resurrection, explicit thresholds, module ownership, machine validation, deterministic order independence, and contradiction-aware abstention.

`GAPS.json` binds each blocker to exact evidence in this specification, the machine registry, validator, workflow, or executable reference. `allReferenceGapsClosed=true` means the contract and deterministic-reference blocker set is closed. It deliberately does not mean that production activation, future-time efficacy, functional biomimicry, or release evidence exists.

## 3. Source-of-truth and projection hierarchy

The authoritative layer contains only immutable or append-only facts:

```text
source ledger
multimodal memory-event ledger
correction/supersession ledger
forget/revocation ledger
action/outcome/credit evidence ledger
```

Every event binds exact source digests, observed time, scope, verification state, retention policy, objective digest, NDU-state digest, and modality asset ranges. Original image, audio, video, and large binary payloads reside in a content-addressed asset store owned by the appropriate durable module. Event rows hold only exact digest, media identity, byte/time/region range, redaction manifest, and preprocessor identity.

The following are rebuildable projections and can never become truth authorities:

```text
FTS/lexical index
vector index
entity and knowledge graph
temporal adjacency
causal adjacency
procedure index
predictive-transition index
engram nodes and synapses
recall caches
```

A vector database is one bounded candidate channel. Nearest-neighbor distance neither proves truth nor permits retrieval attachment. A projection generation is valid only while its source range, tombstone cutoff, encoder/preprocessor manifest, and snapshot digest remain current.

### Long-term memory is both evidence and a learning substrate

The target HNMF composition uses the existing Nervous System to admit experience,
recall task-relevant evidence, select replay and form future skills/parameters.
It is not a vector database renamed as a brain and not a claim that experience
replay, neural memory or multi-actor learning is unprecedented. Existing reference
closure does not certify shared-experience product execution. The four V2 wire
contracts and the local owner bridge are source-implemented, while cross-host
transport, measured transfer benefit and governed activation remain unproved.

| Logical form | Contents and interpretation | Existing owner and default sharing |
| --- | --- | --- |
| Working | current objective/context, transient hypotheses, active Circuit and Cell state | Agentd/Neuron/session owners; private per run/workspace |
| Episodic/evidence | observed source, time, environment and revision-bound Memory; references to actual actions/results | cognitive.store for Memory/source; learning.ledger for learning facts; policy-scoped publication |
| Associative/concept | semantic/temporal/contradiction and engram projections supported by exact revisions | existing KG/retrieval/projection owners; authorized rebuildable views |
| Procedural | candidate or qualified skills/subcircuits with preconditions, effects, stop and recovery | existing TaskFlow/organ and learning artifact owners; independent current execution admission |
| Parametric | immutable common/domain/Agent model, adapter and policy bundles | learning.artifacts; source- and consumer-scoped future adoption |

These are five logical forms, not five new stores. A fact-like source is evidence
that particular content was observed; it is not proof every proposition in it is
true. Retain SourceKind and verification/support state. Generated reflection and
synthetic trajectories remain hypotheses/training material with declared purpose,
never independent real-world observations. Distinguish current validity from
historical explanatory/training use. A code observation binds project/base commit,
environment/tool versions and applicability; it cannot become another workspace's
current file truth without revalidation. Volatile facts remain external to weights.

A shared experience view references source/Memory revisions, actually delivered
context, complete decision/route candidates and behavior, operation outcomes and
corrections, environment/applicability, publication policy and retention lineage.
Learning facts stay with learning.ledger and effect facts with their executor.
Do not add these fields to MemoryEventV1 by convention or reconstruct unobserved
reasoning after the fact. Missing/late/indeterminate results have explicit states;
success is not self-labelled by the contributing Agent.

## 4. Canonical multimodal data model

### 4.1 `ModalitySpanRefV1`

A modality span binds:

- one of `text`, `image`, `audio`, `video`, `code_ast`, `gui_state`, `tool_trajectory`, `structured_data`, or `sensor`;
- content-addressed asset SHA-256;
- a modality-specific bounded range, such as UTF-8 byte range, image region, sample interval, frame interval, AST node path, GUI element path, event interval, row/field selector, or sensor sample range;
- exact preprocessor/encoder manifest SHA-256;
- optional feature-blob and symbolic-projection SHA-256 values;
- uncertainty, privacy class, and optional redaction-mask digest.

A feature vector alone is not a modality span. The original source binding must remain resolvable or explicitly revoked.

### 4.2 `MemoryEventV1`

A memory event is the minimum durable cognitive unit. It contains:

```text
event identity and episode identity
scope and observed interval
one or more modality spans
normalized semantic keys
causal parents and temporal neighbors
objective and NDU snapshot digests
optional behavior propensity
verification, provenance, privacy and retention
supersession and forget state
```

Events are immutable. Corrections append a successor event or correction record. Forgetting appends a tombstone/revocation record and triggers projection rebuild or artifact revocation. No update-in-place is permitted.

Entity/relation/action/outcome projections are **derived owner projections**, not fields of canonical `MemoryEventV1`; their source event identities and digests are carried by the responsible projection owner. Likewise, the legal candidate-set/decision witness is owned by the learning ledger. `MemoryEventV1` carries only the optional bounded `behaviorPropensityPpm` observation and must not embed or reinterpret another owner's decision receipt. This separation is normative for V1.

### 4.3 `CrossModalBindingV1`

A cross-modal binding records that two or more spans are co-referential, temporally aligned, causally related, procedurally paired, or supplied as alternative observations. The record contains an alignment kind, confidence, producer manifest, and support event. Alignment output is provisional until its sources and producer are qualified. Structural `CrossModalBindingV1::validate` does not authenticate referenced span membership; separately transported bindings must additionally pass `validate_cross_modal_binding_against_event_v1` against the exact canonical event.

### 4.4 `EngramNodeV1`

An engram node contains a functional population, modality mask, semantic cue keys, immutable support manifest, adaptive threshold, target activity, confidence, validity interval, and snapshot generation. It does not contain raw source payload, credentials, authority tokens, or unrestricted model hidden states.

### 4.5 `SynapseV1`

A synapse connects two engram nodes with one registered relation:

```text
associative
temporal
causal
procedural
predictive
supports
inhibitory
contradicts
```

Each synapse carries fixed-point weight, bounded delay, plasticity class, eligibility state, support manifest, and snapshot generation. Inhibitory and contradictory edges reduce activation. A synapse with no remaining non-revoked support is retired in the next projection generation.

### 4.6 `RecallPacketV1`

A recall packet contains only bounded identifiers, digests, selected event revisions, active node summaries, activation paths, contradiction groups, coverage, confidence, OOD, abstention reason, and resource receipt. Selected event revisions are non-zero. V1 enforces an exclusive terminal shape: `abstain == None` requires one or more selected events, while `abstain != None` requires zero selected events. Raw source data is attached later only by `context.compiler` after exact revalidation.

## 5. Seven functional engram populations

HNMF uses seven engineering populations. These are functional boundaries, not claims of anatomical equivalence.

| Population | Durable support | Runtime role | Learning role |
|---|---|---|---|
| Sensory Trace | exact modality spans | detect cue-local evidence | preserve modality-specific discriminators |
| Episodic Binding | event/episode/action/outcome | bind what, when, where, who and result | one-shot episode capture and replay entry |
| Semantic Concept | multiple supported episodes/facts | concept and hypothesis completion | consolidation under retention and contradiction constraints |
| Procedural Skill | preconditions/actions/effects/recovery | retrieve bounded procedures | abstract successful sequences without granting execution |
| Predictive World | transition/outcome observations | anticipate next state, risk and outcome | produce prediction error for slow learning |
| Utility/Salience | frozen NDU and observed outcome | admission, attention and replay priority | low-dimensional modulation only |
| Meta-Memory | provenance/privacy/validity/forget | gate recall and force abstention | prevent stale, revoked or unsupported resurrection |

Competition occurs primarily within a population. Excitatory association may cross populations. Meta-memory gates can suppress any population but cannot fabricate evidence.

## 6. Fixed-point neuron dynamics

The deterministic reference uses signed parts-per-million fixed point. Canonical node thresholds and synapse weights use signed unit-range Q16 with `Q16_ONE = 65_536`, so the admitted raw interval is `[-65_536, 65_536]`. Conversion to ppm is `trunc_toward_zero(q16 * 1_000_000 / 65_536)`. Plasticity proposal `deltaPpm` is not caller commentary: it must equal the deterministic conversion of `newQ16 - oldQ16` exactly. Production implementations may use another registered numeric representation only if parity, bounds, and platform determinism are qualified.

For node `i` at settling step `t`:

```text
v_i(t+1) = cue_i
         + leak_i * a_i(t)
         + sum_j positive_relation(j,i) * w_ji * a_j(t)
         - sum_j negative_relation(j,i) * |w_ji| * a_j(t)
         - theta_i
```

All products use checked wide intermediates, deterministic rounding toward zero, and clipping to the declared activation range. Unknown relations or overflow fail closed.

Sparse competition is applied after raw activation calculation:

1. partition candidates by functional population;
2. order by raw activation descending, then stable node identity ascending;
3. retain at most `maximumActivePerPopulation` positive nodes;
4. apply rank-sensitive lateral inhibition to retained peers;
5. apply the global `maximumActiveNodes` bound using the same stable ordering;
6. set all other activations to zero.

The system settles for at most four steps. It never iterates until an unbounded convergence condition. The receipt records the exact step count and bounds used.

## 7. Admission and write path

The write path is:

```text
authority/privacy/redaction gate
temporal segmentation
exact modality receipt validation
cross-modal alignment
entity/action/outcome projection
novelty/salience/evidence admission
immutable event append
outbox publication
rebuildable projection update
```

Admission uses a hard-gate plus bounded utility score. Hard rejection occurs for missing provenance, invalid scope, unknown critical fields, unresolved asset digest, stale preprocessor identity, secret leakage, invalid time range, unbounded payload, or a forbidden source class.

A candidate that passes hard gates can still be dropped as redundant. Redundancy is not decided by vector proximity alone. The admission evaluator considers exact source novelty, temporal novelty, causal information, correction value, procedural value, prediction error, expected future utility, privacy cost, and interference cost. The admission decision and propensity are recorded for later causal evaluation.

`cognitive.store` remains the only authoritative writer for memory and knowledge facts. Neuron, retrieval, compaction, and learning components emit intents or candidates; they never write that store directly.

### Authorized contribution and shared-view publication

A sharing scope is a configured audience and purpose beneath an existing principal
and data-owner policy. It is not a new authority issuer, a fifth NDU subject or an
implicit widening of AgentPrivate/WorkspacePrivate. There is no sharing default
without an admitted policy. A standing policy may automatically admit bounded,
low-risk contributions within its exact audience/use limits; routine experience
must not require a new human approval per event when already authorized.

Keep three permissions distinct: raw evidence read, training use for a named
purpose/parameter scope, and use/distribution of the derived artifact. A read grant
never implies a train grant; training access need not expose raw data to every
artifact consumer. Retention, source license/consent, redaction, credentials,
evaluation isolation and revocation remain noncompensable. Transforming data into
a summary, gradient or adapter does not remove its lineage or authorize wider use.

The intended owner path is local admitted append -> durable contribution intent
-> destination scope/purpose/currentness checks -> idempotent admitted reference
or immutable permitted copy -> acknowledgement -> bounded shared projection update.
Use existing owner operations; no Agent opens another owner's writable SQLite file,
no database files are merged, and federation gains no mutation authority. A copy
is a derived record linked to the original revision, not a new independent fact.
A publication is selectable for its declared use only after durable admission.
The canonical source contracts are `SharedExperiencePublicationV2`,
`SharedExperienceSnapshotV2`, `SharedExperienceUseReceiptV2` and
`SharedExperienceRevocationReceiptV2`. The existing `hepta-memory` SQLite owner
binds them to its exact-revision policy rows; the contracts do not create a new
store or mutate the source `MemoryEventV1`.

A contribution binds producer, durable shard/owner epoch, original event/revision,
semantic content digest, policy generation, destinations and idempotent operation
identity. An exact duplicate returns the same result; a reused ID with changed
semantics conflicts. Lost acknowledgement resumes/reconciles the same operation.
Keep source revision identity distinct from transport attempts and Agent process
identity. Producer signatures/digests authenticate origin/integrity, not truth.

Index exact source lineage before semantic similarity. Keep different observations
with identical wording when their provenance differs; repeated copies of one root
source remain one support root. Preserve contradictory claims with their conditions,
time and provenance rather than vote-counting Agent restatements or averaging them
into an authoritative centroid. Sharing an experience does not create a new outcome.
Sensitive metadata and existence/counts of denied records are not disclosed through
indexes, batch statistics or content-addressed cross-scope deduplication oracles.

## 8. Recall and contradiction path

The recall path is:

```text
objective + NDU + request + current context
MemoryCueV1
parallel bounded candidate channels
stable union and deduplication
local candidate engram subgraph
bounded recurrent settling
per-population sparse competition
pattern completion
contradiction detection
calibrated readout
source/snapshot/generation revalidation
RecallPacketV1 or abstain
```

Candidate channels may include lexical, vector, entity, temporal, causal, episodic-context, procedural, predictive, recency, explicit-memory, and contradiction-support evidence. Every channel has an independent bound and emits identifiers plus a score receipt. The union is deterministic and bounded before graph expansion.

Contradiction is first class. Active nodes connected by `contradicts` are emitted as contradiction pairs. An unresolved high-risk contradiction forces abstention or slow-path review. It is invalid to average incompatible facts into a high-confidence embedding centroid.

A recall packet is stale when any selected event head, source digest, scope, verification, lifecycle, validity interval, asset digest, tombstone cutoff, KG generation, engram generation, or encoder manifest changes. Physical model-request construction must revalidate the entire packet in one coherent read snapshot.

### Recall and Replay are different consumers

Recall is an evidence-selection circuit: it consumes the current task, admitted
read scope and coherent source cut, then returns bounded source-bound information
for the local context compiler. Cell decisions can choose channels, compare
relevance, detect insufficiency and stop. Deterministic source/permission checks
remain authoritative. A learned relevance score cannot widen the read scope.

Replay is a training-selection path: it freezes eligible episodes and targets
under training permission, estimator support, task split and resource limits.
An item useful to Recall is not automatically a valid RL sample. Conversely a
historical failed/obsolete observation may teach a general checking strategy while
being explicitly invalid as a current fact. Procedure recall returns a candidate
skill with preconditions; it never grants execution. Replay consumes records or
admitted simulations, not live historical tool effects.

Both paths reference the same provenance but use independent selection policies,
budgets and permission checks. Recall records actual delivered evidence; Replay
records inclusion/sampling decisions and lineage. The retrieval engine remains
read-only and does not become a trainer or Memory writer. Current model input is
compiled independently per Agent; shared publication is not a broadcast instruction.

## 9. Replay and consolidation

Replay candidates are scored from bounded, independently recorded components:

```text
expected utility gain
prediction error
novelty
rarity
forgetting risk
coverage need
```

The reference uses a deterministic weighted sum and stable tie-breaking. Production may use a learned policy only after logging complete candidate sets and propensities. Source-bucket quotas prevent one user, modality, task, or high-salience source from monopolizing replay.

Consolidation may propose:

- a semantic prototype supported by multiple episodes;
- a procedural abstraction with explicit preconditions, actions, effects, and recovery;
- a predictive transition with uncertainty;
- a new association or changed association weight;
- a threshold adjustment;
- a structural topology candidate.

Consolidation never rewrites source events. Dreamed or model-generated trajectories are tagged separately from real observations and cannot silently become factual support.

### Multi-Agent replay snapshots and slow consolidation

A shared dataset is a versioned view, not a live concatenation of every Agent log.
Bind each included shard's source/learning cuts, owner epoch, schema, admitted
training policy, snapshot manifest and current deletion/revocation frontier. Respect
cross-shard causal parents: a decision/outcome/credit sample cannot silently omit
required delivered inputs or predecessor evidence. A vector of valid local cuts
is not automatically a globally simultaneous snapshot. Close declared dependencies
by exact references or report incomplete/unavailable; unrelated shards need no
whole-system stop barrier. Source unavailability never fabricates a successful
empty shard. Caches/materialized batches stay derivative and scope-bound.

Actor policy/model/Circuit and behavior versions may differ. Record actual routing
and candidate support, environment, delays and collection assignment. An unavailable
propensity may permit declared supervised/predictive use but not unsupported
importance-weighted policy claims. Independent data is counted by episode/task
and root source, not number of imports, replay epochs or Agents quoting it.
Use coverage and source/domain quotas; include supported failures, rare conditions
and retention samples, not success-only or salience-only replay. Retain synthetic
and observed populations separately and disclose their mixing policy.

Run bounded training under existing learning.operator/eval/artifact owners. Freeze
common/domain/Agent targets and evaluator before training; preserve data-use scope
and outcome support. A local update can remain local. Promotion to a domain/common
bundle requires its own permitted-source and downstream-consumer set plus independent
retention/negative-transfer tests. Weight averaging, distillation and local gradient
aggregation are candidate training methods, not automatic safe knowledge merging.
No immediate mutation of a shared selected model; only admitted compatible future
bundles are loaded, with dependent state/calibration/cache invalidation or migration.

Facts, concepts, procedures and parameter candidates have separate readiness states.
Novelty or internal utility cannot certify a true fact or a qualified procedure.
NDU may prioritize useful memory work and data coverage after privacy/safety floors,
but may not reward raw upload volume, increase authority or redefine task success.

## 10. Eligibility, modulation and candidate plasticity

Eligibility for synapse `j -> i` is updated as:

```text
e_ji(next) = trace_decay * e_ji(previous)
           + a_j * a_i
```

The low-dimensional outcome signal is:

```text
M = clip(
      w_utility * utility_delta
    + w_prediction * prediction_error
    + w_novelty * novelty
    - w_risk * risk
    - w_ood * OOD
)
```

Authority, truth, privacy, deletion, and writer ownership never enter `M` as tradable dimensions. They remain hard gates.

A weight proposal is:

```text
delta_w_candidate = clip(learning_rate * M * eligibility,
                         -maximumWeightDelta,
                         +maximumWeightDelta)
```

A homeostatic threshold proposal is:

```text
delta_theta_candidate = homeostasis_rate * (observed_activity - target_activity)
```

Both are written to `PlasticityBatchV1` with exact predecessor and next generation. The current snapshot is immutable. Application creates a new snapshot and validates every old value before changing it. A stale batch conflicts rather than applying partially.

## 11. Forgetting and non-resurrection

A forget request is source-driven. It identifies the authoritative event or source revision, not an approximate vector neighborhood. The propagation candidate contains:

```text
event tombstone
all directly supported engram nodes
all directly supported synapses
all affected projection generations
all training datasets and replay caches
all derived artifacts requiring revocation or retraining
```

Applying a forget batch creates a new generation, removes the event from support manifests, retires nodes or synapses with no remaining support, and invalidates caches. Historical source bytes are handled by their owning retention system; HNMF records the tombstone and never reintroduces them through projection rebuild, replay, model artifact reload, or backup restoration.

Qualification requires `maximumDeletionResurrectionCount = 0` across recall, KG, vector/FTS indexes, engrams, synapses, replay datasets, artifacts, caches, and restore rehearsals.

### Correction, revocation and training-impact propagation

Distinguish correction, access revocation, payload deletion and removal of training
influence. Correction appends a new valid revision without rewriting what was
observed historically; whether historical training remains permitted is an explicit
policy. A shared pointer or copy retains original authority and deletion lineage.
No overwrite, export, summarization or distillation severs that dependency.

Revocation blocks new Recall, batch access and artifact adoption before queued work
can cross their respective final-use boundary. Cancellation of in-flight training
and quarantine of its candidate are tracked; stop acknowledgement is not deletion
proof. A source-trained bundle may require withdrawal, supported unlearning or
retraining from an admitted clean predecessor. Dropping an embedding/tombstone is
not proof its influence disappeared from weights or optimizer state. If no suitable
selective method exists, revoke and retrain; retain truthful incomplete status.

Propagate lineage through projections, shared copies, training/materialization,
normalizers, optimizers, adapters, distilled descendants, caches and backups.
Owner-reference GC does not delete a shared base still used by unaffected artifacts,
but a tainted shared base affects all its derived bundles until cleared/replaced.
Offline owners cannot certify erasure while disconnected; reconnect/restore first
replays current revocation/frontiers and suppresses stale exports or model loads.
Do not restore private payload merely to preserve an audit: retain only authorized
non-sensitive linkage and disposition. Historical recipient disclosures cannot be
retroactively undone; prevent future use and report the actual propagation status.

## 12. Existing-module ownership map

HNMF is decomposed across existing V8 modules:

- `cognitive.types`: canonical event, span, engram, synapse, cue, recall, replay, plasticity, topology, and forget types;
- `cognitive.store`: authoritative event/source/fact/tombstone ledgers and asset metadata;
- `cognitive.read`: coherent snapshot reads and redaction;
- `memory.retrieval`: cue compilation, bounded candidates, associative recall, and packet revalidation;
- `knowledge.graph`: temporal, causal, contradiction, procedure, and prompt-factor projections;
- `compact.engine`: replay and consolidation orchestration without source rewrite;
- `memory.federation`: grant-scoped remote evidence reads only;
- `neuron.runtime`: recurrent state, sparse competition, inhibition, threshold, and eligibility;
- `utility.ndu`: frozen preference/utility snapshot and modulator bounds;
- `intuition.policy`: recall/abstain/slow-path selection over complete legal candidates;
- `learning.ledger`: activation, candidate, propensity, outcome, credit, replay, and unlearning evidence;
- `learning.operator`: bounded predictive-world and continuation-value candidates;
- `learning.eval`: causal, future-time, retention, OOD, subgroup, and lesion/ablation evaluation;
- `learning.artifacts`: immutable event/engram/synapse/model manifests and predecessors;
- `learning.plasticity`: parameter and topology proposals only;
- `context.compiler`: source-aware multimodal packet compilation;
- `intelligence.control`: composition façade only.

No new central owner is introduced. Cross-owner mutation retains local transaction, durable intent, outbox, destination deduplication/apply, acknowledgement, and fenced reconciliation.

## 13. Resource, performance and concurrency bounds

Reference hard bounds are:

| Resource | Bound |
|---|---:|
| candidate events | 512 |
| engram nodes | 4096 |
| synapses | 32768 |
| active nodes | 4096 |
| active nodes per population | 64 |
| recurrent settling steps | 4 |
| final recalled events | 16 |
| activation paths | 32 |
| replay candidates | 4096 |
| replay selection | 256 |
| absolute weight delta | 50,000 ppm |

Production packages must publish p50, p95, p99 latency, throughput, CPU, resident memory, allocation, queue, storage growth, WAL/busy, and recovery budgets. Hot paths cannot require a synchronous central control-plane RPC or full-store scan. Backpressure rejects explicitly; it cannot spawn unbounded tasks or retries.

Snapshot reads use one coherent generation. Concurrent writers use transactions or compare-and-swap. A generation mismatch is a conflict. Last-write-wins is forbidden for source facts, support manifests, and artifact selection.

## 14. Security and privacy controls

Threats include embedding poisoning, cross-modal adversarial alignment, untrusted instruction escalation, secret-bearing media, stale preprocessor identity, source-support forgery, contradiction suppression, activation flooding, replay monopolization, eligibility explosion, topology churn, deleted-data resurrection, scope escape, and self-promotion.

Controls include exact source and asset digests, bounded inputs, canonical schemas, deny-unknown-critical-fields, privacy scope checks before candidate generation, redaction manifests, per-channel and per-population bounds, stable deterministic ordering, clipped fixed-point arithmetic, source quotas, negative authority fields in proposal objects, exact predecessor generations, and independent acceptance.

Raw prompts, credentials, private keys, unrestricted source payloads, and model hidden states never enter general HNMF receipts. External content remains evidence and cannot become a trusted instruction factor without separate governed transformation.

### Isolation extends beyond the context window

Protect five boundaries independently: workspace/effect access; session/Cell/KV and
context state; fact applicability/provenance; training and parameter distribution;
and evaluation/task-split leakage. A private prompt is not a guarantee that a
common trained model cannot reveal or apply private information. Source permissions
propagate into candidate and derived-bundle use. Do not promise zero leakage from
redaction, aggregation, gradients or distillation without a justified method and
measurement for that claim. Initially prefer isolated scoped deltas and raw-data
access through existing owner controls; centralized, federated-gradient and secure
aggregation training are distinct future choices, not implicit federation behavior.

Publication ingestion treats content as evidence, including externally supplied
text embedded in internal Memory. Authenticate source and binding, quarantine
unsupported/malicious instructions, retain contradiction and root-source lineage,
and exercise poisoning/deceptive-summary tests. Neither a signed contribution nor
many sibling Agents repeating it may convert text into instruction or privileged
action. Standing policies reduce approval overhead but preserve deterministic
scope, credential, retention and final-use boundaries.

Cache and batching namespaces include consumer/workspace/purpose/source frontier,
model/adapter/normalizer generation and trust class. Denied/expired/revoked inputs
must not leak through stale context, scores, shared mutable state or model reload.
A new context begins from explicit task inputs, not another Agent's resident state.
Optional shared evidence may degrade to a declared local-only read with disclosed
coverage; mandatory evidence/permission failures must defer or reject, never silently
lower training, privacy or result-completeness requirements.

## 15. Verification and acceptance

The reference package must pass:

```text
JSON duplicate-key and closed-world registry validation
required modality/population/protocol/work-package coverage
negative authority closure
no unresolved placeholder markers
Rust formatting and all-target compilation
deterministic unit tests
bounds and overflow failure tests
cross-modal pattern completion
per-population sparse competition
contradiction-aware abstention
homeostatic threshold movement
eligibility decay and clipped plasticity
no current-snapshot mutation
exact next-generation application
source-quota replay selection
forget non-resurrection
insertion-order independence
topology no-self-activation
```

Future production qualification additionally requires at least three independently identified snapshots over two future calendar windows, minimum effective sample size 200, 95% confidence, candidate LCB greater than baseline UCB, maximum relative old-task regression 2%, citation precision at least 99%, zero unresolved high-risk contradictions, zero deletion resurrection, and independently governed rollback acceptance. These are default floors; task-specific policy may be stricter.

## 16. Bounded migration

Migration is projection-first and reversible:

1. freeze exact existing source, memory, KG, retrieval, and deletion fixtures;
2. wrap existing text memories as text-only `MemoryEventV1` records without rewriting them;
3. add content-addressed modality spans for new observations;
4. build HNMF projections from immutable ledgers;
5. run existing retrieval and HNMF recall in shadow parity;
6. qualify replay and candidate plasticity without current-run mutation;
7. perform future-time, retention, privacy, deletion, crash/reopen, restore, and rollback tests;
8. request a separately governed canary.

At every phase, the predecessor remains selectable. See `MIGRATION.md` for operational details.

## 17. Claim ladder

The reference candidate may claim only:

```text
multimodal contracts specified = true
resource bounds specified = true
deterministic reference recall = true
reference sparse competition = true
reference eligibility/homeostasis = true
candidate-only plasticity = true
reference forget propagation = true
structural proposal types = true
production activation = false
closed-loop longitudinal efficacy = false
functional biomimicry = false
neuromorphic mechanism = false
self-authorized evolution = false
```

Invalid substitutions remain prohibited:

```text
memory persisted != long-term learning
embedding close != factual support
model invoked != neuron efficacy
sparse activation != functional biomimicry
replay test passed != future-time efficacy
proposal generated != topology activated
artifact generated != artifact selected
operator acceptance != promotion
promotion != release
```

### Shared-experience completion is separate from reference closure

The original HNMF V1 protocol count and reference gaps remain unchanged. The
shared-experience V2 type/wire source and local owner adapters are implemented as
versioned extensions of existing packages in `../delivery/WORK_PACKAGES.json`,
ordered in `MIGRATION.md`; source implementation does not certify product execution,
transport, efficacy or activation. SM-01..SM-10 and the clean-Agent four-arm pilot
are future acceptance criteria. A scoped policy/dedup/lineage example is not a
product caller, operating-system isolation test, full unlearning proof or shared
learning benefit. Keep local multi-owner execution, authenticated cross-host
transport and measured longitudinal transfer as distinct milestones.

## 18. Work-package closure

The HNMF blocker set is divided into seven reference work packages:

- `HNM-0-MULTIMODAL-CONTRACTS`: machine protocols, bounds, fields, fixtures, and authority posture;
- `HNM-1-IMMUTABLE-EVENT-LEDGER`: event, provenance, validity, privacy, supersession, and tombstone semantics;
- `HNM-2-HYBRID-PROJECTIONS`: bounded semantic/modality/associative candidates and projection status;
- `HNM-3-SPARSE-ENGRAM-RECALL`: recurrent settling, inhibition, competition, contradiction, OOD, and abstention;
- `HNM-4-REPLAY-WORLD-PLASTICITY`: replay quotas, prediction error, eligibility, modulation, and candidate updates;
- `HNM-5-LONGITUDINAL-UNLEARNING`: next-snapshot application, future evidence gates, and non-resurrection;
- `HNM-6-STRUCTURAL-EVOLUTION`: add, split, merge, retire, and rewire proposal envelopes with no self-activation.

All seven are `closed_reference` only when the validator and executable tests pass at the exact candidate. Activation, acceptance, selection, promotion, and release remain separate external states.
