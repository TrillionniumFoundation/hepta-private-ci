# PRED-1: action-conditioned predictive belief

This is an isolated research package based on
`732e934ba496d90fbe042b8d41d479ef901643e5`. It does not adopt a production Cell,
grant effect authority, or depend on the unmerged Cell/NDU/HCSN branches.

## What is implemented

- Separate outcome, observation status and event-time information. Missing ACKs,
  waiting and unconfirmed cancellation are not failure labels or evidence that an
  effect has not happened. Confirmed cost is a lower bound until settlement.
- Exact, interval `(L,U]`, verified right-censored `T>L` and unobserved labels,
  with a joint finite-distribution likelihood. Imagined labels are refused at
  factual-label admission. Source strings do not authenticate external receipts.
- Fully trainable single-step MLP, action-conditioned GRU, stable diagonal SSM,
  and fast-GRU/slow-state model, including all recurrence/gate parameters.
- The same nonlinear joint head and approximate parameter budget for all four
  models. The SSM is a small reference recurrence, not a reproduction of R2I or
  Mamba. The GRU is not a full Dreamer RSSM. The dual model is not H-JEPA.
- Streaming observed-state updates, candidate forecasts that do not mutate
  belief, and exact optimizer/checkpoint restoration without pickle.
- Independently trained GRU-reset and GRU-no-action controls. No-action removes
  history and candidate action features while preserving the preparation query.

## Controlled environment and its limits

There are two hidden bits: a persistent task context and a changing resource
condition. Observations have noise, missingness and 0–3 ticks of delivery delay.
Inputs preserve arrival order, measurement lag and previous actions. A future
readback cannot be inserted into an earlier decision prefix. The Bayes evaluator
re-filters received evidence at its measurement time and never sees future
evidence. An independent path-enumeration test checks that calculation.

Four actions have different success, time and cost distributions. Each action
can be queried after 0, 2 or 5 fixed preparation ticks. Preparation dynamics are
analytically marginalized, without intermediate observations or replanning.
The neural head predicts the terminal tool's joint residual `(Y,T,C)` on
`{0,1} × {1,2,4,8} × {1,2,4,8}`. Evaluation adds deterministic preparation:

```
total_duration = preparation_ticks + terminal_tool_duration
future_cost = 0.1 * preparation_ticks + terminal_tool_cost
complete_environment_cost = observed_history_cost + future_cost
```

The primary planner enumerates four legal actions at the **fixed five-tick
preparation option**. It does not choose the preparation length. Some sampled
deadlines are shorter than that preparation; those tasks remain infeasible and
are retained in the denominator. This is a small, specified decision problem,
not a general MPC controller, learned skill hierarchy or autoregressive latent
world-model rollout. Scores at the three options are direct forecasts, not
proof of multi-step rollout stability. HCSN replacement is not implemented.

Training labels are coarsened by a registered, ignorable observation mechanism.
Status queries censor time only after proving nonoccurrence; terminal readbacks
provide exact or interval time. An ACK can be missing even after the effect has
happened. Cancellation-request labels test missing-knowledge semantics only;
there is no actual cancellation/stop/recovery execution experiment here.
Real informative missingness needs an observation model or sensitivity analysis.

Only legal training actions are sampled. All counterfactual evaluation outcomes
belong to the simulator evaluator. The model API receives only public history
and candidate query. Truth arrays are read after forecasts and action selection.
The primary oracle is the exact posterior for **the same observations**, not
a clairvoyant agent that sees hidden state.

## Frozen experiment

`registered_config.json` fixes 3 model-family selection seeds and 5 different
evaluation training seeds. Every seed has 4,096 training episodes and 512
development episodes. All six variants receive 30 epochs, batch size 128 and
approximately 3,000 parameters. Development NLL selects each checkpoint.
The first three seeds select the family before training starts on the final
five seeds. Only after all checkpoints are frozen are the 1,024 confirmation
episodes per final seed generated. Episode/source groups never cross splits.

The primary endpoint compares the development-selected family against the
single-step model on the new training seeds:

```
net_utility = P(Y=1 and total_duration<=deadline and future_cost<=remaining_budget)
              - 0.03 * E[complete_environment_cost] - 0.005 * E[total_duration]
```

