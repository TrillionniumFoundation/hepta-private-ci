# Shared Cell foundations: execution evidence, 2026-11-08

**Execution completed; scientific acceptance remains HOLD; production adoption is not granted.**

This evidence package records the complete bounded reference roster, with original native and GitHub CI outputs. It is a synthetic mechanism study, not qualification of seven production Cell implementations, a reproduction of all three papers, or evidence of real-task benefit.

- Source commit: `d967d91c177f413d6962fe8526976680618c441e`.
- Exact unmerged HCSN research parent: `bb048cb811c2b755b7e54e97d24c63ec7ec8d1b7` (PR #5343).
- Review: [PR #5347](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5347).
- Dedicated source-commit CI: [run 42472945935](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42472945935), job `128707779704`, completed successfully.
- This evidence-only delivery changes no experiment implementation. The broader repository CI and protected-branch gates are separate from the successful dedicated run; this document does not grant merge eligibility.

## Complete denominator and source identity

| Check | Native CPU | GitHub CPU |
|---|---:|---:|
| Tests passed / executed | 68 / 68 | 68 / 68 |
| Planned / completed experiment slots | 54 / 54 | 54 / 54 |
| Failed / missing / cancelled slots | 0 / 0 / 0 | 0 / 0 / 0 |
| Credit / temporal / plasticity slots | 36 / 12 / 6 | 36 / 12 / 6 |
| Actual credit updates | 432 | 432 |
| Actual temporal head updates | 1,440 | 1,440 |
| Actual plasticity updates | 432 | 432 |
| Source changed during execution | No | No |

Each environment uses seeds 11, 29 and 47. Repeating these seeds on another environment does not provide six independent seeds. Test-only training fixtures are outside the 54 formal slots and inside measured overall execution cost. Each formal slot has separate create-only started and finished records; original archives retain them.

All 17 common Python files have identical bytes and SHA-256 values. Native execution includes the imported six-file HCSN closure. The full Git checkout inventory additionally includes inherited `run_qualification.py` and three HCSN test files, so its 21-file aggregate digest differs. The plan digest and executed test names agree. `SOURCE_BINDING.json` records both inventories, Git blob identities and original result digests.

## 1. Local plasticity and delayed credit

The following native results are mean ± sample standard deviation across three seeds. Loss change is final minus initial held-out loss, so negative values are improvements. `all` and `sparse` describe spatial feedback availability; every arm receives terminal-only feedback in time. BPTT remains the offline full-gradient oracle. These are descriptive results, not a significance test.

| Method | All: gradient cosine | All: loss change | Sparse: gradient cosine | Sparse: loss change |
|---|---:|---:|---:|---:|
| bptt | 1.0000 ± 0.0000 | -0.00029213 ± 0.00070046 | 1.0000 ± 0.0000 | -0.00029213 ± 0.00070046 |
| tbptt | 0.9960 ± 0.0011 | -0.00026485 ± 0.00070305 | 0.9960 ± 0.0011 | -0.00026485 ± 0.00070305 |
| three_factor | 0.1279 ± 0.0574 | -0.00000673 ± 0.00002069 | 0.1942 ± 0.0430 | -0.00001558 ± 0.00003782 |
| type_specific | 0.9829 ± 0.0045 | -0.00023891 ± 0.00047938 | 0.6875 ± 0.0678 | -0.00014344 ± 0.00028768 |
| diffusion | 0.8941 ± 0.0173 | -0.00013492 ± 0.00027791 | 0.4563 ± 0.0773 | -0.00008816 ± 0.00017706 |
| shuffled_diffusion | 0.8719 ± 0.0292 | -0.00015832 ± 0.00031894 | 0.5696 ± 0.0525 | -0.00009358 ± 0.00018624 |

**Diffusion does not outperform type-specific modulation in this panel.** Shuffled diffusion also improves loss more than the spatial diffusion arm here. The observed result provides no reason to promote diffusion to a preferred algorithm. The ordinary three-factor baseline averages signed group maps, which can cancel; it is a declared fixed baseline with no tuning, not an optimized representative of all three-factor rules.

The implementation separates execution weights from the credit graph, differentiates the declared local self-recurrent eligibility, bounds low-dimensional modulation, and verifies actual rounded candidate updates. Early-message masking, replacement and delay recompute forward outputs, credit and candidate changes. Those paired synthetic effects do not establish that real historical actions receive correct credit. The local tanh model omits cross-unit derivatives and is not the full e-prop or PNAS spiking-network implementation.

## 2. Matched temporal-kernel pilot

All four arms use the same four-channel causal encoder, 9-to-1 linear head, data, fixed-sequence NDU-disabled profile and head-training budget. Temporal kernels are frozen; only ten head parameters train. Each seed/kernel attempt uses 40 updates for each of short recall, long recall and changed-gap adaptation. Total frozen parameter/state counts differ.

| Frozen kernel | Short accuracy | Long accuracy | Shifted before | Shifted after | Frozen parameters |
|---|---:|---:|---:|---:|---:|
| gru | 0.5000 ± 0.0000 | 0.5000 ± 0.0000 | 0.5000 ± 0.0000 | 0.5000 ± 0.0000 | 405 |
| diagonal_ssm | 0.5278 ± 0.0481 | 0.5278 ± 0.0481 | 0.5000 ± 0.0000 | 0.5139 ± 0.0241 | 45 |
| hcsn | 0.5000 ± 0.0000 | 0.5000 ± 0.0000 | 0.5000 ± 0.0000 | 0.5000 ± 0.0000 | 778 |
| lif_event | 0.5417 ± 0.2083 | 0.5000 ± 0.0000 | 0.5000 ± 0.0000 | 0.5000 ± 0.0000 | 45 |

**The near-chance pilot does not demonstrate an HCSN advantage.** HCSN and GRU score 0.5 in each of these four main panels for all three seeds. The complete raw reports additionally retain BCE, Brier score, original-gap retention after adaptation, per-seed feature time and state counts. This head-only experiment does not settle the merits of fully trained kernels, learned delays, waiting/timeout prediction, fast control or anomaly triggering.

Every kernel restores a fully serialized state into a newly reconstructed same-identity kernel and completes the remaining sequence with zero maximum feature error. This is checkpoint correctness, not task efficacy or restored autograd-tape training. The event arm is a fixed LIF reservoir, not EventProp. HCSN retains its inherited finite QPR projection, non-semigroup and possible early refractory-release limitations; no renewal/free-boundary qualification is conferred.

## 3. Continued plasticity

The same fixed graph, decaying schedule, 25% old-task replay, three task sequences and 24 updates per task compare L2 with L2 plus singular-value entropy effective rank. Effective rank is `exp(-sum(p log p))`, with `p = sigma / sum(sigma)`. Three-dimensional linear features are used; extra ER/SVD work is measured rather than treated as free.

| Method | Final effective rank | Final-task training MSE | Mean old-task proxy drop | Censored learning targets |
|---|---:|---:|---:|---:|
| fixed_graph_scheduler_l2 | 2.534091 ± 0.062555 | 0.196687 ± 0.057625 | -0.020973 ± 0.003578 | 9 / 9 |
| fixed_graph_scheduler_l2_er | 2.557722 ± 0.067949 | 0.196565 ± 0.059772 | -0.022465 ± 0.002708 | 9 / 9 |

The paired final-rank difference (L2+ER minus L2) is 0.023631 ± 0.012329. This is a small descriptive improvement on a finite synthetic reference. Retention uses `1/(1+held_out_MSE)`; a negative drop means the proxy improved. Both methods improve that proxy in this panel, so this is not a demonstrated severe-forgetting or rank-collapse recovery test. All 18 task-learning targets are right-censored: none reaches its target within the declared budget. Do not claim a measured time-to-target speedup.

Monitoring includes per-slice retention, learning curves, effective rank, activation-aware utilization, paired representation drift/CKA and actual update/stability bounds. Structural sleep, regeneration, split and merge remain proposals. Their gate requires measured migration/relearning, complete cost including retries and failures, real per-slice retention and net benefit against a fixed graph with a declared scheduler. No structural transition was performed.

## Runtime, cost and limits

| Measurement | Native CPU | GitHub CPU |
|---|---:|---:|
| Python | 3.14.4 | 3.12.3 |
| NumPy | 2.5.2 | 2.3.5 |
| Torch | 2.13.0+rocm10.0.0, CPU used | 2.8.0+cpu |
| Runner wall seconds | 18.900918 | 11.928932 |
| Process CPU seconds | 18.515004 | 11.558228 |
| Whole-process high-water RSS, bytes | 971,956,224 | 295,776,256 |
| Physical energy | Unmeasured | Unmeasured |

The native child including interpreter startup and final serialization took 19.988092 seconds. The inner runner window includes tests, panels and attempt-record writes, but excludes interpreter startup, dependency installation and final report serialization. Both runs use one thread. Hardware and dependency versions differ, so these numbers do not rank environment efficiency. RSS is a lifetime process high-water mark, not isolated per-kernel peak memory. Null energy is unknown, not zero. Neither run establishes end-to-end energy advantage.

The eleven affected Python files passed Ruff 0.15.13 formatting and lint checks locally and in the dedicated CI. The scratch environment could not run `just fmt` because `just` was absent; no full-workspace formatting claim is made. Source publication encountered an inherited promised-blob checkout failure and a first write-tree timeout, then used a verified fresh index and exact parent to publish. A timed-out native start response was reconciled under the same operation key; it did not create a second formal training run. `SUMMARY.json` retains these operational events.

## Broader repository CI remains open

The successful dedicated reference job does not close all required repository checks. Three completed failures on source commit d967d91c were inspected:

| Job | Observed cause | Relation to this change |
|---|---|---|
| [Codespell](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42473041182/job/128708087814) | Four spelling matches in two inherited HCSN evidence files, including a binary archive fragment | No match in the fourteen newly added source/workflow files |
| [Linux Bazel](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42473041182/job/128708527327) | V8 source download returned HTTP 504 during dependency resolution | Tests did not execute; the generic lockfile message does not prove lockfile drift |
| [Windows native paths](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42473041182/job/128708527165) | Checkout failed on two inherited HCSN evidence paths exceeding the allowed path length | Native tests did not execute |

These are bounded observations, not a claim that every other repository check passed or that failures are waived. Exact excerpts and job identities are retained in `REPOSITORY_CI.json.gz`. PR #5347 remains a draft dependent on the unmerged HCSN parent; no merge or production transition was performed.

## Open scientific gates

1. Independently sourced real terminal tasks, future splits, retention slices and an isolated evaluator.
2. Native learning/artifact-owner consumption, fixed-point/quantization checks where required, reversible candidate adoption and per-Cell acceptance.
3. Fully trained temporal kernels and learned-delay/EventProp controls with matched tuning opportunities and actual consumed budgets.
4. Same-hardware isolated peak memory and physical end-to-end energy measurements.
5. Explicit HCSN numerical-domain and renewal/free-boundary qualification.
6. Actual structural migration/relearning and net utility against a strong fixed-graph scheduler.

## Evidence files and integrity

- `native-evidence.tar.gz`: original native result, preregistered plan, 108 started/finished records, native execution receipt and stdout/stderr (113 members).
- `github-ci-evidence.zip`: exact GitHub artifact bytes, containing result, plan and 108 started/finished records (110 members).
- `github-ci-job.log.gz` and `github-ci-receipt.json`: losslessly compressed downloaded job log and selected run/step/artifact metadata.
- `REPOSITORY_CI.json.gz`: selected broader repository CI failures and exact downloaded log excerpts; these remain open.
- `SUMMARY.json`: both environments, raw per-seed metric values, arithmetic means, sample variances and sample standard deviations; no pooling or significance claim.
- `SOURCE_BINDING.json`: source commit, Git blob hashes, both inventory scopes and original result hashes.

| Original archive | SHA-256 |
|---|---|
| Native | `e139686bb247c245215f6fa2211a31cfeb16deca12c3a9019cebcd326f6c1fd5` |
| GitHub CI | `4f28d61f3cca089ee6a388cfb3281f811abdf01e6fa0079bbe6f63af3ac416e0` |

The source README contains the exact command, algorithm contracts and primary research references. The original JSON reports, rather than rounded table cells, are the authority for numeric comparisons.
