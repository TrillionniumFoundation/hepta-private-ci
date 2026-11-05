# Terminal-anchored incumbent advantages: one frozen value-edit experiment

**No pure-weight improvement qualified in this experiment.** The one frozen scientific execution completed within budget, and all 6,400 TRAIN world/path replays and 4,960 held-out world/arm replays matched exactly. The new method improves the raw IID mean but fails the predeclared gated IID/OOD efficacy requirements. All unsuccessful and unselected candidates remain available.

The experiment is an isolated follow-up to the failed continuation-bias grid and failed uniform full-optimal-Q MSE compilation. It uses the same five existing training fits and all original 64 TRAIN public schedules per fit. It does not retrain the base models or access live Trader training.

## Results

| Primary comparison against C | TEST mean increment | Bonferroni-two 95% conditional interval | Lower bound > .005 |
| --- | ---: | --- | --- |
| E after validation gate, IID | +0.0048376514 | [-0.0120719041, 0.0217472070] | No |
| E after validation gate, OOD | -0.0024837919 | [-0.0111656527, 0.0061980689] | No |

Only fit23 E/G passed the finite validation-mean gate. Its OOD validation gain of +0.0389743957 became -0.0124189593 on TEST. The eight rejected E/G artifacts were restored byte-for-byte to C; the two accepted artifacts remain research evidence. No candidate was installed into a production model, and artifact restoration is not a claim of live production rollback. Overall TEST qualification failed, so no model is newly qualified for efficacy.

| Raw frozen arm | IID utility | OOD utility |
| --- | ---: | ---: |
| C | 0.2265222410 | 0.1275367079 |
| E | 0.2490640804 | 0.1253259548 |
| G | 0.2491925890 | 0.1253259548 |
| EU | 0.2265222410 | 0.1275367079 |
| EA | 0.2392931169 | 0.1282890385 |
| M | 0.1992900979 | 0.0883703817 |
| R | 0.1551832559 | 0.0801422551 |
| P, program control | 0.2280377088 | 0.1419144077 |
| J, program control | 0.3654721430 | 0.3128199855 |

E/G choose alpha `.75, .75, .25, .75, .75` for fits `11, 23, 37, 53, 71`. EU chooses no edit in every fit; that means no improvement among its five fixed candidates, not impossibility for every uniform-weight head. EA chooses `.75, .25, .25, .75, .75`. E and G have a small raw IID policy difference in fit11; the gated policies are identical. P/J are program gains and EA's secondary results cannot retrospectively replace the primary E arm.

The complete tables, validation-to-TEST decomposition, behavior metrics and cost ledger are in [reporting/REPORT.md](reporting/REPORT.md), [reporting/DERIVED_REPORT.json](reporting/DERIVED_REPORT.json) and [reporting/COSTS.json](reporting/COSTS.json). The original scientific records are [execution_r1/run/RESULTS.json](execution_r1/run/RESULTS.json), with the independent execution report at [independent_verification/VERIFIED.json](independent_verification/VERIFIED.json).

## Hypothesis and intervention

The previous compiler fitted optimal-teacher absolute Q values. A fixed Belief decoder controls the scale against which continuation scores compete. This trial instead computes the incumbent C's one-step own-law values, anchors them to C's unchanged terminal decoder, and gives greater weight to states C actually reaches:

\[
Y_a(s)=T_{\mathrm{pred}}(s)+Q_C(s,a)-T_{\mathrm{own}}(s).
\]

Here the terminal action is selected by C's unchanged STOP/SUBMIT decoder; `T_own` is that specific action's payoff under the exact checkpoint tables. The target is not an evaluator-truth label. The state distribution is a fixed 90% normalized incumbent-occupancy / 10% uniform-support mixture, normalized separately for each world and over its legal continuation actions. The complete state identity includes accumulated charges.

Only 147 continuation-head parameters may change. The original 85-input / 48-tanh representation, Belief row, core tables and decoder remain protected. A direct quadratic solver and matched projected-gradient solver share the same data, objective, norm radius and stopping tolerance. The gradient comparison is optimization of this fixed-feature subproblem, not complete neural-network retraining.

Each of E, G, EU and EA separately selects one of the same five actual serialized heads at `alpha = 0, .25, .5, .75, 1` using complete TRAIN own-law expected task utility. A tie chooses the smaller alpha. This includes exact no-edit C. It establishes no optimum outside the fixed finite candidate set.

