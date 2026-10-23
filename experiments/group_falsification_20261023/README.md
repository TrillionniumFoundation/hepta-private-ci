# Group falsification: synthetic diagnostic, not reasoning acceptance

**Outcome: synthetic numerical/execution diagnosis only. Natural reasoning acceptance remains OPEN.** No Group product code changes are included. The scorer uses a frozen eight-dimensional one-hot representation and a deliberately task-aligned cyclic-convolution feature for `(a + b) mod 8`. This is a positive numerical control, not a discovered general reasoning algorithm. The cosine baseline is mismatched to this task, not a competitive semantic baseline.

## Scope and source separation

The original frozen `protocol.json` and all original numerical results are preserved. Its “generated source root” terminology denotes separate seeded **episode records**, not natural source-family isolation or unseen-combination evaluation. This clarification is posthoc; it does not change or improve the old outcomes.

Every training split contains all 64 ordered member pairs. All 256 holdout records per seed have a pair already seen in that seed's training split. Unique holdout pairs are 63, 64, 64 for seeds 17, 29, 43, respectively; every one overlaps training. The experiment therefore tests fresh draws on a completely seen input support, not compositional generalization. `input_support_audit.json` reports the actual ordered-pair counts for every split and seed.

The original test named `test_source_roots_disjoint_and_reproducible` only compared two arrays for inequality and checked repeatability. It never established disjoint keys or source provenance. It is now accurately named `test_split_draws_differ_and_are_reproducible`; its assertion boundary is unchanged. Separate episode names do not make shared content independent source families.

Train/development/calibration/holdout sizes are 512/128/128/256 per seed. Development confidence sets an 80th-percentile acceptance cutoff; this is **not a risk-calibration guarantee**. Code writes model hashes and thresholds before holdout generation, but hashes alone do not independently prove historical chronology. The original fixture exception is retained: an early failed oracle-fixture test used seed 17 episode 0 before final execution; later tests use seed 999. Do not describe the pilot as a perfectly blinded trial.

## Comparisons and findings

The heads are cosine, linear, pooled MLP, and explicit relation features plus a linear classifier. Head correct out of 256, in seed order 17/29/43:

| Head | Correct |
|---|---|
| Cosine | 3 / 8 / 3 |
| Linear | 53 / 46 / 51 |
| Pooled MLP | 212 / 172 / 197 |
| Relation | 256 / 256 / 256 |

All MLP fits hit the fixed 120-iteration cap without convergence. No cap increase or result-based model selection was performed.

The search environment exposes node facts only through charged reads; the terminal read reveals an exact answer. Logical depth is **2 or 4**, with action caps 8 or 16, not 8–16 semantic reasoning steps. Zero selective error after reaching terminal is an oracle property, not learned verification. Retrieve, eight-candidate verification, dead-end reads, backtracks, and restarts are charged. A verifier call contains eight candidate evaluations; different call types are not necessarily equal computational work.

Bounded policy, pooled across 384 episode roots:

| Intervention | Correct | Calls |
|---|---:|---:|
| Normal | 294 | 3586 |
| Member order reversed | 294 | 3586 |
| Member replacement | 9 | 4593 |
| Edge shuffle | 13 | 4583 |
| Member masked | 21 | 4563 |
| Zero score noise | 384 | 2688 |
| Risk neutral | 297 | 3601 |

**Risk aversion has no observed benefit:** risk-neutral wins 297 to 294, although calls also differ. Gaussian score noise and the risk penalty are artificial. The order/corruption controls demonstrate properties of this synthetic task only.

Bounded versus the same-head fixed-relation path gains accuracy but uses more actual calls. The paired per-cell bootstrap intervals are exploratory, without multiplicity correction, and do not overcome the cost mismatch. `best_of_2` uses a weaker linear-head restart policy, not a strong same-head best-of-N control. Equal-actual-work efficiency acceptance is **not met**.

`frontier.csv` retains all 280 points: each seed and pooled, both depths, all interventions and policies. Its protocol was frozen after original results were known, before aggregation. Nondominance is descriptive within the same scope/depth/intervention. Single-run trajectory CPU excludes training/setup. **Scientific and equal-work ranking are refused.**

