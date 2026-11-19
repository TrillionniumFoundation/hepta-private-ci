# Fixed-policy closure: source-bound evidence, 2026-11-08

The complete frozen CPU candidate passed **71/71 tests and all four declared
numerical-budget fixtures**. The evidence also retains the earlier failed
64-cell budget, the blocked real-data attempt, the subsequent clock diagnosis,
and the unsuccessful independent Colab binding attempt. This is mathematical
and implementation evidence for named fixtures. Formal comparison fits: **0**.

`STATUS.json` is a historical publication snapshot. Hosted CI outcomes belong
to their exact run, source head and tested tree; this directory does not predict
the result of a future workflow. `MANIFEST.json` hashes every evidence file
except itself. Raw execution receipts are preserved byte for byte, except two
Colab create receipts whose public copies explicitly remove an account contact
email and its reversible hex encoding. `PUBLICATION_REDACTIONS.json` identifies
the original hashes and sizes; the original native receipts remain intact.

## Definitions and implemented closure

| Symbol | Meaning | Scope |
| --- | --- | --- |
| E | Original equity from the referenced corporate-finance model | Not identified with the HCSN engineering reward |
| C | Value in one active cycle | Payoff specification must be stated; the new C^(a,h) includes running rate a and hit payoff h |
| U | Regenerative total discounted value | Repeated active cycles plus the declared reset and refractory policy |
| F | First-hit probability by time T | At most one first passage |
| G | Discounted first-hit mass by T | E[exp(-rho tau) 1(tau <= T)] |
| J | Instantaneous renewal-event rate | Derivative of the cumulative expected count where defined |
| M | Cumulative expected number of events | May exceed one after reset |

The legacy interval feature remains

`call = 0.4 A_rho + G_rho + 0.2 exp(-rho dt) P(active at interval end)`.

The new `interval_value` alias states that meaning without changing old model
behavior. Summing this feature pays a terminal value repeatedly and does not
compute U. In the retained terminal-accounting fixture this overpayment is
about 0.59256; the correct one-terminal recursion agrees to floating-point
precision.

For Brownian log margin x > 0, fixed drift mu, diffusion sigma, reset margin
x_r > 0, discount rho > 0 and deterministic refractory duration d, define

`lambda = (mu + sqrt(mu^2 + 2 rho sigma^2)) / sigma^2`,
`g(x) = exp(-lambda x)`, and
`C^(a,h)(x) = a (1 - g(x)) / rho + h g(x)`.

Then `U(x_r) = C^(a,h)(x_r) / (1 - exp(-rho d) g(x_r))` and
`U(x) = C^(a,h)(x) + g(x) exp(-rho d) U(x_r)`.
The implementation uses stable expressions for the Laplace exponent and
renewal denominator, and includes uniform active-cell, exponential-tail and
remaining-delay basis averages. No perpetual terminal feature is added.

`finite_renewal.py` separately sums the shifted first-passage laws for event n,
whose time is `(n-1)d + tau_(x+(n-1)x_r)`, giving finite-horizon M/J and
discounted event mass, occupation and value. It checks its explicit positive-d,
term-count and numerical-cancellation domain.

The projected chain has a different value function:
`(I - exp(-rho dt) P_QPR) u = a A_rho + h G_rho`.
Finite projected recursion adds the terminal payoff only at the final horizon.
The reported linear-solve residual estimate is not a certified interval bound.
No endogenous optimal boundary, smooth-pasting solution or QVI optimum is
claimed. Those require their own model and boundary equations.

## Executed evidence

| Attempt | Source and execution | Actual result |
| --- | --- | --- |
| attempt-001 | Its retained source.zip; native job 1a1baad21e1-12894-1c6f | 62 tests pass; 64-cell numerical budget fails |
| attempt-002 | Result contains its source hashes and predeclared budget | 128-cell refinement and four fixtures pass the original limits |
| final-native | Archive SHA-256 353f7c0f50d187adeccbd1fff0638d1a649fe2c547c03ebf23e3fceafa846ff8; job 1a1babb7ce2-12894-1cdc | 71/71 tests pass; four budgets pass; source unchanged |
| localization-v1 | Exact official ZIP hash and locked spec are in the report | Download and full parse complete; clock guard blocks before any fit |
| clock diagnostics | Separate retained diagnostic scripts and outputs | All 164860 rows match the declared display-quantization hypothesis exactly; fixed A01 window still exceeds operator dt limit |
| Colab | Lifecycle receipts in colab-v1, with two explicitly marked contact-redacted create derivatives | Binding/reconciliation return FIXED_RUNTIME_NOT_FOUND; no independent worker submitted |

The full native qualification used Python 3.12.3, Torch 2.8.0+cu128 **on CPU**,
FP64 and one compute thread. Wall time was 23.5733 s and process peak RSS was
654380 KiB. These are whole-qualification observations, not training or
inference benchmark costs. The budget run took 13.6415 s. Physical energy,
provider charges, model peak VRAM and independent training effects are not
measured here. Unknown quantities remain null.

