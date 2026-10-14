# Hepta shared-Stem / NDU Tree-FBSDE P0–P6 qualification (research only)

This isolated, **DENY_ALL** experiment is a source-control regression oracle, not a model loader, real Cell runtime, stochastic FBSDE solver, certified global existence theorem, or production permission. It does not change any Neuron V1 Q24 bytes, NDU Q32 definitions, owner, deployment or selection behavior.

## Stage gates / mandatory controls

| Stage | Frozen implementation candidate | Independent actual acceptance evidence |
|---|---|---|
| P0 | Original Laya 421M, Granite 97M, mmBERT-small and EmbeddingGemma 2 exact revisions and licenses | Same source/task group, tokenization and Reader; physically loaded weights, immutable manifests and no-change; separate modal embedding geometry and completed language task scores. Missing model => **unavailable**, never fallback |
| P1 | Shared Encoder + no-change/frozen/learned gated Head; N=64/256/1024/4096 | Real distinct Encoder forwards, physical shared buffer/final-use, scopes, CPU/GPU/RSS/p95/p99, energy if measured, train/search/holdout costs, equal-quality and quality-cost frontier; one physically shared 421M control |
| P2 | Native multimodal Stem vs frozen independent-tower/learned bridge | Source-disjoint real image/audio/video tasks, modality ablations and truth flips, information-bearing token/patch/frame/timestamps, cost/retention and independent labels |
| P3 | Shared Critic + bounded typed OR/AND/CHANCE DAG | Exact proposer/Reader/verifier and tasks across no-search/fixed-depth/vanilla-tree/learned-Critic arms; sealed outcomes, actual work and independent future task success |
| P4 | Finite exact BSDE, analytic global obstruction and numerical coupled profile | Both interface sides, nonanticipativity, global terminal and operator regularity, covariance convention Z Sigma=B, perturbation and error-vs-cheap Bellman baselines; **global status never inferred from leaf/local residuals** |
| P5 | Frozen recursive utility / qualified stochastic NDU candidate | Independent actual time-disjoint utility, risk/feasibility, latency/compute superiority to P3/P4 controls; global existence/regularity assumptions and qualified covariance/driver representation |
| P6 | Candidate-only policy distillation into small Cell/Organ Head | Teacher cost counted, independent new-task gain, old-task retention, negative transfer, rollback and frozen teacher/control comparator |

**Never** accept a test count as real model efficacy, a common budget cap as equal physical work, synthetic fixtures as prospective natural data, a SHA string as verified model provenance, or a local FBSDE terminal condition as a global solution. All study records are shadow/advisory, explicitly nonauthoritative. Compare exact CI SHA and prospective merge context; `blocking-ci` remains mandatory. Preservation of independent per-scope final-use and generation fences is mandatory. All model and outcome evidence from separate research PRs must be read under their own SHA and not automatically counted as P0–P6 acceptance.

## Exact baseline mathematical oracle (P4)

The deterministic coupled boundary test is `dX = Y dt`, `dY = 0`, `X(0)=x0`, `Y(T)=g X(T)`. Its global solution obeys `(1-gT)Y0=g x0`. If `1-gT=0`, there are either no solutions or infinitely many. Even with algebraic uniqueness, a **regular global decoupling field** may be unavailable after its first pole; this reference never treats an algebraic shot beyond that pole as an admitted regular field. The wrong-reset experiment solves each segment against a fresh terminal boundary and deliberately reports `globally_solved=False` even if every local residual is zero. Compare both `X` and `Y` at every interface.

The finite belief tree uses two independent Bernoulli bits, typed `stop/submit/observe` actions and an exact rational conditional expectation. This is a **discrete BSDE special case**, not a fully coupled stochastic neural FBSDE. `belief_tree()` computes optimal expected utility over public observations and never uses hidden-world labels at routing time. The algebraic exact control is intentionally preserved, because an FBSDE solver gives no incremental ability in equivalent read-once linear cases.

## Next increment: independent two-sided stitching and martingale completeness

- `stitch_audit.py` independently parses each **proposed** rational segment and checks X/Y dynamics, both sides of every interface, initial and terminal constraints, and same-global-field continuation. The received record contains no trusted "passed" flag. Unique-but-pole-crossing and non-unique boundaries never qualify as globally regular.
- `conditional_moments.py` recomputes centered conditional moments and solves exact `Z Sigma = B` without inversion. It **rejects singular covariance** and explicitly retains the orthogonal residual even when Sigma is invertible, because invertibility does not prove martingale representation completeness.
- These are small analytic and finite-support references, not general stochastic neural coupled-FBSDE solvers or proofs of universal regularity.

## Next increment: actual CPU Head-only physical observations (P1 *partial*)

`head_only_physical.py` allocates distinct seeded FP32 parameters for 384-feature / 64-state / rank-8 / 8-class gated residual Heads. It actually computes all Cell outputs with NumPy CPU `einsum` at each invocation. It **does not** load a pretrained Encoder, run a genuine Neuron request, train a Head, or prove independent task utility. Synthetic shared features are constructed in-process; physical Encoder forwards are **zero**, not one. Head geometry is **9,744** trainable scalars per Cell. Four separate Python processes ran 100 measured batches per scale with `OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1` on this assistant's local CPU environment. The model and physical host are not authenticated independently. The values below are a one-host study, not reproducible cross-device guarantees.

