# ModernBERT full-token paired Cell Head experiment (shadow-only)

**Decision:** no deployment, promotion, real NDU benefit, future-window learning,
trusted data-use grant, signed artifact CAS, generation/fence, or native Rust Worker.

## Exact predecessor and source

This additive study stacks on #1953 and reuses its independently bounded
historical public research source importer. The original public AG News producer
artifact was observed in GitHub Actions run `38534349397`, artifact
`11881847060`, with entire ZIP SHA-256:

`1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2`

Its physical Model/Tokenizer publisher revision is
`answerdotai/ModernBERT-base` / `fa3113d09d6dacfe5528708803dd92a62240237a`.
The original ZIP's model file manifest contains every exact SHA-256 needed to
reject file substitutions. The 128 original AG News rows have 64 train, 32
calibration, 32 holdout, two Cells with 32/16/16 rows per Cell, and 4 choices.
`observed_at` is null: **no authentic prospective time is claimed**.

The original 128×768 pretrained features are **pooled**, not token matrices.
This experiment does NOT expand or repeat those pooled vectors. Instead, it
uses the dataset text and reloads the genuine pinned Transformer to compute
**one new 64×128×768 masked token tensor per Cell**, with direct module-forward
attempt/row counts. It refuses silent truncation or unexpected tokenizer/model
geometry. The JSON decision input includes complete ordered `question`,
`options` and `state`; it is not the Laya native marker encoding. The two
Head arms receive exactly the same token tensor and mask. A model API choice
remains a separate registered research arm, not a claim of Laya parity.

## Paired training and persistence

Within each Cell, random seed, initialization tensors, train-only valid-token
normalizer, minibatch order, true parameter count, 20 AdamW optimizer steps and
`4` output classes are fixed. `rank=8` and `d=768` give **16,132 trainable
parameters per Cell** for both Head arms. The paired arms are:

- `pooled_cached`: mask then mean-pool once over a common input, reuse the
  resulting vector for the Cell-specific gated classifier;
- `token_query_prepared`: dynamic Cell-owned trainable query attends over
  the same masked token matrix, then uses the identical gated classifier.

Both arms seal their own Head to create-only, private-mode safetensors. They
are read back with exact manifest, weight, scope, generation and artifact
SHA-256 before *any* retrospective calibration/holdout outcome is scored.
The loaded Head bank checks scalar-vs-Packed predictions for all 32 original
holdout cases per seed. Outcome labels of calibration and holdout are omitted
from the frozen training-feature witness; a mutation of these labels does not
change the trained Head bytes or manifest. Repeated seeds are not independent
source families. The study reports per-Cell accuracy, Brier, NLL, newly
correct/lost cases, optimizer timings, observed model forward counts, Head
parameters and Packed parity. It **never chooses a winner**.

There is no OOD test, prospective future utility, independently certified
source-family split, freeze of the *deployed* no-change Head, causal NDU,
model-owner signed receipts, or end-to-end production p95/p99. No sharing
across unrelated principals or sources is licensed by this research.

## Execution (offline, no auto-download)

Stage the source ZIP and the genuine immutable publisher checkpoint in a
private, read-only directory first. `bundle_sha256` is computed from the staged
complete checkpoint under `neuron_shared_encoder.bundle` and independently
compared to the original publisher file roster; it is not a signature.

From `qualification/neuron-shared-encoder`:

```bash
python -m neuron_shared_encoder.physical_token_pair_v1 \
  --source-zip /private/hepta-public-pretrained-38534349397.zip \
  --source-sha256 1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2 \
  --checkpoint-dir /private/immutable-modernbert \
  --bundle-sha256 YOUR_EXTERNALLY_PINNED_COMPLETE_BUNDLE_SHA256 \
  --output /private/new-hepta-token-research \
  --max-length 128 --encoder-batch 8 --steps 20 --seeds 11 23 47
```

The optional separate hosted runner stages the precise publisher model from
its immutable Hugging Face revision, validating **every file** against the
previous GitHub study's SHA manifest and refusing absent/mismatched files.
That is an explicit source-acquisition job only; the execution module never
downloads models, uses pickle, synthesizes features on missing weights or
trusts remote code. The runner deliberately uploads only small Head weights
and numerical receipts, never pretrained weights, original texts or token
matrices.

## Verification commands and nonclaims

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -m pytest -q -p no:cacheprovider tests/test_physical_token_pair_v1.py
```

Synthetic-interface fixtures verify equal training seeds, proper masked
readout, immutable checkpoint readback, holdout-label blindness, source/Scope
rejection and fail-closed behavior. **Passing these tests is not physical
pretrained Encoder execution evidence.** Only exact-SHA GitHub Actions
real-weight forward receipts can establish that such model execution occurred;
production acceptance still needs independent future NDU, trusted final-use,
Artifact CAS/WAL, Q24 parity, 64–4096 target-host tests and operator review.
