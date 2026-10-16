# V14 — Original precommitted retrieval arm versus cheap BM25: physical cost and candidate ceiling

**Research only · SHADOW_ONLY · DENY_ALL.** No model weights or state promotion; V6 seed41 bridge retention is still blocked; this is not a Reader/task-success evaluation.

## Motivation and frozen owner

V13 measured CPU time for a **six-arm research batch**, which is an invalid substitute for deployed cost of its one precommitted `phrase_char` arm. V14 isolates the ORIGINAL exact V13 `0.7 BM25 normalized + 0.1 adjacent phrase + 0.2 within-token char trigram TF-IDF cosine` primary, without changing its coefficients or choosing the stronger `char_only` arm after viewing heldout answers. The source packet, plan, LoCoMo revision, 10 family identities and train/held split all match V13's exact original SHA. Old V13 files remain byte-identical.

- Dataset SHA256: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- V13 source packet SHA256: `9d707c297dc743cffe00d94ead04198b7039f72027743dc6d6e02c826a623a8c`.
- V13 frozen plan SHA256: `8f6efdb78a173d64123209753ebf2dac06b03367637084a4098866cdbfe4df53`.
- Original V13 public negative aggregate SHA256: `7d605aa9184a6df0524b47d71d78d1f3cab5cc478b0e15e3bd41aa978b6dcd1d`.

Original source: 10 distinct LoCoMo conversation roots, 5,882 original turns, 1,986 total questions. Six historical TRAIN source roots and four retrospective HELD source roots (829 questions, 7 annotation-unknown). **These are four source families, NOT 829 independent observations and NOT prospective calendar windows**.

## Actual execution: two isolated process runs for each arm

Same container, CPU-only Python standard-library retrieval; the per-profile scope includes index building and full 1,986-question Top-32 ranking. Raw source dialogue/question text, per-case source IDs and publisher answers remain in private local files. Publisher labels were not read in any ranking process. V14 runs do not load the archived pretrained Encoder/Reader or train Heads.

| Profile | Actual CPU run 1 | Actual CPU run 2 | Whole-process peak RSS (approx) |
|---|---:|---:|---:|
| BM25-only | 3.4051 s | 5.1948 s | 106.4 MiB |
| V13 fixed `phrase_char` only | 13.9951 s | 16.7342 s | 115.8 MiB |

Measured **ratio of two-run mean CPU** = **3.573×** (primary/BM25). This is descriptive on one isolated host, two repeats only, with Python-level indexing. Do not interpret as a production p95/p99, optimized native Rust ratio, or equal-lifecycle cost against pretrained and trained Head alternatives. Different runs experienced runtime noise. V13's earlier 6.79× compared a six-arm research execution and is NOT a per-primary cost ratio.

A separately invoked independent source-first reviewer rebuilt original V13 frozen ranks **over all 1,986 original questions**. Both new arms have **1,986/1,986 identical ordered Top-32 source IDs** with the corresponding V13 ranked routes. The two runs per arm have identical SHA-pinned rank digests. The review occurred outside measured retrieval times and did not read original publisher labels.

After route sealing, a separate scorer independently parsed the original publisher weak source annotations and recomputed the full heldout counts:

| Historical source root | Questions | BM25 weak Hit@3 | Fixed primary weak Hit@3 | Net difference |
|---|---:|---:|---:|---:|
| conv-47 | 190 | 76 | 79 | +3 |
| conv-48 | 239 | 124 | 123 | -1 |
| conv-49 | 196 | 91 | 93 | +2 |
| conv-50 | 204 | 81 | 88 | +7 |
| **Four roots** | **829** | **372** | **383** | **+11** |

Publisher annotation unknown in 7 historical questions. Top-16 weak evidence coverage: BM25 515, primary 528. Top-32: BM25 575, primary 587. Top-3 all-publisher-support: BM25 317, primary 326. These are **publisher-weak retrieval proxies**, not necessarily human-verified sufficient evidence, nor independent semantic correct final Reader answers. +11 is a postseal retrospective observation, **not** a prospectively qualified utility gain; one source family regresses.

## Actual verification and limitations

The new same-input, single-arm `v14_primary_only_cost.py` keeps V13's exact float operations and source-ID sorting and does not execute the four unused diagnostics. Original input/plan IDs, source revisions and ownership flags are checked fail-closed. A separate `v14_original_parity_review.py` compares 1,986 ranked source-ID lists against a fresh invocation of the V13 original ranker, then, in a later process, opens gold strictly for postseal weak scoring. The independent public-only `v14_public_cost_audit.py` binds the original V13 public SHA, checks every heldout family/candidate ceiling, two real per-arm cost samples and explicit negative authority.

Local tests: **28 focused ordinary Python tests** and **28 Python `-O` tests** passed (10 original single-arm contract tests, 18 public negative-claim tamper tests). These source tests are distinct from actual LoCoMo rank replay. Exact-head GitHub Actions must pass separately; hosted CI never claims access to private source or real pretrained model weights.

**Not established:** full task Reader utility; original human semantic review; a new unseen source-family experiment; multimodal necessity; equal lifecycle work vs a physically trained Head, a 421M baseline or Granite97; source-owner signatures; target-host native latency; V6 seed41 retention fix; production authority. Retain DRAFT / DENY_ALL, no main merge, no automatic Cell split/fusion, no selected model, and no FinalUse.

## Next scientifically decisive experiment

Only invest further in a new lightweight Head after acquiring **new source-family** natural tasks and independently verified Reader-sufficient evidence. Precommit full source universe and low-cost hybrid before opening labels; measure query-stage CPU/wall, Reader input/output tokens, total training/feature/candidate work and old-task retention. Run a strong cheap-control Reader with four evidence regimes: none, cheap full-source retrieval, independently sufficient evidence, and necessary-source lesion, using the same fixed Reader and a stronger reference Reader solely as a capacity diagnostic. Commit nothing from private original sources or model weights. If adequate evidence cannot be used by the small Reader, fix Reader capacity/prompt, not Head size; if cheap retrieval wins cost-adjusted, reject further Head training.
