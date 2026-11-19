# P0.8 — one physically shared mmBERT checkpoint, distinct news publisher, label-separated evaluation

**RESEARCH_ONLY · SHADOW_ONLY · DENY_ALL · HOLD_NO_GO · NO MODEL SELECTION · NO MAIN MERGE · NO FINALUSE · NO NATIVE EFFECT · NO PHYSICAL CELL SPLIT**

## Research question and factual scope

P0.7 showed that existing frozen Encoder features carry information on two **different** historical tasks, but used different encoders and did not test one Stem across sources. P0.6 showed Split did not beat a stronger train-only centroid on one old AG News panel. P0.8 asks whether a **single, newly reloaded, immutable pretrained checkpoint** can support both the original AG News task and an independently published HuffPost topic sample under identical readout policy. It is a cross-**publisher** transfer experiment, *not* a prospective time-window study.

No P0.8 hosted original checkpoint forward or genuine HuffPost score should be claimed until the `producer` and `independent-reviewer` jobs have both executed successfully on the exact P0.8 HEAD. The isolated authoring CPU runs source/adversarial and synthetic-feature numerical tests, plus exact **historical** AG News ZIP audits. Neither is a new model result.

## Locked source and model materials

| Material | Immutable identity | Provenance constraint |
|---|---|---|
| Training + old holdout | Existing independent GitHub Actions AG News/mmBERT archive, outer `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7` | Existing original public study used the *different* checkpoint `abc32620dd4f6ab06f5fbe905dc25f310618e09f`; its old score is NOT reused |
| New cross-source test | `heegyu/news-category-dataset@304a05a55bc6abc0446d8fae0d0771716b6a271a/data.json` | Full 87.3 MB original SHA-256 `2cfc51fa4a82a96ecbe251fa383737aa1dea2e0a517f61dece633fcc25a4a065` |
| *One* shared pretrained Encoder | `jhu-clsp/mmBERT-small@0eb3d056ec1d6333cf4e19b0966dfde342a41a3a` | Reviewed 564 MB safetensors `7ee7a6939b730a35e5d2a3e2263a1d1e992d10bc7f86b3470e9cb3cd482c590d`; tokenizer `197d4cc5406ee12cc50c8b5511f2393cc32d9db321545979ce041c1199178356` |

The new *safetensors* revision differs from the legacy `.bin` revision, even though both are called mmBERT-small. **P0.8 always re-encodes all 128 rows using the same newly SHA-locked safetensors checkpoint**. This isolates the within-experiment Stem identity; it does not prove a byte-identical replacement for the earlier P0.6 stem.

## Frozen panel and no leaked transfer labels

- **FIT**: 64 original AG News examples. Real human-supplied original publisher training labels are allowed to the Head optimizer. No original CAL or HOLDOUT label may enter.
- **Old-task retention**: 32 original AG News historical HOLDOUT examples, unlabeled to producer; retrospective outcome owner opens original archive only after seal.
- **New source transfer**: exactly 32 HuffPost historical headline+description texts, 8 examples each in four pre-registered publisher labels `WORLD NEWS→World`, `SPORTS→Sports`, `BUSINESS→Business`, `TECH→Sci/Tech`, timestamp range 2013–2022. Selection is deterministic by domain-separated SHA over source URL + text, with a final independent SHA shuffle. This selects a **balanced artificial panel**, not the natural publisher class distribution.
- Text has a maximum 768 source UTF-8 bytes and is trimmed to 128 tokenizer tokens by the *single* Encoder for both datasets. Duplicate exact case/text identities fail closed. Exact duplicate checks are not semantic dedup or contamination proofs.
- AG News `World`/`Sci-Tech` and HuffPost `WORLD NEWS`/`TECH` are not guaranteed identical concepts. In particular, HuffPost's `SCIENCE` category is **not** mapped to Tech. All reported transfer scores carry `cross_publisher_label_ontology_exact=false`.

The curator job downloads and reads the original publicly labeled HuffPost corpus to freeze a balanced test set; it uploads only AG News training labels and **label-free** held/transfer texts. Thus the physically separated producer job receives no test labels from the curated panel. The later review job separately re-downloads the publisher source and checks exact source bytes, case IDs, prediction seal and gold commitment before scoring. This is **process/job label separation, not an independent human gold issuer or cryptographic proof that the curator never saw labels**. The corpus pre-dates 2026 and is not a new prospective publisher event stream.

