# Stem Encoder × Cell Head qualification (shadow-only)

This **read-only research package** implements an initial, reproducible entry point for the three Stem/Cell studies. It does **not** install models, issue capability tokens, invoke the production Neuron owner, write canonical artifacts, or promote decisions. Its standard-library tests are **L1 instrumentation tests**, not evidence that a real 421M model, NDU evaluator, hardware batch, lifelong learner, or Rust backend was exercised.

Canonical governance: [`docs/learning/EXPERIMENTS.json`](../../docs/learning/EXPERIMENTS.json), [`NEURAL_BIOMIMICRY_SPEC.md`](../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md). Existing parameter composition is marked `design_only_not_wire_schema` in `docs/learning/ARTIFACTS.json`. Preserve owner boundaries: model execution, independent outcome evaluation, selection, and effectful release are separate services.

## Experiment 1: fixed-model, fixed-budget Stem selection

The preregistered `protocol.json` specifies four Stem candidates (mmBERT-small 140M, ModernBERT-base 149M, Jina v2 zh 161M, BGE-small-zh 24M), two external full-decision teacher baselines (Laya 421M, Laya Multilingual 322M), Chinese/English/cross-language slices, shot curves, and OOD. Model parameter counts are approximate model-card values. Check upstream model identities and licenses against **pinned** snapshots before starting. The Laya teachers are **external baselines**: no generic HF adapter is assumed for them.

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

The trace parser rejects incomplete, duplicate, stale-generation, cross-scope, orphan and falsely counted batches. The native trace must record `enqueued_us`, `start_us` and `end_us` using **one actual worker monotonic clock**; the generated `submitted_at_us` values are only workload scheduling offsets, not real timestamps. It reports cold-encoder and cache-hit-Head **end-to-end** p50/p95/p99 plus execution p99 and queue p99 separately, request-attributed CPU (not an independently measured process CPU total), RSS, WAL fsync and recovery checks. Such JSON remains an **unverified offline trace**: it cannot authenticate the owner or attest Rust production execution. Longitudinal retention and negative transfer need additional real, independently observed future-window receipts; they are left `null` instead of invented.

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
from all four approved *local* encoder snapshots. An operator-supplied JSON
maps each of the four model keys to `source`, an immutable 40-hex
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

The full preregistered nonzero-shot Cartesian grid is **1,536 arms** (4
encoders × 4 representations × 6 Heads × 4 budgets × 4 positive shot counts),
not 1,536 demonstrated successful trainings. Unsupported Head/budget combinations
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

The dedicated CI lane runs Rust formatting/compile/test and Python L1 tests.
None of these tests load mmBERT weights or issue production selection authority.
