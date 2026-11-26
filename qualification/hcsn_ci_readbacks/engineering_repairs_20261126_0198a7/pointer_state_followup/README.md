# CPU pointer publication-state test correction

The real immutable artifact was published and the live pointer is now FROZEN.
The old test_real_missing_pointer_refuses loaded that live pointer while still
requiring the validator to reject it as MISSING. This is a fixture error.

## Retained original failure

Parent: 51bed2bd21b3e7505a4123fdc88865ed154b4e71.
Run 45781771974, adapter job 139778698521:
18 migration/archive tests passed; the ordinary pointer suite ran 5 methods,
with only the publication-state fixture failing. The shell exited at that
failure. Its following outer python -O suite did not execute.
The subprocess optimization test inside the ordinary suite did execute.
Recovery job 139782175664 was skipped with an empty step list.
The real 26-call CPU short diagnostic did not start.

The archive preserves the original decoded job log, run and job metadata,
original test, candidate, exact validation source, formatter output, both
regression streams, result, and native process observation. No old outcome
has been relabelled.

## Source correction and bounded regression

The negative fixture sets only its in-memory JSON status to MISSING and retains
the same ValueError/HOLD rejection assertion. A positive test sends the actual
published raw pointer to the unchanged validator and compares its returned
identity with the registered document. The remaining tests are unchanged.

One normal and one optimized outer suite passed, 6 methods each, using main
Python 3.14.3 on macOS. Each suite includes the original 8 nested pointer-only
child invocations. No model, Torch, optimizer, checkpoint deserialization,
or real CPU diagnostic was executed. Official just fmt ran first; source
bytes were unchanged before and after the tests. These tests establish the
fixture correction, not qualification of the Linux Python 3.12.3 CPU profile.

## Following CI and scope

A single ordinary push of this corrected source resumes the preflight for the
previously unstarted short CPU diagnostic. No manual dispatch, rerun, PR,
or change to workflow triggers, frozen source hashes, artifact commitment,
CPU profile, admission predicates, numerical tolerances, or resource limits
is included. The first failed run remains failed.

The existing recovery lane can consume its original bounded 26-call profile
only after its normal gates pass. This is not the complete six-fit replay.
The separate differentiable CI workflow is accounted independently; 26 is not
a cap or claimed count for all work triggered by the source push.
All higher-level scientific HOLD and exhausted E1-E6 budgets remain unchanged.
