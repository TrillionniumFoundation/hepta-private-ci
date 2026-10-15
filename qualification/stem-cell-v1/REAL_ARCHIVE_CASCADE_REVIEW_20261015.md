# P0/P1: real pretrained archive confidence-cascade vs one shared Stem

**Status:** `DRAFT` / `DENY_ALL`, historical independent reanalysis. No model download, weight fitting, inference forward, new 4,096-Cell serving, production model selection, NDU/FinalUse authorization or `main` merge. The only model probabilities and per-case times are taken from *previously completed real-pretrained CPU source archives*. This follow-up actually executes new threshold selection and independent heldout numerical replay, **not new pretrained model inference**.

## Original completed physical evidence, not queued CI

- Historical pinned public AG News input/model artifact `11886761368`, run `38541658096`, complete original ZIP SHA-256 `e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d`.
- Historical completed Granite97/mmBERT actual pretrained 352-Encoder-forward-per-model artifact `11908591037`, run `38570704386`, complete ZIP SHA-256 `d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa`.
- Pinned original 128-source AG News val2 material SHA-256 `8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a`. Both original model reports must match independent historical score's exact numerical source digest, 128 real source-group identities, frozen model revisions and original reported scores. Original reports' JSON content SHA-256 Granite `6098b3e5141694fbf841f092631ef7f00abee606eca12a6c82d6249211ee4e57`, mmBERT `d5382f28e60627c0b4e35446b7bef84e9dc5ffb00cd76e4c1ab1b2a99f1cb2ac`.
- Original Granite: `ibm-granite/granite-embedding-97m-multilingual-r2` revision `835ad14087e140460703cf0fae09f97d469d65c2`; mmBERT-small revision `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`.
- Archived source and model report hashes prove byte identity to the recorded results, not independent publisher signatures, contamination absence or prospective time-window independence. Artifact ZIP expiry is a **hard fail**, never grounds for generating replacement results.

## Reanalysis design: 64 source-group calibration / 64 disjoint retrospective heldout

The original 128 `new_holdout` sources are **cross-sectional**, from the same AG News family; they are not a prospective data arrival or two real temporal future windows. Select the first 64 case IDs sorted by `sha256('hepta-20261015-granite97-mmbert-retrospective-fold-v1:'+case_id)` for *calibration*, the other 64 for label-blind *evaluation*. The material owner writes three distinct sealed files: calibration with original human labels, evaluation input with **no label field**, and evaluation-owner original human labels. The policy-fitting process only reads calibration and blind evaluation, never the owner-label file. The score process can open the original owner labels only after the prediction seal exists. As labels are public in the archived ZIP, this provides **procedural** blinding, not secret-holdout independence from the experiment designer or past publications.

Same historical learned-gated 7,434-parameter original Head per pretrained Stem; training/test and model weights are **not** newly matched, retrained or changed. Any observed difference therefore belongs to **model cascade routing on prior outputs**, not to learned Cell Head fission or training a new Stem.

Predeclared calibrator: for each maximum **calibration** second-model budget `0, 10, 25, 50, 100%`, consider only confidence margins `{0, .005, .01, .025, .05, .1, .2, .3, .4, .5}` around Granite's `p=0.5`; route to mmBERT on selected cases. Choose maximizing *calibration correct count*, then minimizing Brier, then calls, then margin. Do not inspect evaluation labels to choose the policy. The realized heldout call fraction may deviate from its calibration target; report its actual value, don't drop it.

Always report strong controls `granite_only`, `mmbert_only`, `dual_most_confident` (compute both, return more confident), **two fixed nonzero margins** `.20` and `.40`, and deterministic hash-random policies with the *same heldout number* of second-model calls. An observed second call consumes the full historical second-Encoder and second-Head time. All-prediction routes and source case counts undergo an independent stdlib-only reviewer; it imports neither model/producer/Torch, reparses the original two SHA-locked ZIPs, recreates the two cohorts, threshold selection, routes, every output probability, source label, observed duration sum and paired recovered/lost counts.

## Actually completed historical-real-model reanalysis: descriptive null/negative

