# Functional neural biomimicry implementation specification

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Specification:** `ALG-NEURAL-BIOMIMICRY`  
**Bound modules:** `neuron.runtime`, `intuition.policy`, `learning.operator`, `learning.plasticity`  
**Documentation state:** `closed`  
**Implementation state:** not implied

## 1. Scope, ownership and non-claims

This specification defines a testable functional-biomimicry level for Hepta. `neuron.runtime` produces bounded temporal signals and checkpoints. `intuition.policy` consumes those signals for calibrated fast decisions. `learning.operator` supports replay and prediction-error candidates. `learning.plasticity` proposes next-snapshot parameter or topology changes.

The term “neuron” does not claim biological equivalence. NDU supplies preference and utility semantics, not cellular plasticity. A local language model, recurrent state or sparse activation alone is insufficient. Neuromorphic hardware, spiking dynamics, timing-dependent plasticity and energy claims remain a separate research level.

### DecisionCell is the common trainable unit

A Hepta DecisionCell is a logical, stateful decision unit within the existing
Neuron/Intuition substrate. Laya is its initial trainable backend candidate;
backend-neutral ports also admit qualified compact/distilled or numerical models.
The stable unit is the decision contract, not the vendor model or Python API.
A cell is not a biological neuron, top-level module, process, database or complete
NDU subject. Its purpose is an uncertain semantic decision that can improve from
experience. Exact arithmetic, schema checks, signature verification, truth
ownership, transaction commit and reflex vetoes remain deterministic.

System 1 comprises cells, temporal state, approved memory features and action
policies. NDU-guided System 2 provides recursive valuation and learning/credit
signals for admissible actions and next-snapshot parameter updates. Cells need
not each instantiate a heavy solver or an independently running trainer.
`NDU_FBSDE_SPEC.md` owns that optimization semantics; `../cns/TECHNICAL.md` owns
organ composition. This extension specifies a target and does not relabel native
sparse kernels, model receipts or fixture tests as a trained cell implementation.

## 2. Symbols, dimensions, units and normalization

| Symbol | Meaning | Pilot bound |
|---|---|---:|
| `x_t` | approved encoded input | `d_x <=256`, normalized |
| `h_t` | bounded temporal state | `d_h <=256`, Q24 in `[-8,8]` |
| `z_t` | pre-competition activation | `d_z <=512` |
| `a_t` | sparse post-competition activation | top-k, `k/d_z in [1%,20%]` |
| `theta_t` | adaptive threshold | one per unit or group |
| `e_t` | eligibility trace | same shape as trainable local weights |
| `m_t` | low-dimensional neuromodulator | `d_m <=8`, each in `[-1,1]` |
| `delta_t` | prediction error | bounded Q24 |
| `W` | selected local adapter/head weights | immutable current-snapshot artifact |
| `Delta W` | proposed update | trust-region bounded, next snapshot only |
| `tau_h,tau_e,tau_theta` | decay constants | positive versioned scalars |

All dimensions, normalization, top-k policy, inhibitory graph, thresholds, decay constants and fixed-point scales are artifact fields. Runtime state is generation-bound. A process may not combine a checkpoint from one encoder or tokenizer with another generation.

## 3. Formal model and invariants

A pilot temporal cell is

\[
\tilde h_{t+1}=\rho_h h_t+F_W(x_t,h_t),\qquad
z_{t+1}=G_W(\tilde h_{t+1})-\lambda_I L a_t-\theta_t,
\]

\[
a_{t+1}=\operatorname{TopKPositive}(z_{t+1},k),
\qquad
h_{t+1}=\operatorname{clip}(\tilde h_{t+1},-H_{max},H_{max}).
\]

`L` is a registered nonnegative lateral-inhibition matrix with zero diagonal. Competition is deterministic for equal activations through canonical unit ordering. Threshold homeostasis is

\[
\theta_{t+1}=\operatorname{clip}
(\theta_t+\eta_\theta(\bar a_t-a_{target}),\theta_{min},\theta_{max}).
\]

The bounded eligibility trace and three-factor candidate update are

\[
e_{t+1}=\lambda_e e_t+\psi(pre_t,post_t),
\]

