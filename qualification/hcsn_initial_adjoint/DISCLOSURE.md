# Stage 1 evidence boundary

This disclosure supplements the original prefrozen intent without changing
its tested sources or result. The request, SPEC and EXPECTED inventory retain
their original bytes at the prefreeze commit and in the original archive.

The actual mutation check changed the caller's live query list, phase-support
container and model fields after creating the snapshot. Its VJP still matched
the original fixed-model reference. It did **not** corrupt the FrozenProblem
coefficient arrays, identity or read-only flags, and did not execute those
rejection branches. It did not exercise Torch input mutation/version guards.
Snapshot-corruption and native input-guard evidence remain OPEN. Read-only
static inspection of those branches is separate from runtime validation.

The 18 adjoint calls comprise 16 geometry cases and two scalar cases. Two of
the geometry cases have T=0 and take no BDF integration steps. The 196 small
reference matrix exponentials are exactly two geometries times (two atom
reference calls + 32 uniform coarse nodes + 64 uniform fine nodes). Static
perpetual solves total two. No forward DDE/basis, Torch or optimizer call was
made by this stage.

All step, RHS, dense-coefficient and current-Jacobian limits apply per adjoint
call. The stage accumulates 9536 accepted steps, 19161 RHS evaluations and
2234311 stored coefficients across sequential calls; its per-call maximum
stored payload is 934247 coefficients. The one-million-coefficient cap is not
a stage-total cap or process RSS limit. No larger-mesh scaling claim follows.

The 2.66415-second wall and 2.64862-second CPU measurements cover the validation
loop, including its reference computations. They exclude Python/module
startup and the initial source/archive admission. Total process wall time
was not separately instrumented. Peak process RSS was 72760 KiB.

Five original directions per geometry each supply two retained FD scalar
contractions. The old output-coordinate FD experiments were not rerun. This
stage's 345 compared scalar values must not be labeled 345 independently
perturbed coordinates or new full-Jacobian FD coverage. Its target is a
continuous finite-DDE VJP within declared mixed tolerances, rather than the
discrete backward of adaptive BDF or relative rare-tail qualification.
