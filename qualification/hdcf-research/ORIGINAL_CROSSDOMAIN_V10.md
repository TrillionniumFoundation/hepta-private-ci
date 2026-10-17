# HDCF V10 — Independent real-original cross-domain Cell Split falsification

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO_MAIN_MERGE / NO_MODEL_SELECTION / NO_FINALUSE**

## Immutable evidence, not a new training result

This is an additive child of the original DINO/Beans CellBank study [PR #2616](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2616) at frozen `e3cb1dcb94f96503665d511b5d0179ee4a35cb63`. It does not alter the existing frozen Encoder, V8 bridge, V9 original model/data study, five-arm CPU Head training, native Neuron, worker, NDU, permission checks, tool execution or protected `main`.

Independent reviewer opens **four exact GitHub Actions ZIP-byte SHA-256 pins**, not files supplied by an untrusted training process. Text: original [ModernBERT/BANKING77](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38930339541) at physical source commit `b89a0b4a32eaa92881a79140256079aed0c38fe4`, original 96 pretrained Encoder forwards, real 64 TRAIN and 32 held examples, actual three-arm SGD (256 updates/arm). Image: original [DINOv2/Beans](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39007638886) at `e3cb1dcb94f96503665d511b5d0179ee4a35cb63`, original preceding E2 60 pretrained DINO forwards over 36 original TRAIN + 24 historical TEST natural photographs; the V9 later study physically trained binary Head arms and independently verified publisher bytes. **The V10 reader executes no new pretrained forward or Head training.**

The original ZIP artifact IDs, SHA-256, and member allowlists are fixed in `original_crossdomain_v10.py`. Fetching uses a GH-token-authenticated GitHub API request with redirects disabled, then an unsigned request to the prevalidated HTTPS CDN host. No token, source image, source sentence, held label, raw prediction or tensor may be uploaded; only the bounded sanitized aggregate is uploaded. All tests explicitly require real original ZIPs; missing or altered originals fail, never skip or silently substitute fixtures.

## Descriptive true-original findings

| Experiment | Matched equal-touch shared Head | Split Head | Split only correct / Shared only correct | Nominal exact two-sided case-level p |
|---|---:|---:|---:|---:|
| ModernBERT, BANKING77 derived binary, historical TEST | 16/32 | 20/32 | 12 / 8 | 0.5034446716308594 |
| DINOv2, Beans derived binary, historical TEST | 16/24 | 16/24 | 0 / 0 | 1.0 |

The original Beans frozen visual nearest-prototype control, **rescored on the same derived binary task**, obtained **21/24**, while the trained Split Head obtained 16/24. Split won 3 and lost 8 to that visual reference: nominal paired p=0.2265625. The original three-class 20/24 result is a different metric and must never substitute for this binary comparison. Exact Head training work is 196,864 vs 196,864 estimated parameter touches/arm in the text experiment and 98,560 vs 98,560 in the image experiment, respectively; these counts do not include original Encoder cost, data preparation, evaluation, rollback, RAM residency or energy.

The original text and image samples arise from **two distinct publisher/task families**, but were not random independent prospective source cohorts. Pooled 56-case p-values, task-level confidence, additive 421M-equivalent capacity or universal Stem superiority are **prohibited**. The smallest cohort has 24 cases, artificial hash-based Cell-type splits are not meaningful specialized organs, and cross-task accuracy levels measure different labels. The true result is a consistent absence of **qualified specialization benefit**, not a proof that specialized Heads can never work. No verified original audio/video Encoder data or cross-modality generative outputs appear here.

## Reproduction and constraints

Run `python3 -m unittest -v test_original_crossdomain_v10` and `python3 -O -m unittest -v test_original_crossdomain_v10` **only after** four real archives have been acquired and bound to environment variables `HDCF_V10_MODERN_TRIAL`, `HDCF_V10_MODERN_TARGETS`, `HDCF_V10_MODERN_REVIEW`, `HDCF_V10_BEANS_REVIEW`. Use `python3 original_crossdomain_v10.py audit --modern-trial ... --modern-targets ... --modern-review ... --beans-review ... --out ...` for the sanitized aggregate. The dedicated read-only GitHub workflow performs that original check on a fresh runner; local results and separate-source original Actions results must be identified independently of hosted CI completion.

Existing original archives attest original-source-model lineage to their declared byte digests but **not an independent publisher signature, future-time utility, end-to-end host-billed GPU/CPU total cost, causal modality necessity or native permission grants**. Accepting this research receipt **never** changes model selection, cell topology, authorization, deployed weights or production learning. Next scientific experiment should use a source-disjoint, independently labeled, modality-essential held set and learned Organ-level adapter versus equal-budget non-split controls, not repeat hash-based Cell Split on this tiny retrospective corpus.