| Cells | Physical FP32 Head bytes | Measured batch p50 (ms) | p95 (ms) | p99 (ms) |
|---:|---:|---:|---:|---:|
| 64 | 2,494,464 | 0.222789 | 0.349526 | 0.363417 |
| 256 | 9,977,856 | 0.802184 | 1.073024 | 1.957579 |
| 1,024 | 39,911,424 | 3.487297 | 4.602263 | 5.340593 |
| 4,096 | 159,645,696 | 14.759940 | 18.205825 | 19.040091 |

These are **per-batch** wall-time order statistics across 100 runs, not p99 of individual requests, not GPU latency, not energy, not true process-tree peak RSS and not independent physical 421M copies. Full 100-duration sequences, sampled Linux-process RSS, actual weight/input/output hashes and all four reported shapes are kept in `observations/head_{64,256,1024,4096}_100.json`. The separate `head_panel_audit.py` rejects missing samples/scales, forged p50/p95/p99, mixed seeds, source drift, different synthetic shared inputs, and fabricated pretrained/production flags. `observations/panel_audit.json` was computed from those records and **always denies complete P1 qualification**.

This measured panel cannot be used to select a winning Stem. To close P0/P1, reuse existing #1775/#1885/#1897/#1779 real-model candidate studies, then add physical shared Encoder, baseline single 421M model, actual same input/cohort, model lifetime and end-to-end training/serving/migration work. Retain every negative result and incomplete arm.

## P3 → P6 synthetic controlled teacher distillation (actual learning, no model claim)

- `teacher_study.py` generates 320 training-only exact two-bit public-belief problems, freezes their optimal search/stop labels from the existing rational `belief_tree`, and performs **300 actual full-Head Adam updates** to a seeded 9,744-parameter 384/64/rank-8/8-class gated residual Head; **6,264 parameters changed**. The shared 384 feature vector is synthetically encoded from rational priors and costs, never produced by a pretrained Laya/Granite/mmBERT/Gemma model.
- Separately train a cheap 9-parameter logistic control with 300 updates on exactly the same training examples, retaining the no-change Head with identical original bytes. Actual CPU work differs materially; identical optimizer update count is not equal physical compute.
- Three-arm predictions for 160 distinct, later-timestamped synthetic task identities are written **create-only** before the separate `teacher_study_evaluator.py` process recomputes exact future teacher labels. The raw source-only future rows and sealed three-arm predictions are retained under `observations/` along with exact SHA-256s.

| Synthetic 160-case future teacher-agreement arm | Correct / total | CPU fit cost |
|---|---:|---:|
| Frozen initial Head (no-change) | 30/160 (18.75%) | zero updates |
| Learned state-gated Head | 153/160 (95.625%) | ~111 ms in this host's measured optimizer phase |
| Cheap trained logistic | 146/160 (91.25%) | ~10.3 ms in this host's measured optimizer phase |

Paired learned-Head vs cheap linear: **12 recovered and 5 lost** teacher imitation cases (net 7). This is one seed, one tiny synthetic task, with no external ground truth, no statistical generalization guarantee and a markedly more expensive learner. It **does not justify selecting the gated Head** or claiming new reasoning/FBSDE efficacy. Natural task success, independent observer, OOD, old-task retention, Reader adequacy and target-host end-to-end costs remain untested. This is a P3→P6 *mechanism demonstration only* with `DENY_ALL`.

## Run

```sh
python3 -m pip install numpy==2.3.5
python3 -W error::ResourceWarning -m unittest discover -s experiments/ndu_tree_fbsde_gates -p 'test_*.py' -v
# Optional separate-process physical replay and independent consistency check:
for n in 64 256 1024 4096; do
  OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 experiments/ndu_tree_fbsde_gates/head_only_physical.py --cells "$n" --trials 100 --output "/tmp/head_${n}.json" >/dev/null
done
python3 experiments/ndu_tree_fbsde_gates/head_panel_audit.py --inputs /tmp/head_{64,256,1024,4096}.json --output /tmp/head_panel_audit.json
```


## Integration owners, not new owners

- Reuse `codex-rs/hepta-infer-core/src/neuron_feature.rs` and `codex-rs/hepta-neuron/src/inference_control.rs` for eventual signed-Q24 feature receipts.
- Reuse `codex-rs/hepta-ndu` and `docs/learning/NDU_FBSDE_SPEC.md` for exact Q32 and stochastic admission criteria. This oracle does not substitute for them.
- Reuse existing `experiments/shared_stem_cell` research methods on their branches; no second model loader, Cell trainer or release service.
- Retain `qualification/neuron-stem/FBSDE_STUDY.md` / PR #1550 as the primary negative-control provenance.
- Reader capacity is a separate prerequisite: an independently sufficient-evidence Reader failure cannot be relabeled a search or BSDE improvement.

**Current receipts:** 61 locally completed tests, four separately executed 100-trial synthetic-feature/physical-Head CPU measurements, and an actually optimized P3→P6 exact-teacher imitation study with source and three-arm predictions sealed before separate-process teacher scoring. These measurements are NOT four-scale physical full Neuron/Encoder qualifications. There are no newly executed pretrained model loads, real multimodal task scores, independent NDU utility, qualified nonlinear FBSDE results, policy distillation, target-host admission, or production approval from this increment.
