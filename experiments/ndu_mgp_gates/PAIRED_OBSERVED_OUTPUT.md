# P1 actual decoded-output matched-control audit (research-only)

**Status: DRAFT / DENY_ALL / HOLD_NO_GO.** This is an isolated statistical and evidence-integrity harness, stacked on [#3211](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3211). It neither changes frozen [#3055](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3055) training or [#3039](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3039) heldout, nor demonstrates an NDU advantage.

`paired_superiority.py` accepts **individual actual decoded-output scores**, never blends per-Cell standalone scalar losses to infer risk for a combined latent direction. Before scoring, a separately implemented inference runner and external evaluator must freeze real model/decoder, objective, action basis, draw count, seed IDs, heldout cohort, validation comparator and measured physical cost units. This script cannot prove that those supplied fields are authentic.

## Fail-closed entry requirements

- Three or more unique training seeds and **at least 32 complete, registered heldout worlds per seed**; reject any calibration/heldout ID collision, hidden missing outcomes, mismatched draw counts and reorderings.
- Seven required arms: NDU, NoChange, validation-locked static, MoE, risk-neutral MPC, fixed-risk MPC and equal-actuator learned free Controller. Identical public inputs, model, decoder, objective and actuator digests across arms at every paired world.
- Per-draw loss, factual quality, ambiguity and inconsistency, with an immutable raw-output or failure witness identifier; explicit failed/overbudget draw rows remain in the denominator with preregistered maximum loss, zero quality, maximum ambiguity/inconsistency. Digests do not authenticate raw media.
- Measured physical cost ledger per arm/world: encoder, backbone, Cell, controller, decoder, verifier and amortized training. All components must be finite/nonnegative and sum to the actual total. The scalar units must be fixed externally and should represent **actual** cost (not approximate MAC-only counts). This tool cannot inspect GPUs, power or wall clock independently.
- Compute each episode loss **after averaging its draws**, then upper-tail CVaR90 with exact fractional probability mass. Resample **paired** source-group blocks within resampled training seeds for 2,000+ bootstrap replicates; use a familywise Bonferroni upper bound across six baselines and five metrics. Require practical tail-risk superiority, noninferior factual quality/ambiguity/consistency, observed cost at most registered ratio and **zero protected-task quality regression** against each comparator.
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

## Source-group-aware statistical hardening (separate research child)

- Require preregistered `heldout_source_group_ids` mapping each seed to one immutable source group per world, and `calibration_source_group_ids` disjoint from heldout. A source group is the original image, prompt, account, task or other common latent cause of repeated views. Treat all views of a source as one block in bootstrap; require at least eight **balanced** groups per seed and no repeated source IDs across registered training seeds. Reject missing, renamed, overlapping or unbalanced group manifests rather than silently applying the wrong estimator. More general variable-size groups need a separately reviewed estimator.
- Preserve the same group selection and all of its rows simultaneously across NDU and every comparator. This avoids pseudoreplication of correlated views, and makes the effective number of independent sources explicit in the receipt.
- Reject contradictory external metrics for identical decoded raw-output witness digests within the same heldout world. Identical output with identical metrics across arms remains permitted; witness IDs are not cryptographic authentication.
- The cost gate now requires both the observed NDU/control cost ratio and a Bonferroni one-sided upper bootstrap bound on `mean_cost_NDU − max_ratio × mean_cost_control` to be nonpositive. A favorable sample mean alone cannot claim noninferior actual total cost.
- Eight regression cases added, including a near-budget case where the observed cost ratio passes but uncertainty does not; in the locally retained NumPy/PyTorch CPU research subset `44/44` tests pass (`23` specific to the paired comparator). This is not an independent heldout claim, external observer, real-model training, or target-host execution receipt.

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. This change supersedes earlier *unclustered* synthetic examples as suitable statistical evidence; historical frozen #3039 and #3213 negative experimental outcomes remain unchanged. Dedicated trust and P0–P4 independent evidence gates are still open.
