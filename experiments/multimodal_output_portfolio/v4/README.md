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

## Independent full-path counterfactual audit (toy, not natural output)

`counterfactual_audit.py` independently enumerates the finite shock tree
and **materializes four actual synthetic outputs** at termination before
scoring their joint external fixture loss. It charges four mandatory
decoder-emission units, per-action units and fixed activation costs. The
comparator is the **best ex-ante open-loop schedule** over the same bounded
action lattice (not an arbitrarily weak static action); impossible plans
are screened against all modeled physical budget requirements. Its exact
search rejects profiles exceeding 5,000 candidate schedules instead of
silently reducing the baseline search.

The nominated dynamic policy is frozen on the model's registered common
three-branch shock law. Its full-path entropic value is independently
compared with the Controller's recursive value; parity and nominal
dominance over the enumerated open-loop subpolicy are **finite-model
properties**, not NDU foundation-model efficacy.

`paired_nominal_shift` reweights unchanged action policies using an
alternative scalar law. `paired_dependence_shift` changes the *joint*
four-modality shock vectors, allowing anti-correlated modality errors and
exposing a registered adversarial case where the dynamic policy has
**better mean external loss but worse decoded CVaR90 and worse risk-sensitive
utility** than the same nominally optimized static plan. This makes it
incorrect to claim distribution-shift safety from nominal Bellman parity.
The empirical CVaR90 uses exact fractional worst-10% probability mass,
not a ceiling count of worst examples.

This is a unit-testable stress **counterexample on toy media and modeled
integer units**, with no pretrained Decoder/Cell, source-disjoint natural
heldout, real wall/energy measurements, or independent witness to a
real-world terminal fact. The Controller itself is unchanged. The
exhaustive helper must not run on a production inference hot path.

Run:
```bash
cd experiments/multimodal_output_portfolio/v4
python3 -m unittest discover -v -p "test_*.py"
python3 -m compileall -q portfolio.py counterfactual_audit.py test_*.py
```

## Paid independent evidence acquisition versus mandatory outputs

`information_acquisition.py` is a separate two-class *synthetic* Bayesian
test of the user's information-versus-generation portfolio principle. A
public easy/hard observation determines a declared prior, and a separately
specified 98%-accurate witness can be queried at one additional modeled
unit. Four output emissions always reserve four modeled units, and the
witness is observed only **after** a costed query. The controller compares
conditional entropic continuation value and stopping value; hidden truth
labels are used only by the independent offline terminal scorer.

In the registered 50/50 easy/hard toy population with gamma=1 and query
shadow price 0.05, the local exact event enumeration yields:

| Policy | Mean external error | Mean modeled units |
| --- | ---: | ---: |
| Adaptive: query hard, skip easy | 0.015 | 4.5 |
| Always query witness | 0.015 | 5.0 |
| Never query witness | 0.255 | 4.0 |

The external score is based on underlying truth, not on self-consistency
of the four synthesized outputs. In a separate symmetric eight-class
all-shared-wrong thought experiment, the top-1 information bound is
1/7 **without an independent informative observation**. The binary
witness illustration does not evade that bound; it introduces a new
information channel with specified likelihood, which would require
independent real-world calibration and actual cost receipts.

The code demonstrates a *finite possible mechanism for selective
information purchase* only. It does NOT close v3 blocker R03's claimed
real effectiveness, verify any real witness accuracy, train an actual
generator, or incorporate independent query actions into the v4
four-modality Bellman action lattice. That joint runtime integration and
new untouched heldout remain open.

## Next independently measured scientific experiment

Replace the synthetic proxy-state/decoder fixtures with a source-pinned **real** shared Encoder plus four output decoders, observed partial latents, actual Neural/Cell feature invocation and all separately paid decoder/verifier/selection costs. Preregister source-disjoint natural tasks, multiple training seeds and common random-number draws, then compare same-information/static, MoE, risk-neutral MPC, fixed-risk MPC, dynamic NDU and best-of-N with independent decoded-output scoring and risk/coverage/cost thresholds. Train/inference factorial ablations are essential to determine whether NDU changes learned generation rather than only selecting an existing candidate. Do not enable or deploy any output-portfolio policy based only on this code.

## Matched 2×2 learning-versus-control scientific admission

`factorial_admission.py` introduces a deliberately **non-authorizing** score
receipt for the same seed × original source × world × draw across four arms:
`base_static`, `base_ndu`, `trained_static`, and `trained_ndu`.
All arms must share the same input, actual stochastic draw-plan identity,
Decoder checkpoint digest, independent scoring revision, and measured
physical cost unit; every failure remains counted. The gate rejects
incomplete 2×2 panels, duplicate arms, seed collapse, forged/unregistered
source IDs, invalid losses, fabricated MAC-as-physical units, and changed
scoring rules. Only an externally fixed evaluator can establish the
authenticity of caller-supplied hashes and physical measurements.

The resulting contrasts decompose base-model inference-control benefit,
NDU-training benefit with static inference, post-training inference
benefit, and the difference-in-differences interaction. These are
**descriptive** without randomized assignment, matched real model
executions, source-group statistical intervals and independent terminal
outcomes. The helper explicitly returns
`causal_or_statistical_superiority_established=false`. The synthetic
regression tests are not a natural model execution or a closed P3 gate.
