# Label-blind MultiRC evidence-intervention handoff — 2026-10-14

Parent: `36df7ba1c091938667a05348d80df48f70774158` (#1970).
Exact tested code: `73a89bbcde3503559ee808ba679fdabec95d4b60` (#1981).
Draft research only. No main merge, production model promotion, NDU activation or
modification of previously sealed predictions / trained Reader parameters.

## Question answered by this increment

The earlier MultiRC experiment tests four separately trained equal-parameter
Reader configurations. It does not test whether **the same conditioned Reader**
actually responds to changed source passage or question.

After original trained weights and predictions have been sealed, but **before**
the separately stored validation labels are opened, the new sidecar reopens only
the verified conditioned Reader safetensors and blind input bundle. It physically
executes these four inputs on each original held-out question:

1. Original passage + original question, requiring exact replay of the prior
   sealed logits within a predeclared 1e-5 absolute tolerance.
2. A separately tokenized/encoded fixed neutral passage + original question.
3. An actually different held-out passage + original question.
4. Original passage + the other selected question from the same passage.

The neutral case is **not** an annotated critical-premise removal; the other
passage and other question have **no valid new gold labels**. Therefore the
experiment reports absolute shifts of predicted positive-class probability,
never fabricated accuracy, ground-truth retention, or a correctness certificate
under altered evidence. This is not a new training run.

## Validation and cost rules

Read an immutable train/validation panel, original sealed model identity and
trained Reader weights. Reject changed input identity, source overlap, altered
weights, reordered question IDs, non-CPU FP32 tensors, nonfinite values, cache
overflow or unknown ATen work. A new separate strict WorkLedger charges genuine
Encoder, question and Reader operations; it does not rewrite earlier phase
receipts. The command writes a new committed stress receipt on success or an
explicit FAILED marker on failure. A failed attempt does not supply a complete
cost report: aborted prefix costs must not be counted as zero.

Existing original MultiRC run, material preparation and evaluation scorer are
unchanged. The existing hosted work now inserts the blind stress **after
prediction seal and before label join**, with separate ZIP artifacts that exclude
raw news text, labels, hidden features and model weights. A separate stock
random-weight Transformers compatibility test is also required. The public
pretrained test must be judged on its own actual checkout SHA.

## Verified local evidence

Two whole-source runs completed with 587 planned and 587 executed distinct tests
each, no discovery errors, failures, errors, skips or expected failures, and both
process exit codes 0. These are 577 predecessor source tests plus 10 new tests
using actual trained CPU PyTorch Readers. The four changed code/CI blob identities:

- `multirc_evidence_stress.py`: `319d0cf173972040f3fbd7e4b8555556006dfd8d`
- `test_multirc_evidence_stress.py`: `b525953ea0aac009981ece86850b99b11807ee7a`
- `hf_multirc_checks.py`: `f26d5faf3aa914054871935c0be17f2c3d38e644`
- `.github/workflows/hepta-real-multirc-reader.yml`: `5759ef3a3eba74a5b064aee5f855186ca1cd8ffe`

A separate local, synthetic-text / real 4D PyTorch Reader smoke measured 8
questions from 4 passages: five actual passage encodings (4 original, 1 neutral),
8 question representations, 32 conditioned Reader forwards and 6,620 measured
eager CPU FP32 formula operations. Mean probability shifts:

| Intervention | Mean absolute predicted-positive probability change |
|---|---:|
| Neutral encoded passage | 0.02677254 |
| Swapped genuine other passage | 0.02747779 |
| Swapped other question on same passage | **0.00000000** |

The zero response to swapping questions is a **failure signal** about the weak
small synthetic fixture, not proof of invariance/sufficient understanding.
No real ModernBERT pretrained MultiRC result was available at this record.

The original complete run logs, development failures, structured test inventories,
synthetic diagnostic, SHA256 file manifest and replay-verified incremental patch
are retained in the associated delivery ZIP (SHA256
`bd4c471127ad578254a3fa40452a0f526aeed999b45f5b77877c48498b5f0c28`).

## What remains unqualified

No independent passage-label observer, pretrained leakage exclusion, real QA
generalization, sensitivity to a verified *critical premise*, counterfactual
answer accuracy, causal quality advantage, confidence certificate, full system
latency/energy/memory savings, native deployment, modalities, NDU/SYSTEM2 benefit,
or 1024/4096 Cell scaling is claimed. This result is a falsification probe for
evidence and query reliance, not an acceptance certificate.