| Heldout 64 source groups | Correct | Additional second Stem calls | Total *summed historical Encoder CPU forward wall* |
| --- | ---: | ---: | ---: |
| **Granite only** | **61/64** | 0 | 2.786 s |
| mmBERT only | 36/64 | N/A (only 1 Stem) | 4.247 s |
| All two models, choose larger confidence | **61/64** | 64 | **7.033 s** |
| Train-only chosen fallback, all registered budgets | **61/64** | **0** | 2.786 s |
| Fixed margin `0.20` | 59/64 | 6 | 3.185 s |
| Fixed margin `0.40` | 54/64 | 15 | 3.757 s |
| Hash-random matched 6 second calls | 60/64 | 6 | 3.152 s |
| Hash-random matched 15 second calls | 55/64 | 15 | 3.767 s |

The trained rules consistently choose **no second Stem**. Two predefined nonzero fallback rules hurt quality and increase archive-summed compute. This is a *negative* result for **this** mmBERT fallback on **these exact historical predictions**, not a general theorem against multimodal specialists, Cell Split, better model alternatives or System2. It cannot support claims of 10T/100T equivalence or general intelligence emergence.

These are independent original per-model CPU forward times **added arithmetically**; it is **not a physically executed cascade**, a single-run wall measurement, end-to-end p99, queue/device overhead, training cost or energy. Model loading/peak RSS cannot be reconstructed by summing per-case forward timings. Accuracy and Brier are descriptive on only 64 source groups, not an independently replicated future-window success or statistically validated universal superiority.

## Commands with two already downloaded, original ZIPs

~~~bash
python qualification/stem-cell-v1/archive_cascade_materials.py \
  --historical-source-zip "$ORIGINAL_AGNEWS_ZIP" \
  --real-physical-zip "$ORIGINAL_GRANITE_MMBERT_ZIP" \
  --output-dir /research/cascade-owner

python qualification/stem-cell-v1/archive_cascade_policy.py \
  --calibration /research/cascade-owner/calibration.json \
  --evaluation-blind /research/cascade-owner/evaluation-blind.json \
  --output-dir /research/cascade-predictions

python qualification/stem-cell-v1/archive_cascade_review.py \
  --calibration /research/cascade-owner/calibration.json \
  --evaluation-blind /research/cascade-owner/evaluation-blind.json \
  --owner-labels /research/cascade-owner/evaluation-owner-labels.json \
  --predictions-dir /research/cascade-predictions \
  --historical-source-zip "$ORIGINAL_AGNEWS_ZIP" \
  --real-physical-zip "$ORIGINAL_GRANITE_MMBERT_ZIP" \
  --output-dir /research/cascade-independent-score
~~~

`python -m unittest discover -s qualification/stem-cell-v1 -p test_archive_cascade_policy.py -v` does not need any real model ZIP or ML dependency; the separate `test_archive_cascade_real.py` suite **requires** `HEPTA_HIST_SOURCE_ZIP` and `HEPTA_REAL_PHYS_ZIP` environment variables pointing to the exact original archives. Both test sets run in normal and optimized Python. GitHub's isolated read-only two-job workflow re-downloads and SHA-verifies the original two *completed* artifacts, runs policy tests first, then source-archive-tamper tests, prelabel fit, independent original-label review and exact hash comparison to the already locally reproduced sanitized receipt. It never uploads raw source text, original/heldout human labels, weights, tokenizer/model or features as artifacts.

## Required next qualification, and current CI blocker

The newly authored #2244 real Granite97 **P2 training-budget** CI run `38688296844` was still queued at its first job when inspected. Other #2235/#2226 exact-head Granite P2 runs were likewise queued at first job. This archival replay **does not mark any of those outstanding new runs complete**. The connector cannot inspect GitHub Actions repository/org runner/allowance configuration; the cause must not be guessed. If no eligible runner is assigned, this lightweight archival workflow also stays queued, and only the separately reproducible local archive result can be reported.

Before promoting any Cell learning claim, independently qualify P0 Reader sufficiency; real acquired source/model lineage and future/source-family tasks, old task retention, like-for-like complete training+inference+router+migration FLOPs/cost, P2 equal-budget actual Granite97 results, signed target Worker and final-use/CAS/WAL/revocation. Production DENY_ALL remains mandatory.
