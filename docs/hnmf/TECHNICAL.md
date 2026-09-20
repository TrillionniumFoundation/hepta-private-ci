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
entity/relation/action/outcome projections
causal parents and temporal neighbors
objective and NDU snapshot digests
optional legal-candidate-set and propensity witnesses
verification, provenance, privacy and retention
supersession and forget state
```

Events are immutable. Corrections append a successor event or correction record. Forgetting appends a tombstone/revocation record and triggers projection rebuild or artifact revocation. No update-in-place is permitted.

### 4.3 `CrossModalBindingV1`

A cross-modal binding records that two or more spans are co-referential, temporally aligned, causally related, procedurally paired, or supplied as alternative observations. The record contains an alignment kind, confidence, producer manifest, and support event. Alignment output is provisional until its sources and producer are qualified.

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

A recall packet contains only bounded identifiers, digests, selected event revisions, active node summaries, activation paths, contradiction groups, coverage, confidence, OOD, abstention reason, and resource receipt. Raw source data is attached later only by `context.compiler` after exact revalidation.

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

The deterministic reference uses signed parts-per-million fixed point. Production implementations may use another registered numeric representation only if parity, bounds, and platform determinism are qualified.

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