The outer native wrapper succeeded because the mathematics and budget commands
succeeded. Its `execution.json` separately records the localization exit code
2; wrapper success does not turn the dataset attempt into a pass. A targeted
finite-test dispatch whose tool response was lost receives no execution credit;
the final 71-test run includes those nine tests.

## Numerical error budget

The limits were declared before measurement and were not relaxed after the
first failure. Increasing active cells from 64 to 128 reduced the maximum
observed combined scaled value error from 1.1142% to 0.2817%.

| Final fixture | Combined scaled error | Fixed limit |
| --- | ---: | ---: |
| Negative drift | 0.121933% | 1% |
| Zero drift | 0.238414% | 1% |
| Positive drift | 0.281650% | 1% |
| Negative drift, unaligned dt=0.037 | 0.165722% | 1% |

The qualified profile has 128 active cells, 16 refractory cells, endpoint 2.4,
d=0.1 and quadrature order 32. Separate refinements vary space, phase, tail,
time step and quadrature. Each space/phase/tail/time sensitivity must be at
most 0.5%, quadrature sensitivity 0.001%, solve residual estimate 2e-10 and
probability mass error 5e-11. The report also separates initial projection
error from evolution of the reconstructed basis distribution.

These sensitivities are not independent additive certified bounds. Passing
these four conditioned-prior, perpetual fixed-policy fixtures does not qualify
the small default grid, arbitrary posterior distributions, every learned
physical parameter, a long observation-conditioned trajectory or another
refractory duration. A d=0.2 real-data candidate needs separate evidence.

## Real data: what failed and what the diagnosis establishes

The official UCI archive was downloaded before any model fit. Its SHA-256 is
`6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da`.
The raw table has 164860 records, 25 sequences, four tags and 11 activities.
The original attempt fixed A01 first 128 events for training and D01 first 64
for development; E was used only for integrity/schema/clock auditing.

The first audit compared adjacent clock differences against a 2 ms tolerance
and observed 3.1652 ms, so it stopped without training. Independent diagnostics
then tested a measurement model derived from documented datetime quantization:
100 ns ticks from year 1, a single +2 hour offset, rounding to 1/300 s and then
to displayed milliseconds. Every raw row matches the prediction with zero
display residual; every individual time differs by at most 2 ms. All displayed
millisecond tails are 0, 3 or 7. A difference between two quantized timestamps
can exceed the per-record tolerance. The retained v1 failure is therefore a
guard-model error, not evidence that the source timestamp unit is wrong.

This demonstrates compatibility, not that the authors used SQL Server or .NET;
the bundled dataset description makes no such attribution. The diagnostic
does not grant training admission. The unchanged A01 selection contains one
108.1168 ms gap, while the original operator requires dt <= 100 ms. No gap was
clipped, rescaled or replaced, and no window was silently changed. A new
fixed d=200 ms candidate is an explicit model change, not inherited numerical
qualification or a relaxed gate on the old model.

Primary references: [official dataset](https://archive.ics.uci.edu/dataset/196/localization),
[DateTime ticks](https://learn.microsoft.com/en-us/dotnet/api/system.datetime.ticks),
[datetime display precision](https://learn.microsoft.com/en-us/sql/t-sql/data-types/datetime-transact-sql).

## CI and research admission

The parent is [bb048cb](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/bb048cb811c2b755b7e54e97d24c63ec7ec8d1b7).
Its [repository-wide run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42453569515)
failed. `ci_baseline.json` identifies inherited checkout, spelling, contract,
dependency and resource failures; unavailable logs remain unclassified. A
successful aggregate with skipped prerequisites does not count as execution.
This work preserves required checks and adds a dedicated pinned CPU science
lane, which fails if its tests or declared budget fail and always retains
receipts. The new hosted lane must actually execute before any CI pass claim.

The fair-comparison contract names GRU/strong recurrent, CfC, modern SNN,
SSM/Mamba, attention and HCSN, with frozen shared frontend, independent seeds,
physics/content/reset/distribution/channel/coupling ablations and capacity
checks. It is implemented admission infrastructure. Six trained baseline
families, a complete physical-domain qualification, the requested ablation
matrix, measured end-to-end energy and practical superiority remain open.
Episodes from one trained checkpoint do not become independent training seeds.
Performance optimization and hybrid pretraining remain gated on real-task
benefit.

## Reproduction

Extract a retained source.zip into an empty directory. From that root, run
`python -m qualification.hcsn_differentiable.run_qualification --threads 1 --output NEW.json`
and `python -m qualification.hcsn_differentiable.error_budget --output OTHER_NEW.json`
with CUDA disabled, FP64, and OMP/MKL/OpenBLAS thread counts set to one. Preserve
the results even if either command fails. Source manifests exclude evidence
to avoid making execution identity depend recursively on its own receipts.

The separate clock scripts accept the original official archive and an unused
output path. The Colab worker builder is a prepared reproduction helper; it
was not submitted and earns no independent-environment credit. The native-gh
publisher records immutable write intents, reconstructs complete Git tree
hashes, reads back all changed bytes, and creates only new draft stack branches.