\[
q_t=B_m m_t,\qquad
\Delta W_t^{(g)}=\Pi_{\mathcal T_g}[\eta_w\,q_{t,g}\,e_t^{(g)}],
\qquad
W_{candidate}=W_{selected}+\sum_t\Delta W_t.

`B_m` is a manifest-bound map from the `d_m<=8` modulator vector to registered parameter groups `g`; every row has `L1` norm at most one. This removes ambiguous broadcasting between a low-dimensional modulator and a weight-shaped eligibility trace.
\]

`m_t` is derived from independently observed prediction error, utility residual and safety/resource modulators. It cannot contain credentials or authority. `Pi_T` is a trust region: per-layer relative norm, global norm, sign/monotonicity constraints and quantization limits are all enforced.

Runtime never mutates selected `W`. It accumulates an immutable proposal or sufficient statistics for a future artifact. Homeostatic state may evolve inside the current temporal checkpoint only within declared bounds; it cannot change model topology or hard constraints.

Replay consolidation uses immutable episodes sampled by a preregistered mixture of recency, surprise, underrepresented objective class and old-task retention. Replay cannot turn deleted or revoked rows back into eligible data. Prediction error is measured against a frozen world-model revision and an independent outcome.

### Cell computation and parameter factorization

For cell i, (h_next, q_i, mu_i)=F_Theta_i(observation, h_i, messages, boundary).
q predicts outcomes or task labels; mu is the deployed policy after complete legal
set admission, masking and any declared exploration. They have separate output
semantics even when sharing features. Abstain, request-more-evidence and request
slow-path are explicit admissible outcomes, not manufactured confidence values.
A hidden embedding is not directly an identified NDU preference state; the
preference filter/head and its uncertainty are explicit.

The default effective model is Compose(base, organ_adapter, cell_adapter, heads).
For a compatible adapted linear layer, W_i=W_base+B_organ*A_organ+B_i*A_i.
Record layer names, shapes, ranks, scaling and composition order; this additive
example is not a valid merge rule for arbitrary adapter architectures. Zero deltas
must reproduce the base profile within its declared numeric tolerance. Different
base/tokenizer/normalizer revisions cannot share an old adapter or checkpoint
without explicit compatibility or a tested state transformation.

Each cell has independently addressable trainable parameters, but shared tensors
are immutable and physically deduplicated where scope and runtime permit. Shared
optimizer mutation during inference is forbidden. Full-model specialization is an
exception justified by task separation, data support and equal-budget benefit.
Data-poor cells may use a shared head plus isolated state indefinitely; no update
is a normal outcome. A default head is not assumed small: count actual trainable
tensors, optimizer memory and activations for the selected profile.

### Cells participate in circuits; not every control node is a cell

The [Neural Circuit contract](../modules/automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary)
connects cells to deterministic guards/transforms, waits, joins and organ calls.
A routing/termination decision may itself use a DecisionCell, but event eligibility,
deduplication, budgeting, checkpoint CAS and effect authorization remain deterministic.
Keep cell memory, circuit activation cursor and organ membership with their existing
owners. Multiple circuits can reuse a cell implementation while isolating scoped
state and run-specific activations; they cannot concurrently overwrite one shared
mutable checkpoint or trained tensor without the owner's admitted policy.

Record the actual effective model and policy for durable choices. Recovery consumes
committed results instead of recomputing historical decisions with new parameters.
Pure local rebuildable activations may use bounded checkpoints, but persistent
progress cannot depend on an output lost before an effect-relevant choice commits.
Future updates improve both the cell and the circuit policy against named versions;
a more accurate cell alone does not prove better routing or termination.

## 4. Deterministic reference algorithm

```text
validate exact encoder, head, threshold, inhibition and checkpoint generation
encode approved input with frozen local encoder
update bounded temporal state in fixed-point arithmetic
subtract lateral inhibition and adaptive threshold
select deterministic top-k positive activations
update activation-rate moving average and bounded threshold
update eligibility trace from registered local pre/post rule
compute OOD, confidence and abstention signals
append checkpoint and signal receipts atomically
if a low-dimensional independent modulator exists:
  accumulate trust-region-bounded next-snapshot update proposal
never replace current model or topology
```

