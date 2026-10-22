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


## Fail-closed intake corrections (2026-10-22 local regression)

The first seven-arm evidence validator admitted three structurally invalid
inputs even while its overall status remained `HOLD_NO_GO`:

- A *completed* decoded loss larger than the protocol's `failure_loss` was
  allowed. The result would make an execution failure look numerically **better**
  than a successful output. Intake now requires completed loss ≤ the registered
  failure penalty. If the task genuinely has unbounded raw loss, its preregistered
  external scorer must first specify a consistent clipping/penalty contract;
  the reviewer must not silently clip historical results post hoc.
- One protected world in one training seed, with inadequate coverage in that
  or other seeds, could satisfy the old pooled “any protected sample” check.
  Intake now demands at least `max(3, ceil(10% * matched_worlds_per_seed))`
  protected worlds independently in **each** registered training seed. This
  is an admission/support threshold, not a statistical guarantee of subgroup
  no-regression.
- An empty or duplicated calibration-world ID manifest was accepted. The
  registered calibration cohort now requires nonempty, distinct string IDs
  and zero overlap with every heldout world.

Four independent synthetic regressions preserve all preexisting checks and
exercise the formerly accepted invalid inputs. On current-session local CPU,
the full archived P0/P1 research subset was rerun with a reconstructed
`BLOCKED` manifest because the prior standalone archive accidentally omitted
`qualification.json`: **45/45 tests pass**, and final P0–P4 evidence assessment
still exits nonzero as `HOLD_NO_GO`. The reconstructed manifest is a local
test fixture, **not** the byte-identical published qualification record.
No real model/generation, prospective heldout, target-host acceptance or
scientific efficacy claim follows from these 45 tests.
