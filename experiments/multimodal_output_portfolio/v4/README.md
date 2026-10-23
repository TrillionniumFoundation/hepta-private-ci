# HEPTA NDU-OOP v4: four-modality allocation mechanism

**Status: RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL.** This new, independent source-only experiment does **not** change or requalify v1/v1.1/v2/v3 frozen results, deploy a model, authorize a NeuronRuntime driver, or close natural-data/production/specialized-runner blockers. It tests a missing **R05 algorithmic mechanism**: changing the allocation to **text, audio, image and video** as *already observable* intermediate generation state changes, while every required output is still emitted.

## Exact mathematical scope

A public Markov state is `S=(levels[4], step, remaining_physical_units, previous_active_mask)`. `levels` are **synthetic observable quality proxies**, not hidden truth, real semantic success or source labels. A control is the integer vector `w=(w_text,w_audio,w_image,w_video)`, `0<=w_i<=2`, `sum(w)<=2`, or STOP. A finite, joint three-branch shock affects all active modalities. A new Cell activation incurs a fixed once-per-transition budget charge. Every route reserves **four decoder emission units**, so there is no budget-saving omission of required outputs.

At STOP the system materializes four distinct toy media outputs (a text symbol, integer audio samples, image matrix and video frames). The *separate* fixture scorer reads these **decoded raw objects**, charges squared error against an openly registered fixed synthetic goal, and penalizes cross-modality inconsistency. Thus mixture losses are not silently estimated by averaging standalone Head scores. The test verifies a complementarity trap where either image or video refinement alone increases loss but joint refinement reduces it.

The controller optimizes **finite conditional entropic utility**, not a risk/variance surrogate. For risk coefficient `gamma>0`:

`CE_gamma(v) = -log(sum_b p_b exp(-gamma v_b)) / gamma`.

For `gamma=0`, it reduces to conditional expectation. Backward induction computes

`V(S) = max[-decoded_loss(S)-price*emission_reserve, max_w{-price*cost(S,w)+CE_gamma(V(S'_b))}]`

under exact constraints, jointly correlated shocks, and the declared horizon. The solver observes the *new* public state **after** each actual random transition. It cannot read the next shock before selecting its action. This is finite-model optimality only: no Riccati closure, HJB/FBSDE proof, diffusion LM, gradient training, Merton continuous-wealth theorem, or empirical advantage against a pretrained generator is asserted. The mean/covariance function is diagnostic and retains common-cause dependence; the actual optimal action is chosen from terminal decoded utility and full transition laws.

## Why not mark R05 closed yet?

This provides an executable **four-modality allocation algorithm and independent rational-reference unit tests**; it does **not** exercise genuine pretrained text/audio/image/video Decoder/Cell outputs or source-disjoint natural data. R05's real causal result and matched controlled confirmation therefore remain OPEN. Preserve the original v3 `BLOCKER_LEDGER.json` with its `all_blockers_closed=false`; do not overwrite an evidence ledger to create fictitious closure.

## Local verification

Requires only Python >=3.10 standard library:

```bash
cd experiments/multimodal_output_portfolio/v4
python3 -m unittest discover -v -p "test_*.py"
python3 -m compileall -q portfolio.py test_portfolio.py test_reallocation.py
```

The 10 tests include a complete three-decision feedback trajectory that switches from image/video to audio to text after observed shocks with nonzero activation costs, state-conditional reallocation, nonconvex cross-output penalty and joint portfolio action, positive covariance from a shared shock, strict total-physical-budget and fixed switch charging, stable entropic risk, an **independent exact `fractions.Fraction` risk-neutral Bellman reference**, causal noise timing, terminal four-output emission, and fail-closed invalid states/actions. The return trace includes `trace_sha256` and `output_sha256` bound to canonical local JSON. These are **integrity hashes, not signatures or independent outcome attestations**. No CI pass is inferred from local tests.

## Adversarial numeric and configuration admission follow-up

The separate `test_numeric_admission.py` exercises impossible (zero-mass)
conditional branches with extreme payoffs, probability normalization,
typed physical-cost/horizon units, and NaN or boolean profile injection.
Conditional entropic utility now centers only **supported** outcomes; a
zero-probability low outlier must not force all other exponentials to
underflow. Probability laws use an explicit absolute normalization
tolerance rather than the looser implicit relative tolerance. These are
source-level correctness fixes, **not** evidence of risk-model calibration,
natural multimodal quality, or production admission.

## Next independently measured scientific experiment

Replace the synthetic proxy-state/decoder fixtures with a source-pinned **real** shared Encoder plus four output decoders, observed partial latents, actual Neural/Cell feature invocation and all separately paid decoder/verifier/selection costs. Preregister source-disjoint natural tasks, multiple training seeds and common random-number draws, then compare same-information/static, MoE, risk-neutral MPC, fixed-risk MPC, dynamic NDU and best-of-N with independent decoded-output scoring and risk/coverage/cost thresholds. Train/inference factorial ablations are essential to determine whether NDU changes learned generation rather than only selecting an existing candidate. Do not enable or deploy any output-portfolio policy based only on this code.
