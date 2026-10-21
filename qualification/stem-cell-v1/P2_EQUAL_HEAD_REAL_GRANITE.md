# P2 — Equal-resident-parameter Cell specialization vs unsplit and fixed routing

**Research-only / Draft / DENY_ALL.** Child of pinned P1 public Granite97 source study #2160. No original product model, selected Stem, NDU, System2, CellSplit runtime, FinalUse, CNS, or `main` change.

## Single causal question

On the same frozen real Granite97 **384D CLS/L2/Q24** feature bank and original AG News binary labels, does a train-only adaptively specialized two-Cell bank beat **the equally sized true single wide Head, the unrouted two-Head ensemble**, or fixed routing **after actual training and inference cost**? This is a *retrospective cross-sectional diagnostic*, not a qualification for Cell fission or lifelong learning. We implement **both** a true single rank-16 wide Head (with an additional learned affine skip to reach the identical parameter count) and an unrouted two-Head ensemble. Strict equal-active-FLOP/optimizer-work comparison remains a separate scientific gate.

## Original-source material and split

Reuse the exact P1 train and blind material owner, not a separately selected dataset: `p1_real_granite_cohort.py prepare`, pinned SHA `2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4`. Train = 128 original human-labeled public AG News rows. Calibration = 32, test = 64, **input/identity only** before prediction seal. Each original text/source ID is unique. Independent reviewer later reopens the unmodified original panel and its material-owner labels, and uses the source input digest and original ordered 96-case denominator.

`old_train` = first 64 train rows in the previously pinned original training order; `new_train` = remaining 64. These are **not time-disjoint or independent future data**, and retention evaluated on train examples cannot be described as future generalization. Routing threshold is the median of the *train-only* first Granite feature coordinate, selected without looking at calibration or test labels. Such a coordinate is not automatically a meaningful semantic cell type.

## Same-sized physical Head bank and true monolithic wide control

Each Head has 384D frozen input, 64D deterministic proxy state, rank-8 residual, **binary** logits: `down(384,8) + gate(64,8) + gate_bias(8) + up(8,384) + out(384,2) + out_bias(2) = 7,434 FP32 trainable scalars`. Exactly **two distinct physically resident Heads = 14,868 FP32 scalars / 59,472 weight bytes** for **every** comparison arm; the Stem is one separately loaded frozen 97M model. No hidden trainable router parameters or frozen Head parameter aliases. The 64D state here is simply the first 64 frozen feature components, **not** learned recurrent memory.

| Arm | Training & routing | Physical/tensor budget |
| --- | --- | --- |
| `frozen_no_change` | Frozen initialized two-Head ensemble, no SGD | Same two resident Head slots; zero updates |
| `unrouted_equal_parameter` | Mean of both Heads' logits; two-slot unsplit ensemble | Both Head slots train; 20 old-only + 20 old-and-new SGD updates |
| `wide_single_equal_parameter` | **One** rank-16 residual Head plus independent learned binary affine skip, all 14,868 parameters actively used | 20 old-only + 20 old-and-new SGD updates; same 14,868 resident parameters |
| `fixed_two_cell` | Predeclared first-coordinate threshold routes to one of two independently trained Heads | Same two resident Head slots and 40 SGD steps |
| `adaptive_train_only` | Fit parent 20 old-only SGD steps, compute **train-only** old/new Brier excess; split at excess >0.03, clone parent weights exactly before new training; fit 20 old-and-new SGD steps, otherwise retain parent | Two Head slots resident, no test-label-driven split or optimizer reset trick |

All **four trained arms** see **3,840 registered training row exposures** and 40 optimizer steps; the fifth frozen arm performs zero updates. Fixed and adaptive routing use fewer *effective* parameters per individual request than the unrouted two-Head ensemble; active FLOPs, gradients and end-to-end costs are **not physically matched** by fixed update counts. The report always sets `exactly_equal_active_flops_verified=false`; a true strict FLOP-controlled study must follow before attributing any gain to adaptive structure rather than compute or routing.

