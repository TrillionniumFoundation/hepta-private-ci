# Shared-actor boundary contribution study

This experiment separates task stopping from a cell's natural first-passage
barrier. One HCSN actor is actually trained and checkpointed. Fixed, directly
trained and Bellman policies all consume exactly that checkpoint's causal
prefix log odds. A raw Bayesian policy is an explicitly separate oracle.

## Frozen protocol

Each episode has a balanced binary hidden class. Conditional observations are
independent `Normal(sign * snr, 1)`. All policies know the current SNR, the cost
of another observation and the remaining horizon. No realized future
observation or test label enters a policy.

The actor input at a prefix is the current observation, SNR, observation cost
and remaining steps divided by 24. `SequenceClassifier` adds the same physical
time features it uses in the other experiments. The actor has width 24, depth
one and learns its natural threshold directly. AdamW uses learning rate .003,
weight decay .0001 and 240 updates of 32 episodes. Cross-entropy supervises
every prefix. There is no Bayesian teacher or LLR distillation. Validation
prefix cross-entropy chooses among updates 60, 120 and 240; the selected
checkpoint is loaded into a fresh model and prefix outputs must match exactly.

| Split | Episodes | SNR | Observation cost | Horizon |
| --- | ---: | --- | --- | ---: |
| Training | 2,048 | .25, .5, .8 | .005, .025, .08 | 16 |
| Validation | 512 | .25, .5, .8 | .005, .025, .08 | 16 |
| Test ID | 512 | .25, .5, .8 | .005, .025, .08 | 16 |
| Test OOD | 512 | .15, .35, .7, 1.1 | .01, .04, .12 | 24 |

Contexts cycle through the Cartesian product and are shuffled independently
of balanced labels. Every split has a separate RNG seed and episode IDs.

## Policies and objective

The fixed threshold is selected on validation utility from the fixed grid in
`FIXED_GRID`; equal utilities select the earlier grid entry. The direct head
has exactly four trained parameters: one intercept and weights for
`log1p(remaining)`, `log(snr)` and `log(cost)`. It starts at threshold .85 and
receives 100 full-training-set Adam updates with learning rate .03. Its
temperature-.02 stopping probabilities define a differentiable survival
distribution. The objective is the survival-weighted actual training
correctness minus **all observations purchased**, including the first one.
Evaluation executes hard decisions and always stops at the horizon.

The value policy solves a finite-horizon Bellman recursion on 257 log-odds
grid points in [-12,12]. Conditional next-LLR increments have mean
`+/-2*snr**2` and standard deviation `2*snr`. The predictive mixture weights
are the current belief. Gaussian expectations of linear interpolation bases
are integrated analytically. Tables are cached by SNR, cost and horizon.
The value arm uses the learned actor log odds as its current belief; actor
calibration or model misspecification can therefore hurt it. The separate
oracle instead uses exact `sum(2*snr*observation)` log odds. The oracle's raw
evidence advantage must not be attributed to a better stopping boundary.

## Receipts and interpretation

`RESULT.json` contains the selected actor checkpoint hash, training gradients,
validation history, direct parameters and gradients, fixed validation scores,
and per-split metrics. Per-episode NPZ shards preserve observations, labels,
contexts, both log-odds sequences and each policy's full stop mask, first-stop
index, predicted class, correctness, observation count, total cost and utility.
These suffice to independently recompute all reported aggregate outcomes.

The execution is deliberately offline: all actor prefixes are evaluated
before policy scoring. Lower observation counts represent the simulated task
utility and do not establish real owner cancellation, runtime savings or
energy savings. Actor training, prefix evaluation, direct training, Bellman
table construction and policy evaluation costs are recorded. Timing subtotals
are nested scopes and must not all be added to the overall elapsed/CPU total.

Run a sealed formal study with:

```bash
python -m experiments.continuous_spiking_network.boundary_study --seed 11 --output PATH
```

`--development` explicitly marks an unsealed run. Unit fixtures use only small
data and a few updates; they do not substitute for the five formal seeds.
