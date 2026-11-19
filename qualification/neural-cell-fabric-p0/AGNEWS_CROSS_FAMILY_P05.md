# Hepta Neural Cell Fabric P0.5 — original AG News / mmBERT second-publisher shadow audit

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO / NO_MODEL_SELECTION / NO_FINALUSE / NO_PHYSICAL_SPLIT / NO_MAIN_MERGE.** Stacks on **P0.4**; no native production owners edited.

## Why this is a distinct original corpus, and what it does not prove

P0.4 independently re-trained and re-verified the 96 original pretrained 768D ModernBERT feature rows for a historical **binary BANKING77** task; Split Head 20/32 was fully matched by a no-SGD type prior and actual 768D zero-feature lesion. That does **not** imply an Encoder is useless on every task.

This P0.5 slice reopens a **second source family**, original public AG News **4-class** outputs produced with a physically loaded original mmBERT-small pretrained encoder, captured by GitHub Actions run [38546717991](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38546717991), archive artifact `11890616195`, full ZIP SHA-256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`. Historical frozen feature tensor has shape **128 × 384 FP32**, SHA `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`. Receipt reports **16 batched encoder forwards**, not 128 individual independent forward calls. P0.5 executes **no new pretrained Encoder forward or Head SGD**.

It independently re-scores **128 historical precomputed four-arm predictions** (32 held AG News cases per arm) and constructs an entirely **zero-SGD** Dirichlet(1) route prior and a global 4-class prior from the original 64 TRAIN labels. The original 32 CAL labels are never used by these new baselines. Original publisher holdout gold is already **co-located** with the source/prediction ZIP, so this is **NOT a blind source-custody, future-window, prospectively pre-registered or independent-human evaluation**.

## Independent original-label descriptive results

| Original output or new train-only control | Held original correct / 32 | Four-class Brier | Notes |
|---|---:|---:|---|
| Global label prior | 8 | 0.780115 | no Encoder or SGD on new baseline |
| Cell route-only prior | 8 | 0.773727 | no Encoder or SGD on new baseline |
| Learned original linear Head | 18 | 0.624388 | retrospective original prediction |
| Learned original gated Head | **22** | 0.592534 | retrospective original prediction |
| Learned original low-rank Head | 21 | **0.501372** | retrospective original prediction |
| Learned original sparse-expert Head | 13 | 0.890966 | retrospective original prediction |

Gated vs route-only prior: **15 paired wins, 1 paired loss**, nominal exact McNemar **p=0.000518798828125**. This statistical quantity is **post-hoc, from the historically viewed one-publisher panel, with four simultaneous arms**, so it cannot be interpreted as an independently controlled prospective discovery. Frozen untrained gated Head on the same original panel had only **2/32** correct. This indicates a task-specific benefit of trained original Head outputs relative to route counts **within this historical task**; it does **not** isolate whether Cell Split is necessary versus equally budgeted single/shared Head or stronger baselines.

## Study-grade source controls and mandatory blockers

`agnews_crossfamily.py` refuses changed outer original archive SHA, changed 5 inner member hashes, simulated model provenance, wrong feature tensor identity, altered 128 original sample IDs/groups/Cell indices, train/cal/held overlap, missing/duplicate 128 four-arm predictions, unnormalized/nonfinite model scores and inconsistent publisher labels. It extracts **no** ZIP members to disk and uploads no input text/labels/features/individual predictions. `original_fetch.py` obtains the one additional exact GH Actions artifact through the same credential-isolated two-request mechanism as P0.4. The hosted job must fetch genuine original bytes or FAIL; source-only tests skip original-backed cases honestly.

No mixed-task score is calculated across AG News and BANKING77: **they use different task definitions, model families, label spaces, training budgets and source dates**. Thus this P0.5 adds **second-publisher historical context**, not a valid matched cross-source test of one selected shared Stem. It is explicitly not evidence of new 10T/100T-equivalent capabilities, genuine learned NDU-System2 utility, multimodal generation, signed physical CellSplit or Native Computer Use.

## Reproduce on exact already-published public artifact

```sh
cd qualification/neural-cell-fabric-p0
AGNEWS_ORIGINAL_ARCHIVE=/path/to/hepta-agnews-mmb-pretrained-original.zip \
  python3 -m unittest -q test_agnews_crossfamily
python3 agnews_crossfamily.py \
  --archive /path/to/hepta-agnews-mmb-pretrained-original.zip \
  --output /fresh/private/agnews-p05-original-review.json
```

**Next scientific requirement:** a new genuinely future/independent source, common Stem+Head capacity with a matched shared-versus-Split training budget, original source/human gold held by independent evaluator, prelabel seal, complete service resources, retention and enough independent source roots for confidence bounds. Do not select, enable or merge a physical Cell based on historical paper-score wins.