Golden vector `BIO-GV-001` uses two units, `z=[0.8,0.6]`, `k=1`, inhibition `L=[[0,1],[1,0]]`, prior activation `[0,1]`, `lambda_I=0.2`, thresholds `[0.1,0.1]`. The adjusted values are `[0.5,0.5]`, or `[8388608,8388608]` in signed Q24; canonical ordering activates unit `0`. With `a_target=0.5`, `eta_theta=0.1`, and per-unit activity `[1,0]`, the next thresholds are `[0.15,0.05]`, or `[2516582,838861]` in Q24. With `lambda_e=0.5`, prior eligibility `[1,-1]`, and zero local increment, the next eligibility is `[0.5,-0.5]`. The selected weight digest must remain bit-identical.

## 5. Trainable or estimated algorithm

The encoder is frozen during a runtime generation. Pilot trainable candidates are small adapters or heads, not unrestricted full-model retraining. Training separates:

- representation reconstruction or contrastive objective for approved local features;
- prediction-error head for expected next observation/outcome;
- calibration/OOD head;
- sparse competition and activation-load regularizers;
- temporal stability and state-recovery loss;
- eligibility-alignment loss comparing local proposals with a bounded offline gradient oracle;
- old-task retention and subgroup safety losses.

The loss is

\[
L=L_{task}+\lambda_pL_{prediction}+\lambda_cL_{calibration}
+\lambda_sL_{sparsity}+\lambda_hL_{homeostasis}
+\lambda_eL_{eligibility}+\lambda_rL_{retention}.
\]

A local three-factor rule is not assumed equivalent to backpropagation. Its cosine agreement, utility effect, stability and retention are measured. Candidates with high agreement but poor causal utility fail. Hyperparameters and replay mixture are immutable manifests and evaluated on future windows.

### Local Laya adaptation and consolidation

The source-review candidate is NandhaKishorM/laya at
`c7527708f9f5220c669d8aa385077cd28d04708a`. Its `DecisionModel` exposes an encoder,
typed head, scorer and act head; `Agent.system_one` is a no-gradient inference
entry. Local training must use the underlying tensor model rather than returned
JSON. The input sequence jointly contains question, options and state, so a
state-only embedding cache cannot silently replace its question-conditioned
encoder. These observations identify an integration surface, not an installed
Hepta backend or a measured speed/calibration result.

Begin with a frozen base and registered trainable heads/adapters. A shared trainer
serves bounded jobs with per-cell/organ scope; do not create a trainer service per
cell. Bind fixed datasets, optimizer configuration, random streams, model code,
selected precision/device, normalization and parameter masks. An actor objective
uses NDU-consistent advantages or an explicit distilled policy target. Prediction,
calibration, retention and uncertainty losses retain their own semantics; an
internal utility increase cannot label a prediction correct. Critic targets are
frozen/cross-fitted. Training/calibration/evaluation/future data splits are disjoint
at the correlated episode and source-group level.

Three-factor eligibility updates remain a candidate mechanism for bounded local
heads. They are not the exact gradient of a full Transformer. Measure alignment
with a bounded gradient oracle, organ utility and retention before use. Larger
Laya updates use conventional local tensor training through learning.operator;
learning.plasticity bounds candidate parameter groups and structural proposals.
NDU's stochastic Z is not a weight gradient. Selection remains outside the trainer.

Specialization inherits a compatible base/organ bundle. Organ consolidation can
distill supported behavior from several cells, followed by local readaptation and
retention evaluation. Do not blindly average arbitrary fine-tuned weights or
interpret parameter averaging as knowledge transfer. Cell, organ and base update
cadences are independently scheduled against named compatible reference bundles.
Sharing updated parameters across principals requires explicit data-use policy;
shared infrastructure does not authorize pooling private replay or gradients.

## 6. Data, protocol and lineage schema

The following records are canonical cross-module protocols registered in `docs/contracts/CONTRACTS.json` and `docs/contracts/PROTOCOL_SCHEMAS.json`:

