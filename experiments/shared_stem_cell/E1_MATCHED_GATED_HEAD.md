# E1 equal-parameter gated Head probe — RESEARCH / DENY_ALL

Parent: original P0 V12 #2233, `b3b3712828cb5814e1a87d1e69a030ec947c43c1`.
No existing source, model loader, human-label owner, original result or production path changes.

## Precise question

The original P0 fits `Linear(width, 2)`: 770 parameters at 384 dimensions,
514 at 256 dimensions. That experiment is NOT a gated-Head trial or an
exactly equal-Head-parameter comparison across all three compact arms.
This additive experiment asks whether a gated versus additive nonlinear Head
learns on the SAME features, labels, initialization, parameter and step budget.
It does not compare with a fictitious deployment that copies a model per Cell.

Each source feature bank is projected ONCE to 128 dimensions by a fixed
PCG64 Gaussian matrix (seed 20261015), not fitted to TRAIN/CAL/TEST labels.
At each of seeds 41/47/53 the two alternatives own exactly the same tensor shapes:
`a: 128→16`, `b: 128→16`, `out: 16→1`, totaling **4,145 parameters each**.
Gated: `out(tanh(a(x)) * sigmoid(b(x)))`.
Additive: `out((tanh(a(x)) + tanh(b(x))) / sqrt(2))`.
Each architecture has its OWN frozen-weight counterpart. This is RANDOM
INITIALIZATION no-change, NOT the genuine deployed no-change baseline.
Both trained alternatives perform 40 full-batch SGD steps at LR 0.1 using only
original-condition TRAIN labels. CAL-only temperature selection has six values.
All blind source rows are forecast without reading their held human labels.

## Source reuse, verification and measured scope

The CLI first executes the EXISTING `p0_physical_replay_v5` original-case,
feature, weight and prediction reviewer. No alternate checkpoint or fake
fallback exists. It then consumes that original immutable FP32 feature bank.
There is no additional pretrained load or Encoder forward in this sidecar.
A new safetensors archive records the shared projection and all Head tensors;
COMMITTED.json is create-only and written/fsynced last.
The separate NumPy-only reviewer imports neither Torch nor the new trainer.
It independently replays all 40 TRAIN-label SGD steps, CAL selection, frozen
weights and blind predictions; it rejects changed-and-rehashed Head tensors.
The hosted reviewer runs in a separate PROCESS, not an independent signed host.

Projection coefficients, FP32 storage, forward linear MACs, bank construction
CPU/wall time, projected and split buffers are charged separately. At 384D the
frozen projection costs 49,152 coefficients / 196,608 bytes ONCE per shared bank.
It is lossy. SAME Head parameters does NOT mean equal complete training FLOPs,
equal original representation, equal Encoder expense or equal service TCO.
Head timing is sequential, not counterbalanced; it cannot certify speed or p99.
Do not substitute these new 4,145-parameter Heads for the original 770/514-parameter controls.

## Execution and remaining boundaries

`hepta-e1-matched-gated-head.yml` runs source tests then explicitly requires
SUCCESS of original P0 run **38686023757** at the exact V12 source SHA. Pending,
failed, cancelled, missing or expired source artifacts block; none is scored as zero.
It downloads only original FIT, blind inputs and one model's isolated artifact,
never the held-label owner's artifact. Original P0 source acceptance is necessary,
not sufficient for new E1 quality or production acceptance.
Three REAL upstream arms are registered: Granite97, mmBERT-small and
EmbeddingGemma 2 text. Laya stays untouched as the original capability baseline.
ModernBERT is NOT registered with a physical loader in this source lineage;
768D synthetic mechanics tests do not constitute a ModernBERT result.

Local evidence is synthetic FP32 Torch CPU mechanics only. Local versions:
Torch 2.10.0+cpu, NumPy 2.3.5, safetensors 0.7.0; CI intentionally retains the
original pinned NumPy 2.2.6 / safetensors 0.8.0 and must be qualified separately.
No new held-task accuracy, paired semantic superiority, genuine future windows,
learning curves across sample budgets, old-task retention, authenticated model
origin, equal lifecycle cost, 4096-Cell performance, signed NDU/FinalUse/CAS/CNS,
Cell Split or production promotion is supplied. Original owner-label scoring
must explicitly register these new arms before interpreting their task quality.
No model winner is selected. Keep Draft / DENY_ALL / no main merge.
