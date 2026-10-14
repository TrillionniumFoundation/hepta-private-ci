# Hepta Neuron Shared Encoder Qualification V2

**Shadow-only experiment runner; cannot authorize production.** A local CPU smoke passing does not establish Laya accuracy, shared-Encoder reuse equivalence, future NDU gains, worker throughput, journal durability, or a production release.

This project continues the earlier 24-head/36-load experiment. It adds exact input identities, grouped/time-disjoint evaluation, real model adapters, separate original Laya decision-head baseline, batched gated-Cell tensor execution and a fail-closed gate. It is an isolated qualification harness, **not** a new production `hepta-neuron` runtime owner or an actual Hepta worker/ledger integration.

## Dependencies

Python 3.10+ (verified locally with 3.13), PyTorch and pytest. `laya` with its compatible `transformers` stack is additionally required for genuine Laya trials; `transformers` is needed for the standalone ModernBERT checkpoint. Never install or download a model implicitly in a test run. Benchmark results depend on driver, dtype, actual hardware, input length and batch policy.

## Local reproducible smoke

Run from this directory:

```bash
python -m pytest -q tests/test_qualification.py
python -m neuron_shared_encoder.experiment synth-data --allow-synthetic --output smoke_dataset.jsonl --data-count 32
python -m neuron_shared_encoder.experiment validate --dataset smoke_dataset.jsonl --output validated.json
python -m neuron_shared_encoder.experiment head --allow-synthetic --dataset smoke_dataset.jsonl --output head_results.json --steps 16
python -m neuron_shared_encoder.experiment stress --allow-synthetic --output stress_results.json --rounds 2
python -m neuron_shared_encoder.experiment gate --output gate.json
```

`head`: Linear, FiLM, Rank-8/16, MLP, SwiGLU × 2K/16K/64K/262K *upper parameter budgets*. Actual trainable counts and actual optimizer-state bytes are reported; 2K Linear vs 262K MLP are **not equal parameter count**. Shared Encoder forward is frozen and excluded from per-Cell trainable parameters, but must be measured as an amortized system cost in a full run. Train, validation, OOD and future windows are disjoint at `(principal,source_group)` level; future begins after the train and validation timestamps. The OOD AUROC is `1-max_softmax` (a detection diagnostic). An untrained Head is not the persisted Hepta no-change baseline.

`stress`: exercises actual CPU PyTorch batched projections and Cell-conditioned gates at 64/256/1024/4096 cells, 10/50/100% active and same/partial/distinct inputs. The frozen projection is synthetic and does not represent 395M Laya. Batch p95/p99 are **batch service times**, not per-request SLOs. Python feature materialization costs are included, but worker scheduling, GPU memory, CAS checkpoints, WAL, crash recovery and final-use authorization are **not** included. Cache rechecks are currently caller-supplied `admitted=True`, which is not a real verification capability. The prototype cache MUST NOT be transplanted into production unchanged.

## Real pretrained offline trial (when provisioned)

Provide a local already-downloaded **pinned** checkpoint including `model.safetensors`, tokenizer and model configuration; record the SHA-256 of the exact model weights, the **complete checkpoint bundle** and the dataset bytes. Stage the bundle in a private, read-only directory with real files, not Hugging Face cache symlinks. This qualification hashes every file and refuses symlinks or missing local encoder config; it checks the same bundle before loading and after inference. Operator-computed hashes alone do **not** constitute an independent signature or trusted source attestation; review and pin the manifest separately. The real loader fails closed if weights are missing or modified. Running with a synthetic encoder is explicitly prohibited for `representation`:

```bash
MODEL=/absolute/path/to/pinned/laya
DATA=/absolute/path/to/approved-labelled-splits.jsonl
SHA_MODEL=$(sha256sum "$MODEL/model.safetensors" | cut -d' ' -f1)
SHA_BUNDLE=$(python -c 'import sys; from neuron_shared_encoder.bundle import checkpoint_bundle_sha256; print(checkpoint_bundle_sha256(sys.argv[1], "laya-joint"))' "$MODEL")
SHA_DATA=$(sha256sum "$DATA" | cut -d' ' -f1)
python -m neuron_shared_encoder.experiment representation \
  --encoder laya-joint --checkpoint-dir "$MODEL" \
  --weights-sha256 "$SHA_MODEL" --checkpoint-bundle-sha256 "$SHA_BUNDLE" \
  --dataset "$DATA" --dataset-sha256 "$SHA_DATA" --output laya_real_shadow.json
```

`laya-joint` builds question+option marker sequences via Laya's own encoding functions and measures the original Laya model's true `system_one` policy (when that pinned package/checkpoint is locally installed). The lightweight head receives **lossy pooled CLS + option-marker statistics**, intentionally quantifying the representation loss; this does not claim Laya functional equivalence. Checkpoints using parallel option attention are explicitly rejected pending a compatible masked Encoder path. The exact installed Laya package source identity also needs independent attestation.

For a distinct ModernBERT-base checkpoint, use `--encoder modernbert-joint` and a local Transformers-compatible checkpoint and tokenizer. It uses an explicit, **different** joint-string format, so it is not a bit-level Laya tokenizer/control. Compare predictions on the same frozen records/splits and normalized prediction semantics. Higher-level Organ Expert Bank parameter totals are reported separately from per-Cell parameters.

## Expected real dataset JSONL

Each line must include these fields:

```json
{"row_id":"r1", "source_group":"episode:123", "event_time":"2026-09-01T00:00:00+00:00", "split":"train", "principal":"p1", "organ_id":"o1", "cell_id":"c1", "state":"approved text", "question":"route?", "options":["A","B","C"], "label":1}
```

A complete file must have `train`, `validation`, `future`, `ood`, with a stable number/order of choices (2..16). Labels are integer option positions; no source group may appear in two splits and the future times must follow all train and validation timestamps. Only one scoped Cell is admitted per head trial, avoiding accidental cross-principal training. Sensitive data-use policy and consent are **not** established by JSONL validation and must be granted by the existing Memory/Replay owner outside this harness.

## Promotion gate and native integration blockers

Even if an evidence JSON contains every named field, `gate` remains **BLOCKED**: it does not verify issuer identity, independent signatures, revoke status, NDU benefit, final-use tokens, artifact CAS, state migrations or CNS route cutover. An independent Hepta Evaluator, Selector and Executor must evaluate and approve a signed candidate. A real no-change baseline must be frozen for each Cell; testing untrained heads is insufficient.

Native integration still required after successful real model experiments:

1. `hepta-infer-worker-host` driver must physically separate shared Encoder ownership, organ adapters and Cell heads and execute real batched requests. This Python project does **not** patch those Rust owners.
2. Replace the prototype feature cache's caller-supplied bool with exact final-use and live source entitlement checks. Bind Encoder, tokenizer, preprocessing, input/option layout, principal/purpose, generation, authority epoch and revocation; invalidate on reload or revoke.
3. Measure inference **per request and per batch** on target hosts, independent Head optimizer footprint, GPU peak, p95/p99, checkpoint/WAL amplification, stale-read denial and restart recovery.
4. Train and evaluate full Laya, pooled Laya Head, ModernBERT-base, Organ Expert Bank on the same approved, grouped future-window protocol. Add independent NDU and negative-transfer evidence; only then propose promotion.

_No change in this harness alters any Hepta production contracts, grants or model versions._

## E1–E5 strict research qualification (V3, no deployment)

The independently versioned shadow module is `neuron_shared_encoder.validation_v3`.
It does not replace the immutable Rust inference owner, sign model receipts, apply
NDU decisions, change CNS routes or enable model final-use. The existing native
`GatedHeadCpuDriverV2` is a fixed Q24 elementwise multiplier; V3 introduces
`static_gate` and a genuinely input-dependent `dynamic_gate` **in PyTorch
research only**, not in the Rust production worker.

### E1 — same-task, same-budget real Encoder matrix