```text
NeuronCheckpointV1 {
  checkpoint_id, predecessor, generation, encoder_digest,
  head_digest, temporal_state_digest, threshold_digest,
  activation_summary, eligibility_digest, logical_sequence,
  normalization_digest, expiry
}

NeuronSignalReceiptV1 {
  signal_set_id, checkpoint_before, checkpoint_after,
  model_runtime_digest, input_feature_digest,
  signals, activation_sparsity_ppm, inhibition_residual,
  prediction_error, confidence_ppm, ood_ppm, abstain
}

PlasticityProposalV1 {
  proposal_id, selected_artifact, dataset_digest,
  update_rule_digest, modulator_digest, eligibility_digest,
  parameter_delta_digest, trust_region_metrics,
  retention_metrics, evaluator_receipts, rollback_predecessor
}

TopologyProposalV1 {
  proposal_id, predecessor_topology, operation,
  typed_nodes_edges, compatibility_plan, resource_delta,
  security_review, lesion_plan, rollback_plan
}
```

### Internal plasticity proposal compatibility profile

The Rust `hepta-plasticity` records described here are internal deterministic records, not replacements for the canonical JSON `PlasticityProposalV1` or `TopologyProposalV1` protocols above. The legacy internal record uses domain `hepta.plasticity.proposal.v1`. It remains available only through explicit version-1 read dispatch. Its historical digest cannot be fully recomputed from the stored record because the old preimage included `maximum_absolute_delta` but the stored record omitted that field. Consequently, a V1 read may validate bounds, ordering, lineage, nonzero digests and deny-all authority, but it treats the historical digest as opaque. New V1 creation and append fail closed, and V1 is never silently converted or relabeled as V2.

The only new-write profile is the parameter-only `ParameterProposalV2`. It contains no topology operation and uses domain `hepta.plasticity.parameter-proposal.v2`. The exact SHA-256 preimage is:

| Ordinal | Source | Canonical bytes |
| ---: | --- | --- |
| 0 | domain | literal UTF-8, unframed |
| 1 | version | `u16_be(2)` |
| 2-4 | proposal, proposer and evaluator IDs | each `u32_be(UTF-8 length) || UTF-8` |
| 5 | selected artifact digest | raw 32 bytes |
| 6-7 | window ID and window digest | framed ID, then raw 32 bytes |
| 8-9 | baseline and candidate generations | each `u64_be`; candidate is the exact successor |
| 10-16 | dataset, update-rule, modulator, modulator-broadcast, eligibility, evaluation and rollback-predecessor digests | each raw 32 bytes in the stated order |
| 17 | norm-profile digest | raw 32 bytes |
| 18 | candidate count | `u32_be`, in `[1,32]` |
| 19 | candidates | canonical candidate sequence described below |
| 20 | status | `u8(0)` for `requires_independent_acceptance` |
| 21 | authority mask | `u8(0)`; every authority bit is false |

Caller-supplied candidates are sorted by candidate ID and exactly one is `no_change`. A candidate encodes framed candidate ID, kind code (`0=no_change`, `1=update`), `u32_be` delta count, sorted deltas, `u32_be` layer-metric count, sorted layer metrics, global delta squared norm and global baseline squared norm. A delta encodes framed layer ID, framed globally unique parameter ID, signed Q32 delta/lower/upper raw values as `i64_be`, then its raw 32-byte evidence digest. A layer metric encodes framed layer ID, delta squared L2 norm and baseline squared L2 denominator as unsigned `u128_be`. Global squared norms are also `u128_be`. `no_change` has no deltas and zero delta norms; every update candidate has at least one nonzero delta. The envelope contains one bounded supplied candidate set, not several selected or final proposals, and contains no selection field. At most 4,096 deltas may occur across that supplied set, and a norm profile contains `1..256` layers.

The norm profile uses domain `hepta.plasticity.parameter-norm-profile.v1` and encodes selected artifact digest, `u32_be(5000)` per-layer maximum relative norm in ppm, `u32_be(2500)` global maximum relative norm in ppm, `u32_be` sorted layer count, each framed layer ID plus nonzero baseline squared L2 Q64 denominator as `u128_be`, and the checked sum of those denominators as global baseline squared L2. For every candidate and layer,