## Training and paid controls

All Head candidates use `FP64 NumPy`, `384D L2-normalized actual frozen features`, `512 per-active-head SGD updates`, `lr=0.05`, weight decay `0.0001`, three seeds 101/211/307. One active Head has 4×(384+1) = **1,540** FP64 scalars. A two-Cell Split has 3,080 resident scalars; it pays the **same** 512 per-example SGD updates and active parameter touches as a single shared Head, but **not equal memory capacity**. Never report equal model capacity.

A data-only two-way Cell router is trained with eight iterations of unsupervised k-means on the **64 training examples only**. It is reused unchanged on the old and new source. Independent SHA-random routing provides a negative control. The downstream original labels cannot change the routing geometry. Controls are: shared-one, Split, random route, frozen initialization, swapped Split route, zero-feature Split, train-only global and route priors, plain centroid and train-only LOOCV-calibrated centroid. The centroid pays 512 additional LOO evaluations across its frozen eight-temperature grid, although its SGD cost is zero.

Old-task retention, new-transfer 4-class accuracy, multiclass Brier and log-loss, and paired Split-vs-centroid/Shared outcomes are all reported. Do not collapse predicted task scores into NDU recursive utility; no NDU trained policy, FBSDE or System2 uplift is established.

## Exact execution workflow and security boundary

`hepta-cell-fabric-p08-huff-transfer.yml` is a read-only, same-repo-only, SHA-bound experimental Actions workflow:

1. **Source tests**: ordinary and `python -O` adversarial tests without HF material or pretrained model downloads.
2. **Curator**: SHA-verify existing actual AG News source and independent HuffPost corpus, export short-lived unlabeled test text with a SHA256 hidden-gold commitment. This step reads publisher labels only to freeze a class-balanced panel.
3. **Producer**: **does not receive test labels**. Download pinned, SHA-verified, safe `model.safetensors` and tokenizer; load with `trust_remote_code=False`, genuine CPU `ModernBertModel` forward for all 128 rows in batches of four, no test-label training. Freeze independent Head outputs, exact resource and model identities in a create-only 0600 prelabel file; publish short-lived encrypted-in-transit Actions artifacts (not repository files).
4. **Independent reviewer**: after *producer success*, reacquire both original datasets and their SHA-locked gold, reconstitute exactly the same publisher case identities and previously sealed prelabel SHA, verify work/memory claims, compute descriptive per-arm results. Upload **aggregate only**; no raw articles, held labels or per-case scores in the final report.

Data artifacts are short lived and may contain public publisher text or sealed per-case model scores for transfer between trusted GitHub runners. They are **not** private signed issuer evidence. The producer's CPU/forward counters are *self-reported process observations* rather than hardware attestation. No workflow may mutate live model selectors, application state, authorization, or `main`.

All failure modes (missing upstream bytes, stale SHA, unavailable pretrained model, mismatched outputs, privacy or provenance drift, wrong label-seal ordering, timeout) are `HOLD_NO_GO` and make the actual research workflow fail. There is no simulated replacement for a failed original forward or loss of publisher material.

## Proof limits and ordered next evidence

**P0.8 can at best establish historical cross-publisher transfer of ONE frozen Stem on one balanced, mapped-label panel.** Even a strong score would not prove that Cell splitting generalizes: compare Split against Shared and train-only LOOCV centroid under all three seeds, old-task retention and total physical serving costs. `NO_MODEL_SELECTION`, `NO_CELL_SPLIT`, `NO_FINALUSE` are unconditional. To claim genuine *future-window* utility, register and freeze a later independent publisher sample **before its original labels are available to the model producer** and obtain independently controlled gold after seal. To claim motor/CPU/GPU/UI speedup, run full final-use and same-work host measurements with original authorized OS readback; no such effects occur here.

## Reproduction

Local source-only (historical AGNews original ZIP optional; skipped original-specific cases are not successes):

```bash
cd qualification/neural-cell-fabric-p0
python -m unittest -q test_p08
python -O -m unittest -q test_p08
```

Real publisher/model execution takes place only through the exact-head four-job P0.8 Actions workflow. The original AG News ZIP is acquired via `original_fetch.py` with its own immutable hash, no fake source path. The final status must be checked on the PR's *latest commit*; prior-head CI green is not transferable.