Require one SHA-256-pinned dataset/split manifest and persisted no-change
baseline, a common train seed, steps, optimizer, batch and learning rate, plus
pinned weight/bundle/tokenizer SHA-256 for all four candidates:
`laya-joint`, `mmbert-joint` (140M candidate), `granite-joint` (97M),
`modernbert-joint` (149M candidate). The E1 contract scanner accepts a
**complete schema** as `SCHEMA_COMPLETE_UNVERIFIED`, never `PASSED`.
Separate offline `representation` runs and operator-verified artifact/dataset
receipts are still required for any scientific comparison; genuine Laya
`system_one` requires its original model/checkpoint and cannot be replaced
by pooled CLS logits. Generic Hugging Face mean pooling for
mmBERT/Granite/ModernBERT is an explicitly separate control; it does not
assert equivalence to an official model-specific pooling or teacher policy.
No implicit download, remote-code trust, fake checkpoint or synthetic
Encoder is allowed for E1 real claims.

To run all four **genuine** offline E1 model candidates after every pinned
checkpoint is available, supply a JSON matrix with each Encoder's
`local_path`, `weights_sha256`, `tokenizer_sha256`, `bundle_sha256`,
and the common dataset/split/no-change/training pins. Then use:

```bash
PLAN_SHA="$(sha256sum e1_matrix.json | cut -d' ' -f1)"
DATA_SHA="$(sha256sum approved.jsonl | cut -d' ' -f1)"
python -m neuron_shared_encoder.validation_v3 e1-run --input-json e1_matrix.json --input-sha256 "$PLAN_SHA" --dataset approved.jsonl --dataset-sha256 "$DATA_SHA" --output e1_real_shadow.json --dimension 128
```

The runner preflights all four local paths and tokenizer bytes, verifies
the bundled/weight hashes via the existing offline adapter and never substitutes
a synthetic checkpoint. A missing model blocks the entire matrix. It trains
the same Head candidates on each frozen Encoder output, with train-only
normalization, and separately records the original full Laya policy.
The model bundle pin and local results are not independent operator signatures
or proof that an external no-change baseline was genuinely frozen.

### E2 — capacity and fixed-Gate folding

`e2-heads` trains Linear, static Gate, input-conditional sigmoid/SiLU Gate,
FiLM, rank-8/16, MLP and SwiGLU using the same frozen features, source splits,
optimizer and update budget. Budgets 2K, 16K, 64K, 262K are *upper bounds*;
actual parameters and optimizer bytes are recorded. After training, the
static Gate is folded to a Linear weight matrix and its maximum absolute
logit difference is recorded. This proves mathematical redundancy to
floating-point tolerance, not bitwise Q24 equivalence. Q24 rounding and
hardware parity require independent native tests.

### E3 — full-joint input versus public-input / Cell-state fusion

`e3-reuse` collects both `encoder_forward_invocations` and
`encoder_forward_rows` from actual calls to the adapter; counts are not
inferred from the logical Cell count. The public-input key excludes Cell
state but includes principal, purpose, generation, authority epoch,
Encoder/tokenizer/normalizer digests, evaluation split, **and source-group
partition by default**. Identical public questions across independent
source groups are not automatically entitled to share an Encoder result.
The opt-in `research_synthetic_cross_source=True` ablation deliberately
drops this partition only in the non-authorizing synthetic-hash CLI path,
and reports `SYNTHETIC_UNVERIFIED_UPPER_BOUND`. A real model without
independently verified cross-source entitlement conservatively retains
source-group isolation, even if this eliminates all such reuse. It cannot
bypass a real source-entitlement or signed final-use check. The local
Cell-state branch in this V3 control uses a **synthetic hash**, explicitly
labelled `SYNTHETIC_HASH_NOT_DEPLOYABLE`. Both variants undergo equal-budget
linear/dynamic Head training and future-set scoring, but even when the
Encoder itself is real, this hybrid is not a qualified production
state-fusion model. Replace the state hash with a pinned, trained and
independently validated local adapter before claiming E3 quality parity.

### E4 — frozen no-change versus candidate; never promotion