\[
\frac{\lVert\Delta_l\rVert_2}{\lVert W_l\rVert_2}\le 0.005,
\qquad
\frac{\sqrt{\sum_l\lVert\Delta_l\rVert_2^2}}{\sqrt{\sum_l\lVert W_l\rVert_2^2}}\le 0.0025.
\]

Checks compare squared integer ratios and fail on overflow. The global denominator is the sum over the complete declared layer profile, so a small layer can pass the global aggregate while failing its own layer gate; the `0.5%` layer constraint is not rendered redundant by the `0.25%` aggregate constraint. The profile digest binds denominators to the selected artifact identity, but does not prove that a caller supplied a complete or truthful artifact profile. Likewise, structural checks over the supplied candidate sequence do not prove generator-relative candidate completeness; unequal proposer/evaluator ID strings do not authenticate independent identities; and nonzero artifact, window, dataset, update, modulator, eligibility, evaluation or per-delta evidence digests do not authenticate their provenance, freshness or completeness. Independent consumers must verify those external facts before any selection or acceptance. This internal record alone cannot support either decision.

Registry identity is `(selected_artifact_digest, window_id)`. Re-appending byte-identical V2 semantics is idempotent; any other record for the occupied slot conflicts, including a changed window digest. Proposal IDs are unique independently of slot identity. Capacity is caller-configured and capped at 4,096; it counts distinct retained V1 records plus inserted V2 slots. Rejected conflicts and idempotent retries consume no capacity.

Golden migration vector `PLASTICITY-V1-GV-001` has a 307-byte legacy preimage and digest `a143a54a94d60d2734237612f1c2e0af4b4d986ea52efa6099765b83442dedb4`. It is read-only and cannot be upgraded. Golden vector `PLASTICITY-V2-GV-001` uses proposal `proposal:2`, proposer `proposer:1`, evaluator `evaluator:1`, selected-artifact seed `selected-artifact`, window `window:1` with digest seed `window`, generations `7 -> 8`, digest seeds `dataset`, `update-rule`, `modulator`, `broadcast`, `eligibility`, `evaluation`, rollback equal to the selected artifact, layer denominators `layer:a=1000000` and `layer:b=4000000`, and two candidates. `candidate:no-change` has no deltas; `candidate:update` has `(layer:a, parameter:a, 2, -10, 10, SHA-256("delta-a"))` and `(layer:b, parameter:b, -3, -10, 10, SHA-256("delta-b"))`. The norm-profile preimage is 156 bytes with digest `d31bd6f69d36817557272d747e5209d431e3ef3058e6f415dc57da4f8f98fb97`; the complete V2 proposal preimage is 898 bytes with digest `e2ecdc9e0fd3278865665a2b0b168a3048919e86e8979e2e90bc6e5db9ab357c`. These are independently encoded fixed oracles, not values captured from the Rust implementation.

Checkpoints are append-only and generation-specific. A compact checkpoint may summarize eligibility but must preserve replay-equivalent recovery within tolerance. Artifact lineage includes encoder, tokenizer, preprocessor, quantization, license/SBOM, device/runtime, dataset, training code and real consumer evidence.

### Decision-cell design records and owner mapping

The following names are design records, not registered wire IDs or Rust API
claims. Extend existing contracts only where semantics fit; otherwise register a
new producer/consumer version before implementation admission. Never reinterpret
existing NeuronTickInputV1, NeuronSignalReceiptV1 or BodyGraphSnapshotV1 bytes.