## Cost and independent audit

Each complete evaluation pass produced 12,288 head evaluations, 13,440 trajectories, and 69,513 charged search calls. The first pass failed during summary JSON serialization after evaluations. The second pass repeated exactly the same substantive predictions and trajectories; it is not independent replication. Total executed search calls are **139,026**, not 69,513. The successful pass has 8,365 unresolved trajectories and 8,971 charged backtracks/restarts.

Successful whole-process measurements were 7.4546 seconds wall, 9.7039 seconds CPU, and 186,272 KiB peak RSS. Dense inference FLOPs estimate: 11,881,456; training and scalar/environment overhead are excluded, so total FLOPs remain unknown. The failed first pass has recorded lower bounds of 5.7242 seconds wall and 7.1027 seconds CPU; its full process totals remain **unknown**, not zero or estimated by the second pass.

Independent review verified the handoff and all manifest hashes, checked every trajectory's call/event/budget/terminal-read invariants, reproduced both versions' counters, confirmed unchanged substantive outputs, and reproduced `frontier.csv` and `frontier_audit.json` byte for byte. No model training or natural-data download was repeated for the review. Four original mechanism tests passed.

Review also reproduced a measurement-wrapper defect: a nonexistent executable raised `FileNotFoundError` without writing a record. The revised wrapper records `launch_failed`, error details, and a null child exit code/CPU/RSS; only observed wrapper elapsed time is reported. This repair does **not** backfill the historical first-pass gap. Success, nonzero-child exit, and missing-executable regression tests pass, for seven tests total.

## Reproduce without overwriting recorded aggregates

This is an explicitly Linux-only diagnostic because it uses Linux `resource` accounting and KiB RSS semantics. Runtime dependencies used were NumPy 2.3.5, scikit-learn 1.8.0, and SciPy 1.17.0. No dependencies are installed by these scripts.

From a checkout containing this directory:

```sh
OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 python -m unittest discover -s experiments/group_falsification_20261023 -p 'test_*.py' -v
```

For an optional fresh synthetic run, copy `run.py`, `measure.py`, `protocol.json`, `frontier.py`, and `frontier_protocol.json` into a new private directory. In that directory run:

```sh
python measure.py process.json python run.py --out results_v2
python frontier.py
```

`results_v2` must not already exist. Fresh measured times need not reproduce old timings. Keep generated trajectories, weights, and process records private; do not replace the published original aggregates with a fresh run. Repository-wide `just fmt` and Rust tests are not claimed by this review; no Rust code changed. The original `just` installation attempt and model/data access were denied, and those requests were not retried or rerouted here.

## Sources and remaining blockers

Primary references: [Deep Sets](https://arxiv.org/abs/1703.06114), [Tree of Thoughts](https://arxiv.org/abs/2305.10601), [Set Transformer](https://proceedings.mlr.press/v97/lee19d.html), and [QASC](https://arxiv.org/abs/1910.11473). `sources.json` preserves the original public reference URLs and recorded content hashes. These moving-branch source URLs were not independently refetched during review; their digests identify reported inspected bytes, not an immutable upstream commit. No paper benchmark or natural-data result is claimed.

Pretrained encoder and QASC access remain blocked. Natural source-family isolation, real 8–16 semantic steps, strong same-head best-of-N, equal-actual-work controls, CPU replication, full optimizer FLOPs, and first-failed-run total process costs remain open. The deferred QASC design in the unchanged protocol has not been executed.

Historical negatives remain unchanged: Head 251/256 versus cosine 250/256 has an interval crossing zero; output v5 seed 29 worsened; all N/N REFINE=0. PR3547 remains DENY_ALL advisory, not physical reservation or proof of real Encoder/multistep reasoning. This diagnostic does not turn them into passes.

## Publication boundary

Only code, tests, protocols, aggregate tables, documentation, and public hashes are included. `SHA256SUMS` is the exact public-file allowlist. Raw trajectories, model weights, archive bytes, environment inventories, private paths, and process command records are excluded. `evidence_public_hashes.json` identifies the retained private evidence without embedding it.
