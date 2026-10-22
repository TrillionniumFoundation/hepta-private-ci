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
