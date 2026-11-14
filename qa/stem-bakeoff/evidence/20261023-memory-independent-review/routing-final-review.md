# Final independent review — fixed-weight routing diagnosis, run-002

## Verdict and evidence identity

The completed event is internally consistent with its frozen development protocol. Independent retained-evidence reconstruction found **no experimental mismatch in 19,379 comparisons**. This establishes execution/evidence integrity within the inspected local environment; scientific phase-3 qualification remains open.

Evidence root `E` = `/workspace/scratch/12ef9c5bdc23/routing-diagnosis-work/run-002`.
Frozen repository `R` = `/workspace/scratch/12ef9c5bdc23/hepta-memory-work`.
Historical population `H` = `/workspace/scratch/1d69f04ee9f4/memory-population-20261023`.
Exact executed diagnosis modules are in `E/diagnosis-source`; their original top-level copies remain in `/workspace/scratch/12ef9c5bdc23/routing-diagnosis-work`.

- `E/result.json` SHA-256: `916d71c43c09a80ccd942bacb63dd4eeace98c66340f67181cafbf3884ddf9a3`.
- Repository HEAD: `d61a36e21d1ad6d90614c145455b88c647c430e8`; tree: `0d90b68980aec0b927f89a66e4d6c767616c3edc`; tracked worktree clean.
- Exact five-module source-map digest: `f618cc5c165f198e906691f8a84ac80a2ba7f9c5cc6ce3fee596a60370a4e511`.
- Independently checked 107 repository Python files, all five executed modules and retained copies, 201 historical JSON reports, 48 checkpoint files, and all six publisher base files against prepared pins.
- Base model publisher bytes total 271,170,520; SmolLM2-135M-Instruct revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`. Both SHA-256 and the registered publisher Git-blob/LFS digests were checked, without importing model code.
- Pin chain: `E/prepared.json` → `protocol.json`, `input-pins.json`, `source-identity.json`, `cohort-pins.json`; start receipt binds prepared bytes. Final rehash matched; no old checkpoint/report/source was altered by this audit.

## Raw evidence, source utility and frozen routing

1. Each seed has 304 source questions read by both fixed children: 608 fresh raw outputs become 304 two-expert utility observations. All 912 observations across three seeds were reconstructed from `source-expert-*/...-stdout.json`, retained journals and source capabilities; utilities were not copied from old evaluation answers.
2. A utility is exact raw text equality **and** capability eligibility; unsupported/mismatched ancestry cannot earn credit. Explicit negatives and rows where neither child succeeds train rejection. This is supervised source-label learning from a trusted local research fixture, not autonomous fact verification.
3. All 27 decoder processes' request, owner admission, scope, rank/seed, questions, prompt/generated token counts, effective state and adapter tensor/state digests matched retained bytes. Safetensors container-file SHA, sorted tensor-content SHA, and shape/dtype/state SHA were treated as distinct contracts.
4. `diagnosis_trial.run_seed` supplies only final `probe_id/question/family/operation/source_roots` to `diagnosis_routing.fit_and_freeze`; the latter enforces that closed schema. Source-only selected observations match fitted router training/provenance hashes. Original config, thresholds, feature dimension, seed and 400 updates per fit are unchanged.
5. Final question text is used for feature extraction/prediction before freezing; final gold and this event's final decoder output are absent from fitting and hyperparameter selection. The historical final cohort was already exposed, so this is a development diagnosis, not a fresh blind confirmation.
6. `retain()` writes new files exclusively and fsyncs. Each final reader request binds the route-plan digest and frozen timestamp. Route-plan commit file mtime, binding and recorded process start order agree: freezing preceded the first final worker by **44.846 / 37.758 / 37.342 ms** for seeds 1907 / 2719 / 4051. All final route-plan hashes remained unchanged.
7. Pure standard-library arithmetic reproduced all **3,816** saved linear-router predictions and checked **720** final nearest-source routes; cosine checks allow 1e-12 numerical tie tolerance. This audit performed no decoder/encoder inference, fitting, gradients, Torch import or NumPy import.
8. All final child and single outputs were computed. Policy selection and metadata guards were applied to that retained matrix for scoring; **live selective dispatch and guarded execution were not exercised**. Evidence: `final-assessments.json` flags and `diagnosis_scoring.score_final`.

## What the distribution comparison isolates

Old `H/seed-*/selection/router-observations.json` contains **64 positive + 12 explicit negative** observations. Full-cross contains 256 + 48; balanced contains 64 + 12. All three have the same nominal **16:3** class ratio; the claim that balanced preserves the original nominal ratio is correct.
The original 64 positive questions all use wording 0. The original 12 negative questions are outside the four new negative templates. Balanced chooses 16 positives and 3 negatives per new wording; full-cross presents every underlying positive and negative in all four wordings (`diagnosis_common.panels`).
Effective rejection targets also depend on measured child success, and therefore differ despite the common explicit class ratio:

| Seed | Original effective reject | Full-cross effective reject | Balanced effective reject |
|---|---:|---:|---:|
| 1907 | 18/76 | 68/304 | 16/76 |
| 2719 | 28/76 | 109/304 | 27/76 |
| 4051 | 30/76 | 119/304 | 29/76 |

The full-cross/balanced comparison holds decoder weights, router configuration and update count fixed. It changes training row count, per-fact wording exposure and the measured effective target distribution. Full-batch training over 304 rows costs more per update than over 76. This supports a source-distribution sensitivity diagnosis; it does **not** uniquely isolate sample count, a particular wording mechanism, or equal-total-compute superiority.

## Recomputed final outcomes

Each cell below is **retention correct / transfer correct / unknown correct**, with denominators **64 / 32 / 24**. Oracle and uniform cover known questions only, so unknown is inapplicable. Their `all` denominator is 96; other policies' `all` denominator is 120. Comparisons below use matching cohorts. Uniform values are exact two-expert expectations, not sampled decisions.

| Policy | Seed 1907 | Seed 2719 | Seed 4051 |
|---|---:|---:|---:|
| Original | 2 / 3 / 12 | 0 / 1 / 16 | 0 / 0 / 16 |
| Full-cross | **60 / 8 / 4** | **41 / 7 / 13** | **39 / 0 / 21** |
| Balanced | 59 / 8 / 5 | 41 / 9 / 11 | 31 / 0 / 21 |
| Lexical | 59 / 4 / 4 | 44 / 7 / 6 | 42 / 3 / 4 |
| Dense | 37 / 6 / 12 | 32 / 7 / 10 | 41 / 0 / 18 |
| Metadata | 61 / 8 / 24 | 42 / 9 / 24 | 45 / 5 / 24 |
| Single | 45 / 11 / 0 | 43 / 7 / 0 | 40 / 2 / 0 |
| Eligible oracle | 61 / 8 / — | 47 / 9 / — | 45 / 5 / — |
| Uniform expectation | 33.5 / 4 / — | 27 / 4.5 / — | 28 / 2.5 / — |

Every policy's rows, supported/raw correctness, guarded metrics and reported group denominators were reconstructed from actual final raw outputs; results match `E/seed-*/result.json` and `final-assessments.json`. All eligible-oracle metric dictionaries also match the historical fixed-child final oracle exactly.
Full-cross strongly improves over the original failed router, but is below single on retention in seeds 2719 and 4051. Its mean retention gain over single is +6.25 points, while the required nonnegative gain in every seed fails. Balanced's mean gain is only +1.5625 points and seed 4051 falls from single's 40/64 to 31/64.
Full-cross retention trails metadata in every seed and trails lexical in two seeds. Full-cross transfer totals 15/96, balanced 17/96, lexical 14/96, and single 20/96; lexical is below/tied/above full-cross by seed, respectively. These are descriptive aggregates of correlated probes, not independent-task significance estimates.
Unknown correctness in the learned-router arms here comes from action abstention; no raw unknown decoder answer contributes. Full-cross raw rejection 4/24, 13/24 and 21/24 all miss the original ≥90% gate. Metadata's 24/24 uses supplied structured operations and roots, not a learned question-only parser.

## Real baseline functionality and complete event costs

Lexical is source-only unigram/bigram TF-IDF cosine nearest-question routing. Dense uses actual, adapter-enabled, frozen-parent final-hidden-state prompt-mean features and cosine nearest-source routing. Both store source questions and measured expert/reject targets, not answer values; they are real routing baselines, not full answer-retrieval systems. Source diagnostic scores include self-prototypes and are not test accuracy.
Lexical index+prototype bytes are 529,158 / 529,281 / 529,311. Dense index+prototype bytes are 1,415,428 / 1,415,551 / 1,415,581, **plus** a 977,024-byte retained feature matrix per seed. Parent extraction took 111.285 / 116.409 / 115.110 s; the tiny cosine-index times alone are not dense baseline cost. `routing/route-costs.json` and `parent-features/receipt.json` retain separate measured components.
Added event work reconciles to **2,904 decoder queries**, **185,136 decoder input tokens**, **6,156 generated tokens**, **1,272 parent-feature forwards**, **80,544 feature input tokens**, **2,400 router updates**, **0 decoder updates**, **0 gradient probes**, **27 decoder + 3 feature subprocesses**.
Whole-event wall time is **1,435.813547 s**; child CPU 2,541.961509 s and parent CPU 4.667423784 s. These clocks are not additive with nested stage wall/CPU costs. Added artifacts before final result: **21,166,875 bytes**; shared base reused once: **271,170,520 bytes**. Cost accounting charges the shared raw matrix once rather than once per simulated policy.
Historical sunk work is separately retained: **7,680 decoder updates**, **192 gradient forward/backward probes**, **1,200 old router updates**, plus prior source/final reads. Prior codec evaluation is explicitly outside this diagnosis's cost scope. Equal-total-budget, net compression and cost superiority are not established.

## Gates still blocked and audit qualifications

The original gate logic is `R/scripts/memory_cell_population/population_protocol.py` plus `population_aggregate.assess_trial`. Even an ideal router cannot fix insufficient frozen experts: oracle retention 47/64 and 45/64 is below 75% for seeds 2719 and 4051. Metadata already equals oracle in seeds 1907 and 4051, making a ≥5-point advantage over metadata impossible on those matrices. Per-family transfer oracle maxima are also far below the original 75% requirement.
Three random seeds reuse the same synthetic task construction and exposed cohort; wording rows and source dependency groups are correlated. They do not provide three independent natural-task groups. Final flags correctly remain false for confirmation, scientific phase-3 closure, capacity advantage, general memory, production acceptance, equal total budget and live dispatch.
Per-seed `decoder_hash_check` strings still say whole-trial checking is pending. The completed global integrity assertions and this full independent rehash close that check; the immutable per-seed text is a stale status string, not a remaining model-checkpoint verification failure.
The first audit harness mistakenly compared tensor-content SHA to the safetensors file SHA; a second edit initially looked for base identity in the version locator instead of pinned lineage. Both were audit-harness issues. Their logs/source/JSON are preserved separately; they were corrected only in `/tmp` and are not experimental failures. The final audit has zero mismatches.
The original early cutoff review `/tmp/hepta-routing-independent-review.md` remains byte-identical, SHA-256 `2dd598a4c5b98ad7c02cfb150a27fe3c21a60e836964ca09745c04daf53f4843`. This final review is additive, not a rewrite of what was observed before completion.
Publication v2 explicitly corrects the lexical-transfer comparison: lower/equal/higher than single by seed, pooled 14/96 versus 20/96. Its assembled archive SHA-256 is `54d2a5f7189176a94d2421c30939429fbe63951fff39cabf0fef14d5ed6a4fa9`; the archived report was read directly and every archived run-002 file matched the original byte-for-byte with a complete inventory. Details and archive-part paths are in the companion compact JSON.
This reviewer and experiment share a local host/principal. Hashes, process receipts and arithmetic reconstruction give inspectable local evidence, not independent-host execution attestation. Audit arithmetic is charged separately: 3,816 saved-router predictions and 720 nearest-source checks, approximately 6.06 s, 85.5 MB peak RSS, no decoder/encoder work.

## Audit artifacts

Detailed machine-readable audit: `/tmp/hepta-routing-final-independent-audit.json`; compact summary: `/tmp/hepta-routing-final-independent-summary.json`; reproducible stdlib audit: `/tmp/hepta-routing-final-audit.py`; final log: `/tmp/hepta-routing-final-audit.log`.
Initial harness evidence: `/tmp/hepta-routing-final-audit-initial-harness.py`, `/tmp/hepta-routing-final-audit-initial-harness.log`, `/tmp/hepta-routing-final-independent-audit-initial-harness.json`, `/tmp/hepta-routing-final-audit-version-field-harness.log`.
