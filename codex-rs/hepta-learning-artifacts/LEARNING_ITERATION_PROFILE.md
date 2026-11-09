# Frozen evaluation identity in the ordinary Root candidate

The original owner supplies `LearningIterationRequestV1::evaluation_profile`
before the initial checkpoint, dataset construction and training. The digest is
mandatory and nonzero. It commits to the intended evaluation protocol; it does
not certify the protocol's scientific adequacy or an evaluator's independence.

The initial checkpoint binds this profile with the completed source task,
selected bundle, owner identities, envelope and training budget. Training lineage
and both `Qualified` and `NoUpdate` evaluation receipts must match the original
profile. A mismatch stops before the next stage and leaves the preceding
checkpoint unchanged. A valid signature cannot replace the frozen protocol.

The original Root profile and dedicated handoff carry the same encoded initial
snapshot. Registered checkpoint storage, transport and cold recovery therefore
retain the same profile; no additional trainer-selected value is accepted by
the ordinary learning delivery path. Real stage owners, independent evaluation,
Circuit providers and governed publication remain separate assembly obligations.

## Explicit compatibility boundary

The initial digest domain is `hepta.learning.iteration-checkpoint.v2\0` and the
binary checkpoint format is `HEPLCP02`. A 32-byte profile follows the selected
artifact digest, before the complete selected bundle. The existing 8,192-byte
binary bound is unchanged. Maximum fixtures occupy 6,452 bytes for evaluated
NoUpdate and 6,977 bytes for the update or proposal-rejection paths.

`HEPLCP01` and old initial bindings are refused. Their profiles were not frozen;
they cannot be inferred from candidate lineage or later evaluation results. No
record is rewritten, re-registered or automatically migrated. Outstanding work
must be reconciled using its original identity and original pinned owner; this
change grants no permission to redispatch it. New operations require their own
original-owner registration and profile before work.

Receipt signing remains `hepta.learning.iteration-observation.v1\0`; the signed
predecessor binds the new initial domain. The outer Root profile and handoff
schemas retain their existing authority and carry the explicitly versioned
inner checkpoint. NoUpdate still requires unchanged selection and actual use
by a distinct next task before completion.

The contract, codec and regressions are selectively integrated from
`f6247df765bb82d18247ed7d492635d09d2bb403` onto the ordinary Root candidate.
Tests cover profile binding before work, signed trainer drift, both evaluation
dispositions, recovery without writes, old-format refusal and retained-model
NextUse. They use engineering fixtures and do not establish useful learning,
production activation, independent custody or complete resource costs.
