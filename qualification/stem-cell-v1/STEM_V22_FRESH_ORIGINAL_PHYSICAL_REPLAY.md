# Hepta V22 — independent fresh 135M Reader replay on V21 original LoCoMo plan

**RESEARCH_ONLY / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. No main merge, production model selection, FinalUse, NDU or Cell Split.**

## Fixed ancestry and one precise scientific question

V21 #2507 independently reproduced original LoCoMo → 5,882 source turns → 1,986 BM25 rankings → historical V16 **32 questions × four evidence regimes = 128** byte-exact input prompts. This V22 addon is based on the exact V21 HEAD, not on a mutable main or a rewritten Qwen branch.

Question: **does a fresh local CPU process executing the exact original 135M manual Torch Reader with the original SHA-pinned weights and tokenizer reproduce the original V16 physical token/case census and historical *publisher-answer-substring proxy*?** This does not compare a stronger Reader or prove semantic sufficiency. Even a positive result measures numerical implementation reproducibility, not an independent issuer-signed model capability.

Fixed identities:

- Historical original GitHub artifact: `11586991191`, outer ZIP SHA-256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.
- Original LoCoMo SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Original 135M safetensors SHA-256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
- Original BPE tokenizer SHA-256 `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`.
- Original source-only digest `9d707c297dc743cffe00d94ead04198b7039f72027743dc6d6e02c826a623a8c`.
- Original BM25 ranking digest `b0b38675d2d5458795d0577d5c861b796dfbdf9e7d4cd089838895c419831697`.
- Full V16 request-plan SHA-256 `26a4d5a4883c98d61d9405f739dda7e49f433370c30290275f0f04441d7067c8`.

## Actually executed on local CPU (2026-10-16)

First isolated original-weight process completed **128/128** actual original model calls, **2,951 counted true Torch forward invocations**, **16,264 actual input tokens, 2,855 generated tokens**, **403.838 CPU seconds / 209.606 wall seconds**. The start journal was create-only, `0600`, and flushed/fsynced before every model call; the output receipt was create-only and sealed only after all 128. Original source, prompts, start journal, raw generated tokens, output strings, historical source IDs, full original data and full original model weights remain in the private runtime and **are not committed**.

An independent separate Python reviewer reopened the original source, reran the V21 source/rank/plan reconstruction and the tokenizer, verified each of 128 start/request/input-token/source/answer-token joins, independently recomputed all **2,951** forward-call counts (accounting for EOS), and only then opened publisher answer text for the weak literal proxy.

**New actual results reproduce the original V16 historical proxy without mismatch:**

| Answer literal cohort | No evidence | BM25 top3 | Annotated witness | Witness removed |
| --- | ---: | ---: | ---: | ---: |
| 16 cases with literal present in witness | 0/16 | 0/16 | 8/16 | 0/16 |
| 16 cases annotated without that literal | 0/11 known | 1/11 known | 0/11 known | 1/11 known |

Five of the latter 16 publisher answer fields are absent and **remain unknown**, rather than becoming model errors. Strict complete-answer string equality is zero in all arms. These are *not* semantic correctness scores, human-certified evidence sufficiency, future-time generalization, or a causal inference on independent family roots. There are only **four correlated historical conversation roots**, and the original V16 sample was retrospectively selected using publisher answer literals.

**Second fresh model process:** A new separately loaded process completed the **same 128 requests / 2,951 real forward calls**, **397.960 CPU / 205.939 wall seconds**. An independent verifier first repeated the complete source/request/start/token census on both sealed outputs, then checked **all 128 original generated token sequences, unredacted answer bytes and ordered evidence IDs were byte-for-byte identical**. Together the two physical processes performed 256 actual requests and **5,902 forward calls**. The public `V22_ORIGINAL_DOUBLE_REPLAY_20261016.json` holds only digests, counts, clock observations and hard-denial flags. It is not a host-identity signature or a Qwen experiment.

**Scientific nonclaims:** This locally executed manual Torch model is not independently signed by a model issuer or verified to match official Hugging Face operator behavior, and the current host identity is not cryptographically distinguished from earlier archived hosts. Do not claim cross-host authenticity from the filename. No stronger Qwen reference was actually executed here. A dedicated independent stronger-Reader and human-review study remains a strict gate before selecting Stem, Cell Split or NDU.

## Separate physical execution and postseal review

On an approved private local machine with the already verified original model material:

```bash
export PYTHONPATH=qualification/stem-cell-v1
# V21 rebuild must happen first; it writes PRIVATE/source.json,
# PRIVATE/routes.json, PRIVATE/v16-plan.json from the SHA-checked original corpus.
python qualification/stem-cell-v1/v21_original_plan_rebuilder.py \
  --original PRIVATE/locomo.json \
  --private-source PRIVATE/source.json \
  --private-routes PRIVATE/routes.json \
  --private-plan PRIVATE/v16-plan.json

python qualification/stem-cell-v1/v22_original_crosshost_execute.py \
  --source PRIVATE/source.json --routes PRIVATE/routes.json \
  --plan PRIVATE/v16-plan.json --reader PRIVATE/reader \
  --answers PRIVATE/original-v22-first.json

# A NEW process; `--original` is only opened AFTER the complete first model seal.
python qualification/stem-cell-v1/v22_original_crosshost_review.py \
  --original PRIVATE/locomo.json --source PRIVATE/source.json \
  --routes PRIVATE/routes.json --plan PRIVATE/v16-plan.json \
  --answers PRIVATE/original-v22-first.json \
  --starts PRIVATE/original-v22-first.json.starts.jsonl \
  --reader PRIVATE/reader --receipt PRIVATE/v22-redacted-review.json
```

For an actual second independent model process, execute the original runner again using an entirely new create-only answer filename, then compare the two *separately sealed* outputs with `v22_original_repeat_compare.py`. The public source-only workflow **does not download either original weights or private data, nor does it run a pretrained model**. It only checks source/negative contracts and internally consistent sanitized summaries; those checks must never be called independent physical forward attestation.

## Acceptance and production posture

- Full replay must bind the exact old V21 source/rank/plan, fixed reader weights, full 128 attempts, original integer tokens and output/source identities.
- Missing, duplicated, changed, symlinked, oversize or partially sealed source/output is rejected. Missing gold is censored, not fabricated.
- Reproduced historical weak substring counts are observations, **not verified gains** or new learning.
- Qwen3 128 full reference calls, independent human judgments, complete matched cost accounting, old-task retention, new future sources, NDU/FBSDE benefit and multi-modal generation remain **unproven**.
- `blocking-ci`, Architecture and V22 exact-head workflow are required before any integration claim. No `main` merge, no tool/effect authority, no automatic Cell Split.
