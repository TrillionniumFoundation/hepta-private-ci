# Explicit normalized-longdouble coupled law and smooth-gradient qualification

This is a **new opt-in numerical profile**, not a repair of the failed FP64 profile.
The original417-update campaign stays terminal and unevaluated. A separate fixed
FIT-prefix diagnosis showed that exact summation of represented binary64 policies
alone did not admit its whole64-row batch; explicit normalization did. That evidence
motivated this new implementation rather than a relaxed old residual threshold.

`normalized.py` normalizes each policy in genuine extended precision before semantic
transport, constructs the maximal-semantic joint, and differentiates the complete
smooth normalized-logweight graph. It keeps the previous residual floor64float64eps,
relative-balance bound sqrt(float64eps),1e-12 marginal guards and rounded binary64
risk costs. It neither substitutes a denominator nor masks failed rows. Positive
exact min ties reject gradients; forward serving can still form valid tied laws.
Both-constant maps give deterministic output andzero utility logweight gradients.

The returned binary64 table is interpreted with its actual CDF total and rechecked
for marginal preservation. Analytic reference gradients are not exact derivatives
of every floating-point instruction. The original aligned anchor is unchanged.
`NormalizedCouplingProfile` uses new schema/mode/key, nested model/semantic bindings
and runtime mantissa/exponent identity. Loading requires explicit expected new mode
and model; old/new envelopes and precision mismatches reject. Original defaults,
old source, old checkpoint meanings and earlier quality gates are unchanged.

## Qualification

Twelve payload-free literal tests passed. Full anchor+utility raw-logit finite
differences had maximum absolute error8.71e-11; actual new CDF-law values differed
by at most1.53e-16. Rational-simplex reference gradient difference was0 on the fixed
fixture, not a universal exactness claim. Permuted semantics, complete batch scaling,
constants/one-constant maps, ties with unequal one-sided derivatives, dyadic residuals,
old-mode mass-drift refusal, identity/binding/roundtrip, swap/translation, invalid
inputs and lack-of-extended-precision refusal were covered.

Whole waited qualification child:0.782639CPU,0.787356wall,34492KiB RSS, under5CPU/
30wall/512MiB/4MiB, CPU0/single-thread/shared synthetic lock. Zero model restores,
updates or dataset rows. Source review corrected a test's branch-signature binding
to the actual new normalized graph before any execution; no outcome-driven changes.

From this directory, with the existing qualified repository dependencies:

```sh
PYTHONPATH=../coupled-prefix-numerics:../coupled-law-gradient:../explicit-semantic-transport:../semantic-coupling:../semantic-coupling-batch:../transport-aligned-training:.. python -B -m unittest -v test_normalized
```

`PLAN.md` is the pre-execution qualification plan. `RUN_PLAN.md` separately fixes
the new eight-cell comparison and its unchanged scientific gates. Source/tests,
plans and aggregate results only are public; no model payloads, per-row outputs,
private runtime paths or original-digit restoration claims.

## Fixed scientific result: alignment failed the primary gate

All eight predeclared cells completed300updates each. Four independent-training
controls exactly reproduced their prior tensor digests. All final models were
frozen before validation. Every arm computed both new derivatives on each batch;
all evaluation used the same new normalized coupled serving profile.

Partial-command full/low macro contrasts (seed11 / seed23):

| Contrast | Joint CE change | Text mass change | Greedy text change | Joint success change | Pixel MSE change |
|---|---:|---:|---:|---:|---:|
| coupled N minus independent N | −0.007430 / −0.009183 | −0.003815 / −0.007960 | 0 / −0.001603 | −0.004877 / −0.006557 | +0.000146 / +0.000197 |
| coupled N minus coupled A | +0.010196 / +0.012515 | +0.008434 / +0.007652 | +0.006410 / +0.001603 | +0.007734 / +0.009428 | −0.000223 / −0.000275 |

The internal coupledN−A comparison passes allfive original gates in both seeds,
but coupledN is worse than the prior independentN baseline in both seeds. CoupledA
also worsens its independentA comparison. Thus the **overall primary gate fails**;
internal N>A is not a claim of improvement over the better baseline. No gate or
reward was changed; jointMAP was not substituted for the greedy-text criterion.
Exact objective alignment therefore did not improve generation in this fixed
budgeted experiment. This is a scientific negative, distinct from the earlier
FP64 campaign's unevaluated numerical abort.

Complete new science child: **11.247789CPU seconds**,11.298129wall,53060KiB RSS,
under30CPU/90wall/512MiB/4MiB with single-thread/CPU0/shared lock and completewait4.
The higher ceiling than the old20CPU FP64 run was declared before execution.
2400updates,7220forwardbatches/471120rows,4800newloss calls/307200rows,10320served
joint tables,20640CDFmarginal checks,20scalar-reference checks and10profile roundtrips.
All numeric domains admitted; failure-only diagnostic counters stayed0. Maximum
training relative imbalance3.22e-11 was below the unchanged1.49e-8 threshold.

Per-arm training ranged1.168794–1.274705CPU seconds; equal planned work is not equal
measured total spend. The twelve repeated literal tests and scalar reference helpers
(including any internally computed gradients) are inside whole-child CPU. The prior
0.782639qualification,0.714013diagnosis,2.117035old-aborted-science,0.568155old-literal
qualification and0.447929sum of measured base-preparation prefixes remain separate
historical costs. Source/review, older experiments and unknown supervisor tails are
additional, not zero or hidden in a claimed speedup.

Two existing supervised base bundles were restored; no new checkpoints were saved
and no TEST data were used. The synthetic validation was reused
exploratorily, not fresh held-out evidence or a natural-image/digit-study result.
Further work should diagnose the objective's incentives, not retune this failed
alignment family or relabel a weaker internal baseline as overall success.
