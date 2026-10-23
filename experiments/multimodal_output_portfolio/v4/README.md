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
real-world terminal fact. The independently defined counterfactual scorer remains unchanged; the
finite Controller receives an isolated bounded-work implementation below. The
exhaustive helper must not run on a production inference hot path.

Run:
```bash
cd experiments/multimodal_output_portfolio/v4
python3 -m unittest discover -v -p "test_*.py"
python3 -m compileall -q portfolio.py counterfactual_audit.py test_*.py
```

## Bounded finite solver work and cache ownership

The original `@lru_cache(maxsize=65536)` on `Controller.solve(self, state)`
created a **module-global cache whose keys retain Controller instances**.
Finishing an episode did not promptly release its controller from the cache.
It also bounded *cached entries*, not total branch expansions or solver work.

The follow-up uses one instance-owned, exact `State` memo per Controller and
rejects expansion beyond **32,768 unique states** or **1,000,000 enumerated
shock branches**. Bound exhaustion is a fail-closed research error; it is not
silently turned into a feasible STOP or a proven low-cost optimal policy.

`work_receipt()` now reports expanded states, cache hits, evaluated branches,
cached states and the fixed caps. `execute` includes those counters in the
hashed **`hepta.ndu.modality-portfolio.trace.v2`** payload, changing its schema
rather than reinterpreting earlier v1 trace bytes. The new
`test_solver_work.py` checks completed-controller garbage collection,
cross-controller isolation, deterministic replay, cache hits, fail-closed
caps and complete four-modal emission.

Counters are logical source-level work units **not CPU time, GPU FLOPs,
resident bytes, energy or target-host latency**. They do not make a CPU-heavy
exhaustive optimizer production-suitable; a learned bounded policy head or
precomputed finite lookup and independent physical benchmarks remain required.

## Next independently measured scientific experiment

Replace the synthetic proxy-state/decoder fixtures with a source-pinned **real** shared Encoder plus four output decoders, observed partial latents, actual Neural/Cell feature invocation and all separately paid decoder/verifier/selection costs. Preregister source-disjoint natural tasks, multiple training seeds and common random-number draws, then compare same-information/static, MoE, risk-neutral MPC, fixed-risk MPC, dynamic NDU and best-of-N with independent decoded-output scoring and risk/coverage/cost thresholds. Train/inference factorial ablations are essential to determine whether NDU changes learned generation rather than only selecting an existing candidate. Do not enable or deploy any output-portfolio policy based only on this code.