`e4-future` requires a *real, externally prepared* frozen no-change
probability snapshot and a distinct candidate snapshot, each with an
operator-supplied exact file SHA-256. They must contain the ordered
`row_ids`, probabilities for all dataset rows, `dataset_sha256`,
`cell_scope` [principal, organ_id, cell_id], `source_commit`,
`artifact_digest` and `role` (`frozen_no_change` or `candidate`).
It fails closed on scope/dataset/row/order mismatch, invalid probabilities
or identical artifacts. It reports grouped future-window bootstrap 95%
intervals for Brier improvement, 15-bin ECE, NLL, OOD detection AUROC and
future source-group negative-transfer fraction. The optional positive
*retrospective statistical signal* requires at least 30 future groups,
positive lower CI and zero materially degraded groups. It is reported as
`RETROSPECTIVE_POSITIVE_UNVERIFIED`, **not** an NDU decision or a
causal learning claim. V3 now inspects optional per-future-row
`prediction_committed_at_by_row` maps in both snapshots and checks each
declared prediction timestamp precedes the outcome's timezone-aware
`event_time`. Missing, partial, naive or late timestamps are reported
as `MISSING_OR_INVALID`. Even complete ordered claims remain
`TEMPORAL_ORDER_CONSISTENT_UNVERIFIED`; untrusted JSON timestamps and
SHA-256 pins cannot prove independent precommit or absence of
future-label leakage. `causal_learning_verified` and final-use stay false.
The independent Evaluator must still verify actual precommitted predictions,
causal improvement and receipt authenticity; Selector and Executor remain
separate owners.

### E5 — complete host telemetry schema, no fabricated measurements

`e5-host` requires one record for each of 64 / 256 / 1,024 / 4,096
Cells, with exact host/run/commit, encoder physical call/row/input
counts, requests, throughput, CPU, peak RSS, GPU peak if applicable,
per-request and per-batch p95/p99, WAL bytes, crash recovery, lost-replay
counts, CAS/signature/CNS latency. A complete operator-submitted JSON
is `COMPLETE_UNVERIFIED` until independent signed source, target-host
measurements, generation-fence tests and operator authorization are proven.
Synthetic `stress` does not fill in missing worker/host fields.

### Example isolated smoke

```bash
cd qualification/neuron-shared-encoder
python -m pytest -q tests/
python -m neuron_shared_encoder.experiment synth-data --allow-synthetic --output smoke_dataset.jsonl --data-count 32
DATA_SHA="$(sha256sum smoke_dataset.jsonl | cut -d' ' -f1)"
python -m neuron_shared_encoder.validation_v3 e2-heads --allow-synthetic --dataset smoke_dataset.jsonl --dataset-sha256 "$DATA_SHA" --output e2.json --steps 2 --budgets 2048 16384
python -m neuron_shared_encoder.validation_v3 e3-reuse --allow-synthetic --dataset smoke_dataset.jsonl --dataset-sha256 "$DATA_SHA" --output e3.json --steps 2 --budgets 2048 16384
```

Read the generated JSON `evidence_class`, `production_admission`, and
unverified fields before interpreting any values. CI intentionally exercises
missing real Encoder and target-host receipts and requires both to remain
blocked. The E4 frozen baseline is **not generated from random/untrained
Heads**, and all V3 claims are research/shadow only.


### Exact-head CI and fair-comparison acceptance ledger (2026-10-14)

The 2026-10-14 source HEAD `b7cdeba1db215ee30418b2269ddd147dee064410`
has a completed, successful shadow workflow
[38513414552](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38513414552).
That result covers isolated Python research checks, **not** a production
release. Architecture source-head and base-merge checks succeeded but
their aggregate required check must independently complete. Whole-tree
[blocking-ci 38513414635](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38513414635)
is not green: actual job logs show `cargo-deny` reporting Matrix SDK
0.18 dependency advisories and unmaintained `unsafe-libyaml`;
`repo-checks/build-test` failed at `pnpm run format:check`; macOS
Bazel Clippy also failed. None can be overridden, ignored or relabeled
as a successful scoped E1–E5 receipt.

