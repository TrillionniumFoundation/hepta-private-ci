# Explicit graded-node physical derivatives and Torch replay

This is a new geometry-specific qualification. The uniform public derivative
entry still refuses a graded model; callers select solve_graded_partials or
graded_physical_flow explicitly. The two wrappers share the same variational
delay equation, while each supplies its own generator and reset derivatives.

For actual adjacent spacings a,b, downward/upward rates are
(sigma^2-mu*b)/(a*(a+b)) and (sigma^2+mu*a)/(b*(a+b)). Their mu derivatives are
-b/(a*(a+b)) and a/(b*(a+b)); the mu diagonal is minus their sum, generally
nonzero. Sigma derivatives are 2*sigma divided by the same two denominators.
Reset derivatives use the actual node interval selected by searchsorted, not
an assumed uniform spacing. B and Vr still enter through log(Vr)-B with a
fixed initial relative law. Fixed geometry/stretch/delay are not differentiated.

The augmented engine rejects reset knots, zero-rate edges, nonfinite chains,
unrecognized geometry, and declared state/Jacobian/history budget excesses.
It permits at most 8,192 augmented scalar states and 2,000,000 conservative
cross-Jacobian slots/snapshot-history scalars; exceeding a limit is a failed
request, never a partial passing report.

Local final checks: 8 tests pass (5 uniform regressions, 3 new graded checks).
The graded finite-difference record contains 1,635 coordinates from four
synthetic fixtures: point, atom and uniform phase laws on a 16-interval grid,
plus a 64-interval mixture using mu/sigma/q from the observed training range.
That last law is newly chosen synthetic input, not an original held-out task
or one of the original 14,336 posteriors. All coordinates use two central-FD
steps 2e-4/1e-4. Maximum absolute error is 7.035628657448001e-8 under the fixed
3e-6 absolute plus 4e-4 relative gate. Raw full arrays, steps, nodes and tested
source hashes are retained. Boundary/reset chain, signed conservation, actual
node-knot refusal, source immutability and tolerance tightening are checked.
An absolute-plus-relative gate does not imply relative rare-tail accuracy.

Actual new graded CPU Torch execution, desktop job 1a1ce98acc8-2564-171c,
completed successfully with an authoritative complete/durable terminal receipt.
It passed gradcheck, both theta mutation controls, trainable-initial-state
refusal, source mismatch and runtime mismatch checkpoint controls. Four actual
Adam calls compare a continuous two-step physics fit with one step plus a new
Python process for the second. Complete parameters/Adam/RNG/record states agree
exactly. These are new graded executions, separate from the earlier uniform
native runs and hosted CI. It is not a task-quality or complete C2 replay.

New checkpoints bind source identities, runtime version/build/thread witnesses,
geometry and the fixed probability/content/query inputs. A changed runtime
witness is rejected; this does not authenticate binaries or qualify arbitrary
runtime migration. Probe wall time is 27.397395757958293 seconds after parent
imports and includes child imports; source transfer and packaging are excluded.
The native probe is POSIX-specific and used Python 3.12.3, Torch 2.8.0+cu128
on CPU, NumPy 2.3.5 and SciPy 1.17.0 with one thread.

All five actual checkpoints, actor outputs, source bundle and member index are
in the native archive (29,684 bytes; SHA256
0fd3e5eebc30e278151f5e53fae25810f9f6b463865c0b532a5aa16c720ece17).
Every original member was read back and size/SHA checked. The 11-file tested
source archive includes exact original test harness bytes. Final formatting
preserves ASTs; tests were not rerun locally afterward. Hosted checks on the
published head remain separate and may execute additional real optimizer calls.

This closes only the recorded fixed-prior graded physical derivative/VJP and
small optimizer-continuation mechanisms. Initial episode-prior gradients,
trainable content/filtering/network state, full training, whole-domain/relative
rare-tail forward accuracy, task benefit, strong baselines, energy and adoption
remain unqualified. HOLD_NO_GO.
