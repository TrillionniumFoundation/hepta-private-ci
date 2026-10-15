# Shared Stem V5 - physically executed frozen Encoder / matched Cell Head candidates

**Research contract only. No qualified pretrained mmBERT/Granite learning results,
NDU selection, production split or release authorization are claimed.**

This implements the previously missing producer corresponding to the independent
V4 `multimodal_candidate_gate.py` readout. It **does not** fabricate an existing
`no_change` baseline; that baseline must come from the actual frozen incumbent
owner and be independently pinned. The V4 evaluator still requires every arm.

## Host / source / model prerequisite

Run a local **CPU** environment containing pinned `torch`, `transformers`,
`tokenizers`, `safetensors`, `numpy`, `psutil` with network downloads disabled.
The operator must physically stage each real candidate checkpoint and tokenizer,
record the complete file SHA-256 inventory and immutable model revision under an
`hepta.multimodal-pinned-text-encoder.v1` profile. The same pinned `LocalEncoder`
verifies model weight tensors on materialization and rechecks snapshot bytes
at completion. The source does not fetch or manufacture weights.

Use `python multimodal_pinned_candidate.py host` on the *target host* to produce
machine-class and exact software/optimizer fingerprints. These are self-observed
profiles, **not independent hardware attestations**. Freeze the V4 JSON plan
including those digests before training and before future outcomes exist. The
manifest requires one `no_change` and at least one frozen candidate. All
candidates must have exactly equal *actual* Head trainable parameter count and
steps, not padded dummy parameters. CPU, AdamW with fixed learning rate 0.01,
weight decay 0, batch 16, state width 64, low rank 8 and deterministic seed are
fixed by this program, not candidate-specific command flags.

Each TRAIN JSONL record is a canonical object containing `case_id`, `group_id`,
`scope`, `observed_at`, `split:"train"`, `text`, 64-number `state` and `label`.
The SHA-256 over the complete JSONL is precommitted by `plan.train_sha256`.
TRAIN groups and times must match the frozen V4 plan. Minimum 16 examples.

Each FUTURE-INPUT JSONL record has `split:"future"`, `text`, a 64-number
`state`, and the common metadata but **no `label` or `target_text`**. It also
has an `input_sha256` computed from `text_input_digest(scope, text, state)`.
The exact source-only cohort digest is precommitted in the plan. Future group
and exact text overlap with TRAIN are rejected. The separate FUTURE-TARGETS
JSONL file and its labels must be accessible **only to the independent evaluator**;
neither producer command accepts a future-target argument.

## Run order

1. On a target host, create the pinned immutable V4 plan, all model profiles,
   train JSONL, future-input JSONL and private future-target JSONL. For each
   candidate, use `--candidate` matching its profile and frozen plan inventory.
2. Train, writing **new** directory with `head.safetensors` and a canonical
   `train_receipt.json` containing its SHA, parameter count, actual steps,
   forward count, resource observations, source identity and local verification.
3. In a distinct process, read the SHA-pinned training receipt and Head bytes,
   re-load the same exact frozen Encoder, use only future source inputs, then
   write a new directory containing `candidate_result.json` and
   `predict_evidence.json`. The former matches the exact V4 evaluator schema.
4. Independently retrieve the frozen *real* `no_change` baseline result and
   all candidate results, retain their full byte hashes, and call the existing
   V4 evaluator with FUTURE-TARGETS. No automatic winner or promotion is issued.

Example (insert literal precomputed SHA values and actual paths):

```sh
python experiments/shared_stem_cell/multimodal_pinned_candidate.py host
python experiments/shared_stem_cell/multimodal_pinned_candidate.py train \
  --plan plan.json --plan-sha256 PLAN_SHA --candidate granite_97m \
  --profile granite.json --profile-sha256 PROFILE_SHA \
  --model-snapshot /models/granite --train train.jsonl \
  --train-sha256 TRAIN_SHA --output-dir /tmp/granite-head
python experiments/shared_stem_cell/multimodal_pinned_candidate.py predict \
  --plan plan.json --plan-sha256 PLAN_SHA --candidate granite_97m \
  --profile granite.json --profile-sha256 PROFILE_SHA \
  --model-snapshot /models/granite \
  --train-receipt /tmp/granite-head/train_receipt.json \
  --train-receipt-sha256 TRAIN_RECEIPT_SHA \
  --head /tmp/granite-head/head.safetensors \
  --future-inputs future-inputs.jsonl --future-inputs-sha256 FUTURE_INPUT_SHA \
  --output-dir /tmp/granite-future
```

## Evidence limits and explicit fail-closed states

- `physical_forwards` counts model-interface forwards via the real local owner
  and is **not** a separate attested backend trace. RSS is sampled current
  process RSS, not verified global peak or precise GPU allocation. Energy is
  `null` when not metered. Both train/predict separately reload the model;
  their measured times cover these phases but not downstream external effects.
- CPU host digest is a **machine-class fingerprint**, not a physical identity or
  authorization receipt. Model SHA-256 proves material identity, **not**
  trusted model publisher, training provenance or actual pretrained efficacy.
- The runner requires a fixed width and exact trainable Head count; if mmBERT
  and Granite exposed different dimensions, a shared frozen projection must be
  qualified explicitly. It will not silently insert one or pad dummy params.
- Persistent checkpoint stores trained Head weights, not an incremental
  online-learning optimizer ledger. Independent calibration, negative transfer,
  NDU, graduation/promotion, Rust immutable shared buffers and 4,096-Cell
  target-host measurements remain subsequent gates.
- Tests with `FakeLocalEncoder` explicitly mock the owner check for fixtures;
  they **cannot certify** production model loading. Hosted CI additionally
  builds a local random-initialized small stock BERT, stages real safetensors,
  trains and reloads a Head in separate processes, runs future-only inference
  and rejects modified model weights. It must not be called a pretrained test.

Neither the CLI nor V4 readout signs receipts. All results must stay in Draft
research until exact pretrained weights/publisher, real future data, an
independent NDU owner, final-use authorization and target-host resource tests
are qualified. `winner: null` and `production_accepted: false` remain mandatory.
