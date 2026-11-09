# Frozen evaluation profile in native learning iterations

`LearningIterationRequestV1::evaluation_profile` is the original owner's
mandatory nonzero commitment to the evaluation protocol. The caller supplies it
before the initial checkpoint, before dataset construction and before training.
It is not copied from the trained candidate or inferred from an evaluation
result. Current owner, trust and revocation checks remain at their existing
boundaries.

## Admission behavior

The initial checkpoint commits the profile together with the completed source
task, selected complete bundle, owner identities, source revisions, envelope and
learning budget. A different profile gives a different initial head even when
the operation ID is reused.

The original coordinator checks two independent boundaries:

- Training lineage must name the frozen profile as well as the exact selected
  source bundle and dataset snapshot. Mismatch refuses the training receipt and
  leaves the dataset checkpoint current; evaluation is not dispatched.
- An evaluation must name that same profile and candidate. This applies to both
  `Qualified` and `NoUpdate`. A valid signature does not exempt either result
  from the profile check.

Restoration must match the complete original request. Replacing its profile
cannot reuse earlier receipts or the original protected checkpoint binding.
`NoUpdate` continues to retain the complete incumbent bundle; independent
selection, a current FinalUse operation and a committed distinct next task are
still required for `UsedByNextTask`.

## Explicit compatibility boundary

The initial digest domain is now `hepta.learning.iteration-checkpoint.v2\0`.
Receipt signing remains `hepta.learning.iteration-observation.v1\0`; the
predecessor commits the new initial domain and mandatory profile.

The native checkpoint binary format is `HEPLCP02`. Its request adds a 32-byte
profile digest after the selected artifact digest and before the complete
selected bundle. The record remains bounded to 8,192 bytes; the existing
protected Root envelope remains bounded separately. The largest existing
fixtures grow by 32 bytes, to 6,452 bytes for evaluated NoUpdate and 6,977 bytes
for the update/proposal-rejection paths.

`HEPLCP01` is rejected. It did not commit a preregistered profile, so deriving a
replacement from candidate lineage would recreate the vulnerability. Old
records and signatures remain historical evidence under their original pinned
source. There is no in-place relabeling, automatic migration or silent default.
An explicitly new operation requires its own owner-frozen profile and initial
checkpoint. Outstanding effects of an old operation must be reconciled under
that original identity; this format change does not authorize redispatch.

## Native verification and cross-repository fixtures

Focused tests cover profile-dependent genesis, a valid signed trainer profile
substitution before evaluator dispatch, attempts to change the profile on
restore, both evaluation outcomes, old-format refusal without a CAS write, and
both NoUpdate routes through cold recovery and exact incumbent next use.

The existing original generation-readback fixture can additionally emit paired
`HEPTA_LEARNING_CHECKPOINT_V2` records when
`HEPTA_GENERATION_LEARNING_READBACK_STDOUT` is set. It uses the exact native
checkpoint codec on the coordinator used by the actor and checks that the
checkpoint head equals the original readback's learning head. The output names
its raw bytes, SHA-256, initial head and frozen profile. The retained/adopted
cases each have pending-output and acknowledged-output observations; those are
two cases at two stages, not four independent experiments.

These exports are fixture data with fixture-derived pins. They grant
`DENY_ALL`, do not export current permission, and do not establish protected
production checkpoint custody, real training, independent evaluation, model
improvement, settlement, actual neural loading or production qualification.

## Scope of the profile commitment

The digest binds the host's registered protocol; it does not interpret its
contents or certify scientific adequacy. The independent evaluator still owns
the actual no-change, cell-only, routing-only and joint comparisons, matched
budgets, retention/interference checks, holdout protection and decision rules.
Chain execution/work evidence cannot supply those outcomes or replace current
local adoption authority.
