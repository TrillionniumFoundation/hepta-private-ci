# Stem Encoder × Cell Head qualification (shadow-only)

This **read-only research package** implements an initial, reproducible entry point for the three Stem/Cell studies. It does **not** install models, issue capability tokens, invoke the production Neuron owner, write canonical artifacts, or promote decisions. Its standard-library tests are **L1 instrumentation tests**, not evidence that a real 421M model, NDU evaluator, hardware batch, lifelong learner, or Rust backend was exercised.

Canonical governance: [`docs/learning/EXPERIMENTS.json`](../../docs/learning/EXPERIMENTS.json), [`NEURAL_BIOMIMICRY_SPEC.md`](../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md). Existing parameter composition is marked `design_only_not_wire_schema` in `docs/learning/ARTIFACTS.json`. Preserve owner boundaries: model execution, independent outcome evaluation, selection, and effectful release are separate services.

## Experiment 1: fixed-model, fixed-budget Stem selection

The preregistered `protocol.json` specifies five frozen-HF Stem candidates (mmBERT-small 140M, mmBERT-base 307M, ModernBERT-base 149M, Jina v2 zh 161M, BGE-small-zh 24M), two external full-decision teacher baselines (Laya 421M, Laya Multilingual 322M), Chinese/English/cross-language slices, shot curves, and OOD. Model parameter counts are approximate model-card values. Check upstream model identities and licenses against **pinned** snapshots before starting. The Laya teachers are **external baselines**: no generic HF adapter is assumed for them.

`model_runner.py` uses **real local HF encoder weights** to train **one frozen encoder + one Head at a time**. It refuses network model fetching, validates a SHA-256 digest over an audited **self-contained snapshot**, and rejects trainable parameter counts exceeding budget. It computes temperature and the fixed 80%-coverage confidence threshold **only** from a disjoint calibration split. The model runner emits predictions, cost-neutral timing observations and a SHA-bound ".run.json" manifest with the Python/Torch/Transformers versions, encoder/Head parameter counts, feature/training times, cache usage and observed RSS; it **cannot emit reward/outcome receipts**.

Dependencies for model runs are pinned by the experiment operator in the execution environment (torch, transformers, tokenizers and model-specific runtime); CI does **not** install model dependencies or download weights. A locally audited Jina custom-code snapshot requires the explicit `--allow-audited-custom-code` flag. Hash that snapshot after vetting it; never execute newly downloaded or unreviewed model code. The digest is a local content-tree checksum, not a Hugging Face commit ID. An external manifest must bind both.

A read-only test command (replace paths/digests and choose a concrete arm):

```sh
python3 qualification/stem-cell-v1/model_runner.py \
  --dataset /approved/dataset.jsonl \
  --snapshot /models/mmbert-small-self-contained \
  --expected-snapshot-digest <64-hex-local-tree-sha256> \
  --model-key mmbert_small --representation joint \
  --head linear --budget 2048 --shots-per-class 32 \
  --train-steps 100 --device cpu \
  --output /scratch/mmbert-joint-linear-2048-32.jsonl
```

