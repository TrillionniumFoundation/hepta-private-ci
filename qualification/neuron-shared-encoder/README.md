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