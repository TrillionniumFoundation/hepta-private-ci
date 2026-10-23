# P1 actual decoded-output matched-control audit (research-only)

**Status: DRAFT / DENY_ALL / HOLD_NO_GO.** This is an isolated statistical and evidence-integrity harness, stacked on [#3211](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3211). It neither changes frozen [#3055](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3055) training or [#3039](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3039) heldout, nor demonstrates an NDU advantage.

`paired_superiority.py` accepts **individual actual decoded-output scores**, never blends per-Cell standalone scalar losses to infer risk for a combined latent direction. Before scoring, a separately implemented inference runner and external evaluator must freeze real model/decoder, objective, action basis, draw count, seed IDs, heldout cohort, validation comparator and measured physical cost units. This script cannot prove that those supplied fields are authentic.

## Fail-closed entry requirements

- Three or more unique training seeds and **at least 32 complete, registered heldout worlds per seed**; reject any calibration/heldout ID collision, hidden missing outcomes, mismatched draw counts and reorderings.
- Seven required arms: NDU, NoChange, validation-locked static, MoE, risk-neutral MPC, fixed-risk MPC and equal-actuator learned free Controller. Identical public inputs, model, decoder, objective and actuator digests across arms at every paired world.
- Per-draw loss, factual quality, ambiguity and inconsistency, with an immutable raw-output or failure witness identifier; explicit failed/overbudget draw rows remain in the denominator with preregistered maximum loss, zero quality, maximum ambiguity/inconsistency. Digests do not authenticate raw media.
- **Common-random-numbers fairness is mandatory:** preregister `paired_noise_seed` and `paired_noise_protocol=common-random-numbers-v1`, derive one deterministic per-seed/world/draw `draw_randomness_sha256` shared by all seven arms, and deny mismatched/missing stochastic witness fields before statistics. Different lucky/noisy samples per arm could manufacture an apparent NDU effect. This locks the declared sampling plan structurally; only a separate trusted recorder can establish that live generation actually used the recorded seeds.
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

## Additional 2026-10-23 local adversarial controls

Four new tests reject a mismatched NDU draw RNG, absent preregistration, absent control draw witness, and verify the new field never grants scientific authority. The original 15 P1 tests become 19; the local standalone suite (P1+raw decoder checks+evidence denial) recorded 45/45 passes. These fixtures are synthetic, not independent model outputs or evidence that a real diffusion/omnimodal NDU implementation wins.

## Failure-penalty correctness (2026-10-23)

- A failed output cannot become a *better* outcome than an extreme completed output: every successful draw's external loss must be at most the preregistered `failure_loss` ceiling; otherwise the study is inadmissible. In the counterexample, allowing a completed loss 1000 alongside a failure penalty of 2 would reward recoding catastrophe as failure. This is now a hard reject, not clipping or a posthoc threshold update.
