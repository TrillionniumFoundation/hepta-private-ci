# R15 observed-data calibration and model comparison

## Shared public information

Calibration observes a known initial WRITE value and a sequence of
`(elapsed time, observation quality, raw token)` records. Initial WRITE is an
intervention: the likelihood is conditional on that value. Elapsed time occurs
before each observation. A public `read` channel emits one of four noisy content
tokens or a recovery erasure; `refresh` emits a higher-quality content token.
The calibration use of refresh changes observation quality, not the hidden
process. Actual task action costs and successors are defined separately.

The generator samples the hidden finite state internally, but returns only the
public records. Candidate training has no hidden phase, current true content,
teacher belief, complete-state target, future token or true-model parameter.
It maximizes the normalized forward algorithm's observed log likelihood.
Impossible observations have zero likelihood; no probability floor turns them
into possible observations.

`make_training` returns JSON-compatible data with canonical SHA-256 identity.
Every dataset uses a separate seeded generator. By default fit seeds are below
one million, training seeds are `11000000 + fit_seed`, and validation seeds are
`21000000 + fit_seed`. Confirmation must use a separately registered namespace
and open only after source, model and policy freezes. A supplied public sequence
is rejected if its recorded digest differs or it contains extra state fields.

## Three required estimators

1. **HX:** two parameters, sigma and liquidity, with maturity and other financial
   constants fixed. These determine the declared finite generator and reset
   distribution. This is a finite synthetic neural extension, not a theorem that
   the original financial model is regenerative or task optimal.
2. **Free rates:** a non-financial four-parameter CTMC with independent positive
   up, down and absorption rates and a reset location. Recovery rates, content
   retention, emission channels, state topology and observation history match HX.
   Log rates and a bounded reset-coordinate logit are optimized directly.
3. **Same-matrix HMM:** ordinary filtering with the fitted HX matrices. Its model
   payload is identical to HX. It must give the same posterior and actions when
   history, state representation and controller are also identical. Its fitting
   cost is reused only in an explicitly shared execution; standalone accounting
   includes the source calibration cost.

The free model has more parameters and a different inductive prior. Both models
start from the same finite Q, obtained from a fixed, seed-jittered public
initialization independent of the generator truth. The free model's conversion
of this starting Q is charged within its own optimization budget. The world is
HX-generated, so conclusions are conditional on this structural advantage for
the HX family; matching raw information does not match all inductive priors.

The calibration module records a diagnostic choice between free rates and
same-matrix HMM by public validation sequence log likelihood; a tie selects the
same-matrix HMM. The enclosing task experiment separately chooses its primary
ordinary comparator by actual task utility on independent preconfirmation task
validation episodes. These two selections must retain separate identities and
criteria. Neither validation stage selects optimizer iterates or changes source,
budgets or bounds. Superior density likelihood need not imply superior action
utility. Confirmation retains both candidate outcomes as well as the task-
validation-selected primary ordinary comparator.

The enclosing experiment supplies typed addresses and WRITE/DISTRACTOR routing
equally. This tests state retention and decision use after address binding is
made explicit; it does not demonstrate learned semantic routing. Its exact
planner optimizes only the current query's three slots, not the joint value of
all six queries. The disk checkpoint demonstration restores belief, model,
clock and operation counts; it does not implement a full owner crash/restart
with pending actions and accumulated fees.

Task-level noninferiority follows the controlling protocol: four one-sided
98.75% Student-t lower bounds, for utility and correctness in IID and OOD,
Bonferroni family alpha .05, each compared strictly with the -.01 margin.
The eight fit seeds are the statistical replicates. This calibration module
neither performs that gate nor promotes a model merely for better likelihood.

## Optimization and cost contract

The default optimizer is SciPy L-BFGS-B with finite-difference gradients of the
actual observed likelihood. Both candidates receive the same 64 sequences of
length eight and at most 80 objective evaluations and eight process CPU seconds.
Validation has 32 additional sequences. Every valid or rejected evaluation is
retained with its parameter vector, score or error, and timing. Budget checks
occur before each new objective; one construction/evaluation/export operation
may overshoot and its full cost is retained. The best finite training likelihood
among actually evaluated candidates supplies the export. Budget exhaustion and
optimizer failure are reported separately from convergence.

Each fit returns training and validation raw data, candidate payloads accepted by
`Law.from_payload`, selected ordinary identity, complete evaluation ledgers and
measured costs. Common generation is charged once in the complete search. The
all-search ledger includes both fits, both validation scores and the HMM alias.
Standalone HX, free and HMM columns each include their applicable calibration;
these are alternative deployments and must not be added together. The
equal-calibration HX/HMM comparison does not call reused knowledge free.
The enclosing fit-function CPU also retains unallocated setup/selection
overhead; the parent process must meter interpreter startup, imports and final
JSON saving. Online filtering, planning, communication, checkpoint/recovery I/O
and hardware energy are outside this module and require separate measured ledgers.

## API

```python
data = make_training(law, seed, count=64, length=8)
log_likelihood = likelihood(data, candidate_law)
result = fit(seed, config)
model = Law.from_payload(result["models"]["hx"]["payload"])
likelihood_diagnostic_name = result["selection"]["ordinary"]
```

`fit` returns `training`, `validation`, `models`, `selection`, `accounting` and
`timing`. The `true_theta` configuration is visible to the experiment generator
only and is not read by the optimizer, initializer or validation criterion.
Factorized or mean-state variants are mechanism ablations; they must not replace
the free-rate and same-matrix HMM strong ordinary comparisons.
