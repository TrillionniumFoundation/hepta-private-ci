# Q24 frozen-prefix noninterference (research only; 2026-11-10)

Base: PR #5811, commit `3e17e081ed13a89526c3dadebfaf25bac00fd8d8`.
This separate branch modifies only the native research comparator; it
must not be mistaken for owner-authenticated training or evaluated improvement.

At cutoff `t`, a feedback supplied with `available_sequence > t`
cannot yet count as an **observed** action or contribute to the training
candidate. Previously the reference counted such a future receipt as supplied
and thereby decreased `unobserved_action_count`. The original
`transcript_digest` also committed to future label values. That hash remains
an explicitly **full-input audit**, never a selection key.

The new `causal_training_digest` binds contract, group mapping, actions,
only feedback available by `t`, corresponding projected deltas, and
as-of-cutoff counters. It omits the number, receipts, and label values of
later-arriving feedback. Tests compare three different future datasets against
the identical absent-future cutoff; they separately verify expiry-as-observed
and a later cutoff changing the prefix. Supplying invalid future data may
still fail validation: this is a trusted-input reference, NOT an access-control
filter that should read confidential future information.

**HOLD_NO_GO:** no native StageOwner or independently authenticated source/
feedback verifier has called this API; no Q24 trained model, frozen-B
evaluator, NoUpdate/Adopt, independent next task C, cold recovery, matched
compute cost, scientific superiority, or production qualification is shown.
Both digests remain self-declared and `AuthorityPosture::DENY_ALL`.
The original owner must enforce time-gated *data access*, not rely on
this helper to erase information that it was improperly given.
