# P1 actual decoded-output matched-control audit (research-only)

**Status: DRAFT / DENY_ALL / HOLD_NO_GO.** This is an isolated statistical and evidence-integrity harness, stacked on [#3211](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3211). It neither changes frozen [#3055](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3055) training or [#3039](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3039) heldout, nor demonstrates an NDU advantage.

`paired_superiority.py` accepts **individual actual decoded-output scores**, never blends per-Cell standalone scalar losses to infer risk for a combined latent direction. Before scoring, a separately implemented inference runner and external evaluator must freeze real model/decoder, objective, action basis, draw count, seed IDs, heldout cohort, validation comparator and measured physical cost units. This script cannot prove that those supplied fields are authentic.

## Fail-closed entry requirements

- Three or more unique training seeds and **at least 32 complete, registered heldout worlds per seed**; reject any calibration/heldout ID collision, hidden missing outcomes, mismatched draw counts and reorderings.
- Seven required arms: NDU, NoChange, validation-locked static, MoE, risk-neutral MPC, fixed-risk MPC and equal-actuator learned free Controller. Identical public inputs, model, decoder, objective and actuator digests across arms at every paired world.
- Per-draw loss, factual quality, ambiguity and inconsistency, with an immutable raw-output or failure witness identifier; explicit failed/overbudget draw rows remain in the denominator with preregistered maximum loss, zero quality, maximum ambiguity/inconsistency. Digests do not authenticate raw media.
- Measured physical cost ledger per arm/world: encoder, backbone, Cell, controller, decoder, verifier and amortized training. All components must be finite/nonnegative and sum to the actual total. The scalar units must be fixed externally and should represent **actual** cost (not approximate MAC-only counts). This tool cannot inspect GPUs, power or wall clock independently.
- Compute each episode loss **after averaging its draws**, then upper-tail CVaR90 with exact fractional probability mass. Resample **paired** worlds within resampled training seeds for 2,000+ bootstrap replicates; use a familywise Bonferroni upper bound across six baselines and five metrics. Require practical tail-risk superiority, noninferior factual quality/ambiguity/consistency, observed cost at most registered ratio and **zero protected-task quality regression** against each comparator.
- The validation-selected comparator name is frozen in the manifest, but this code cannot verify the timestamp or independently prove that the validation selection did not inspect heldout. An external observer must check provenance, input isolation, cold-start drift and the registered freeze.

## Reproducible local check

```bash
python -m pip install 'numpy==1.26.4'
python -m unittest discover -s experiments/ndu_mgp_gates -p test_paired_superiority.py -v
```

Local CPU replay of the **exact Git blob** versions `25b59c9a30bd7846660a27d47cbf123cf021f740` and `23a8779de8e5a475a667bebb4b69457ba9df3535`: 15/15 adversarial tests. Two 2,000-bootstrap simulated cohorts correctly produce opposite **provisional** decisions while **both** retain `HOLD_NO_GO`. Exact-head hosted CI: `.github/workflows/ndu-mgp-paired-observed-shadow.yml`; its completion is a narrow structural gate, not scientific efficacy.

## Scientific state and negative controls

- [#3039 corrected v1.1](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3039) **failed** preregistered CVaR90 benefit versus strong static; no incremental advantage versus fixed-risk DP.
- [#3213 original-image grounding](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3213) also failed to establish NDU benefit versus strong router or best-of-two. Its one-seed/structured-overlay pipeline is **not** a substitute for natural multimodal or continuous-latent 3+ seed independent confirmation.
- P0 genuine encoder→flow→Cell→raw decoder frozen experiment, P1 positive independently scored matched-cost outcome, P2 a real frozen masked diffusion LLM, P3 natural sound/image/video with streaming constraints and P4 factorial train/test prospective replication remain open. Any failed scientific hypothesis remains a legitimate negative result, not a success to be manufactured by retuning.

No tool or physical action execution is permitted. No signatures, final-use authorization, irreversible streaming, model promotion, main merge or production deployment follows from this harness.

## Four-way split and original-source integrity amendment (child Draft)

Prior #3251 compared calibration-world IDs with heldout-world IDs, but did not demand original-source manifests for **training** or **validation**. An image with a different crop/augment ID could therefore appear as an allegedly fresh heldout item after it influenced training or baseline selection. Per-world seed bootstrap also treated repeated views of one source as independent. Neither shortcut supports independent generalization claims.

This child requires independently frozen **training, validation, calibration and heldout** world-ID and original-source-group manifests; rejects pairwise overlap in **both** ID namespaces; rejects re-labelled heldout sources, unsupported imbalanced group sizes, duplicate calibration IDs and seed-group reuse; and samples full original-source clusters within sampled training seeds in the paired bootstrap. A measured total-cost **bootstrap upper bound**, not only its mean ratio, must fit the registered resource margin. It also rejects contradictory external scores for the same decoded-output witness on the same world. Training repeats of an original within its training partition remain allowed; this is a provenance contract, not a raw-image hashing or cryptographic observer.

Tests are adversarial synthetic fixtures. Even with all checks passing, the manifests, external evaluator, actual decoder execution, pretrained model, cost readings and future-window identity are caller supplied and untrusted; **all decisions remain DRAFT / DENY_ALL / HOLD_NO_GO**. Existing #3039/#3213 negative results are untouched.


## Absolute per-world physical budget correction (child Draft)

The registered `max_total_cost_ratio` and paired mean-cost upper CI are **not a
hard physical budget**: seven arms all spending 21 seconds can satisfy a
1.05 cost ratio and pass the original cost gate despite a 2-second project
budget. The baseline failure is reproducible using the earlier unmodified
shadow evaluator on 3 seeds × 32 worlds.

This additive research correction requires `protocol.hard_world_cost_limit`
in the same `cost_units` already frozen externally, and compares every
arm/world's reconciled measured total to that absolute limit. A world exceeding
the cap must remain in its registered denominator with the **actual** measured
overrun and the full `failed` penalty on **all** decoded draws, or the result
is rejected. It reports `overbudget_episodes_by_arm`, and
`absolute_world_cost_budget` cannot pass any strong-comparator gate when a
single arm has an overrun. This is intentionally conservative: an
out-of-budget baseline must not make an NDU win appear fair.

Local synthetic CPU suite (including five hard-budget regressions) passes
57/57 tests. The new source remains ordinary unauthenticated research input;
the caller-provided cap, timing measurement and output witness require a
separately trusted independent observer. No new model training, heldout
evaluation, production resource monitoring, physical authorization or
scientific NDU superiority has been established.


## Semantic failure-penalty and small-budget ledger integrity (child Draft)

An original decoder outcome marked **completed** previously accepted any finite
nonnegative `loss`, even if the registered fixed penalty for a `failed`
draw was lower. A completed loss of 30 and failed loss of 2 were both legal:
abort/failure could appear statistically safer than success. This correction
**fails closed** on a completed loss exceeding `failure_loss`, on *every* NDU
and strong-control arm. The registered external evaluator must bound its
completed-loss domain or specify a valid failure penalty **before** touching
new heldout data. The patch does not clamp values, rewrite labels or retune
the existing experiment after seeing heldout.

The former physical ledger reconciliation accepted an **absolute** discrepancy
of `1e-9` even for costs around `1e-7`. For a registered cap `1.035e-7`,
the original reference could record `actual_subtotal=1.04e-7`,
`declared_total=1.032e-7` and incorrectly pass a *provisional* 2,000-bootstrap
comparison under a 1.05 cost ratio. The new check uses a **scale-relative**
`math.isclose(..., rel_tol=1e-10, abs_tol=0)`, preserving genuine IEEE-754
roundoff without a unit-dependent escape hatch. The already strict absolute
`total > hard_world_cost_limit` admission is retained.

Five synthetic adversarial/boundary tests are added: NDU severe completed
loss, strong comparator severe completed loss, equality at the frozen maximum,
fraudulent tiny cost ledger, and allowable tiny roundoff. Locally 63/63
`pytest` tests pass with Python 3.13 / NumPy 2.3.5 / torch 2.10 CPU.
This is a **research metadata validator**, not real decoded-output generation,
source authentication, scientific superiority, or trusted physical metering.
The published #3039 and #3213 negative results, frozen #3055 protocol,
production authority, and all model weights remain unchanged.


## Protected-task cohort representation (child Draft, fail-closed)

Previous P1 evaluation required only `np.any(protected)`; a synthetic
experiment with **one protected world among 96** (three registered seeds)
could report every comparator's `protected_task_no_regression=True` and
`all_provisional_gates_pass=True` if other thresholds were satisfied.
One original source is not valid multi-seed protected-task coverage.

The revised research protocol requires an explicit
`min_protected_source_groups_per_seed` integer **at least 8**, locked before
heldout, and a minimum of this many distinct **original-source groups in
each training seed**. Views/crops of one original source cannot satisfy the
requirement. The report exposes `protected_worlds_per_seed`,
`protected_original_sources_per_seed` and the registered floor. Missing
coverage in even one seed fails closed. Six synthetic adversarial/boundary
regressions cover missing or trivially low floor, one protected world, absent
seed cohort, repeated-source aliasing and complete per-seed receipts;
**69/69 local Python CPU checks pass**.

The eight-source floor is a **minimum research provenance sanity guard**,
not proof of statistical power or representative protected-population
coverage. Actual generalization and non-regression still require externally
frozen protected labels, source-identity verification, sample-size/power
analysis, prospective independent holdout, and physical model execution.
This change does not alter #3055/#3039/#3213 frozen studies or authorize
model deployment/Final-use.


## Protected-task absolute service guard (child research amendment)

The #3282 source-coverage minimum is necessary but **not sufficient**: a
synthetic 3-training-seed, 512-world-per-seed paired cohort can have eight
distinct protected original sources per seed, with **every protected draw
failing in every arm**, yet all six comparative NDU CVaR/non-regression gates
and `all_provisional_gates_pass` returned true. This is not evidence that
protected tasks are served. The original all-failed contrast is retained as
the new negative control, never as a successful NDU run.

Before any heldout, register both:
- `min_protected_ndu_quality`: required source-equal **absolute** NDU
  protected-task mean quality in each training seed, in [0.5, 1].
- `min_protected_ndu_completion`: required source-equal **absolute**
  completed-draw fraction in each training seed, in [0.5, 1].

These thresholds are compulsory and have no dynamic default. The evaluator
counts each distinct protected original source once (averaging its protected
views first), separately for every training seed, and publishes the source-equal
quality and completion rates. `protected_task_absolute_service` blocks
**every** provisional strong-baseline comparison when either floor fails.
Existing per-world protected non-regression and minimum independent source
coverage remain mandatory. The documented procedural floors are conservative
research safeguards, **not** a validated statistical-power result, verified
protected-label source, production safety certification, or substitute for
independent bias/error audits.

This patch is additive to frozen parent #3282; no original #3039/#3213 negative
heldout outcome, original #3055 source, product authority or deployed model is
changed. The 75-test local CPU suite passed before publication. New exact-head
CI must also pass; science remains `DRAFT / DENY_ALL / HOLD_NO_GO`.
