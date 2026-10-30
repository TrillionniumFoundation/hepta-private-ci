# Controller v2: a separately registered development iteration

This iteration addresses implementation weaknesses identified in the completed
v1 study. It does not alter that study's results, rename its test sources as new,
or assert that a different estimator guarantees better generation.

## Diagnoses motivating the changes

1. The v1 supervised pretraining visits only `shared`, one rotating modality,
   then `shared`. The actor can instead visit any legal sequence up to six
   continuations. Its early and late stopping states were poorly covered by
   supervised training. V2 supervises the encoded state and each prefix of a
   randomly sampled legal sequence of length 1–6. These are sampled sequences,
   not an enumeration of all possible sequences.
2. V1 multiplies the sum of every action and emission score by a single
   episode-level return coefficient. A 4,864-dimensional Gaussian media
   emission and two categorical text outcomes contribute to this same score.
   V2 retains this exact sampling law and objective, but gives each sampled
   action and the emission its own predictable baseline. It records both v2
   coefficient second moments and the old LOO coefficients on the same draws.
   These diagnostics are not estimates of population gradient variance.
3. V1 distillation uses teacher-visited states. V2 queries the same frozen
   approximate planner on student-visited states over three aggregation rounds.
   The generator and both critics must remain tensor-identical; only the actor
   changes. Planner calls occur in actual training trajectories and their cost
   is measured. Serving the student invokes no planner. DAgger does not turn
   this teacher into an oracle, and a smaller cloning loss is not a quality or
   cost acceptance result.
4. Eight arms now include `ordinary_dynamic_risk` and `hepta_fixed_risk`, so the
   Hepta and dynamic-allocation contrasts can hold the risk objective fixed.
   The joint-versus-actor-only contrast still includes supervised anchoring;
   it does not isolate a pure reward-only generator effect.

## Conditional moment score

Write the observed net return as `R = U - C_total`. For a random draw at a
pre-draw history with already charged cost `C`, the risk control variate is

```
b(history) = (exp(2*C + v(history)) - 1) / 2,
```

where the critic was computed with the current parameters before any optimizer
update and predicts the suffix log moment. Each selected conditional score is
multiplied by `expm1(-2*R)/2 - b(history) - LOO_residual`. The residual uses
only other independently sampled episodes' initial-state prediction errors.
All baseline and observed-return values are detached. The critic's fitting loss
remains `exp(v) - exp(-2*R_suffix)*v` and uses detached input features.

An inaccurate predictable baseline can increase variance but does not change
the population score expectation. V2 bounds only the predictable baseline's
log value to `[-12,12]`, reporting the count. Actual returns and target moments
are not clipped. For the mean control, `C + v/2` is an arbitrary detached
control variate derived from the same gamma-2 critic; it is explicitly **not**
a conditional mean-return predictor. Exact finite-law tests cover both cases,
including two history-dependent actions, an emission, and independent residual
LOO. A counterexample demonstrates the bias produced by future-dependent
baselines; the runtime records its baselines and prefix costs before each draw.

Supervised initialization, the explicit 0.05 anchor, and optimizer gradient
clipping remain declared. The estimator does not model the direct derivative of
physical timing with respect to parameters. It treats the conditional timing
law as parameter-exogenous, just as the registered v1 estimator does.

## Data and acceptance boundaries

The three namespaces `controller-v2-train`, `controller-v2-distillation`, and
`controller-v2-development` generate distinct deterministic synthetic source
identities. Training uses no old v1 test draws and no reserved natural sources.
This is still the small four-output restoration mechanism, not a natural
semantic-generation result. Development inference is real file delivery and
readback with the same contract, cost ledger, STOP and horizon rules.

`controller_v2_protocol.json` fixes development seeds 17 and 29, widths 32 and
64, eight arms, 384 prefix-pretraining updates, and 64 × 8 joint trajectories
per arm. Each arm evaluates 32 development sources with two draws each.
Distillation uses 36 separate development-training sources. Checkpoints retain
source/protocol identities and use the existing safe tensor checkpoint format.

The runner reports separate physical CPU/wall costs for pretraining, each arm's
training/evaluation, DAgger, and teacher/student evaluation. Its enclosing
process supervisor must report startup/import/exit and other unassigned work;
phase counters are not substitutes for whole-process cost. Artifact saving and
report construction remain in the enclosing process total. Actual failed
trajectories remain included in returned metrics, and an infrastructure crash
is an incomplete run, never a passed experiment.

The runner has no confirmation mode and never promotes a candidate. Any later
claim requires a separately frozen selection, full cost accounting, untouched
confirmation sources, and the independent natural-observer qualification.

```bash
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.controller_v2 \
  --seed 17 --width 32 --output /tmp/hepta-controller-v2-dev-17-32
```

Every output directory must be new. `RESULTS.json` retains all per-source and
per-draw results, phase costs, training diagnostics, model identities, and
explicit false qualification fields. `SUMMARY.json` is only a compact view.
