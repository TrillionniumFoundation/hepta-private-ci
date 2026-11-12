# Frozen complete-macro policies

`macro_policy.py` provides STOP, light, calibration-tuned fixed, point,
unconditional and conditional controls under one complete-macro action identity.
READ means PREPARE_ROI, READ_ROI, fresh selection, WRITE_TEXT and STOP.
STOP means WRITE_TEXT and STOP; neither label changes a primitive action's meaning.

The value target is `(READ quality - READ cost) - (STOP quality - STOP cost)`.
Pairs require identical observed initial states, current public-state digests,
disjoint fitting/calibration sources, a one-to-one source-ID/original-byte binding,
both legal macro actions and distinct retained branch evidence.
Known terminal failures remain in the target when measured; unknown outcomes
remain unknown and in the recorded denominator. Acquisition, selection/use and
external-effect heads use separately witnessed labels; their probabilities are
not multiplied into an already realized net-return target.

Context changes, unavailable READ, insufficient completion budget, absent support
and incomplete calibration cause conservative STOP. Conditional source-minimum
residuals do not establish conditional coverage. Input cost completeness does not
establish the cost of a new execution. Numerical fixtures test contracts only.

Seventeen policy regressions and seven cold-parser regressions passed locally without
skips. Native execution, source-held-out real tasks, physical full-cost accounting,
policy efficacy and production adoption are separate gates. HOLD / NoUpdate.
