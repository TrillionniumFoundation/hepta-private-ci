# Hepta P1 — Pinned Granite97 + genuinely source-bound 64–4096 Cell cohort

**Research-only / Draft / DENY_ALL.** This experiment is stacked only on the original #2141 physical shared-Stem Cell cohort and reuses its exact `PackedGatedHeads` / independent native `F.linear` mathematical controls. It does **not** replace the original research model loader, `inference.control`, selected model, signed FinalUse, production `neuron.runtime`, data authority, NDU, CNS, Cell Split owner or protected `main`.

## Why this experiment is necessary

#2141 executed 64/256/1024/4096 physically resident 9,744-parameter Cell Heads and correctly reported shared Encoder work. However, that original Encoder contained **147,840 randomly seeded parameters** and its labels were synthetic. No real pretrained task-quality, original publisher source or total-load cost conclusion follows from that panel. A 4,096-Cell *population* is also **not** 4,096 simultaneously active Cells or 4,096 independently capable 421M models.

This prospective extension joins actual pinned real pretrained public-model execution, the original English AG News **128 train / 32 calibration / 64 test** source groups, full 4,096 physically resident Heads, sparse real *train-only* gradients, frozen and genuinely trained binary Reader controls, and a separately label-opening stdlib scorer. It includes deliberately unfavorable no-cache and limited-real-source controls. No existing E1/Reader/no-change evidence is altered or imported as a passing result.

## Exactly pinned external owners and provenance

1. **Full Granite R2 model**: `ibm-granite/granite-embedding-97m-multilingual-r2` at revision `835ad14087e140460703cf0fae09f97d469d65c2`, using **only** the upstream existing `FrozenCompactStem` in repository commit `e05f939f65fb76f6bdbf7470eef7e63b77284dcd`. Genuine official CLS + L2 pooling, 384D, local-only, no remote code or pickle checkpoint, Q24 quantization, <=512 original tokens and no silent truncation. The checkpoint is independently acquired against the exact Hugging Face revision and all available publisher LFS SHA256s *in hosted CI*; this runtime itself still has no independent publisher signing capability.
2. **Public source**: original `public_agnews_source` / `public_agnews_panel` at `f8d168a7689eb3624d97c44751791badd069e521`, then the original `e1_public_triplet_real_cpu.load_panel` at exact E1 commit `09bb40d8bf3a058a34607179d4e0fbdf11a41277`. Original 224-case canonical panel SHA256 **`2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4`**. Public English world/sports labels are **retrospective cross-sectional**, not secret future outcomes or independent issuer signatures. Publisher train/validation parquet bytes are checked by the original source owner.
3. **Existing Head owner**: #2141's packed 384-feature / 64-state / rank-8 / 8-output Head: 9,744 parameters per actual Cell; 4,096 resident Heads contain 39,911,424 independent private scalars / 159,645,696 FP32 payload bytes. A separate **770-parameter binary linear probe** is trained only on original 128 train cases for 40 complete SGD steps and evaluated after that training on the original 96 calibration/test cases. Frozen/no-change, learned and train-label majority controls must not be confused with physical specialist Cell quality.

## Physical experiment and exact usage costs

Each cohort loads a single frozen Granite97 checkpoint once per hosted process, verifies the CPU model tensor byte digest before/after **private Cell-only** training, and actually computes 224 unique public input features once for a label-blind evaluation bank (128 train + 96 blind evaluation). The binary linear comparator uses only train labels; original human evaluation labels are never accepted as a parameter of the physical runner. The independent scorer opens the original owner labels later.

For each size 64 / 256 / 1,024 / 4,096, activate precisely `max(8, floor(N/10))` Cells and allocate **all** private Head weights. Every active Cell performs actual packed forward and two sparse SGD steps using a genuine original **train** label, with dormant tensor bytes preserved. Frozen and trained Head outputs are independently reconstructed with per-Cell `F.linear`.

| Input distribution | Actual distinct sources when 409 Heads active | Legitimate full-cache behavior |
| --- | ---: | --- |
| `repeated4` | 4 original test source texts | 4 physical Stem calls + 405 feature reuses |
| `test_panel` | **64**, not 409 | 64 physical Stem calls + 345 reuses; never invent 409 independent test families |
| `two_scopes` | 4 original texts / 8 principal-scoped keys | 8 physical Stem calls + 401 permitted same-principal reuses |
| Zero-byte cache negative control | Same original source roster | 409 physical calls + 0 cache hits |

Counts above are **expected reference identities** for a successful 4,096-Cell hosted execution. They are **not newly measured public Granite97 numbers until its exact-head workflow completes**. The 26 local tests use a non-pretrained small *fake* 384D local PyTorch Encoder and carry `pretrained_weight_execution_claimed=false`. They verify algorithmic controls, not the actual pretrained checkpoint.

