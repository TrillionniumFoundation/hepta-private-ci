# P1 actual decoded-output matched-control audit (research-only)

**Status: DRAFT / DENY_ALL / HOLD_NO_GO.** This is an isolated statistical and evidence-integrity harness, stacked on [#3211](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3211). It neither changes frozen [#3055](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3055) training or [#3039](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3039) heldout, nor demonstrates an NDU advantage.

`paired_superiority.py` accepts **individual actual decoded-output scores**, never blends per-Cell standalone scalar losses to infer risk for a combined latent direction. Before scoring, a separately implemented inference runner and external evaluator must freeze real model/decoder, objective, action basis, draw count, seed IDs, heldout cohort, validation comparator and measured physical cost units. This script cannot prove that those supplied fields are authentic.

## Fail-closed entry requirements

- Three or more unique training seeds and **at least 32 complete, registered heldout worlds per seed**; reject any calibration/heldout ID collision, hidden missing outcomes, mismatched draw counts and reorderings.
- Seven required arms: NDU, NoChange, validation-locked static, MoE, risk-neutral MPC, fixed-risk MPC and equal-actuator learned free Controller. Identical public inputs, model, decoder, objective and actuator digests across arms at every paired world.
- Per-draw loss, factual quality, ambiguity and inconsistency, with an immutable raw-output or failure witness identifier; explicit failed/overbudget draw rows remain in the denominator with preregistered maximum loss, zero quality, maximum ambiguity/inconsistency. Digests do not authenticate raw media.
- Measured physical cost ledger per arm/world: encoder, backbone, Cell, controller, decoder, verifier and amortized training. All components must be finite/nonnegative and sum to the actual total. The scalar units must be fixed externally and should represent **actual** cost (not approximate MAC-only counts). This tool cannot inspect GPUs, power or wall clock independently.
- Compute each episode loss **after averaging its draws**, then upper-tail CVaR90 with exact fractional probability mass. Resample **paired** worlds within resampled training seeds for 2,000+ bootstrap replicates; use a familywise Bonferroni upper bound across six baselines and five metrics. Require practical tail-risk superiority, noninferior factual quality/ambiguity/consistency, observed cost at most registered ratio and **per-world protected-task no-regression on all four semantic metrics** (loss, quality, ambiguity, inconsistency), plus protected per-world physical cost bounded by the predeclared total-cost ratio against every comparator. Every component's Boolean result is included in the receipt so strong global bootstrap gains cannot conceal a protected-world failure.
- The validation-selected comparator name is frozen in the manifest, but this code cannot verify the timestamp or independently prove that the validation selection did not inspect heldout. An external observer must check provenance, input isolation, cold-start drift and the registered freeze.

## Reproducible local check

```bash
python -m pip install 'numpy==1.26.4'
python -m unittest discover -s experiments/ndu_mgp_gates -p test_paired_superiority.py -v
```

Local CPU replay of the **exact Git blob** versions `25b59c9a30bd7846660a27d47cbf123cf021f740` and `23a8779de8e5a475a667bebb4b69457ba9df3535`: 15/15 adversarial tests. Two 2,000-bootstrap simulated cohorts correctly produce opposite **provisional** decisions while **both** retain `HOLD_NO_GO`. Exact-head hosted CI: `.github/workflows/ndu-mgp-paired-observed-shadow.yml`; its completion is a narrow structural gate, not scientific efficacy.

## Protected-task regression found and fixed (2026-10-22)

The prior per-world protected-task gate only checked `quality`. A 3-seed, 32-world/seed, 2,000-bootstrap synthetic adversarial cohort had **all ordinary CVaR/quality/ambiguity/inconsistency/cost gates passing**, with one protected world having loss 0.47 versus ~0.44 in a free learned controller, ambiguity 0.17 versus 0.06, and inconsistency 0.13 versus 0.04. Before the patch this still produced `all_provisional_gates_pass=true`. The new gate returns `protected_task_no_regression=false` and `all_provisional_gates_pass=false` without changing the already frozen research outcomes. A separate regression tests a protected-world cost spike while the aggregate cost budget still passes. The P1 study remains unauthenticated and `HOLD_NO_GO` regardless of fixture behavior.

A second demonstrated escape: setting just that failed world's `protected_task=false` in its post-evaluation observation row restored `all_provisional_gates_pass=true`, despite 2,000 bootstraps and the five-metric fix. To deny posthoc category relabeling, each training seed must now declare a nonempty `protected_world_ids` list in the frozen protocol and a canonical SHA-256 `protected_worlds_digest`; every observed protected-task Boolean must equal registered world membership. Relabeling, digest drift, or missing seed coverage raises `EvidenceGap`. **The digest is self-consistency only, not proof the protected cohort was externally frozen before heldout.** Independent signed custody is still missing; no production or science promotion follows.

This patch reran **42/42 local research-subpackage tests** (21 P1 tests, 6 new over the #3251 baseline). These tests do not execute a model or constitute an independent research replication. Prior 15-test blob references above are historical, not the newly changed SHA. Require exact patched-head CI and normal repository gates.

## Scientific state and negative controls

- [#3039 corrected v1.1](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3039) **failed** preregistered CVaR90 benefit versus strong static; no incremental advantage versus fixed-risk DP.
- [#3213 original-image grounding](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3213) also failed to establish NDU benefit versus strong router or best-of-two. Its one-seed/structured-overlay pipeline is **not** a substitute for natural multimodal or continuous-latent 3+ seed independent confirmation.
- P0 genuine encoder→flow→Cell→raw decoder frozen experiment, P1 positive independently scored matched-cost outcome, P2 a real frozen masked diffusion LLM, P3 natural sound/image/video with streaming constraints and P4 factorial train/test prospective replication remain open. Any failed scientific hypothesis remains a legitimate negative result, not a success to be manufactured by retuning.

No tool or physical action execution is permitted. No signatures, final-use authorization, irreversible streaming, model promotion, main merge or production deployment follows from this harness.
