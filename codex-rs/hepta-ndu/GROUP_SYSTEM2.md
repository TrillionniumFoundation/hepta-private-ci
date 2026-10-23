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
  complete candidate-set digest, and every Cell observation. Its required
  'subject_binding_digest' seals the full owner tuple (subject class, group,
  generation, objective, shared Encoder, utility profile and resource ceiling),
  and stale or cross-owner traces now fail closed.
- 'decide_group_continuation_v1' requires one legal explicit abstain candidate,
  rejects duplicate candidate IDs and duplicate Cell observations, rejects
  negative cost/risk/uncertainty, verifies subject/generation bindings,
  enforces Cell and candidate caps, and chooses a legal continuation only when
  its deterministic net value is strictly positive.
- The result always carries 'AuthorityPosture::DENY_ALL'. It cannot authorize
  model invocation, selection, promotion, release, external effects, or
  durable mutation.

## What this does not claim

This is not a learned FBSDE, a trained critic, a hidden-chain-of-thought
implementation, or evidence that System2 reasoning has emerged. The current
policy is a replayable continuation gate:

net = continuation_value - current_value - cost - risk

The legal abstain candidate has its own net value under that same equation.
A strictly positive continuation is selected only if its net value is also
strictly greater than the abstain alternative; equal values favor abstention.
The abstain net is validated before any selection so overflow cannot hide
behind an otherwise positive continuation. These are advisory economics,
not an allocation of physical microsecond budget or production authority.

The candidate set is digest-bound and the trace digest is deterministic, so a
future learned critic, Neural Differential Utility solver, or router can be
introduced behind the same owner boundary and compared against this baseline.

The neuron crate now emits CellEvidenceV1 after binding a CellHeadOutputV1 to
the existing local runtime receipt. The observation adapter widens its Q24
value and uncertainty to the Group NDU's Q32 coordinate and derives the
resource cost from execution time plus queue age. This is the first executable
bridge from shared Encoder/per-Cell head evidence into the group continuation
gate; it still grants no authority and does not make a learned System2 claim.

## Shadow depth controller

`NDU_SHADOW_SYSTEM2.md` and `shadow_system2.rs` add the next owner-local seam:
`NduShadowRequestV1` binds the input, stem, shared Encoder, group adapter,
critic, trajectory, and policy digests. The pure fixture controller can hold,
spend one bounded depth step, or abstain when depth, budget, risk, or
uncertainty fences require it. The result carries replayable request and receipt
digests and remains `AuthorityPosture::DENY_ALL`.

This fixture is not a learned critic and does not mutate runtime state. The
future learned critic and adaptive-depth model should be trained offline and
promoted only after it beats this deterministic baseline on replayable utility,
risk, resource, abstention, calibration, and OOD slices.


## Full-owner trace binding (draft compatibility change)

The old research trace accepted a same-subject/same-generation record when
replayed against a different Group or Encoder. The decision digest included the
new subject, but the incoming trace had no matching owner-tuple commitment to
verify. The strengthened draft trace now requires an explicit canonical
`subject_binding_digest`, checked before candidate selection. Its bytes are
also part of the decision trace digest, so old draft receipts cannot silently
qualify under the new schema.

This is an owner-local consistency check, **not** an authenticated signature,
real Encoder forward receipt, independent evidence observation, or runtime
permission. Do not infer P0/P3 or production qualification from unit tests.
