# Round 2: structure-preserving native Stem experiment

## Pre-execution protocol freeze

Additive continuation of hepta-private-ci PR #1755, parent commit
9631307b604340180b1e706baf96b8ce3aec2f58. The original five Python files, weights,
raw outputs and positive/negative findings remain unchanged. This protocol is
locally frozen before the new sweep, not externally preregistered or blinded.
The preceding 48 source/math tests include short training-mechanism runs.

The parent archive SHA256 is
99fcd4caa91320dafdc99483f120eec5a1f60c1039934bdf708dce39c4cd88c1.
All 223 content hashes were reverified before reconstructing the source slice.
Parent hosted numerical workflow 38443935517 passed; its full sweep was skipped
by design. Parent blocking-ci 38443935512 failed. Neither status qualifies new code.

## Question and exact new family

Does a learned structure-preserving family remove the earlier out-of-profile
failures while preserving the benefit of a full-Jacobian equation solver over
ordinary optimization? The complete training law, objective, horizons, seeds,
parameter box and original fit implementation are unchanged. No new zero-risk
training examples are added. B/C always have identical function class, inputs,
initial bytes and full (non-detached) residual within a paired family.

Let E_r(a,b;p)=log(p exp(r a)+(1-p)exp(r b))/r, extended at r=0 by expectation.
Define

    S_theta(v)(s) = c(s) + gamma * [w_theta(s) E_(rho/2)(a,b;p)
                                  +(1-w_theta(s)) E_(3rho/2)(a,b;p)],
    w_theta(s) = sigmoid(MLP_(2->16->1)(4p(1-p),rho)).

There are 65 trainable parameters, equal in count to the raw family. The gate
cannot see continuation values, task IDs, solved targets or test outcomes. The
basis temperatures are fixed at one half and three halves, not the target one.
There is no exact-target expert in the mixture. The model class need not contain
the exact nonzero-risk target; approximation bias is an expected possible result.
It uses a substantially stronger entropic prior than the raw MLP. This is NOT a
proof about arbitrary recursive utilities or a general language encoder.

For fixed coefficients and any parameters, both experts and their convex mixture
are increasing in each continuation value, translation equivariant, consistent
on constants, bounded between the minimum and maximum continuation, and
nonexpansive in the sup norm. Applying gamma gives gamma-Lipschitz stability.
Indeed each entropic expert has nonnegative partial derivatives summing to one;
the coefficient does not depend on continuation, so the mixture inherits them.
At rho=0 BOTH experts equal the exact expectation independently of the weights.
For nonnegative terminal indicators, c=0 and gamma=1, all values remain in [0,1].
These are real-arithmetic structural properties, not gains learned by the solver.
Floating-point tests sample them; they are not interval-certified universal bounds.

The implementation centers the exponentials and uses expm1/log1p to avoid
small-risk cancellation. It does not clip final predictions into [0,1].

## Frozen arms and budget

Two families (raw and structured), two optimizers (Adam B and TRF C), three seeds
11/23/47, two nominal training CPU caps 2/8 seconds: 24 fitted runs. L-BFGS at
8 seconds for both families and all seeds: six more. Original from-scratch
Transformer/Adam at 8 seconds for all seeds: three more. Six untrained controls
(raw/structured initial models at the three seeds) and one exact D reference.
Total: 40 fresh-process runs, 33 actual fits. No pretrained model or warm start.

Primary contrast: structured C versus structured B on the NEW COMPOSED terminal
family at 8 seconds, reporting all three paired initializations, not selecting
the best seed. New uniform-terminal accuracy is separately reported. Family
comparisons identify a changed prior/function class, not just a solver change.
L-BFGS controls the claim that any difference merely reflects beating Adam.
Untrained controls distinguish hand-built structure from learned approximation.

TRF is the inherited reduced-space nonlinear collocation solver with complete
Jacobians. It is not the general Pontryagin system of an unrestricted policy
problem and does not establish continuous-time viscosity convergence. Both Adam
and TRF optimize exactly the same squared full finite-law recursive defect.

## New evaluation families and single-field interventions

New uniform terminal seed 2026101401, compositional terminal seed 2026101402 and
indicator seed 2026101403 each provide 32 functions. The composed functions use
bounded combinations of bit coordinates, pair interactions and preference
interactions, scaled to [-.8,.8]. They are generated without consulting an oracle
or earlier error. Train still uses the original 12 terminals from seed 1201.
Distinct terminal functions in the same generator family are not independent
natural-language or world-model domains.

Ten panels: new uniform, new composed, horizon eight, six-bit/192-state world,
changed known kernel, risk-zero only, unit-discount only, zero-cost only,
indicator-terminals only, and joint probability configuration. The four single
interventions preserve all other world coefficients and terminal bytes wherever
applicable. Longer horizons and larger states are labeled, not silently pooled.
The changed kernel is supplied to every arm; it is not hidden physical drift.

All predictions and weights are sealed BEFORE any new oracle score. No holdout
selects model, stopping rule or optimizer. Independent scalar Decimal-50 oracle
and the zero-risk matrix-power cross-check are retained. General FBSDE utility,
continuous-state PDEs and natural-language capability are outside this benchmark.

## Metrics and cost accounting

Retain every panel's RMSE, max error, full-state finite-horizon residual envelope,
original contract-choice accuracy/regret, and RAW invalid probability frequency,
raw/clipped Brier and expected calibration error. A fixed 51-point exogenous
price grid [-.25,.25] makes additional contract decisions less saturated. Prices
are not chosen using oracle near-ties. Their repeated cases are not independent
samples; report regret rather than manufacturing an answer-accuracy benchmark.

Record pre/post fit weights and norms, all original residual/Jacobian/AD-lane and
optimizer counters, training CPU/wall, prediction/sealing, independent oracle,
diagnostics and reloading costs. Each fitted or initial model is saved and
reloaded for all ten panels. Whole-child CPU and spawn-to-exit wall time include
imports, serialization and process overhead. Fresh-process peak RSS is reported
both after fitting and after all evaluation. CPU cap checks can overshoot by one
nonpreemptible operation. No exact CPU/FLOP/energy match is asserted. Total FLOPs,
energy and GPU peak remain unavailable rather than fabricated.

Timeouts/launch/child/evidence errors enter the full census and cause the sweep
to fail after retaining results. Outputs are exclusive-create; retries require
new directories. Source SHA256 binds each child and whole sweep. This is local
assistant CPU execution, not a project-cloud or native Hepta production host.

## Commands

    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m unittest -v
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
      python structure_sweep.py --out /absolute/new/output

Dependencies remain NumPy 2.3.5, SciPy 1.17.0, PyTorch 2.10.0 CPU, Python 3.13.
No owner authority, native runtime, CURRENT, main merge or existing CI exemption.
