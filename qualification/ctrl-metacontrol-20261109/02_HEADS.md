# CTRL 2: observed realization and control-value heads

Research candidate only: **HOLD / no-update**. This extends the identity stage
on #5450; it does not admit a native controller or change #5451's CLI fallback.

`metacontrol.py` accepts only a bounded public state: features, context belief,
pending evidence, freshness, legal actions and remaining budget. Offline labels
keep selected-object use and declared-effect occurrence separate from quality.
Missing labels stay unknown; nonmissing labels need separate receipt hashes,
whose artifact verification remains the collector's responsibility.

The value target is observed continuation quality minus paired STOP quality
minus incremental cost. Unknown cost is not zero. The fully solved linear ridge
critic and logistic heads weight each source equally; realization probability
does not multiply the already unconditional value target again. One-class
execution data produces an explicitly labelled smoothed base rate.

Point, unconditional-residual and finite-cell conditional-residual modes share
that critic. Calibration is source-disjoint and frozen. Sparse or unsupported
inputs fall back to the supplied light action. Any non-STOP action needs a
declared cost ceiling and terminal budget reserve; the owner must still recheck
the actual budget before dispatch and account for controller time.

Four focused fixture tests accompany this stage. The final 14 mechanism and
7 study tests passed together after numerical/freeze hardening. Derived
nonfinite predictions are refused; diagnostics require frozen calibration.
Training and calibration cost qualification are tracked separately.
Fixtures establish implementation behavior, not
real policy gain, complete-cost certification or conditional coverage.
