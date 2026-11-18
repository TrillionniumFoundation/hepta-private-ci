# Independent CPU-only check of the original eager softmax checkpoint candidate

This is an **auxiliary operator crosscheck**, not another E1–E6 experiment arm, not
a training run, not an evaluation on B3, and not a claim that a 3,584-position
BF16 model backward fits the original 70% GPU allocation cap.

## Fixed source and execution

- Stacked source: `2776b2e7e6464ce57014f2ed755a965b35037ec5` of
  [#6722](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6722).
- Actual imported `checkpoint_softmax.py` SHA-256:
  `81ad33310f7bb427d01d25fd4ff696d281e6c53f3bba24cbc80667df63316aaa`.
  The remote file was rehashed before import; the same content is pinned by
  `run_crosscheck.py`.
- Original installed reference: `transformers.models.qwen2.modeling_qwen2.eager_attention_forward`,
  Transformers 4.57.3 source defined in the original protocol.
- Installed PyTorch: `2.9.1+cu128`, **CPU tensors only**;
  `CUDA_VISIBLE_DEVICES=""`, no GPU lock taken, no model or weights loaded.
- Actual durable execution: host `desktop`, job
  `1a1f049ee8e-ffbe-76d`, idempotency key
  `e1e6-t4-independent-cpu-checkpoint-identity-20261118-001`.
  Authoritative job status: `succeeded`, exit 0, stdout 1,031 bytes,
  stderr 0, both captures complete and durable.

The actual run compared original Qwen2 eager with the byte-pinned checkpointed
softmax **for six shape/dtype combinations**: lengths 7, 129 and 257 with FP32
and BF16, including two cases crossing the 128-query-row partition boundary.
Each used grouped-query attention with four query heads and two key/value
heads, sixteen-dimensional head states, a strict upper-triangular causal
mask, zero dropout, the same random input tensors, and a mean-square output
loss. It compared all output and attention-weight values and all query,
key and value backward gradients.

**Observed:** all six cases had maximum absolute difference **0.0**
in every compared output, attention-weight tensor and gradient. Exact values
from the original durable stdout are retained in `RESULT.json`.
The script mirrors that execution with a repository-relative path so the
same operator can be independently reproduced. Its own future execution
does not retroactively establish a result for a different installed library
version.

## Qualification boundary

This tests only small synthetic attention tensors and the local operator
under the recorded software version. It does **not** test the full Qwen2
model, LoRA parameter gradients, actual A data and labels, 3,584-token
backward-memory peak, CUDA kernel equivalence, physical cost, real student
repair, native adoption, or independent controller custody.

The original three OOM attempts, the rejected SDPA candidate if separately
observed, B3's pre-training holdout, Research NoUpdate, and every original
business gate remain unchanged. No other executor's working tree, source,
GPU reservation or evaluation target is modified by this stacked evidence.
