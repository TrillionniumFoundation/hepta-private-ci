# Neuron Stem Qualification — shadow only

This directory contains executable research tools for three planned comparisons:
(1) four frozen encoder backbones, (2) four feature representations and six
low-parameter Head architectures, and (3) 64/256/1024/4096-cell scaling.

No script here can select production artifacts. The tests run without network
access or downloaded pretrained weights, and do not establish model accuracy.

## Data

Input JSONL rows must contain case_id, group_id, scope_id, task_id, split,
language, state, question, options, label and event_time. The required splits
are train, calibration, test, future, ood. Group and exact-content leakage are
rejected, and future events must follow the earlier windows.

## Commands

First generate the plan and audit the dataset:

    python3 qualification/neuron-stem/qualified_eval.py matrix --models qualification/neuron-stem/models.json --out matrix.json
    python3 qualification/neuron-stem/qualified_eval.py audit --dataset TASK.jsonl --out audit.json

Train one task-specific Head from a frozen, SHA-pinned real HF Encoder:

    python3 qualification/neuron-stem/hf_trial.py --model mmbert-small --revision FULL40HEXSHA --task-id decision-v1 --dataset TASK.jsonl --mode joint --head film --budget 2048 --shots 32 --steps 100 --output candidate.jsonl

Assess predictions against independently collected no-change predictions:

    python3 qualification/neuron-stem/qualified_eval.py score --dataset TASK.jsonl --baseline no-change.jsonl --candidate candidate.jsonl --out comparison.json

Probe an actual HF inference backend (not the Hepta production worker):

    python3 qualification/neuron-stem/scale_probe.py --model mmbert-small --revision FULL40HEXSHA --dataset TASK.jsonl --mode joint --cells 1024 --active-fraction 0.25 --repeat-fraction 0.5 --similarity medium --requests 256 --batch-size 8 --db /tmp/stem-scale.db --output /tmp/stem-scale.jsonl

## Evidence limitations

Production teacher predictions for Laya 421M / Laya Multilingual 322M,
task outcome evidence, signed NDU receipts and data permissions must be
provided independently. Jina's optional remote model code requires an
explicit, pinned, reviewed opt-in. Encoder revisions must be full commit SHAs.

The scale probe genuinely executes batched frozen Encoder forwards and
independent Cell Heads, and measures SQLite WAL clean-reopen consistency.
It does not measure production worker queues or verified crash recovery.
A first warm forward is not a cold-load observation; model load time is
reported separately. CPU/RSS data are valid only on the measured host.

Never treat reported utility IDs or measurement labels as cryptographically
verified receipts. All results remain shadow-only. Independent Evaluator,
Selector and Executor promotion boundaries remain unchanged.

Run offline tests:

    PYTHONPATH=qualification/neuron-stem python3 -m unittest discover -s qualification/neuron-stem -p 'test_*.py' -v


## Jina v5: shadow-only follow-on (stacked qualification)

The Jina v5 Text Nano/Small and Omni Nano/Small profiles are registered under
`models.json:jina_v5_models`; they are **not** fed to the older
`hf_trial.py` AutoModel/mean-pooling path, which would produce incompatible
task embeddings. Instead, `jina_v5.py` uses Jina's official, task-adapter-aware
`SentenceTransformer.encode_query/encode_document` methods, verifies the full
768/1024-dimensional output, and L2-normalizes supported Matryoshka slices.
It never silently falls back to pooled raw hidden states or to an unpinned model.
Everything requires a full 40-character Hugging Face revision SHA.

All model weights and external model code must be approved and staged on the
target host. By default no download is allowed, and executing remote model
code requires the explicit `--allow-pinned-remote-code` opt-in. Do not review
`main` once and assume a later revision is the same code. The project is
non-commercial, but Jina weights retain their independent CC BY-NC 4.0 notice.

### Genuine learned-Head trial