Test and calibration folds must be source-group and episode-disjoint. Inputs must have `sample_id`, `source_group`, `episode_id`, `split`, `language`, `scope`, `state`, `question`, `options`, and `label` (zero-based class index). Splits: `train`, `calibration`, `held_out`, `future_1`, `future_2`, `ood`. The test dataset must be source-licensed, approved, pinned and timestamp-separated; synthetic fixtures never count as measured utility. Use matching examples, steps, number of output choices, seeds and device profile across candidates. Collect warm-up separately from measured encoder latency, and record truncations (BGE's 512-token context is a material limitation).

## Experiment 2: representation × Head × trainable budget

The four pre-registered representations are: question+state joint encoder; two independently cached sentence vectors; eight pooled state token landmarks plus question encoding; and parameter-free, question-conditioned lightweight cross-attention over those landmarks. Head options: linear, elementwise FiLM, rank-8/16, MLP and SwiGLU. The frozen encoder is *not* updated during inference and the local bounded LRU may reuse token states **only within a matching scope/revision**. Unsupported tiny-parameter Head combinations are explicitly rejected, not silently expanded. The current cross-attention readout has no trainable Q/K/V projection; adding one requires a separate preregistered arm and counting its parameters.

This runner extracts one sample at a time (no production backend batch claim). It is a **model-specific feasibility entry point**, not an automated full Cartesian grid, distributed training service, or calibrated evidence for all tasks. Its latency figures include Python, tokenization and possible cache effects, and are not portable target-host benchmarks. Vary sequence lengths, task types and repeated inputs separately, and document memory/optimizer/time for each Cell. 0-shot stays a no-change baseline rather than an arbitrarily untrained Head.

## Experiment 3: logical Cell scaling and native receipt analysis

`scale.py generate` generates deterministic request intents for 64, 256, 1024 and 4096 logical Cells, active fractions 1/10/50/100%, in-scope input repetition 0/50/90%, and task similarity same/mixed/disjoint. Generating intents **does not run a real model**. Feed them into a permitted, bounded, **native Hepta inference worker**. Export *actual* request, backend batch, WAL fsync and recovery traces from the owner, then run `scale.py analyze` with those traces:

```sh
python3 qualification/stem-cell-v1/scale.py generate \
  --logical-cells 1024 --active-fraction 0.1 --input-repeat 0.5 \
  --task-similarity mixed_family --model-digest <64-hex> \
  --output /scratch/stem-workload.jsonl
python3 qualification/stem-cell-v1/scale.py analyze \
  --workload /scratch/stem-workload.jsonl \
  --trace /scratch/native-owner-trace.jsonl \
  --output /scratch/scale-diagnostic.json
```

The v2 trace parser rejects incomplete, duplicate, stale-generation, cross-scope **within a batch**, orphan, unbounded, impossible-clock and falsely counted batches. Each batch now echoes its exact request member IDs, Scope, Generation and backend execution clock interval. See [NATIVE_TRACE_V2.md](NATIVE_TRACE_V2.md) for the required fields and adversarial conformance tests. Its `trace_claimed_multi_request_batches` is **not** an authenticated physical batch count; `independently_verified_backend_multi_request_batches` stays `null`. The native trace must record `enqueued_us`, `start_us` and `end_us` using **one actual worker monotonic clock**; the generated `submitted_at_us` values are only workload scheduling offsets, not real timestamps. It reports cold-encoder and cache-hit-Head **end-to-end** p50/p95/p99 plus execution p99 and queue p99 separately, request-attributed CPU (not an independently measured process CPU total), RSS, WAL fsync and recovery checks. Such JSON remains an **unverified offline trace**: it cannot authenticate the owner or attest Rust production execution. Longitudinal retention and negative transfer need additional real, independently observed future-window receipts; they are left `null` instead of invented.

## Independent evaluation, NDU, acceptance

`study.py` accepts model predictions JSONL and **separate, independently generated** outcome receipts JSONL, paired by `arm` and `sample_id`, and emits a SHA-256-bound report:

```sh
python3 qualification/stem-cell-v1/study.py \
  --dataset /approved/dataset.jsonl \
  --predictions /scratch/all-arm-predictions.jsonl \
  --outcomes /approved/independent-owner-outcomes.jsonl \
  --output /scratch/stem-analysis.json
python3 -m unittest discover -v -s qualification/stem-cell-v1 -p 'test_*.py'
```

Independent outcome receipts must have `arm`, `sample_id`, `observer_digest`, `snapshot_digest`, `external_ndu_utility` and `total_cost`; these values are **not produced by the model runner**. Use true NDU utility / complete lifetime costs, including load, train, evaluation, serving and checkpoint cost; do not confuse classification accuracy with terminal utility. The independent evaluator must validate authenticated outcomes, verified legal actions and current revocation externally; a self-declared JSON digest is **not** a signature. The analyzer therefore never grants `shadow_eligible` or `production_authorized`, even if its statistical precheck passes.

Bootstrap is clustered by source group, uses fixed 2,000 replicates and Bonferroni correction, and compares NDU LCB against the frozen no-change arm. Keep at least 400 independent groups, 3 snapshots, 2 future windows, old-task degradation <=2%, OOD false acceptance <=0.5%, and cost ratio <=1 at the chosen utility/cost comparison. Each future window must separately show a positive grouped utility LCB with >=50 independent groups; each language slice must have >=30 independent groups and <=2% utility degradation. The OOD floor is enforced against the **95% Wilson upper bound**, not an optimistic point estimate. Every candidate must be independently accepted, signed and promoted using existing Evaluator → Selector → Executor boundaries and actual target-host tests; **none of that is implemented by this package**.

## Evidence progression and known blockers

| Gate | What this package provides | What must still be run |
|---|---|---|
| L0 | Frozen protocol/matrix and subgroup design | Dataset and hardware/revision manifest freeze |
| L1 | Deterministic generator, strict receipts analyzer, isolated head trainer, unit tests | CI verification on exact HEAD |
| L2 | Offline real-weight HF hook | Download/vet snapshots, train/evaluate all arms, independent labels, calibration/OOD |
| L3 | Native trace schema checks | Actual worker `run_batch` instrumentation, fsync/restart fault cuts, target-host CPU/RSS |
| L4 | Group bootstrap + noncompensable floors | Authenticated NDU future outcomes, longitudinal negative transfer, independent evaluator |
| L5 | No privileged paths | Existing release gate, shadow/canary, rollback, authority/revocation/lineage proof |

**Never promote because `study.py` says `statistical_precheck_passed`.** It is not a signed NDU decision.

## Next phase: immutable multi-arm execution plan

`matrix.py` can now construct a **finite, immutable local experiment plan**
from all five approved *local* encoder snapshots. An operator-supplied JSON
maps each of the five model keys to `source`, an immutable 40-hex
`upstream_revision`, `snapshot_path`, an independently reviewed tree `sha256`,
`license_approved: true`, and, for Jina's custom-code profile only,
`custom_code_reviewed: true`. Remote names and remote commit IDs are operator
claims, **not** independently authenticated by this planner. Compare
artifact/source contents with the upstream release separately before approving
training.

```sh
python3 qualification/stem-cell-v1/matrix.py plan \
  --dataset /approved/episodes.jsonl \
  --snapshots /approved/frozen-snapshot-descriptors.json \
  --train-steps 100 --device cpu \
  --output /scratch/hepta-stem-frozen-plan.json
python3 qualification/stem-cell-v1/matrix.py run \
  --plan /scratch/hepta-stem-frozen-plan.json \
  --arm mmbert_small:joint:linear:2048:32 \
  --output /scratch/mmbert-joint-linear-2048-32.jsonl
```

The full preregistered nonzero-shot Cartesian grid is **1,920 arms** (5
encoders × 4 representations × 6 Heads × 4 budgets × 4 positive shot counts),
not 1,920 demonstrated successful trainings. Unsupported Head/budget combinations
are intentionally rejected by `model_runner.py`. The 0-shot/no-change and two
Laya teacher baselines remain external, separately observed baselines. Plan
and per-arm output artifacts are **append-only / no overwrite**; plan, dataset,
local weights, protocol, runner source and generated predictions are SHA-256-bound.
The planner never creates NDU success labels or production capabilities.

The standalone runner now reports process CPU seconds and process-lifetime peak
RSS when available; the peak is **not** a per-arm incremental memory delta.
Sampling requires distinct source groups **across** labels, not merely within
each class. Equal hardware, precision, runtime and evaluator configuration must
still be checked by the external qualification owner.

## Native Worker batching: bounded contract, not yet L3 acceptance

`codex-rs/hepta-infer-worker-host/src/model_worker_batch.rs` adds a native
`NeuronBackendBatchDriver` trait with **no sequential fallback**. The worker
preflights all 2–32 requests against current grants, loaded manifest, distinct
request IDs, payload digests, encoder identity, compatible feature/output widths
and available active slots before invoking the backend exactly once.

Backend replies must contain one exact ordered request/input echo per member and
return model-specific typed receipts without granted authority. Driver failure,
forged batch/member identity, count mismatch and memory-budget overflow fail
closed and release in-flight slots. The batch digest is **not** a cryptographic
backend attestation: unit tests use a loop-based mock solely to prove these
worker-level properties. A real tensor-capable driver, generation/scope validation
at the upstream owner, native timestamps, signed provenance, WAL fsync and crash
recovery remain separately required for L3 and cannot be inferred from this
trait or its unit tests.

The dedicated CI lane runs Rust formatting and compilation, targeted native Worker/Head and final-use-ordering tests, plus Python L1 tests. Full App Server end-to-end tests are independent, non-waived production blockers.
None of these tests load mmBERT weights or issue production selection authority.

## Q24 CPU Head vertical slice (native arithmetic, not Encoder execution)

The separate `model_worker_cpu_head.rs` provides a real, deterministic,
**local CPU Q24 affine + hard-gated Head** kernel for previously encoded
feature vectors. Unlike the earlier mock batch driver, this performs actual
matrix multiplications in Rust. It executes many Cell Heads in a single
driver-level batch call with individually bound typed receipts and no implicit
single-request fallback. Signed Q24 uses ties-to-even and rejects results
outside [-8,8]. A constant gate or zero prediction matrix can be encoded as
a canonical **empty tensor** to avoid counting or allocating dummy weights.

The 512-feature Neuron V1 limit is a real admission constraint. Native
profiles do **not** truncate the 768/1152-dimensional outputs produced by
some Encoder/representation combinations: these require a separately
preregistered, independently evaluated Organ projection. Current native
execution remains a **Head-only stage**. No mmBERT, ModernBERT, Jina,
BGE or Laya encoder weights have been loaded into the Rust worker.

Optional local affine Head export from real, frozen Encoder training:

```sh
python3 qualification/stem-cell-v1/model_runner.py \
  --dataset /approved/episodes.jsonl \
  --snapshot /approved/mmbert-small \
  --expected-snapshot-digest <audited-local-tree-sha256> \
  --model-key mmbert_small --representation joint \
  --head linear --budget 2048 --shots-per-class 32 \
  --train-steps 100 --device cpu --export-q24 \
  --output /scratch/mmbert-joint-linear.jsonl
```

This additionally writes an append-only `.q24.json` candidate, with
individually SHA-bound Head and bundle weights, Q24 tensor inventory,
calibration-only parity results and model/runner lineage in `.run.json`.
`native_bridge.py` folds only truly affine Head families
(Linear, FiLM, Rank-8/16); it rejects MLP, SwiGLU, unbounded coefficients,
incompatible feature widths, and over-budget physical tensor inventories.
The exporter uses a frozen 0.02 maximum absolute calibration-logit error
and requires zero calibration argmax mismatches. These are *feasibility*
checks, not independent accuracy or NDU acceptance.

`test_native_bridge.py` compares Python SHA-256/Q24 canonical vectors
against golden constants also asserted by
`model_worker_cpu_head_tests.rs`. The Rust CPU measurement reports actual
CPU kernel elapsed time and *tracked numeric buffer allocations*; it is
**not** an independent process RSS attestation, a fused Encoder kernel, a
signed provenance receipt, WAL crash recovery, a target-host 4096-Cell
benchmark or production admission.

Still missing for L3–L5: exact owner admission and scope/generation fencing,
authenticated exported tensor CAS load, live microbatch scheduling,
independent resource measurements, a registered quantized projection for
wide embeddings, target-hardware throughput/RSS, crash-recovery/WAL cuts,
independent NDU future-window outcomes, and operator promotion authorization.

## Shared Encoder feature fabric: real offline batch path, not production authority

`shared_encoder_batch.py` adds a frozen, local Hugging Face Encoder executor
that computes an actual **single batched forward** on distinct approved inputs,
plus deterministic mean or eight segment-landmark feature extraction. The
`FrozenLocalHfBackend` requires a SHA-256-verified local snapshot, uses
`local_files_only=True` and `trust_remote_code=False`, and refuses silent
truncation or network downloads. Encoders requiring custom model code (including
some Jina snapshots) cannot use this generic loader without a separately audited
backend implementation. `transformers` and `torch` are optional runtime
dependencies, not CI downloads.

`SharedStemEngine` rejects a mixed Scope, Generation, revocation frontier,
representation or pinned model/preprocessor/runtime profile **before any
model call**. It computes each distinct input once per bounded batch of
1–32 requests; same-scope Cells can reuse immutable, float32-digest-bound
features. The bounded in-memory LRU is keyed by
`(scope, generation, revocation, encoder, preprocessor, runtime, input, representation)`
and never retains raw text. It supports explicit scope and generation
invalidation; the upstream real owner must still deliver revocation events.
No cached embedding, model digest or caller-provided scope hash is a signed
authority witness. Cross-scope sharing is deliberately disabled.

Wider-than-512 output is reported *as wide*, not silently truncated or
automatically admitted to `NeuronFeatureRequestV1`. An independently trained,
pinned, qualified projection remains a blocker for ModernBERT 768D and
multi-vector token-landmark paths. The `feature_digest` binds canonical
float32 values and representation; no persistent feature artifacts or
production-ready Rust bridge are created by this module.

`test_shared_encoder_batch.py` includes 4096 **logical** Cell
reuse assertions under a clearly marked synthetic backend and, if Torch
is installed, a real small synthetic Torch tensor forward. These are
L1 behavior checks, not 4096 concurrent requests, trained mmBERT inference,
target-device throughput, safe cross-principal sharing, or NDU learning uplift.

No-change remains frozen, and this implementation is **shadow_only_not_authorized**.
In particular, the current research Scope digest is not authenticated by
`AuthBus`, cache revocation is not yet connected to owner events, cross-process
feature buffers are not immutable CAS artifacts, and there is no claim that
Python inference is on the production Codex/Hepta execution spine.

### Native and full App Server CI distinction

L1 targeted Rust validation selects `test(model_worker::)` and the
final-use ordering guard; it does **not** skip or waive App Server end-to-end
integration tests for production. A separate historical App Server test
requires a configured Codex executable and can still fail full-suite CI.
The static final-use order regression now checks the entered-use helper used
by the current code, rather than searching for the removed direct
`request_typed::<TurnStartResponse>` call. A green L1 job alone remains
insufficient for L3 or production promotion.


## Experiment A: full-decision 395M–435M four-way comparison

The existing qualification directory now contains decision_421m.py, an
append-only, read-only evaluator of eight paired arms: original Laya
421M, Laya Typed-Decisions 421M, DeBERTa-v3-large 435M, and
ModernBERT-large 395M, each evaluated as an off-the-shelf checkpoint
and after equal-budget, equal-step fine-tuning.
An already task-trained checkpoint is not automatically zero-shot.
The four real model/decision adapters, their pinned local weights and
licensed/authorized dataset must be supplied by an independent operator;
this script does not load arbitrary model code or generate pretend accuracy.

Example offline workflow (no unapproved model download):

    python3 qualification/stem-cell-v1/decision_421m.py plan \
      --dataset /approved/time-partitioned.jsonl \
      --descriptors /approved/decision-checkpoints.json \
      --train-steps 100 --trainable-budget 262144 \
      --batch-size 16 --context-tokens 512 --device cpu --dtype fp32 \
      --output /scratch/decision-frozen-plan.json
    python3 qualification/stem-cell-v1/decision_421m.py evaluate \
      --plan /scratch/decision-frozen-plan.json \
      --runs /scratch/actual-run-metadata.json \
      --predictions /scratch/actual-model-ordered-logits.jsonl \
      --output /scratch/decision-review.json

Snapshot descriptors use exact keys defined by SOURCES with source,
parameter_count, upstream_revision (40 lowercase hex), snapshot_path,
sha256 (verified local content tree), and explicit license_approved and
adapter_reviewed approvals. Each run metadata entry binds its arm,
checkpoint_sha256, weights_sha256, dataset_sha256, upstream_revision,
training_sample_groups_sha256, seed, runtime_profile, input_contract,
truncated_input_count, train_steps and trainable_parameters. Equal-budget
arms additionally bind training_split=train and optimizer=adamw.
Measured trainable parameter counts must agree within 10% and stay
under the fixed ceiling; options order, zero truncations and runtime
profile must agree. Real decision adapters emit arm, sample_id, logits
in the ordered legal option space, weights_sha256 and measured latency_ms,
never gold labels or NDU utility.

The evaluator demands all eight arms and all paired samples,
source-group and episode separation, time-separated train/calibration/
held-out/future windows, calibration-only temperature/confidence,
15-bin ECE, Brier, NLL, OOD acceptance, measured latency, and
Bonferroni-adjusted source-group paired future confidence bounds.
Production promotion is always prohibited: metadata digests are not
cryptographic owner attestations and offline predictive accuracy does
not prove causal NDU gains or physical 4096-Cell resource savings.
Its pure-Python fixtures only test instrumentation and rejection logic.

## Experiment B and C interoperation

The original model_runner.py and matrix.py now include mmBERT-base
~307M alongside the original four frozen-HF candidates. Thus the
complete planned nonzero-shot grid becomes 1,920 arms
(5 encoders × 4 representations × 6 heads × 4 budgets × 4 shot counts),
not 1,920 executed trainings. Jina v5 Text Nano ~239M is handled by
the pinned task-adapter-aware backend in stacked PR #1499, not by
disguising a generic Jina v2/HF pooled embedding as v5.

Experiment C uses #1499's separate no-change/frozen/learned statistical
and chronological training trials, plus the native Worker branch #1498.
Synthetic 4096 logical-Cell tests remain L1 conformance, not real
production CPU/RSS/p99/WAL/crash-recovery evidence.


### Exact dataset identity bridge for Jina v5 (Experiment B)

The optional, **schema-only** jina_dataset_bridge.py maps the *same*
source dataset from six Stem splits to PR #1499's five Jina splits:
held_out -> test, future_1/future_2 -> future with an unchanged
future_window tag. It preserves case/group/episode identities, all ordered
options, time, language, task, scope, principal and per-Cell identity.
No unspecified identity is manufactured and cross-window source groups
or matching text across training/evaluation folds are rejected.

This bridge requires explicit cell_id, task_id and principal_id fields
on the approved Stem dataset, plus an externally approved byte SHA:

    python3 qualification/stem-cell-v1/jina_dataset_bridge.py \
      --source /approved/episodes.jsonl \
      --approved-source-sha256 64-hex-from-existing-data-owner \
      --output /scratch/jina-compatible-episodes.jsonl

It writes a non-authorizing append-only .bridge.json digest manifest.
The converter neither authenticates the data-use owner, executes Jina v5,
nor supplies token-state Landmark/Cross-attention support. Those Jina
representation cells stay UNQUALIFIED until their own task-adapter
implementation can supply demonstrably equivalent token states.


**Metric compatibility:** decision_421m.py reports multiclass Brier as
sum of squared class errors divided by the number of options, matching
PR #1499's qualified_eval. The earlier stem-cell-v1 study.py reports
the *unnormalized* class-error sum. Do not rank models by Brier values
from those two report schemas without first applying the explicit
choice-count normalization. A model-selection reviewer must compare
identically normalized scores on paired cases.


### Real local HF execution: Experiment A DeBERTa / ModernBERT

hf_joint_decision_runner.py now implements **actual local pretrained-weight
inference + learned action Head** for two 395M–435M candidates. Unlike the
model-free reviewer, this performs encoder forward passes over the full
state + question + ordered options text, masked mean pooling, and
deterministic AdamW updates for a parameter-counted bounded two-layer Head.
The pretrained backbone is FROZEN. Strict locally reviewed safetensors,
tokenizer, 40-hex upstream revision, complete local tree SHA, exact approved
dataset bytes, and input length no larger than the shared 512-token profile
are required. It refuses network download, remote-code execution, silent
truncation and already existing output artifacts.

Use exactly the same group- and future-window-separated corpus as
decision_421m.py, with pretrained checkpoints provisioned by the
independent model owner. Example for **one** of two HF arms:

    python3 qualification/stem-cell-v1/hf_joint_decision_runner.py \
      --dataset /approved/time-partitioned.jsonl \
      --expected-dataset-sha256 <approved-source-byte-sha256> \
      --model-key deberta_v3_large \
      --snapshot /approved/deberta-v3-large-safetensors \
      --expected-snapshot-sha256 <reviewed-tree-sha256> \
      --upstream-revision <reviewed-40hex-upstream-sha> \
      --license-approved --adapter-reviewed \
      --train-steps 100 --trainable-budget 262144 \
      --batch-size 16 --context-tokens 512 \
      --seed 7347 --device cpu --dtype fp32 \
      --output /scratch/deberta-equal-budget.jsonl

Repeat with modernbert_large and its own reviewed checkpoint using the
**identical data, Head architecture, steps, batch size, seed, context and
target device**. The .run.json receipt contains the frozen Encoder
parameter count, physical trainable Head count and Head weights digest,
the exact runner source digest, dataset/upstream/model revision, measured
per-row cold inference latency, RSS and training duration. It has the
existing decision_421m.py reviewer metadata fields and an explicit
non-authorizing status; a manifest hash is not an independently signed
hardware or learning result. Source and license approval flags are operator
claims and require external attestation.

**Checkpoint-phase fairness limit:** raw pretrained DeBERTa-v3-large and
ModernBERT-large do not include an original Laya-equivalent pretrained
typed Decision Head. This runner therefore emits ONLY equal_budget arms,
and NEVER fabricates untrained-Head zero-shot scores. The four-way
reviewer continues to require eight valid arms before returning a complete
comparison. Genuine reviewed checkpoint-stage decision adapters, both Laya
model checkpoints and a shared operator-approved dataset still must be
provided; until then, the final four-way assessment is BLOCKED.

Local no-weights tests check Head size, actual tiny-PyTorch tensor updates,
determinism, attention-mask pooling and failed provenance admission.
They are L1 interface evidence, NOT pretrained 421M inference, full
backbone fine-tuning or Hepta native 4096 Cell measurements.


**Anti-false-zero-shot admission:** for each checkpoint phase, the external
run record must explicitly attest pretrained_typed_decision_head_present=true
and disclose upstream_task_exposure as task_specific, generic_decision, or
unknown. A fresh random HF classification/decision Head is NEVER a
qualifying checkpoint-stage comparator. These fields are offline operator
attestations, NOT cryptographically verified independent receipts. They
prevent accidental leaderboard promotion from invalid model semantics.


### A-stage partial comparison when pretrained HF Decision Heads do not exist

The offline decision_421m.py now has two *different* registered review
scopes. The default --comparison-scope full remains strict: **eight real
arms**, including four genuinely pretrained typed-decision checkpoint
comparators, are required. Raw DeBERTa-v3-large and ModernBERT-large
Encoder-only checkpoints may legitimately have no such Head. Do not
manufacture one and call its random logits "zero-shot".

To get a useful actual four-model learned-Head comparison first,
independently execute four :equal_budget arms (original Laya, Typed Laya,
DeBERTa-v3-large, ModernBERT-large) on the same pinned task data, optimizer
steps, trainable parameter budget and inference hardware; then invoke:

    python3 qualification/stem-cell-v1/decision_421m.py evaluate \
      --plan /scratch/decision-frozen-plan.json \
      --runs /scratch/four-real-equal-budget-run-receipts.json \
      --predictions /scratch/four-real-equal-budget-logits.jsonl \
      --comparison-scope equal_budget \
      --output /scratch/four-model-equal-budget-shadow-report.json

It rejects unknown, missing or duplicated arms and checks full paired
test/calibration/future/OOD coverage and frozen model/weight lineage.
The report explicitly sets full_comparison_present=false,
checkpoint_comparison_status=NOT_COMPARABLE..., and
production_promotion_permitted=false. It **cannot** be used as a
replacement for missing checkpoint-stage or independent NDU evidence.
The previously frozen 8-arm complete experiment remains available and
unchanged as the stricter separate analysis.

Optional PyTorch end-to-end test_hf_joint_end_to_end.py exercises a real
small learned Head through the complete runner with a synthetic/mocked
Transformer and source-grouped fixture; no real 435M weights are claimed.
CI without optional PyTorch skips that test and does not certify model
inference.


### Exact per-arm evidence bundle: no unchecked manual JSON merge

decision_arm_bundle.py now joins actual separately executed model-arm predictions
and their existing .run.json sidecars before calling decision_421m.py.
It extends the same Experiment A qualification directory and does not
introduce any runtime or learning owner.

The source JSON descriptor contains a single arms array; each entry has
arm (for example, deberta_v3_large:equal_budget), prediction_path, and
run_manifest_path relative to an approved evidence-root directory.
The current manifest must include output_predictions_sha256, exact
checkpoint/data/weights SHA, matching train groups, runtime, seed,
optimizer/steps/parameters and no production authorization.
Each JSONL record is checked against the frozen dataset's exact scored
sample IDs and ordered-logit width; duplicate keys, gold labels,
unexpected arms, missing samples, altered bytes, symlink escapes,
unbounded files and source revision mismatches are denied.

    python3 qualification/stem-cell-v1/decision_arm_bundle.py \
      --plan /scratch/decision-frozen-plan.json \
      --evidence-root /approved/actual-model-runs \
      --descriptor /approved/actual-four-arm-file-manifest.json \
      --comparison-scope equal_budget \
      --output-prefix /scratch/review-input

This creates append-only review-input.runs.json,
review-input.predictions.jsonl and review-input.bundle.json. Feed the first
two to decision_421m.py evaluate with the **same scope**.
A file SHA binds bytes, not an independent execution or NDU signature;
therefore neither the assembler nor subsequent offline scorecard is a
production acceptance receipt. A small all-synthetic no-model unit suite
tests digest tampering, duplicate arms, gold-label leakage and path escapes.


### Exact input fingerprint admission in Experiment A

Each Decision arm now carries a mandatory label-free input_digest. It is
the SHA-256 of canonical JSON over sample_id, source_group, episode_id,
split, scope, language, state, question, the complete *ordered* options,
and event_time. Gold labels, rewards and observed outcomes are excluded.
The local HF runner computes this digest from the exact consumed data;
decision_arm_bundle.py and decision_421m.py independently recompute it
from the frozen dataset. Missing digests, wrong options order, or another
source episode fail closed even if the supplied prediction file and
.run.json sidecar have been rehashed to match each other.

The fingerprint prevents accidental source/option mispairing but does
not cryptographically prove that external model code truly encoded the
claimed input. Real model runner provenance, authenticated owner receipts,
independent evaluator/NDU and production final-use are still mandatory.


### Mandatory DeBERTa-v3-large weight-format admission (L2 blocker)

The upstream Microsoft deberta-v3-large model repository currently contains
pytorch_model.bin, not a model.safetensors checkpoint. The L2 HF runner
intentionally refuses unsafe automatic PyTorch pickle fallback. Real
DeBERTa-v3-large experiments therefore require an **independently reviewed,
isolated, self-contained safetensors conversion** of those upstream weights
with its own model/source lineage, conversion tool/command/version/SBOM,
operator review, immutable 40-hex upstream Git revision, and a new
byte-level local tree digest. An unreviewed .bin file is not valid
execution input, even if its checksum was frozen. Merely adding an empty
file with a .safetensors suffix (as some model-free tests deliberately
do) is NOT a real conversion and AutoModel will reject it.

ModernBERT-large publishes safetensors, but still requires audited local
files and exact revision/dataset approval. No dynamic network downloads,
remote code, unknown-pickle unpickling or automatic conversion are
permitted in this shadow runner. This explicit format gate is separate
from model accuracy, NDU or production authorization.


**Original Laya provenance correction:** the 421M original weight artifact
is published as convaiinnovations/laya on Hugging Face; NandhaKishorM/laya
is its separate software repository. Experiment A uses the former as the
pinned checkpoint source and requires independent review of the latter as
the executable adapter. Neither weight SHA nor Git commit alone attests
which decision Python package actually ran. Do not conflate them.


### Pretrained safetensors must load completely, not merely exist

The local HF Decision Head runner now requests output_loading_info from the
actual Transformers AutoModel loader. It rejects missing, unexpected, mismatched
pretrained tensor keys, loader error messages, or a backend that fails to provide
a complete report. A converted safetensors file with omitted layers is NOT a
qualifying pretrained checkpoint even if its SHA matches an approved tree.
The run manifest records verified_encoder_loading, and decision_arm_bundle.py
requires the exact complete-load receipt and matching pinned local runner-source
SHA for both DeBERTa-v3-large and ModernBERT-large equal-budget arms.

To use a model with an intentional architecture-specific extra head, the
independent operator must first prepare/review a base-model-only safetensors
artifact and pin its content. Do not add an ignore list of missing or
unexpected tensor keys to make an incomplete checkpoint look green. This
loading receipt is local technical evidence, NOT cryptographic attestation
of the operator, upstream revision or NDU outcomes.


### L2 safetensors actual tensor-materialization guard

The HF AutoModel output_loading_info report is necessary, but in some
Transformers versions/architecture profiles a clean loading-info list alone
does not prove that the checkpoint tensors were restored. The real local
DeBERTa/ModernBERT runner therefore additionally traverses every registered
safetensors shard with safetensors.safe_open and checks that its entire key
inventory exactly matches model.state_dict(), including tensor shapes and
actual values. Float32 source weights are compared after converting to the
selected runtime dtype (fp32/bf16/fp16). Any missing/extra keys, duplicate
shard entries, meta tensors, wrong shapes or differing loaded values block
the research trial. This is bounded to 64 shards and 2.5 billion source
weight bytes and records tensor_count, tensor_elements and shard count.
The arm evidence bundler requires the corresponding full-materialization
receipt in addition to the complete loading-info and source-code SHA.

This strict base-model-only convention can reject upstream artifacts
with model-specific name prefixes, tied-parameter aliases or extra
pretraining heads. They require a separately audited, content-pinned
canonical base conversion rather than weakening the gate. Model-free
mocks test both matching and wrong-in-memory tensor values, but do not
prove real 435M DeBERTa execution or external NDU benefits.


### Real HF physical microbatch, isolated by Scope (research only)

The existing offline local-weight `hf_joint_decision_runner.py` now accepts
`--encoder-microbatch-size 1..32` (default 1). Batches of 2..32 adjacent
joint decision inputs from the SAME Scope are tokenized without truncation,
padded explicitly, and run through ONE physically shared
`AutoModel(...).last_hidden_state` forward call. No input may enter a
different Scope's microbatch; all full state, question and ordered options
remain represented. The masked per-case feature must numerically match a
single-case execution. The output receipt records actual physical Encoder
forward call counts and observed physical batch widths, and conservatively
charges each case the **entire measured batch time**. It never divides a
shared duration by batch size to fabricate an apparent p99 improvement.

The contract tests include a real CPU torch multi-case forward with padded
lengths, cross-Scope rejection, over-budget token rejection and a complete
24-case small fake-encoder/real learned-Head path with exactly six
four-request forwards. The synthetic fixture does not load actual
DeBERTa/ModernBERT weights, and even the genuine HF offline mode remains
**not** the Rust Worker/Agentd native backend or target-host 4096-Cell
performance proof. Physical pooling is limited to an audited locally
loaded checkpoint; independent NDU/CAS/final-use remain blocking.


**Comparison fairness:** before running any four-model equal-budget trial
with `--encoder-microbatch-size > 1`, first freeze the Experiment A plan
with the **same** `decision_421m.py plan --encoder-microbatch-size N`.
Both the direct evaluator and the SHA-bound arm bundle reject execution
receipts whose physical Encoder batch ceiling is different from the
frozen plan, including the original Laya controls. A missing batch
declaration means legacy single-input execution (N=1); it cannot be used
to claim an N>1 trial. This is a budget/trace-consistency check,
not independent hardware attestation or permission to compare actual
inference p99 from different hardware.


## Cache admission accounting: boxed Python objects (2026-10-12)

The shadow `SharedStemEngine` and `ProjectedStemEngine` retain Python tuples
of boxed f32 and Q24 numbers, rather than contiguous 4-byte / 8-byte native
tensors. Charging only `width × element_bytes` substantially undercounts
resident heap use and invalidates 4096-Cell cache-capacity comparisons. Both
bounded LRUs now charge a conservative **Python-object resident estimate**
including key fields, stored metadata, tuple storage, boxed elements and an
OrderedDict/allocator margin; they refuse oversize inserts and evict before
admission. This may reduce cache hits when the actual configured budget is
small, as it should. The original float32/Q24 canonical feature hashes are
unchanged.

`cache_bytes` and `projection_cache_bytes` therefore describe the
**accounted retained shadow cache estimate**, not packed tensor bytes, process
RSS, CUDA allocations, temporary Encoder/Head activations or WAL usage.
True host CPU/RSS/GPU and p95/p99 measurements still require a target-worker
run. Tests check that a raw 768-float `3072`-byte budget cannot silently
retain the boxed vector and that a `16`-byte raw Q24 budget cannot retain a
boxed projected feature. Mock 4096-Cell reuse remains L1-only, not throughput
or production RAM evidence.

