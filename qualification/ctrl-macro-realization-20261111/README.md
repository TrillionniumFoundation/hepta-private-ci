# CTRL complete-macro realization — stage 1

Exact predecessor: `eabe2d8c1a23834bd0db39f683c33977b477fd9f` (#5990).

The post-episode observer separately reports retained observation acquisition,
current candidate coverage, original selected index/use, and completed delivery
consumed by the independent scorer. It reuses strict native macro admission.
Correct-candidate/wrong-selection is distinct from an execution failure.
Missing original reply bytes or legacy selection witnesses remain unknown.
Reference scoring is post-episode only; sealed roles are refused before I/O.

Actual local regressions: 13 new observer methods plus 6 inherited admission
methods, 19/19 passed with zero skips. Directed red tests first reproduced
sealed-reference-before-rejection, Boolean ordinals, and nested public-field
acceptance; these are manufactured counterexamples, not historical exploits.
Formatting preserved each tested AST. The source-head Actions suite explicitly
requires all 13 new methods; its result must be inspected independently.

No new independent source, policy-efficacy trial, full physical-cost claim or
production authority is established. V4 and original FIT40 terminal UNKNOWN
records are unchanged. **HOLD / NoUpdate.**
