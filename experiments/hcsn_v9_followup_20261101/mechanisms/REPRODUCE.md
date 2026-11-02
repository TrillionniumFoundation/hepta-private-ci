# Finite service-risk attribution and shape refitting

Use the pinned v8 repository plus this additive directory. The original v8 bytes
remain unchanged. NumPy/SciPy/PyTorch are required; runtime versions and observed
module paths are in RUNTIME_IDENTITY.json. Set your interpreter so these packages
are importable. Results must use a new output directory; do not overwrite evidence.

From the repository root:

```bash
python -m experiments.hcsn_v9_followup_20261101.mechanisms.campaign prepare --output /tmp/new-v9-mechanisms
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/new-v9-fit-cost --timeout 900 --sample-interval 0.5 -- python -m experiments.hcsn_v9_followup_20261101.mechanisms.campaign fit --output /tmp/new-v9-mechanisms
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/new-v9-eval-cost --timeout 1800 --sample-interval 0.5 -- python -m experiments.hcsn_v9_followup_20261101.mechanisms.campaign evaluate --output /tmp/new-v9-mechanisms
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/new-v9-replay-cost --timeout 300 --sample-interval 0.5 -- python -m experiments.hcsn_v9_followup_20261101.mechanisms.fixed_risk_replay --output /tmp/new-v9-mechanisms
```

PLAN.json freezes source and all ten historical checkpoint/selection hashes before
new fits; EVALUATION_FREEZE.json binds newly fitted models and service forecasts
before world generation. The five old ordinary training fits are explicitly
historical. Both GRU and SSM execute on every new world. Each resets its recurrent
state per count query, as in v8; this is not a persistent AV-state comparison.

New service risk is a declared finite synthetic extension: each arrival tick has
success probability 0.9 - 0.7*t/20. A failed READ leaves the observation unchanged
and still costs 0.04. All arms share actual per-arrival uniforms. Both controllers
use the fitted success forecast; the risk-omitted intervention changes only that
forecast to one. The task-value controller retains the same one-planned-READ
heuristic. It is not exact dynamic programming or a financial Put-channel model.

Each of three new sampled datasets refits one drift multiplier separately for
the original, mean-preserving two-point and at-most-one-transition count shapes.
All 21 candidate train NLLs, the selected scale and independent validation NLLs
remain. This is physical-model refitting; it is not neural analytic-network
retraining. Refitted-shape comparisons include both the changed shape and its
separately selected drift scale; they are total refitting effects, not frozen-
parameter single-factor effects. The shared planner still samples the inherited
common estimated renewal law; only count prediction uses the fitted scale.
Simplified shapes lose support, and the frozen NLL floor 1e-12 is an
explicit scoring convention, not a restored-support claim.

Formal fit/evaluation/test/replay/audit receipts enclose fresh workers, imports,
children and serialization. Their internal per-arm timers are nested and must
not be added. Preparation and source-development CPU were not fully metered;
complete historical preparation and pretraining costs remain unknown. No complete
memory or attributable physical energy advantage is asserted.