| Arm | Operation |
| --- | --- |
| C | Exact published continuation incumbent; strong no-edit model baseline |
| E | Anchored one-step target, occupancy mixture, direct solve; primary weight arm |
| G | Same objective/information as E, matched PGD and same finite path |
| EU | Anchored target with uniform-support weights; same finite path |
| EA | Unanchored one-step `Q_C` target with occupancy mixture; same finite path |
| M | Previously frozen old DQ MSE model; no new fitting or selection |
| R | One seeded random edit matching the final selected and serialized E norm |
| P | No weight edit: analytic own-law terminal posterior program control |
| J | No weight edit: complete own-law Bellman program control |

## Freeze, held-out evaluation and inference

`PROTOCOL_FROZEN.json` was written before fitting any new candidate or generating any new world. Its SHA256 is `226713c4ceab5ebf4da08e62d495a529ddb41a461bec1ce3f7f6ffbecab981dd`. This is a local source/protocol freeze, not an external preregistration. Earlier proposal/review drafts are retained and do not define the executed protocol.

All 100 finite path heads, their 6,400 ordered TRAIN world/path scores and every selected raw model freeze before validation. The run then generates 160 fresh validation worlds. E/G are accepted per fit only if both domains do not lose against C and the equal-domain mean gain is at least .005, with their own solver numerical gate passing. A rejected candidate restores the complete serialized C, including deterministic gzip bytes. An accepted candidate has no claimed restoration.

All gate decisions and chosen model identities freeze before generating the 320 TEST worlds. New schedule content is checked against all 2,416 available historical schedules and other new schedules; any duplicate aborts without replacement. Unknown external trials and unavailable historical confirmation content remain outside that exclusion guarantee. Content uniqueness is not proof of statistical independence.

The only two primary comparisons are `E_gated - C` in IID and OOD. The unit is the mean for each of five reused training fits. The paired Student-t df=4 intervals use Bonferroni across those two comparisons; both lower bounds must exceed .005. These are conditional, model-assumption intervals for the existing training family. There are zero new training fits, and world counts do not increase that inferential sample size. This is not a new Hepta 2x2 D-minus-B factorial.

## Independent checks

`verify_records.py` does not import the new experiment worker or `task_graph.py`. It checks source/model identities, exact rational F64 norm membership, protected fields, all five actual alpha values, finite-set selection, the random draw and norm match, every gate and byte-identical rejected rollback, content exclusion, predetermined arm sets and local event ordering. It independently inverts the closed-form df=4 CDF to check the statistical intervals.

Its full replay options require exactly 6,400 TRAIN world/path evaluations through the old frozen recursive executor and 4,960 held-out world/arm evaluations through a separate literal-head recursive evaluator. All eight task/behavior values and visited-node counts are checked. The frozen original representation/core/law definitions remain shared; this is not a wholly independent implementation of the original simulator.

The separate reviewer's final record is preserved byte-for-byte in [review/INDEPENDENT_EXPERIMENT_REVIEW.json](review/INDEPENDENT_EXPERIMENT_REVIEW.json). Its [post-hoc arithmetic audit](review/POSTHOC_RECORD_AUDIT.json) and [read-only checker](review/verify_posthoc_records.py) independently confirm the 48-world decomposition and illustration rule without executing new models or teachers. The reviewer observes a maximum scalar linear-accounting residual of 2.57e-16, also below the frozen 2e-13 tolerance.

## Reproduction

All required model, schedule, historical-exclusion and original task-definition inputs are included. The preparation manifest records their original identities and public source commits. Candidate inputs retain original public TRAIN schedules, not their Q, posterior, labels, sampled outcomes or original VAL rows.

The recorded environment is Python 3.12.14, NumPy 2.3.5 and SciPy 1.17.0. Use a fresh output directory and the existing protocol; do not call the freeze script to generate a new seed for a replay.

```bash
python measure_process.py --output replay_r1 --wall-limit 1830 -- \
  python run_experiment.py --protocol PROTOCOL_FROZEN.json --output replay_r1/run

python measure_process.py --output replay_verification --wall-limit 1230 -- \
  python verify_records.py replay_r1/run --output replay_verification/VERIFIED.json \
  --replay-train --replay-holdouts
```

To verify stored records without recomputing neural features or trajectories:

```bash
python verify_records.py execution_r1/run --output records_check.json
```

Every output is create-only. Existing results, failures and process receipts must be retained. Replaying the same frozen protocol reproduces the same worlds and is a computational replay, not another statistical confirmation.

## A bounded post-hoc explanation of the accepted candidate's failure

After the failed main result and its complete independent replay, a separately frozen diagnostic examined all 16 existing fit23 OOD validation worlds and all 32 OOD TEST worlds. It generated no new sample or parameter. Source/input identities, all 48 records, the stated illustration rule and the 3.130104 CPU-second process receipt are under [posthoc/](posthoc/README.md).

