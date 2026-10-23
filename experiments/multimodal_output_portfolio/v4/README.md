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

## Bounded offline compilation and snapshot-only finite inference

`snapshot_policy.py` adds a **research-only exact finite** offline compiler
that reuses the parent v4 Bellman equation via its undecorated solver body.
Per-compilation work is fail-closed at 32,768 expanded states or 1,000,000
branch evaluations. Unlike an unbounded inference-time recursive search,
the online `PolicySnapshot.choose` is a constant-time dictionary lookup
for a state previously reached by the selected policy; uncovered states,
wrong source/profile/scope or insufficient emission budget fail closed.

The compiled portfolio contains canonical `Config`, initial state, source
digest, state/action/value rows and a SHA-256 integrity digest. A stable
canonical byte format supports cold reload; loader validation checks exact
profile/source/scope, bounded row count, nonfinite and duplicate values,
admissible physical budget, **every** reachable stochastic successor and
absence of extraneous states. Recomputing the checksum of a corrupted,
incomplete state graph does not bypass coverage validation. These SHA-256
digests are **not signatures, remote attestation or promotion authority**.
The compiled policy is not learned; no real adapter/Encoder is loaded.

`test_snapshot_policy.py` covers 128 same-seed parity replays of all four
toy decoded outputs, complete costs and routes, no Controller invocation
in the runtime path, cold bytes export/reload, intentional corruption,
recomputed-digest missing-branch attacks, source/profile/revocation-like
mismatch, budget exhaustion and initial-cell activation constraints.

`benchmark_snapshot.py` emits an explicitly host-scoped Python research
receipt for 12 **cold**, separate exact Bellman evaluations, one offline
compilation, 1,000 policy lookups and 100 toy output rollouts. All 100
rollouts compare terminal outputs, external fixture loss and modeled
resource spend with the original controller. Cold solving, lookup and
decoder emission are measured separately; this is not an energy, full
end-to-end decoder, neural throughput or target production device test.
The workflow runs the benchmark but does not set a universal latency claim.

## Source-converged profile admission and compiled-policy replay

The sibling `#3416` bounded numeric admissibility profile was ported
**byte-for-byte** into this compiled-snapshot candidate: integer and finite
physical resource limits, bounded risk/price, conditional probability support
and value limits, immutable four-channel tuple state/action vectors and
committed nonnegative 63-bit replay seeds. The independent sibling regression
`test_profile_safety.py` is retained without rewriting its original assertions.
This also prevents mutable vectors from entering Bellman caches.

`snapshot_policy.rollout_snapshot` now enforces the **same seed bound** as the
original `portfolio.execute`; otherwise a compiled policy had accepted
entropy-derived, negative or oversized seeds that the source generator rejects.
`test_compiled_profile_admission.py` verifies both APIs reject identical
invalid seeds, retain 0/max-seed replay, survive canonical cold snapshot reload,
and preserve all four toy outputs and physical-cost parity.

Any source change invalidates previously compiled snapshot source digests:
recompile and re-evaluate against the exact reviewed source. No older CI run
qualifies this composition. This closes only a narrow numeric/state/replay
source integration gap, not real learned-generator efficacy or production use.

## Integrated 2×2 output-training / control evaluation and source-tail admission

This research integration carries **unchanged exact Git blobs** for both
\`factorial_admission.py\` and \`test_factorial_admission.py\` from #3424, and
\`registered_factorial.py\` and \`test_registered_factorial.py\` from #3440.
It combines those frozen-source validators with #3436's typed finite control,
bounded offline snapshot and cold-reload replay in one candidate tree. No
existing v1/v2/v3 experimental data, policy weights or scopes are modified.
Their tests now run together on the same revision in the scoped workflow.

The independent four-arm roster is:
\`base_static\`, \`base_ndu\`, \`trained_static\`, \`trained_ndu\`.
The registered cohort fixes every training-seed / original-source / world /
draw key before score inspection. It binds four-arm input, randomness, common
Decoder and scoring identities; retains failed and over-budget rows with the
frozen failure loss and paid physical cost; and calculates equal-weight
seed/source/world/draw contrasts rather than treating extra draws as new
independent sources. All digests and outcomes remain **caller-supplied**, and
the four arms have not been run on a real pretrained common model here.

\`registered_tail.py\` extends this **descriptive-only** admission with
fractional CVaR90 over **declared original-source IDs within each training seed**. The same source appearing under two model seeds is **not** two independently acquired sources. It reports separately:

* Worst 10% of per-source mean **decoded external losses**, balanced by
  training seed, original source, world and draw.
* Worst 10% of the worst per-world draw-tail loss for each source, so a rare
  catastrophic draw cannot be concealed by the same source's good mean.
* Similarly clustered modeled physical-cost tail and the upper-tail
  distribution of the within-source NDU-minus-static paired loss contrasts.

The report now distinguishes source-within-seed weighting strata from
`declared_unique_original_source_ids` and explicitly counts original IDs
reused across training seeds. Neither unique-looking IDs nor byte digests
authenticate independent original-source acquisition; all independence and
causal-superiority flags remain false. These additions do not modify the
original frozen CVaR, pooling, matching or cost calculations.

The difference of two CVaR values is **not** the CVaR of their paired
difference. Both are reported without conflating their interpretations.
The 90% level and within-seed weighting unit are frozen in code; no heldout
test can select a more flattering tail threshold after outcome inspection.

\`test_registered_tail.py\` proves in synthetic adversarial fixtures that
duplicating 100 favorable draws does not create 100 independent sources,
that equal average quality can conceal a harmful worst-decile loss, that
failed/expensive outputs remain in the source tail, and that fractional
tail mass, reordering, mixed units and missing panel rows behave correctly.
These are **unit tests**, not externally observed multimodal model gains.

Run the scoped workflow / local command:

\`\`\`bash
cd experiments/multimodal_output_portfolio/v4
python3 -m unittest discover -v -p "test_*.py"
python3 -m compileall -q portfolio.py counterfactual_audit.py \
  information_acquisition.py snapshot_policy.py benchmark_snapshot.py \
  factorial_admission.py registered_factorial.py registered_tail.py test_*.py
python3 benchmark_snapshot.py
\`\`\`

No combined run may be called \`PASS\` until tests on **this exact source
commit** complete; older source-head checks cannot be inherited. The cold
finite snapshot benchmark excludes pretrained Encoder/Decoder invocation,
actual energy, native IPC and independent terminal outcome acquisition.
A statistically powered natural-data confirmation, common physical budget,
reliable independent witness, real 2×2 model training, and protected-task
quality remain OPEN. **RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO** stays fixed.

## Next independently measured scientific experiment

Replace the synthetic proxy-state/decoder fixtures with a source-pinned **real** shared Encoder plus four output decoders, observed partial latents, actual Neural/Cell feature invocation and all separately paid decoder/verifier/selection costs. Preregister source-disjoint natural tasks, multiple training seeds and common random-number draws, then compare same-information/static, MoE, risk-neutral MPC, fixed-risk MPC, dynamic NDU and best-of-N with independent decoded-output scoring and risk/coverage/cost thresholds. Train/inference factorial ablations are essential to determine whether NDU changes learned generation rather than only selecting an existing candidate. Do not enable or deploy any output-portfolio policy based only on this code.
