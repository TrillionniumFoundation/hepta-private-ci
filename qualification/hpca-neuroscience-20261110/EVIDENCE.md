# HPCA-MICRO-V1 original run audit — 2026-11-10

**Verdict: HOLD_NO_GO.** Synthetic, fixed-target microbenchmarks only. Do not interpret as model training efficacy, cognitive neuroscience replication, production acceptance, or evidence that a new optimizer beats contextual policy gradient.

## Exact source and execution

- PR: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5739
- Source HEAD at first complete execution: f07f41f9a396f7096211b9cc984543b773ce719b
- Previous main base: 732e934ba496d90fbe042b8d41d479ef901643e5
- GitHub Actions: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42823724940
- Job: 129855449784, conclusion **success**.
- Invariant tests: **9 passed** in 0.635 seconds (from original CI job log).
- Full report artifact: **hpca-micro-result**, GitHub artifact ID **13768490076**, retained for 14 days.
- Source-manifest SHA-256 (credit.py, schedules.py, replay.py, run.py): **3305e052434eee355d6230785e19e3bd41b7e7ee59691f78a89211e7c79fb63d**.
- Calibration seeds 9001..9006; held-out evaluation seeds 11001..11016, 16 paired trials.
- Bootstrap intervals are exploratory; no preregistered confirmatory multiplicity correction was performed for these synthetic results.

## Measured micro-results

| Arm | Candidate | Control | Source-limited reading |
| --- | ---: | ---: | --- |
| H1 aggregate mean MSE (lower better; 256 updates per arm) | Heterogeneous 0.11269163 | Uniform 0.14798182 | Difference −0.03529019; paired exploratory 95% interval [−0.03696190, −0.03363943] |
| H1 PERC mean MSE | 0.04250566 | 0.01408723 | **Regresses** |
| H1 PRED mean MSE | 0.05712996 | 0.05712996 | No observed advantage |
| H1 CTRL mean MSE | 0.17859627 | 0.38376503 | Benefits in the deliberately fast-changing proxy |
| H1 ACT mean MSE | 0.17253461 | 0.13694506 | **Regresses** |
| H2 action correctness | Correct route 0.86539908 | Contextual gradient 0.86539908 | **Mathematically identical**, no new-algorithm claim |
| H2 action correctness | Correct route 0.86539908 | Random 0.56438180 / shuffled 0.38314914 | Strong only against information-wasting routing |
| H2 full broadcast | 0.62409847 | Correct route 0.86539908 | Broadcast costs 412.312 vs 137.438 parameter writes; **not cost matched** |
| H3 8-step, 15% sparse feedback | Event-ID 0.72137239 | Latest-trace 0.50408945 | Event binding helps versus corrupted trace in this setup |
| H3 8-step, dense feedback | Event-ID 0.95884947 | Latest-trace 0.48908216 | Strong negative control, not neurochemical diffusion |
| H3 zero delay, dense feedback | Event-ID 0.95692007 | Latest-trace 0.95692007 | Required parity |
| H4 old-task retention | Stratified 0.62202381 | Uniform 0.52976190 | Old-memory gain at downstream cost |
| H4 new accuracy | Stratified 0.82638889 | Uniform 0.93055556 | **Regresses** |
| H4 old retention | Error-priority 0.62797619 | Uniform 0.52976190 | Priority scans 4800 vs 160 reads |
| H4 new accuracy | Error-priority 0.29861111 | Uniform 0.93055556 | **Severe regression**; do not adopt |
| H4 old/new accuracy | Exact-key 1.0 / 1.0 | Hashed models below 1.0 | Deterministic source lookup strongest for these known keys |

The equal neural replay arms perform 560 candidate optimizer updates; exact key retrieval makes no parameter updates and performs 32 reference reads per seed. It is not valid to compare gradient counts alone as full resource cost. Revoked keys and superseded revision 2 are excluded from all replay candidates. Under this fixture, their denial is checked, not independently verified against production owner stores.

## Gating implications

**No production switch:** do not make PERC/ACT slower as a rule from the aggregate result, nor adopt error-priority replay from one favorable retention measure.

1. Fit resource-matched, per-family tuned and direct-gradient baselines on the same real model, split sources and test budgets; report all per-family floors and old/new/OOD tradeoffs.
2. Rebind actor credit to actual immutable decision and effect receipts, delayed/UNKNOWN outcomes and original owner fences; explicitly deny future reward and stale model sources.
3. Deliver actual fact, episode, procedure and recovery task families; retain exact-key RAG and strong uniform replay, and charge scans, dedup, cold retrieval and revocation.
4. Lock independent evaluator, multiple-comparison plan and repeated training seeds before reading confirmatory results.
5. Close end-to-end Agentd different-next-task and checkpoint cold-reopen / signed NoUpdate-or-Adopt with the real production Cell contracts.

**This file is a stable human-readable abstract of the CI artifact, not a replacement for the full 5,347-byte original JSON.** Source HEAD above is the identity of the executed code; later documentation-only commits must not relabel the originally executed tree.
