# P3: Real five-arm paired decoder rollouts (DRAFT, DENY_ALL)

A source-only, auditable next step after the completed negative P1 pilot (#3213) and the strict terminal-risk covariance contract in P2 (#3234). **Nothing here rewrites or reruns P1's 768 final-test episodes.** The purpose of this executable is to **gather missing real, independently evaluated, same-source × same-seed terminal outcomes** for the baseline and the four individual trained Cells. It does not claim to have gathered them in this PR.

## Real output contract

The existing frozen Florence-2 model performs image-conditioned phrase grounding. Every arm receives the same public five-field input, the same task category and the same per-source/seed stochastic sampling seed. Every arm independently executes a model encoder (no across-arm memoization), follows the same prefix/rectangle grammar guard and runs up to 48 generated tokens. Actions:

| `arm` | Decode-time change |
| --- | --- |
| `nochange` | No learned Cell residual, but the identical structural grammar guard |
| `semantic` | Only the semantic Cell logits residual |
| `horizontal` | Only horizontal coordinate Cell residual |
| `vertical` | Only vertical coordinate Cell residual |
| `completion` | Only sequence-boundary Cell residual |

Each Cell acts **inside** the actual decoder, before token selection, not as post-hoc candidate scoring. Sampling uses a fixed temperature and deterministic source+seed generator. The 10-second wall cap is **soft**: non-preemptible encoder calls can overrun and are not discarded. Per-arm costs include that arm's encoder, decoder, applied Cell, control, renderer and unallocated failure/overhead. No cost from another arm is silently shared.

The inference function `run_arm` has **no reference argument**. It only consumes an observation, frozen backend and frozen Cell state. It stores original output boxes, controls, hashes and timing. After **every planned generation** has been written, `to_terminal_batch` independently calls the old evaluator with the separate COCO references, retains loss 1 for incomplete/failed/over-budget outputs, and validates the exact five-arm × same-seed roster against P2. A plan digest binds all resumed rows; new/source changed plans require a different work directory. The job is local, with no communication or device effect authority.

## Original-image exclusion and data limitations

`fresh_cohort.py` reads the original 384-image historical exclusion registry AND the original 256-image P1 cohort source manifest. It constructs an immutable 640-image exclusion registry without reading P1 predictions or experimental scores. The original P1 manifest lives in the downloadable P1 evidence ZIP under `cohort/manifest.json` (SHA256 `71168c26fffdd913d71a69d8708cec957f55dc2bece112c9c50153fbf31de75d`). Both historical sources must pass their original frozen byte-hash checks. The original historical wrapper is `qa/ndu-grounded-generation/historical_exclusions.json`.

Then it calls the previously published official COCO loader with a **new selection seed** and requires exact-image and dHash near-duplicate checks. It builds 128 train / 32 dev / 32 reserved calibration / 64 untouched test original-image groups. **COCO original-image isolation is not real-world entity isolation or proof of absence from foundation-model pretraining.** The model and Cell weights remain fixed across all rollouts, and the SHA256 of every involved implementation, checkpoint, objective, source list and protocol is recorded.

## How to execute on a permitted project worker

From the repository root, install the v1 pinned dependencies (as already documented in `qa/ndu-grounded-generation/README.md`). Set `$MODEL` to the **verified original Florence-2** directory, `$CELLS` to the **preserved P1 trained cells.pt** (SHA256 `1508a2f4f633b1fa44e05f2a7b750c642e3a39360cf59224d3d4790f31a04396`, now enforced before generating), `$ANNOTATIONS` to the official pinned `instances_val2017.json`, `$PRIOR_V1` to the preserved original P1 `cohort/manifest.json`, `$OUT` to a **fresh empty run directory**.

```bash
python qa/ndu-real-paired-rollout/fresh_cohort.py \
  --official-annotations "$ANNOTATIONS" \
  --historical-exclusions qa/ndu-grounded-generation/historical_exclusions.json \
  --v1-cohort-manifest "$PRIOR_V1" \
  --output-cohort "$OUT/cohort" \
  --image-cache "$OUT/images" --download-images

python qa/ndu-real-paired-rollout/paired_rollout.py \
  --model "$MODEL" --cells "$CELLS" --cohort "$OUT/cohort" \
  --work "$OUT/rollouts" --split train --budget 10 --seeds 23,41

python qa/ndu-real-paired-rollout/paired_rollout.py \
  --model "$MODEL" --cells "$CELLS" --cohort "$OUT/cohort" \
  --work "$OUT/rollouts" --split dev --budget 10 --seeds 23,41
```

This plans 1,280 real train and 320 real dev single-arm episodes. Calibration remains reserved and **TEST is deliberately sealed**: the code hard-rejects attempts to open the blind split until independent risk-policy selection, calibration and preregistered release checks exist. Do not disable this gate to make a report look complete. Parent scoring runs only after real outputs exist; the existing P2 `fit` may then consume the **train** terminal batch, and `evaluate_frozen` may consume only held-out dev. Neither phase in this PR implements actual risk-sensitive multimodal combination or independent free-form image/text generation.

## Checks and release boundary

```bash
python -m unittest discover -s qa/ndu-terminal-portfolio -p 'test_*.py' -v
python -m unittest discover -s qa/ndu-real-paired-rollout -p 'test_*.py' -v
```

Eight new tests use a small **FAKE** backend and synthetic PNGs. They verify same-seed source input, causal logits modification, reference exclusion, exact roster, failure cost, source-hash guards and previous cohort exclusion. They are **not new real model results**. Any future real run must retain independent score, source provenance, timing, full trajectories and blind-test authority. Do not report tail-risk diversification just from a linear surrogate; only actual combined-output runs can validate a frontier.

Status: **DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. No implicit tool authority, model promotion, real-device execution, memory writes, topology evolution, merge approval, or production release.