| Design record | Required semantic contents | Existing owner responsibility |
| --- | --- | --- |
| cell declaration | scoped cell and organ IDs; NDU subject reference; typed input/output/termination contracts; state schema; effective parameter bundle; permitted action templates; budget and fallback | neuron.runtime for local configuration; existing organ composition for membership |
| cell step | run/objective/body and cell generations; exact predecessor; source-bound observation and message IDs; causal sequence; monotonic deadline; complete candidate set/order; omissions; current resource allocation | neuron.runtime checkpoint writer; inference.control supplies authenticated model result |
| cell result | proposed state successor; typed prediction distribution; actual action policy/propensity or deterministic-policy identity; abstention/OOD/calibration disposition; consumed resources; effective bundle identity | neuron.runtime state; intuition.policy action; no effect authority |
| learning example | cell/organ decision IDs; joint or sequential behavior law; critic/objective/bundle revisions; independently observed outcome/watermark; credit/support diagnostics; deletion lineage | learning.ledger canonical facts; utility.ndu/learning.operator derived values |
| parameter bundle | base code/weights, tokenizer and preprocessing; organ/cell deltas and heads; shapes/order/precision; state compatibility; calibration and policy digests; predecessor; source dataset and optimizer artifact references; revocation lineage | learning.artifacts immutable bytes/manifests; existing selector admits adoption |

The checkpoint key adds a scoped cell slot beneath the existing owning subject;
it is not a new global owner. Existing single-writer CAS and outbox semantics
apply. A model reply cannot commit state or execute its proposed action by itself.
Model replacement drains in-flight work and publishes a coherent compatibility
bundle; independent unrelated organs need not change simultaneously.

The existing internal ParameterProposalV2 permits at most 4096 scalar deltas.
Retain it for bounded local updates. Larger adapter/full-model candidates must use
a versioned artifact-level delta reference with validated tensor inventory, bounds,
source/target identities and lineage; do not inflate the scalar protocol or claim
that an arbitrary nonzero digest proves a complete trained artifact. Such a new
adapter is a remaining implementation task, not introduced as an accepted wire
format by this documentation amendment.

## 7. Numerical stability, complexity and resource bounds

Pilot runtime cost is bounded by `O(d_h*k_f + |E_I|)` for sparse fan-in `k_f` and inhibitory edges `E_I`. No dense `d_h^2` path is allowed above `d_h=256` without qualification. p95 signal latency is `<=3 ms`, p99 `<=8 ms`, transient allocation `<=512 KiB`, active checkpoint `<=1 MiB`, and checkpoint write amplification `<=4x` logical bytes.

State norm, activation rate, threshold, eligibility norm, modulator norm and update norm are hard bounded. Pilot values are `H_max=8`, eligibility norm `<=4`, modulator absolute value `<=1`, per-layer relative parameter delta `<=0.5%`, global relative delta `<=0.25%` and at most one proposal per artifact/window.

Replay batches are bounded by rows, bytes, objective classes and age. Consolidation has a declared resource budget and cannot starve foreground operation. A missed replay window is observable degradation, not permission for an unbounded catch-up queue.

### Bounded cell adapter contract for implementation

The target internal interface separates prepare, inference, policy and commit:
`prepare_cell_step` validates a frozen definition and owner inputs without writes;
`infer_cell` consumes an admitted inference reservation and returns tensors with
runtime identity; `decide_cell` returns a complete legal behavior policy and state
proposal; `commit_cell_step` CAS-publishes state/receipt through the existing owner.
`propose_cell_update` consumes an immutable dataset, fixed value/credit profile,
trainable-parameter mask and budget and returns only a candidate artifact.
These names describe implementation work, not existing exported Rust symbols.

Use existing exact stable IDs/digests/generations for identity fields and monotonic
logical deadlines for ordering. Bound observations by the admitted tokenizer/input
profile and log actual truncation. Bound candidates by the legal-set profile,
state by the registered Neuron checkpoint profile, messages by per-port count/byte
limits, and training by job byte/step/time quotas. Each deployment must provide
nonzero maximums before admission; no unconstrained default or implicit unlimited
batch is allowed. Numeric tensors carry dimension, units, normalization and
precision; identity, authority and deletion fields never pass through learned
embeddings or approximate conversion.

Reject typed InvalidDefinition, ScopeMismatch, IncompatibleBundle,
IncompleteCandidates, StaleSource, DeadlineExceeded and CapacityExceeded before
state mutation. BackendUnavailable and UnsupportedEstimator permit only the
registered abstain/slow-path/no-update fallback. CommitUncertain requires
owner reconciliation by exact semantic operation identity; it is not retryable
as a new action. Unknown critical fields and ambiguous parameter tensor inventory
reject. These are target error semantics to map into existing owner error types,
not additions silently accepted by old wire decoders.

