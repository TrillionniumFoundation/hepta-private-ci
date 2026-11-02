# V10 historical frontend training

This is actual ordinary-head fitting and common-cache execution, not another asset checker. **No stronger frontend was qualified.** The six-class emotion task, 48 recordings and eight actors are inherited historical V3 material. Missing v6 heads, complete historical exclusions, genuine new recordings and five-class/semantic-binding qualification remain unavailable.

`DATA_INVENTORY.json` records the available arrays and original recording/actor/label identities. There are 24 training clips from four actors, 12 validation clips from two actors, and 12 already exposed old-test clips from two actors. The available original-rate features have 16 log-mel audio coefficients or 16 low-frequency visual DCT coefficients per observation. Actual waveforms and decoded video pixels are absent from this recovered material. The ordinary model sees only causal content and fixed physical temporal bins, excluding source/actor IDs and labels from inference inputs.

Two executed campaigns are kept separately:

- `results002`: 216 actual fits—audio, video and AV, each with 72 train-only ridge/kernel candidates. Features use the same 0.1-second causal window payloads as V3. Every weight, training/validation prediction and candidate metric is retained. Minimum validation NLL chooses once before old-test scoring in this run. `source001/fit_frontend.py` preserves these exact source bytes.
- `results003`: 288 actual fits after the first campaign failed to improve accuracy. Adds a spectral-shape family and uses original-rate 16-dimensional observations before window compression. This is an explicit **additional-information development diagnostic**, not a same-information gain. Its protocol records the prior failure; no old-test independence or prospective source publication is asserted.

| Input / selected ordinary head | Validation correct / 12 | Old-test correct / 12 | Old-test NLL | Original V3 old-test correct / 12 |
|---|---:|---:|---:|---:|
| Window audio | 4 | 3 | 1.735232 | 3 |
| Window video | 2 | 1 | 1.809044 | 2 |
| Window AV | 3 | 2 | 1.693247 | 5 |
| Native-rate audio | 4 | 3 | 1.721183 | 3 |
| Native-rate video | 2 | 2 | 1.796430 | 2 |
| Native-rate AV | 3 | 2 | 1.724264 | 5 |

All values use prefix three seconds and the same old recordings. The first campaign's AV NLL improves over the original head's 1.877591, while its accuracy falls from 5/12 to 2/12. That is a retained failure, not a calibrated-correctness, noninferiority or strong-audio result. Prefix-one/two outcomes are retained as supporting diagnostics; they are not separately trained confirmation cohorts. The ordinary reference is a finite grid, not an upper bound on what an audio architecture can do. No binding task was trained or qualified by these runs.

The new `OrdinaryCacheHead` actually applies the selected window model to the shared immutable cache. All 432 historical modality × prefix × split output vectors reproduce saved probabilities within 2.998e-15. That arithmetic check preceded two added constructor guards: final-source checks separately reject wrong weight bytes and native-rate weights used with a compressed window cache, then verify one real cache output. Their exact scope/source hash is in `CACHE_IDENTITY_HARDENING.json`. The adapter supplies class probabilities only; it does not pass maximum softmax off as empirical correctness or install a controller.

The independent `audit_saved.py` imports none of the fitter, its model or metric code. Final audits bind predictions to original archived recording IDs, actors and labels, reproduce every training kernel and normal-equation residual, independently recompute saved candidate metrics, check minimum-NLL selection and compare all selected arrays to the selected candidate. `AUDIT002_FINAL.json` and `AUDIT003_FINAL.json` contain the actual completed receipts. Feature construction and media decoding are outside that saved-arithmetic audit.

The initial worker failed because the default environment could not import Torch required by the inherited data loader. Its exact failure, source protocol and **0.440052 CPU seconds** remain in `cost001/results001`. The existing `/tmp/hcsn-torch-runtime` was then reused; no dependency was installed. The successful complete enclosing workers cost **4.423258** and **37.493400 CPU seconds**, including imports, fitting, saved predictions, original-head comparisons and outputs. Their nonoverlapping total including the failed worker is **42.356710 CPU seconds**. This is a measured lower bound for these three workers; independent audits, adapter checks, development retries and historical preparation are outside it. Full-family memory and device energy remain null. No H=20 economics or production acceptance claim follows.

From the repository root, provide the already available Torch import path (or an equivalent installed compatible Torch), then use a new output directory:

```bash
PYTHONPATH=/tmp/hcsn-torch-runtime:$PWD OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost \
  --out /new/output/frontend_cost --timeout 300 --sample-interval .5 -- \
  python -m experiments.hcsn_v10_followup_20261101.frontend.fit_frontend \
  --input-policy native --out /new/output/frontend_fit

OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.hcsn_v10_followup_20261101.frontend.audit_saved \
  /new/output/frontend_fit --out /new/output/frontend_audit.json
```

The current script has four feature families. `--input-policy window` therefore runs the extended 288-fit window version; to reproduce the original 216-fit window campaign, use the exact preserved `source001/fit_frontend.py` as the module source in an isolated source copy. All preexisting v9 evidence bytes remain unchanged.
