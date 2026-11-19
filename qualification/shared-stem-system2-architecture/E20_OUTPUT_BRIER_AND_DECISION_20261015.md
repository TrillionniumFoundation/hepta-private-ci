# E20 — 原始预训练 Reader 输出量化：分类一致性、Brier 扰动上界与完整成本边界

**2026-10-15 / RESEARCH ONLY / DRAFT / DENY_ALL**  
Parent: E19 #2230 exact source `9ea2f28762389b3a839eb128d7b1b413cf00982b`.

This report records executed **original pretrained-output** evidence from
ModernBERT / four frozen Reader historical GitHub artifact `11946621518`,
outer ZIP SHA-256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.
Four original MultiRC passages, eight questions, 33 authentic answer candidates.
There is NO new foundation model forward, retraining, task set, label sampling,
new independent signer, model selection, changed Worker wire, or production effect.

## New answer: numeric signal recovery is not decision improvement

E19 established that pre-centering Question-wise Float32 class margins before
BF16 residual casting retains 19 within-question pairwise distinctions that
BF16 quantization of two individual output logits loses. That is a statement
about **representation detail**, not the classifier's hard decision or semantic
truth. A new independent full-original-source E20 audit compares the original
classifier to all seven inherited E19 output profiles and finds:

**all 4 Reader arms × all 7 output-precision profiles preserve the exact 33/33
original hard decisions on this one historical case panel**.

Important tie correction: the actual original scorer uses
`logits.index(max(logits))`, choosing **class zero** on equal logits. The
new E20 implementation uses `margin > 0`, not `margin >= 0`. A hostile
almost-equal two-logit example tests a true positive class being lost when
BF16 quantization creates a zero margin. The 33 genuine archived examples
have zero hard flips under either strategy; that fact is observed, not a
universal assurance against precision loss.

## Human-label-independent Brier interval

For original positive-class probability p and quantized reconstructed q,
define the two-class Brier for binary truth y as

`B(y,p) = (p-y)^2 + ((1-p)-(1-y))^2 = 2*(p-y)^2`.

Independently of the unavailable per-row human labels in the prediction
stage, the absolute delta is bounded case by case by

`max(|2q²-2p²|, |2(1-q)²-2(1-p)²|)`.

The E20 producer sums this worst-case term across the **same** 33 candidates
and reports a Float64, outward-nextafter numeric envelope; the independent
reviewer computes its own equivalent formula via `tanh` and independently
quantized E19 output values. These are experimentally recomputed **FP64
numeric envelopes**, not formally verified roundoff proofs or confidence
intervals for unseen natural-task outcomes. Class-0 ties are preserved.

Historical archive readback (example conditioned arm, summary across all 33):

| Post-output profile | Hard flips | Mean absolute p delta | Mean binary-Brier worst-case delta |
| --- | ---: | ---: | ---: |
| BF16 cast two logits, subtract | 0 | ~0.000101043 | ~0.000249249 |
| BF16 cast FP32 margin directly | 0 | ~0.000158139 | ~0.000455727 |
| **FP32 center + BF16 residual + FP32 anchor** | **0** | **~8.0e-9** | **~2.0e-8** |
| FP16 cast two logits, subtract | 0 | ~0.0000159074 | ~0.000044659 |

Both source-HEAD and synthetic-merge research CI are required to recompute
these values; no positive task-improvement conclusion is permitted. The
existing **historical** original-human aggregate is opened **only after**
create-only blind output sealing. Exact archive SHA plus old score-member SHA
are checked. Since each new profile leaves each hard decision unchanged, its
human-label candidate accuracy **must** match the original 16/33, 17/33,
16/33 and 19/33 for Conditioned, Mean-pool, No-evidence and No-query,
respectively. No reconstructed per-candidate truth is claimed. The unknown
post-quantized Brier score is reported as an *interval around the real
historical Brier value*, never a fabricated newly evaluated exact score.

## Actual arithmetic cost and unqualified whole-service cost

The research code executes and meters **40 actual Python process-time/wall-time
batch invocations**, each covering 4 arms × 33 candidates, for three output
paths: FP32 direct, BF16 individual-logit, BF16 centered. The original ZIP
is read once outside timed compute. The measured benchmark is a complete
reference Python feature transformation and logistic calculation; it excludes
pretrained model execution, tokenization, training, Reader/Head serving,
permission checks, transfer, storage, asynchronous queues, energy, reviewer
and deployment costs. Microbenchmarks do **NOT** support a target-host speed
winner and may be dominated by Python overhead. Keep every raw timed sample.

An illustrative *payload-only* four-arm 33-answer panel is 1056 bytes
for two FP32 logits per candidate vs 392 bytes for one BF16 centered
residual per candidate plus one FP32 anchor per **complete question**.
The anchor demands the entire question's candidate slate and exposes extra
buffering/liveness/cross-scope consent requirements. Neither number is an
observed system RSS, network packet cost or deployed zero-copy benefit.

## Required next physical gates

1. E15/E16 **actual** four-fold human-label training/held review, once
   hosted jobs finish. A local synthetic-label test is never a human gain.
2. E17/E18/E19/E20 exact source-HEAD and synthetic-merge hosted CI, preserved
   original pretrained archive and independent review; `blocking-ci` unchanged.
3. Actually execute *frozen real Reader/Stem forward* in fp32/fp16/bf16,
   controlling model/tokenizer/candidate/slate/reference host. This E20
   research only casts already computed fp32 output values.
4. Independent source/time/OOD groups, per-question mixed-label success,
   calibration, data permission, revocation, complete end-to-end cost,
   measured numeric-device precision and no-change comparison.
5. A qualified real task advantage is still required before System 2 NDU/FBSDE
   policy training or FinalUse. Retain the original E12–E14 negative results.

**Disposition:** `production_accepted=false`; `model_selected=false`;
`natural_task_gain_established=false`; `whole_service_cost_win=false`;
`actual_bf16_foundation_forward=false`; `DENY_ALL`.