### Shared serving, bounded activation and measured scaling

Logical cells share resident inference workers and read-only bases. Group work by
compatible model/tokenizer/adapter/shape/precision while preserving per-request
scope, deadline and exact policy identity. Admission happens before queueing;
queue overflow and expired work produce explicit fallback without hidden retries.
Training uses a separate bounded resource allocation and cannot steal reserved
foreground/safety capacity. Adapter eviction never erases durable state or lineage.

Cache keys include complete question/option order, source frontier, scope, model,
adapter, tokenizer, normalizer and calibration generations. Check current deletion
and revocation before reuse. Shared base weights save residency, not automatically
FLOPs: different question-conditioned sequences still require computation. Never
claim all cells execute for the latency of one forward pass.

For planning, resident weight bytes are B_base + sum(B_resident_organ_delta) +
sum(B_resident_cell_delta); add state, caches, activation peaks and concurrent
optimizer jobs separately. Compare logical-cell counts 8/64/256/1024 while holding
active concurrency and workload fixed, then vary concurrency separately. These
are experiment points, not demonstrated capacity or new runtime limits. Record
p50/p95/p99 end-to-end latency, queue age, rejected work, GPU/RSS peaks, adapter
miss cost, storage growth and crash-recovery time. Existing sparse-tick latency
targets do not include an unmeasured full Laya inference/training invocation.

## 8. Failure detection, fallback and rollback

Failures include model/tokenizer/preprocessor mismatch, invalid checkpoint generation, state explosion/collapse, activation collapse, all-unit activation, threshold saturation, eligibility overflow, modulator provenance failure, replay lineage violation, OOD false acceptance, trust-region breach and attempted current-run weight/topology mutation.

Fallback order is valid temporal candidate → stateless selected head → deterministic calibrated rule → slow-path request. A corrupt or incompatible checkpoint is quarantined; the process may reconstruct from the last valid checkpoint and ordered events. Rollback selects the exact predecessor artifact and topology snapshot and verifies checkpoint compatibility. No partial layer mix is allowed.

## 9. Security, authority, privacy and unlearning

Neural state carries no authority and never stores raw credentials, secret values, unrestricted prompt text or external instructions. Local-model output is advisory. `intuition.policy` cannot bypass a hard veto, and `learning.plasticity` cannot select or install its proposal.

Feature admission is purpose- and principal-scoped. Checkpoint inspection exposes bounded summaries, not raw private content. Unlearning traverses inputs, feature caches, checkpoints, replay eligibility, world-model rows, adapters, proposals, artifacts and backups. A checkpoint depending on deleted content is revoked or rebuilt before reuse.

## 10. Verification, golden vectors and property tests

Required tests cover deterministic top-k ties, lateral inhibition, target activation rate, threshold recovery, eligibility decay, zero modulator, positive/negative modulator, trust-region clipping, state checkpoint/reopen, encoder mismatch, OOD/abstention, replay scheduling, deleted-row exclusion and predecessor rollback.

Ablation families include full mechanism, no inhibition, no homeostasis, no eligibility, no replay, shuffled modulator and frozen temporal state. Lesion tests remove registered units or edges and measure utility, stability, calibration, forgetting and resource change. Property tests enforce bounded state, bounded sparsity, deterministic tie-breaking, zero current-artifact mutation and replay lineage closure.

### Cell-specific executable tests to implement

Cover zero-delta/base equivalence; wrong-base or wrong-shape adapter rejection;
cross-principal state/cache isolation; candidate-order permutation mapping;
complete-set omission and truncation; runtime logits versus recorded behavior
propensity; deferred outcome handling; expired queued work; adapter eviction and
reload; cancellation before/after checkpoint commit; acknowledgement loss; shared
base replacement with old adapters; deletion reaching replay/optimizer/checkpoint
and restore; and no-data/no-update. A frozen observation with two choices and
known value difference supplies a hand-computed policy-gradient direction test.
Model these as tests in existing owning packages, not per-cell global CI gates.
Their definition here is not a test-pass receipt.

## 11. Quantitative acceptance gates