A mean gain of 0.02 and one-sided paired sign-flip p<=0.05 is the registered
simulation signal. With five independent training seeds, the smallest p is
1/32. Sign exchangeability is an assumption; seed-bootstrap intervals are
descriptive. Auxiliary comparisons are exploratory, and causal memory/action
checks always compare GRU to its own reset/no-action versions. A different
winning architecture versus reset-GRU does not isolate memory causality.

Report all seeds, Brier (outcome and deadline/budget event), exact finite-support
CRPS, joint NLL, distribution error to Bayes, decision regret, terminal success,
deadline/budget success, time tails and full simulated costs. Unknown training
labels are not filled with zero; ordinary evaluation scores use complete
simulator truth and cannot automatically be applied to censored real traces.

Parameter counts and training opportunities are approximately matched. Measured
CPU time is not forced equal. Training, selection, inference, planning and total
campaign CPU/wall time are retained. Simulator work units are not money, energy
or host CPU. These are separate measurements; physical cost remains incomplete.

## Run and inspect

Reference execution environment: Python 3.12, NumPy 2.3.5, one BLAS/OMP thread.
The code uses Python 3.10-compatible syntax, but this dependency combination is
not a claim that Python 3.10 has been qualified.

```sh
uv run --no-project --python 3.12 --with numpy==2.3.5 \
  python -m unittest discover -s scripts/hepta_pred1 -t scripts -p 'test_*.py' -v

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=scripts \
  uv run --no-project --python 3.12 --with numpy==2.3.5 \
  python -m hepta_pred1.run --config qualification/pred1/registered_config.json \
  --output /an/absent/output/directory
```

Outputs are create-only. The attempt record, source snapshot, config/source
hashes, dataset fingerprints, checkpoints, all training curves, per-seed scores,
per-episode arrays and artifact manifest are retained. Failed attempts keep
their failure status. There is no overwrite/retry that deletes an unfavorable
result. Source changes during a campaign make it fail.

Checkpoint files are create-only and distinct for each improving epoch. If an
attempt stops because a frozen checkpoint's bytes changed, `hepta_pred1.recover`
can reconstruct only the originally committed bytes in a separate output tree:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=scripts \
  python -m hepta_pred1.recover --original /original/failed/attempt \
  --output /a/new/recovery/directory
```

The original manifest/source/config/selection are checked. Data and evaluation
code and the model's non-storage methods must match. Reconstruction accepts only
the original SHA; it cannot substitute a better candidate. Previously completed
confirmation metrics and episode arrays must replay exactly, excluding timing
measurements. Repair training costs are added without adding independent seeds.
The original attempt remains failed, and the recovery has its own manifest.

The dedicated `hepta-pred1.yml` workflow runs correctness tests on Linux, macOS
and Windows. Adding it does not make it part of the existing `CI required`
fan-in. Platform CI, the numerical campaign, actual tool success and production
adoption are separate acceptance results.

## Hepta integration boundary

Existing `hepta-contracts/src/provider_effect.rs` distinguishes admission,
completion and indeterminate effects; provider completion alone does not prove
task success. The tabular model in `hepta-bellman-operator/src/world_model.rs`
has authority/OOD boundaries but does not represent these missing labels or a
persistent belief. This package preserves those boundaries without changing
either production state machine. A later real-trace adapter must bind operation,
payload, model/state schema, source frontier, observation availability, legal
actions and task obligations to authenticated domain readbacks and cost records.

Before production claims: qualify an actual trace adapter; test information-
dependent missingness, variable histories and distribution shifts; implement
and test recursive imagined rollouts; run common-planner RSSM/modern SSM/HCSN
comparisons with independent tuning and full resource accounting; then measure
real task benefit. This finite simulator alone cannot establish RSI.

## Research references

- [DreamerV3, Nature 2025](https://danijar.com/project/dreamerv3/): learned latent
  world models and imagined behavior training.
- [TD-MPC2, ICLR 2024](https://arxiv.org/abs/2310.16828v2): finite-horizon latent
  trajectory optimization with terminal value; continuous-control evidence.
- [R2I, ICLR 2024](https://arxiv.org/abs/2403.04253): state-space world models for
  memory and long-range credit assignment.
- [H-JEPA v2, 2026-11-01](https://arxiv.org/abs/2610.06805v2): hierarchical
  action-conditioned prediction. Four simulated environments support planning;
  DROID provides offline planning fidelity, not online robot success.

These papers motivate separate research comparisons; the package is not a
reproduction of their full algorithms or their published performance.