Example with **preexisting, licensed task JSONL**, a reviewed revision, and
installed dependencies (`torch`, `transformers`, `peft`,
`sentence-transformers`, `psutil`, and Jina's pinned model dependencies):

```sh
python3 qualification/neuron-stem/jina_v5_trial.py \
  --model jina-v5-text-nano --revision FULL40CHARMODELCOMMITSHA \
  --task-id decision-v1 --dataset /approved/decision.jsonl \
  --principal-id local-researcher --head linear --budget 16384 \
  --dimension 256 --representation joint --shots 32 --steps 100 \
  --allow-pinned-remote-code --output /evidence/nano-predictions.jsonl
```

The trial trains **only the Cell Head**: shared trainable projection count = 0
because native Jina Matryoshka truncation provides 256/512-dimensional features.
This avoids hiding an independently learned per-Cell projection's cost. A
separate frozen-Head/no-change prediction file MUST be provided before quality
claims; a new Head trained on test/future labels is invalid. Task labels are
used for training only in `train` and for temperature selection only in
`calibration`. All representations are genuine Jina sentence-level embeddings;
this does not implement landmark tokens or learned cross-attention.

Compare independently produced paired predictions:

```sh
python3 qualification/neuron-stem/statistical_gate.py \
  --dataset /approved/decision.jsonl \
  --baseline /evidence/no-change.jsonl \
  --candidate /evidence/nano-predictions.jsonl \
  --min-future-groups 30 --bootstrap-replicates 2000 \
  --output /evidence/nano-offline-quality-gate.json
```

The bootstrap resamples **source groups**, not individual correlated events,
and requires the 95% confidence lower bound on accuracy gain > 0 and the
upper bound on Brier delta < 0, without task-level regressions above the
precommitted tolerance. Even a passing offline quality gate is advisory only:
`production_promotion_permitted` and NDU signature verification remain false.

### Multimodal shadow pairing

Provide a separately held-out JSONL, with unique `case_id`, `scope_id`,
`group_id`, `split` (test/future/ood), `modality` (image/audio/video),
relative `path`, `media_sha256`, and `paired_text`. All media is local,
contained within `--media-root`, has a frozen digest, and is not copied to the
report. At least two unique positive texts must exist in each retrieval cohort.

```sh
python3 qualification/neuron-stem/jina_v5_multimodal.py \
  --text-model jina-v5-text-nano --text-revision TEXT40CHARCOMMITSHA \
  --omni-model jina-v5-omni-nano --omni-revision OMNI40CHARCOMMITSHA \
  --modality vision --dimension 256 \
  --dataset /approved/paired-media.jsonl --media-root /approved/media \
  --principal-id local-researcher --allow-pinned-remote-code \
  --output /evidence/paired-alignment.json
```

This measures retrieval-alignment only. Object relation and video temporal
reasoning require separately approved labels and fusion experiments, not
merely text/Omni vector cosine.

### Measured research batch/WAL probe

```sh
python3 qualification/neuron-stem/jina_v5_scale_probe.py \
  --model jina-v5-text-nano --revision FULL40CHARMODELCOMMITSHA \
  --dataset /approved/decision.jsonl --principal-id local-researcher \
  --cells 1024 --active-fraction .25 --repeat-fraction .5 \
  --round-robin --requests 4096 --batch-size 8 --dimension 256 \
  --allow-pinned-remote-code --db /evidence/scale-wal.db \
  --output /evidence/scale-trace.jsonl
```

The scale probe records measured research-encoder batch calls, active Head
count, actual tick coverage, group-committed SQLite WAL costs, full-batch
latency, process CPU/RSS, and a clean-reopen invariant. Heads here are
**random initialized**; this is a resource probe, not a learning test.
Neither the probe nor its output is a Rust production worker receipt,
authenticated NDU result or unclean-crash recovery qualification. The 4096
Cell case is valid only with explicit actual coverage reporting.

### Offline tests and mandatory evidence boundaries

```sh
python3 -m compileall -q qualification/neuron-stem
PYTHONPATH=qualification/neuron-stem python3 -m unittest discover \
  -s qualification/neuron-stem -p 'test_*.py' -v
```

The offline CI intentionally does not download 239M–1.74B weights or
fabricate learning, CPU/RSS, GPU or future-NDU measurements. To qualify
production, independent operators still need signed artifact/CAS, complete
inference-control worker and scheduler evidence, real target-host resources,
unclean crash/ack-loss replay, future windows, real utility receipts, and
Executor/Selector separation. All existing and new scripts fail closed with
zero authority to change a selected model or active Cell generation.