**Fairness requirements before comparing E2 as scientific evidence:**
- The 2K / 16K / 64K / 262K values are **ceilings**, not equal parameter
  counts. Compare each candidate's *actual* trainable parameters, peak
  optimizer memory, wall-clock training time and measured inference cost.
- Within each task and Encoder, hold frozen feature bytes, source splits,
  seed set, update steps, batch schedule, tuning/search opportunity and
  evaluation window fixed. Run several seeds and paired group-level
  intervals; never infer a winner from a single two-step smoke.
- Compare static Gate to its **post-training** folded Linear equivalent
  at identical frozen weights before any efficiency claim; independently
  compare ordinary Linear trained from scratch at a matched actual
  parameter budget. Report the fixed-gate parameter overhead separately.
- Gate on future Brier/NLL, task utility, OOD rejection, calibration,
  negative transfer and cost rather than selecting by accuracy alone.
  The research runner cannot act as the independent NDU Evaluator.

**E3 physical reuse requirements:** Record logical requests, admitted
distinct full-input digests, encoder invocations, forwarded rows,
tokenized lengths, cache hits/misses, feature materialization bytes,
queue latency and end-to-end p95/p99 on the same hardware. Deduplicate
only after live source entitlement and final-use checks. Do not equate
shared weights, number of logical Cells, or an instrumented mock
callback with a physically shared Transformer forward.

**Production-blocking evidence:** genuine pinned four-Encoder weights
and approved data; frozen no-change predictions collected before
future labels; independent NDU Evaluator/Selector; real signed
Artifact CAS + Final-use + generation fences; true physical batch;
64/256/1024/4096 Cell target-host CPU/RSS/GPU/WAL/restart receipts.
Keep this PR Draft/shadow until every independent owner gate passes.

### E2-V4 — matched actual parameter-count nonlinear ablation

The isolated `strict_e2.py` runner compares `dynamic_gate` (sigmoid
input-dependent gate, SiLU drive) with `swiglu`. They share the exact same
linear tensor geometry, actual trainable parameter count, tensor
initialization, CPU sample order and train-only feature normalization.
The upper budgets 2K/16K/64K/262K remain ceilings, **not** arbitrary claims
that different Head architectures have identical parameter counts.

From this qualification directory after generating a synthetic dataset
with `experiment synth-data`:

```bash
DATA_SHA="$(sha256sum smoke_dataset.jsonl | cut -d' ' -f1)"
python -m neuron_shared_encoder.strict_e2 \
  --allow-synthetic --dataset smoke_dataset.jsonl \
  --dataset-sha256 "$DATA_SHA" --output e2_equal_shadow.json \
  --dimension 128 --budget 16384 --steps 32 --seeds 11 29 47
python -m pytest -q tests/test_strict_e2.py
```

Actual offline Encoder runs require local, complete pinned checkpoint files
and exact `--weights-sha256` plus `--bundle-sha256`; they do not fetch
models from the network or fall back to synthetic features. A frozen
`frozen_projection` is deterministic but **random and untrained** whenever
the real Encoder hidden width differs from the requested Head width.
Such an experiment must not be read as quality-equivalent to a learned
projection or to full Laya.

The **descriptive** comparison uses paired validation Brier differences
across source groups and training seeds. It returns INCONCLUSIVE if the
95% grouped-and-seed Bootstrap interval crosses zero, or when fewer
than eight independent validation groups or three seeds are present.
This is an exploratory interval, not confirmatory inference or NDU.
Future data are only reported post hoc and never used to choose the
descriptive winner. Tests check that changing future labels leaves the
validation-only judgment and training sample schedule unchanged.
The JSON has `production_admission=BLOCKED`, `ndu_verified=false` and
`selection_authorized=false`; no signature, causal prequential commit,
Final-use or live Encoder physical-call proof is conferred by its hashes.

### Fixed Gate folding: real algebra vs Rust Q24 rounding

