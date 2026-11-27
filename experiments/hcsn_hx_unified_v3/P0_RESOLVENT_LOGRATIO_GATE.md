# P0 gate: preserve the independent HX equity resolvent log distance

**DRAFT / RESEARCH ONLY / DENY_ALL.** `all_blockers_closed=false` and
`production_activation_allowed=false`. This fixes one numerical input path,
not the coupled financial endogenous obstacle/QVI or any neural production model.

## Exact dependency and scope

- The parent is draft #4472 exact HEAD
  `4fe4610a575ee47b8f9175681d8a57ae97f09d8f`.
- Its `_log_asset_ratio` is already used in `equity_closed` and first-passage
  APIs, but `equity_resolvent` still directly evaluated `log(asset / b)`.
- The nearest-f64 quotient can amplify a real one-ULP asset separation by
  nearly a factor of two. For boundary 0.1 and the next representable asset,
  the old log is `2.2204460492503128e-16`, whereas an independent 110-digit
  reference is `1.3877787807814454e-16`.
- Replace only the resolvent's input-coordinate conversion with the already
  present stable helper. The independent killed-diffusion/Green integral,
  closed form, bond, stopping/renewal oracles, and production paths are unchanged.

## Bounded local reproduction (not exact-HEAD test execution)

Local Python 3.13.5 and mpmath 1.3.0 independently compared the *inspected
log-coordinate expressions* on 126 deterministic one-ULP boundaries: six
explicit scales plus 120 seed-20261031 log-uniform scales in 1e-250..1e250.
The largest old relative discrepancy was `0.9414608753670368`, versus
`2.220446049250313e-16` for `log1p((asset-b)/b)`. All 126 stabilized
distances differed from the high-precision reference by at most `5e-30`
absolute. An explicit old-path negative assertion failed, and the stabilized
one passed. **These are function-expression reproductions, not a full-checkout
import, integrated equity-value assessment, or CI run.**

## Committed source-import regression (unexecuted on exact full HEAD)

`test_equity_resolvent_one_ulp.py` calls the real `equity_resolvent` and
patches only `scipy.integrate.quad` so it can inspect the exact integration
limits without claiming to have evaluated a financial Green integral.
It compares 126 source-coordinate results to independent 110-dps `mpmath`,
checks unchanged ordinary quotient behavior, and tests default-barrier
endpoints. Before merge or scientific admission, execute on a *full exact-HEAD
checkout*, then run the inherited HCSN HX test suite and independent finance
resolvent/boundary oracles:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_equity_resolvent_one_ulp
python -m unittest discover -s experiments/hcsn_hx_unified_v3 -p 'test_*.py'
```

## Remaining strict vetoes

P0: coupled full HX finance free-boundary/QVI, certified interval and low
precision/GPU bounds, gradients and full legal-domain refusal.
P1: slope/parameter/budget-matched Call/Risk/Margin causal improvement.
P2: selective copy, MQAR, overwrite, irregular-time and physical repeated-event
memory. P3: actually trained and audited four-modal paired/OOD encoders.
P4: native Rust/GPU 64/256/1024/4096 Cell CPU/RSS/throughput/p99/joules/recovery.
P5: preregistered matched-token/matched-FLOP hybrid superiority. No blanket
production approval or reclassification of prior negative outcomes.
