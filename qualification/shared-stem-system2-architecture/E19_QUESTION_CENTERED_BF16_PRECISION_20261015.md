# E19 — Preserve original Reader candidate signal by centering before low-precision packing

**2026-10-15 · Draft research only · `DENY_ALL` · no selected model / no production authority.**

Exact parent E18 PR #2220 (`8fb0d9280aea13da1f10a1960349ff7092572b76`).
The proposed patch is additive: new E19 Python research, tests, workflow and documentation only. Do not change the original trained Reader, stemming, model weights, selected NDU, Q24/Q32 wire, FinalUse, authorization, CAS, Evidence WAL, production code or `blocking-ci`.

## Scientific question and model source

The previously completed **original pretrained ModernBERT + four frozen trained Readers** produced genuine logits on 4 MultiRC passages / 8 original questions / 33 authentic answer candidates. Its original successful hosted artifact `11946621518` has SHA-256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`. The original candidate observation and create-only prelabel seal are independently verified by the inherited E14 parser. E19's blind producer decompresses **only** the pre-human-score original prediction and seal, not the ZIP's human-score member or original label source. There are **zero new pretrained Encoder or Reader forwards**.

E18 demonstrated that **rounding the two final logits before subtraction** to BF16 erases every surviving within-question candidate margin difference for the conditioned Reader. E19 tests whether a physically realizable *post-output* transform can avoid that information loss, without changing the model.

## Registered calculation and workload

For each question `q` with its complete candidate slate and original validated FP32 logits `(l0_i,l1_i)`:

```
m_i := fp32(l1_i - l0_i)
a_q := fp32(sum_i(m_i) / n_q), using an accurate accumulator
r_i := fp32(m_i - a_q)
packed_r_i := RNE_BF16(r_i)          # or IEEE FP16 for the control
reconstructed_m_i := fp32(a_q + fp32(packed_r_i))
```

The two residuals (BF16 or FP16) are **actual dtype casts in a PyTorch 2.10 CPU control** applied to original historical FP32 logits, and independently replayed with two separate exact numeric algorithms (the producer uses `struct` RNE; the reviewer uses rational source sums and independent exponent-based RNE). The independent reviewer requires the exact *complete question slate*, not an arbitrary mixed-source aggregation.

Frozen arms: original FP32, BF16(two logits → subtraction), BF16(FP32 subtraction → BF16), BF16(question center → BF16 residual + FP32 anchor), analogous three FP16 arms. Retain E18 Q24 separately as inherited original numeric reference. Evaluate equal-value candidate pairs, missing/false ties, pairwise ordering reversals, hard-prediction drift and absolute margin error, on original 33 predictions. No label-driven threshold, source selection, model choice, or training.

## Actual bounded original-archive findings (physical kernels checked, *not* model forwards)

| Conditioned Reader, 8 authentic questions | Questions preserving distinct candidate margins | Equal candidate-margin pairs (55 total) |
| --- | ---: | ---: |
| Original FP32 | 4/8 | 36/55 |
| BF16 applied to two logits before subtraction | **0/8** | **55/55** |
| BF16 applied to original FP32 margin | **0/8** | **55/55** |
| **Question-centered FP32 margin → BF16 residual + FP32 anchor** | **4/8** | **36/55** |

For these exact observations, question-centered BF16 **preserves all 19 originally distinguishable pairwise orderings** and does not manufacture distinctions among the original 36 identical pairs. The analogous FP16 centered transform also preserves the four varying questions. The original no-query Reader remains genuinely invariant for all eight questions under every transform; the proposed encoding **cannot create missing semantic signal**.

The accompanying same-question 33-candidate *payload-only hypothetical geometry* is 264 bytes for two FP32 logits per candidate, 132 bytes for two BF16 logits per candidate, 66 bytes for one raw BF16 margin per candidate, and **98 bytes for one BF16 centered residual per candidate plus one FP32 anchor for each of 8 questions**. These omit scope/key metadata, cache fences, workspace, activation, FP32 upstream work, group assembly and time required for any actual runtime. **98 bytes is not observed service RSS, end-to-end zero-copy, BF16 model efficiency, or full-server total cost.**

## Why this is not yet a production choice

- A full question's candidate slate must be available before an anchor can be computed; streaming and per-candidate isolated inference can pay extra delay and cost. Every anchor must be bound to the exact question, original Encoder/Reader revision, scope, observation/source frontier, generation and revocation. Cross-group cache reuse is disallowed. This study does **not** implement the actual authorized owner-bound cache.
- This keeps an **FP32 computation upstream**. The CPU PyTorch test only physically casts archived *output tensors* to BF16/FP16; it does **not** execute BF16 pretrained Encoder weights, BF16 Reader layers, quantized activation functions, or new physical inference.
- Restoring a few original logit differences is not a new semantic understanding, full-question success or future-window gain. Original human score aggregate reports all 8 original MultiRC questions contain both positive and negative candidate labels. An all-tied/no-query representation remains incapable of completing those questions using only that representation.
- No independent signed source owner, new source/time-disjoint human tasks, p50/p95/p99 serving latency, measured real energy, old-task retention, complete model/Head/Verifier costs, or admitted full FBSDE/System2 improvement. Keep current E12–E14 original real task **NO_GO** intact. E15/E16 original held-out human-label training jobs are separate and must report actual results before any claims.

## Run full local or GitHub research evidence

```bash
ROOT=qualification/shared-stem-system2-architecture
export PYTHONPATH="$ROOT"
export HEPTA_E19_ORIGINAL_ARCHIVE=/absolute/path/to/verified-original-11946621518.zip
export HEPTA_E18_ORIGINAL_ARCHIVE="$HEPTA_E19_ORIGINAL_ARCHIVE"
export HEPTA_E17_REAL_ARCHIVE="$HEPTA_E19_ORIGINAL_ARCHIVE"
python -m unittest discover -s "$ROOT" -p 'test_e19_*.py' -v
python -O -m unittest discover -s "$ROOT" -p 'test_e19_*.py' -v
python "$ROOT/e19_precision_pack.py" --archive "$HEPTA_E19_ORIGINAL_ARCHIVE" --output /tmp/e19-blind.json
sha256sum /tmp/e19-blind.json
python "$ROOT/e19_independent_review.py" --archive "$HEPTA_E19_ORIGINAL_ARCHIVE" --blind /tmp/e19-blind.json --blind-sha256 "$(sha256sum /tmp/e19-blind.json | cut -d' ' -f1)" --output /tmp/e19-independent.json
python "$ROOT/e19_torch_cast.py" --archive "$HEPTA_E19_ORIGINAL_ARCHIVE" --output /tmp/e19-torch-casts.json
```

Dedicated source-HEAD and synthetic-merge jobs reacquire the original exact ZIP, run all 25 new original-archive tests and inherited E18/E17 tests in normal and `python -O` modes, record the original/checkout SHA and original raw results, create-only seal before historical human-score opening, execute actual CPU PyTorch casts, and retain failure artifacts. A workflow definition or an already-passing ancestor is not a passing current-source receipt.

**E19 disposition:** `model_selected=false`, `production_accepted=false`, `system2_fbsde_admitted=false`, `e15_e16_prospective_human_gain=false`, `actual_bf16_model_forward_completed=false`, `online_cost_adjusted_gain=false`, `authority=DENY_ALL`. Keep Draft; never merge, activate or bypass global CI on these diagnostics.