| Gate | Required threshold |
|---|---|
| Temporal recovery parity | max component error `<=2` Q24 units |
| Activation sparsity | within registered target ±`2 percentage points` |
| Dead-unit fraction | `<5%` after warm-up |
| Always-active fraction | `<1%` |
| Threshold saturation | `<0.1%` updates |
| State/eligibility overflow | `0` |
| OOD false acceptance | `<0.5%` |
| Calibration ECE | `<=0.03` |
| Three-factor/oracle cosine | lower 95% bound `>0` on supported slice |
| Parameter proposal | within every trust-region bound |
| Current-run parameter/topology mutation | `0` |
| Full mechanism versus each ablation | preregistered utility/stability benefit or claim withheld |
| Old-task degradation | no worse than `2%` per slice |
| Rollback/reopen | `100%` mandatory fault suite |
| Deleted-row replay | `0` |

Functional biomimicry requires the full ablation and longitudinal evidence set; passing runtime unit tests is insufficient.

## 12. Paper traceability and Hepta extensions

`PAPER-NDU-EU-2025` informs bounded temporal preference/utility semantics, not the local neural update. `PAPER-HOLDER-Q-2026` informs the slow value/operator candidate, not biological plasticity. Sparse competition, lateral inhibition, eligibility, homeostasis, neuromodulation, replay consolidation, lesion/ablation and trust-region next-snapshot updates are Hepta hypotheses requiring direct evidence.

No cited paper is used to claim spiking neurons, synaptic biological identity, consciousness, neuromorphic energy efficiency or safe autonomous evolution.

### Engineering references and limits

Source review: [Laya DecisionModel](https://github.com/NandhaKishorM/laya/blob/c7527708f9f5220c669d8aa385077cd28d04708a/laya/common.py)
and [inference boundary](https://github.com/NandhaKishorM/laya/blob/c7527708f9f5220c669d8aa385077cd28d04708a/laya/agent.py).
The [model card](https://huggingface.co/convaiinnovations/laya) identifies open
weights and task specialization. Runtime admission still needs an exact weight
revision, digest, dependencies and license/SBOM review; a Git code pin is not a
weight pin. No model-card accuracy or latency is a Hepta qualification result.
[LoRA](https://arxiv.org/abs/2106.09685) motivates low-rank parameter sharing;
[S-LoRA](https://arxiv.org/abs/2311.03285) motivates bounded multi-adapter serving.
Neither proves native Laya compatibility or multiscale efficacy. These are
engineering references, not additions to the NDU theorem-evidence claim ladder.

### Delivery through existing packages

The DecisionCell requirements are planned `designExtensions` of existing
`../delivery/WORK_PACKAGES.json` entries. Earlier source-complete package state
never certifies the new extension. Implement in this dependency order: BIO-0
contract integration and NEU-1 real backend profile; NEU-2 scoped state plus
NDU-1 utility/gradient reference; C1 read-only retrieval-organ baseline; bounded
local adaptation and NDU-2 organ credit; ART-1/ART-2 compatible bundle lifecycle;
PLS-2/PLS-3 structural changes; BIO-2 slower shared consolidation. Evaluate through
LRN-2 and LONG-1/2/3 throughout, not only after rollout. INT-2 remains the single
product-composition boundary. Runtime adoption must wait for its existing data,
authority, artifact and lifecycle predecessors even when source coding is parallel.

No new global work-package DAG, per-cell module registry or duplicate training
framework is introduced. Ordinary documentation and owner-authorized source
changes use affected checks; target-host, learning-efficacy and production gates
apply when that boundary is actually exercised.

## 13. Implementation sequence and completion rule

Implementation order is exact local-model manifest → deterministic temporal cell and checkpoint → sparse competition/inhibition → calibration and OOD → eligibility/homeostasis → independent modulator → bounded proposal artifact → replay consolidation → prediction-error world model → ablation/lesion qualification → future-time retention → optional topology proposal and canary.

Documentation closure means the mechanism, state, tests and thresholds are specified and machine-gated. Source implementation, `N1` real consumer evidence, `N2` temporal recovery and `N3` functional-biomimicry evidence remain separate. This file does not by itself advance `N0_METAPHORICAL`.
