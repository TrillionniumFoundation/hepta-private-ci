# E2 Token Reader versus Pooled Feature Gate — shadow-only

**Status:** research implementation; no production worker changes, authorization, learned
Cell promotion, published NDU result, causal future-window evidence or runtime
selection. This is an additive experiment stacked on draft #1827 (which is
itself stacked on #1772). Do not merge this branch directly into \`main\` and
do not treat its tests as an activation permit.

## Why this ablation matters

Shared physical Encoder weights do not imply a shared forward: question-conditioned
inputs can require new Encoder calls. Once a particular input is actually admitted
and encoded, it can be useful to share a read-only **token feature matrix**
rather than a single pooled vector. A Cell may then learn where to look inside
those tokens without running the Encoder again. This can improve quality at an
extra active-Cell reading cost; neither quality nor resource benefit is assumed.

The proposed CPU shadow comparison receives one already-frozen float32 tensor
\`tokens[N,L,d]\` and boolean token mask \`mask[N,L]\`, with no model load or
Encoder call. Both Head arms see the *identical* frozen content and train with
equal parameters, initialization, row sampling, optimizer and learning budget.

- **Pooled baseline:** masked-mean feature, followed by a learned
  \`2*sigmoid(q)\` feature-wise multiplier and identical low-rank gated classifier.
- **Token-query:** masked dot-product attention \`softmax(H q / sqrt(d))\`,
  token-weighted feature, followed by the identical gated classifier.

For Head width \`d\`, gating rank \`r\` and output classes \`c\`, both arms
have exactly \`d + 2*d*r + d*c + c\` trainable scalars. For example:
\`d=384,r=16,c=2 => 13,442\`, and \`d=768,r=8,c=2 => 14,594\`.
These are **per-Cell** FP32 experiment weights, not deployed BF16/Q24 bytes.

Equality of parameter counts **does not establish equal FLOPs or service
cost**. The pooled mean can be cached once and reused across Cells in a
production-quality baseline; this initial Python module does not implement
that cross-Cell pooled-cache optimization. Nor does it prove physical sharing
among multiple Cell processes, real Worker backend batch or target-host p99.

## Offline call boundary

Use the existing local Python package in \`qualification/neuron-shared-encoder\`:

\`\`\`python
from neuron_shared_encoder.token_reader_v1 import (
    paired_token_reader_trial, snapshot_sha256,
)

# tokens: contiguous CPU float32 [N,L,d] from one frozen Encoder checkpoint
# mask: contiguous CPU boolean [N,L]; labels: aligned CPU torch.long [N]
# rows: aligned list of immutable metadata only (no raw state/prompts)
# pins: encoder/tokenizer/preprocessor/normalizer/dataset SHA256,
#       positive generation and authority_epoch
digest = snapshot_sha256(tokens, mask, rows, pins)
report = paired_token_reader_trial(tokens, mask, labels, rows, pins, digest,
                                   rank=16, budget=16384, steps=20,
                                   seeds=(11, 23, 47))
assert report["production_admission"] == "BLOCKED"
\`\`\`

Each row must contain exactly \`row_id, principal, purpose, organ_id, cell_id,
source_group, event_time, split, label, options, input_sha256\`. It must bind
a complete question and ordered option input digest. One scoped Cell is
evaluated per call. Splits are \`train, validation, future, ood\`; source groups
cannot cross splits, validation must begin after training, and future after
validation. Options may vary across rows, but output width cannot.

Each input snapshot is bound by a SHA-256 over its tensors, mask, shape, row
metadata, model pins, generation and epoch. Frozen tensor content is re-hashed
after training to reject observable in-process changes. SHA-256 **does not**
authenticate where those tensors came from, prove approved data-use, or replace
a signed immutable Worker snapshot with independently checked Final-use.

The experiment enforces CPU float32, at most 4,096 records, 256 tokens per
record, width 768, 8,388,608 token values, and bounded rank, optimizer steps,
batch, unique seeds and allowed parameter budgets. Padded tokens are masked
inside each Head as well as before normalization. The normalizer uses only
valid **training** tokens. Training for both arms completes before any
validation/future outcome is scored. Future metrics are still retrospective
because an independent signed prequential evaluator is absent.

## Verification

From the \`qualification/neuron-shared-encoder\` directory:

\`\`\`sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m pytest -q tests/test_token_reader_v1.py
python -m compileall -q neuron_shared_encoder/token_reader_v1.py \
    tests/test_token_reader_v1.py
\`\`\`

The existing shadow workflow runs \`pytest -q tests/\` on the exact PR SHA,
so the new test is included without altering production CI ownership.
Local isolated 2026-10-14 CPython 3.13 / PyTorch 2.10 CPU result:
**18 passed**. Source bytes of both added Python files were checked against
their GitHub blob SHA-1 after upload. This does **not** prove an exact-head
hosted CI pass; that requires completed GitHub check receipts.

Tests cover masked-token invariance, digest drift, swapped principal/purpose/
Cell, missing input binding, repeated row/source-group leakage, naive/future
time, option geometry, training-class coverage, incompatible labels, empty
mask, NaN, parameter budgets, malformed pins and future-label independence.

## Remaining hard gates (not provided by this PR)

1. Pinned, independently approved **actual** mmBERT/Granite/ModernBERT/Laya
   token-level hidden states with full question/options and token mask
   provenance. No synthetic smoke may fill missing genuine model evidence.
2. A separately signed no-change comparison, true future-time outcomes,
   negative-transfer review and independent NDU Evaluator/Selector/Executor.
3. Precomputed pooled-vector baseline, end-to-end real worker scheduling,
   active-compute accounting, GPU/CPU/RSS and p95/p99; correct amortization of
   Encoder forward when many Cells share one admitted input.
4. Native Q24 numerical agreement, physical immutable snapshot ownership,
   generation/fence/revocation-scoped Final-use, durable Artifact CAS/WAL and
   checkpoint recovery, all validated independently before any promotion.

**No model winner, parameter budget, new Cell generation or topology is selected here.**
