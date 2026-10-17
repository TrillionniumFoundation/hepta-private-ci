# Group System2 / NDU boundary

This module adds the first owner-local Group System2 seam for a population of
Neuron Cells. It is deliberately deterministic and advisory.

## What is fixed

- 'GroupNduSubjectV1' binds the group owner to a subject class ('Domain' or
  'Agent'), group identity, generation, objective, shared encoder artifact and
  utility profile.
- 'GroupCellObservationV1' carries each Cell's head/action evidence and a
  bounded resource cost.
- 'GroupDecisionTraceV1' binds the input, route, behavior, terminal outcome,
  complete candidate-set digest, and every Cell observation.
- 'decide_group_continuation_v1' requires one legal explicit abstain candidate,
  rejects duplicate candidates, rejects negative cost/risk/uncertainty, enforces
  Cell and candidate caps, and chooses a legal continuation only when its
  deterministic net value is strictly positive.
- The result always carries 'AuthorityPosture::DENY_ALL'. It cannot authorize
  model invocation, selection, promotion, release, external effects, or
  durable mutation.

## What this does not claim

This is not a learned FBSDE, a trained critic, a hidden-chain-of-thought
implementation, or evidence that System2 reasoning has emerged. The current
policy is a replayable continuation gate:

net = continuation_value - current_value - cost - risk

The candidate set is digest-bound and the trace digest is deterministic, so a
future learned critic, Neural Differential Utility solver, or router can be
introduced behind the same owner boundary and compared against this baseline.

## Next integration

The next implementation slice should add a real shared Encoder owner and an
artifact CAS/final-use binding. Its output should populate the Cell observations
without duplicating the encoder per Cell. After that, add a shadow-only learned
critic and bounded depth/continue controller; promote neither until it beats this
deterministic baseline on replayable utility, risk, resource, abstention, and
OOD slices.