The source-runner loads the exact pretrained Stem once, executes all **224 original source Encoder calls**, freezes full Stem tensor identity before/after fitting, and writes 96 original-case predictions per arm. Source feature Q24 vectors, fitted FP32 weights and logits are temporarily retained **locally for independent numerical replay**; they are excluded from the Actions upload. The decoder, NDU, 4,096 production Cell execution, power and target-host p99 remain unmeasured.

## Independent score, numerical replay and negative outcomes

The independent evaluator replays **all five** arms, including the single wide Head, and imports only `numpy` and the **existing** P1 original-source reviewer, never Torch, the new trainer or a model loader. It independently opens original calibration/test human labels **after** the unlabeled prediction record exists, checks original panel bytes and full case identity, decodes every Head parameter from little-endian FP32, recomputes each heldout logit from independent matrix equations, and reports per-partition accuracy/Brier, paired recovered/lost cases against the unrouted 14,868p baseline, explicit split status and recorded CPU work. It rejects rehashed but changed logits, source features, weights, train schedules, original label bytes or fake result flags. The report is source-internal integrity evidence, **not** independent publisher-origin or host/weight attestation.

The local unit test uses a seeded **random 147,840p toy Linear Stem** whose outputs satisfy the same Q24 interface. This is true PyTorch numerical training, not Granite97 pretrained efficacy. Sign, direction and magnitude of score differences in the toy are NOT accepted as qualitative causal effects, and all null/negative contrasts remain visible.

## Execute

The source checkout contains the original P1 material already:

```bash
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_p2_real_cell_split.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_p2_real_cell_split.py' -v
```

For the **real pinned public model** (only in separately scoped hosted job with exact source checkout and verified safetensors):

```bash
python qualification/stem-cell-v1/p2_real_cell_split.py \
  --train-material /approved/source-owner/train.json \
  --blind-material /approved/source-owner/blind.json \
  --compact-source /approved/pinned-compact \
  --output /approved/p2/unscored.json

python qualification/stem-cell-v1/p2_real_cell_split_review.py \
  --original-panel /approved/original-panel.json \
  --train-material /approved/source-owner/train.json \
  --blind-material /approved/source-owner/blind.json \
  --owner-labels /approved/source-owner/owner-labels.json \
  --report /approved/p2/unscored.json \
  --output /approved/p2/independent-score.json
```

No result is accepted until the exact-source hosted pretrained job, NumPy replay, inherited `blocking-ci`, security and product-level owner reviews actually complete. Test status must be taken from **this exact commit**, not an ancestor.

**Unresolved:** true time-disjoint future windows, independent source/semantic label adjudication, Reader sufficiency, stronger external/reference Readers and alternate unsplit architectures, strict equal-*compute* comparison, 4,096 real target-Worker cohort, memory/energy/p95/p99, signed current authority, NDU vs cheap Bellman/Critic, multi-modal generation, and any 10T/100T capability claim. `production_promotion_permitted=false` always.

## Actual local three-seed negative control (not pretrained Granite97)

The versioned toy evidence receipt `P2_LOCAL_TOY_REPLAY_20261015.json` contains **three independently initialized frozen 147,840p random** Stems (seeds 41/47/53), every full model report digest, and the separately recalculated 96-case descriptive accuracy/Brier scores from the original **fake** source fixture. All three synthetic trials admitted a train-only split; on original-shaped 64-case test subsets, the **unrouted two-Head 14,868p control** scored **46/64, 39/64, 41/64**, while adaptive split scored **42/64, 38/64, 40/64** respectively. The true 14,868p wide single-Head control scored **42/64, 37/64, 41/64**. Retain this unfavorable/non-superior result; seeds and fake labels do not identify any generalization, superiority, or statistical effect in pretrained systems. No real publisher label, prospective future period or authentic model forward was tested in this local receipt.