For the existing Rust reference driver, folding a fixed gate is exact in
real-valued algebra but **not necessarily bit-identical** in Q24.
The original computes `round(weight * round(feature * gate))`; a
folded implementation computes `round(round(weight * gate) * feature)`.
Their rounding orders differ. The non-authorizing regression
`q24_fold_ablation.py` duplicates the published Rust
round-to-nearest/ties-to-even convention and proves one deterministic
counterexample: original -2,980,555 versus folded -2,980,556 Q24 units
(one least-significant bit difference).

`python -m pytest -q tests/test_q24_fold_ablation.py` verifies identity
gates, signed ties-to-even, type/dimension/range fail-closed behavior and
the explicit one-LSB witness. A Python arithmetic model cannot replace
an actual native Rust test against the real Worker, signed artifacts,
generation fences or a target-host quantized end-to-end run.

### E1/E2/E3 module-forward accounting — V6 research diagnostic

`encoder_meter.py` scopes synchronous PyTorch pre/post hooks around the
*actual top-level Encoder module*, separately from the experimental adapter
invocation counter. E1, offline E2 and real E3 record completed forward calls,
attempts, forwarded rows and **padded token slots** (shape-only, avoiding
GPU synchronizations). E3 records this independently for joint input and
public-input runs. A row-count or forward-count discrepancy fails closed.
Synthetic-hash trials explicitly return a null model-forward observation.

This is NOT a GPU kernel trace, active token count, throughput/RSS receipt,
signature, source entitlement, true Rust Worker sharing or independent
NDU evidence. The observer does not keep raw input or attention masks;
it runs only in synchronous, offline qualification. Model calls that bypass
the top-level module's `__call__` and asynchronous accelerator failures are
outside this observer and require a separately verified backend profiler.
All outputs retain `production_admission=BLOCKED`.

Run isolated regression tests:

```bash
python -m pytest -q tests/test_encoder_meter.py tests/test_strict_e2.py
```

A synthetic Torch test deliberately performs multiple model forwards within
one adapter call to ensure the reported counters cannot be conflated. Another
injects an exception after a first successful forward and verifies the
attempt/completion mismatch plus hook cleanup. A CPU floating-point
reproducibility comparison tolerates numerical error up to 1e-6 while
preserving exact model count, optimizer bytes and sample-draw identities.

## E4 prequential hash-chain shadow audit

The optional `e4-future --prequential-event-log ... --prequential-event-log-sha256 ...`
mode checks a *separately supplied, SHA256-pinned* JSON event log before
reporting future-window Brier statistics. It does not replace the original
frozen no-change and candidate probability snapshots or existing safety gates.

The log has `dataset_sha256`, `cell_scope = [principal, organ_id, cell_id]`,
and `events`. Each canonical event contains its zero-indexed `seq`,
`previous_digest` (64 zeros for genesis), `event_digest`,
`dataset_sha256`, `cell_scope`, `row_id`, `source_group`,
`input_digest` (pre-outcome row question/options/state fingerprint),
`generation`, `authority_epoch`, `recorded_at` (timezone-aware) and
`kind`. Forecast events additionally contain `role` (either
`frozen_no_change` or `candidate`), exact `artifact_digest`, and the
matching probability row. Outcome events instead contain the observed integer
`label`. The hash is SHA256 of the fixed domain separator followed by
canonical JSON of the event excluding its own `event_digest`; see
`neuron_shared_encoder.prequential_receipts.event_digest` for the exact
algorithm and `input_digest` for the full pre-outcome input identity.

The audit requires two distinct forecasts for each future row *before* its
outcome, checks source/Cell/model/epoch and row-specific option semantics,
requires nondecreasing claimed append timestamps, and rejects digest-chain
tampering or forecast/snapshot mismatches. Passing returns only
`HASH_CHAIN_CONSISTENT_UNVERIFIED`: anyone can rebuild the unsigned chain,
forge timestamps, or backfill after seeing future labels. No causal learning,
NDU verification, trusted witness, production Final-use or Cell promotion is
ever granted. The true independent Evaluator must consume owner-signed
pre-outcome writes and verified later outcomes.