The TEST loss occurs under the checkpoint's own law as well: own-law E-minus-C is -0.0139610269, versus evaluator-law -0.0124189593. Under the evaluator's unnormalized E visitation distribution, states with negative own-law one-step C advantage contribute -0.0463161318; the other states contribute +0.0338971724. Their sum is the actual -0.0124189593. This identifies out-of-sample head/target inconsistency on the exposed states. It does not distinguish all possible causes among feature capacity, the trust radius, the quadratic approximation and coverage, nor prove that the checkpoint law is correct everywhere.

For each law separately the diagnostic verifies

\[
V_E(s_0)-V_C(s_0)=\sum_s d_E(s)\,[Q_C(s,\pi_E(s))-V_C(s)],
\]

where `d_E` is unnormalized reach, not the normalized training weights. It also separately partitions the policy difference at first common-prefix action divergences using each state's complete `V_E - V_C` suffix. The largest residual of either global identity is 1.11e-16. A local one-step counterfactual is not substituted for the complete E policy value.

The stated post-hoc illustration rule selects the worst existing TEST world, index6. At tick5, with no pending observation and read budget3, C chooses READ but E chooses WAIT:

| Quantity at the first differing state | WAIT | READ |
| --- | ---: | ---: |
| C head score | 0.2199535594 | 0.2336972805 |
| E head score | 0.2477313258 | 0.2441127457 |
| Own-law one-step Q, then following C | 0.0870621138 | 0.5586208473 |
| Evaluator one-step Q, then following C | 0.1463583656 | 0.5681082476 |

Both value models strongly favor the final reading opportunity. The edited linear head changes the WAIT-minus-READ margin from -0.0137437211 to +0.0036185801 and reverses the action. The complete world utility difference is -0.4217498820. The full 49-coordinate delta-weight-times-hidden decomposition is preserved in [the diagnostic record](posthoc/execution_r1/run/test_006.json.gz), with maximum linear-margin residual 2.43e-16 across the diagnostic. Those are fixed-representation contributions, not independent causal interventions on individual weights or new confirmation. Counts of changed states are support unions and do not increase the number of independent training fits.

## Compute and scope

The scientific worker is bounded at 1,200 CPU seconds / 1,800 wall seconds, with one numeric thread and a measured 1 GiB RSS target. A failure preserves partial artifacts; no smaller-fit or smaller-world substitute is allowed. Complete child-process CPU/wall/RSS receipts include imports and final writes. Controller CPU covers only its main body, so controller startup imports and final receipt writing are not included. Preparation, semantic checks, freezing, the worker and independent verification have separate receipts.

The complete scientific worker used **535.948697 CPU seconds / 537.594690 wall seconds**, peak RSS **260,947,968 bytes**. Independent complete replay used **332.887897 CPU seconds / 369.168702 wall seconds**. Preparation, semantic checks, both freezes, science, independent replay, the bounded post-hoc diagnostic and reporting total **875.455436 measured child CPU seconds**. The manifest/packaging and other unmetered orchestration are not included in that known sum.

Endpoint solving alone used 0.216800 CPU seconds for E and 4.370660 for G. Including their common TRAIN state/feature/teacher work, common quadratic setup, complete finite path and selected-model serialization, the restricted candidate-construction figures are **167.378052 versus 173.693328 seconds**, a G/E ratio of **1.037731**. This is not a full-training or end-to-end deployment speedup. J's cold own-law planning for the 480 held-out worlds used an additional **101.134916 CPU seconds**. Nested component timings must not be added again to complete process totals.

The finite task already charges requested reads, sensor repairs and simulated elapsed time. Actual CPU has no measured economic conversion here. Base-model training, unknown past searches, agent/editor time and energy have not been recovered as full costs. Solver-only speed differences cannot be presented as end-to-end training or full NDU economic superiority.

Each held-out arm starts with a cold feature cache, but the evaluator's truth oracle/cache can be shared among arms in a world. `policy_cpu_seconds` already contains feature work; adding `feature_cpu_seconds` would double count it. Neither per-arm evaluator totals nor those cold-feature timings are a production cold-start or neural-throughput benchmark.

The task predicts latent sign at tick six; it does not implement first passage or financial Call/Put decisions. P/J are program controls and their own-law planning cost is reported. Any benefit from them is not credited to weight editing. This trial makes no claim of actual Trader improvement, universal circuit understanding or global optimality over the full network.

The frozen result's `all_original_failures_retained=true` refers to this run and the known preserved materials. It does not claim that unknown external trials or unavailable historical confirmation content can be reconstructed. No additional candidate tuning, resampling or new efficacy experiment followed this failure; the separate bounded post-hoc diagnosis is disclosed above.