Every original source used by multiple Cells has a key bound to the exact public source group + original input SHA256, named principal, scope, generation, authority epoch, selected revision and readout. A per-use research hook executes even on cache hits. This hook is **not** original signed FinalUse. A case cannot change group, answer option, tokenizer/model identity or tenant and still silently hit the old cache.

The report separately records: model-load cost; **224** baseline unique feature materializations; the uncached versus cached Cell *additional* actual Stem API calls; precise per-use Cell/Encoder observations; real Head training and test forward time; resident Head tensor payload; process lifetime RSS; complete source/Head quality-probe costs. Source-materialization work is **counted in both arms** and is never misrepresented as saved inference. Order-biased Python CPU timings are descriptive; no independently qualified request p99, GPU, energy, physical Transformer kernel count or full 421M replication cost is claimed.

## Fail-closed genuine task and independent scoring

Source owner `prepare` produces separate create-only **train-with-labels**, **blind calibration/test** and **owner-only evaluation labels** artifacts. In real hosted execution, the physical model runner receives **only train + blind material**. The independent stdlib `p1_real_granite_review.py` later loads the exact original source panel and the withheld evaluation-label file; it independently rebuilds all 224 identities and both frozen/learned prediction denominators, recomputes descriptive accuracy/Brier and paired recoveries/losses, verifies physical Cell counts, negative cache cases, costs and the model's unchanged weight digest claims, and always returns `DENY_ALL`.

No successful numeric result can be relabeled into authenticated publisher provenance, three real future time windows, Reader sufficient-evidence entailment, old-task retention, qualified NDU/FBSDE net utility, video/audio/image generation, original Rust Worker performance or 10T/100T general equivalence. Even if the real pretrained binary probe beats its frozen initialization, **that result does not establish that 4,096 Heads learned new language abilities**. The binary readout and the 9,744-scalar specialist bank are separate roles.

## Local source-only tests (do not load pretrained weights)

```sh
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_p1_real_granite_cohort.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_p1_real_granite_cohort.py' -v
python -m compileall -q qualification/stem-cell-v1/p1_real_granite_*.py \
  qualification/stem-cell-v1/test_p1_real_granite_cohort.py
```

**27 distinct numerical/adversarial tests** passed locally in *each* of the normal and `python -O` runs, no skipped methods. Includes a complete 14-slot same-mock-Stem cohort with 14/14 independent source/quality/cost numerical audits, and CPU tensor residency at 4,096 physical Heads under mocked public-feature protocol; 409 active; 64 legitimate original-test keys (not mislabeled as 409 independent tasks); 8 source/principal-scoped keys; fully null/insufficient cache; physical frozen weight and dormant-Head equality; train/holdout label separation; original-panel and label tamper; full model API cost census; and false production/weight-origin assertions. Mock weights never qualify pretrained efficacy.

## Hosted real-weight stages (no fake/fallback model permitted)

Dedicated `.github/workflows/hepta-p1-real-granite-cell.yml` verifies the exact source SHA, runs source-only regression suites, uses **pinned** read-only checkouts for the three existing research owners, acquires original checked public AG News bytes, downloads only exact public safetensors/tokenizer/JSON model files, checks publisher LFS hashes, then performs `run-batch`: all **four** resident Cell populations x **three** distributions plus two zero-cache negative controls while keeping one selected real checkpoint in RAM. The source documents original cohort failures rather than silently treating missing workloads as successful. An exact independent post-seal scorer must then run to emit a valid descriptive score.

Relevant commands for the **hosted prepared** paths:

```sh
python qualification/stem-cell-v1/p1_real_granite_cohort.py prepare \
  --original-panel "$ROOT/panel.json" --e1-source pinned-e1 \
  --output-dir "$ROOT/original-material"
python qualification/stem-cell-v1/p1_real_granite_cohort.py run-batch \
  --train-material "$ROOT/original-material/train.json" \
  --blind-material "$ROOT/original-material/blind.json" \
  --compact-source pinned-compact \
  --output-dir "$ROOT/cohorts"
python qualification/stem-cell-v1/p1_real_granite_review.py \
  --original-panel "$ROOT/panel.json" \
  --train-material "$ROOT/original-material/train.json" \
  --blind-material "$ROOT/original-material/blind.json" \
  --owner-labels "$ROOT/original-material/owner-labels.json" \
  --report "$ROOT"/cohorts/*.json \
  --output "$ROOT/independent-score.json"
```

**Required next evidence after this:** genuinely independent future task data, matched shared versus real independent 421M copies including cold loads, complete native target-host p95/p99 and RSS/energy, independent Reader outcome, semantically meaningful Cell specialization and equal-parameter fixed-Router/no-split controls, stable Cell retention, signed owner CAS / WAL / FinalUse, crossmodal actual generation, real NDU net utility and exact-source `blocking-ci`. Do not auto-merge or promote on source-only green tests.
