# Matched scheduler estimand correction

Scientific admission remains **HOLD**; production authority remains **NONE**.
This is a scoring correction above #5601 at
`a5694833dee37aeebf44f2d8c2053b10b649bf52`, with no new real-task trials.

The original scorer reported a mean over planned matched pairs but tested the
equally weighted mean of cluster means. Those statistics differ when frozen
clusters have unequal sizes. The correction flips each whole cluster contribution
to the reported pair-weighted mean. It preserves cluster dependence rather than
treating every pair as an independent randomization unit.

The retained controlled example has five singleton clusters with gain +1 per pair
and one cluster of 96 pairs with gain -0.05 per pair. The mean gain is 0.2/101.
The old descriptive p-value was 0.03125; the matching whole-cluster test gives 0.5.
The old computational reviewability flag was true; it is now false. A second
example has identical terminal errors but lower costs. A frozen minimum reduction
of zero formerly passed the terminal-error-reduction gate. Actual reduction must
now be strictly positive as well as meeting the frozen minimum.

The baseline source with both new regressions ran 11 tests and failed exactly two;
the corrected full package passed 169 tests, zero skipped. Original before/after
logs, counterexamples and exact executed/published source identities are retained.
Pinned Ruff 0.15.13 formatting changed layout while preserving all 50 executed
Python ASTs. Tests were not rerun after formatting. The sparse workspace has no
complete repository justfile/Rust workspace; the actual `just fmt` failure is
retained. Full repository checks and exact-head CI remain unqualified.

These are synthetic counterexamples with explicit always-true test callbacks.
They establish implementation behavior, not independent evaluator custody,
physical cost coverage, real randomization or a scheduler benefit. The descriptive
sign-flip statistic still requires independently randomized clusters and a frozen
estimand for valid inference. No scientific or production promotion is performed.

`MANIFEST.json` covers every retained evidence file except itself. The code and
protocol files remain at their ordinary repository paths. Baseline test source is
identified by the fixed commit; the logs preserve the actual failing run.
