# Adaptation-only native Adam v1

This candidate addresses T10's measured CPU admission constraint, rather than
changing its negative result. NC's 3792 candidate updates consumed 4.187833
objective CPU seconds and 4.781844 training-loop CPU seconds. Its saved receipts
admit another operator envelope for every candidate but not the CPU guard.
An older shared-build profile identifies Adam as a substantial caller, but it
does not measure how much of T10's time fusion can save.

The optional adapter is limited to continued candidate and residual training.
Shared decoder300 and dense pretraining500 retain JointModel.apply_gradients.
Every adaptation arm uses the same adapter. Content parameters, gradients,
original Python norm/reduction order, clipping, learning rate, Python power
denominators and independent parameter clocks remain unchanged. One C call
applies the original element expressions to the six content arrays, retaining
their moment storage. It creates no concatenated parameter copy. Compilation
uses no fast-math and explicitly disables contraction with -ffp-contract=off.

The acceptance requirement for this implementation was fixed before numerical
execution: bitwise equality of all parameters, first/second moments and clocks
after 1, 8 and 64 handmade updates, including zero/tiny gradients, clipping and
different parameter clocks. Invalid late gradients, learning rates and changed
bindings must reject before mutation. These are implementation proofs, not a
TRAIN/validation experiment or a CPU benchmark. Failed checks must be retained;
numerical tolerances must not be relaxed to accommodate their results.

Per-step mathematical work is unchanged. Setup scans the six initial parameter
arrays and any existing moments for finite values; it has an explicit charged
comparison inventory. Actual candidates start with empty clocks, so h32 costs
7288 additional setup comparisons per candidate, 65592 per nine-candidate arm.
Allocation, pointer binding, copies and compilation stay inside actual charged
CPU. The full common native compilation cost is attributed to every system.
No timing estimate is substituted for actual spending, and no arithmetic saving
is claimed from fusion.

Only a later immutable source freeze and actual complete-budget build can show
whether removed temporary arrays and dispatch overhead permit useful additional
updates or improve the original content/control contrasts. T10's failure,
budgets, qualification gates, sealed r1 and unopened r2 remain unchanged.

Verification completed before the next freeze: three native hand-array tests
passed, with explicit byte equality for every parameter and moment array after
each update. The original numerical-equality log and the stricter byte-check log
are retained separately. Adapter injection/driver/compiler checks also passed;
one initial compiler-mock fixture failure is retained with its corrected log.
The complete independent suite passed 180 tests in 5.326 seconds and the root
suite passed 49 tests in 0.304 seconds. No dataset, qualification, held-out or
timing benchmark was executed for these checks. Actual benefit remains unrun.
