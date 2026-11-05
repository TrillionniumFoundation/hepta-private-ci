# Frozen protocol clarification

The v2 protocol and its executed data are retained byte-for-byte. The v2
`timeout_cap` field specifies that each query chooses a cap no larger than
remaining time and that outcomes beyond the selected cap are censored at that
cap. This is the semantics executed by `model.py`, the README equations, and
all `evidence/cancellation_complete` histories.

The older `deadline_rule` field was carried over from v1 and says that outcomes
beyond the remaining global time collapse to timeout at the deadline. That
sentence fully describes only the special case where selected cap equals
remaining time. For the v2 general case it should read: **outcomes beyond the
selected cap collapse to one timeout event at the selected cap; their likelihoods
are summed before conditioning, and control resumes with remaining time reduced
by that cap.** A shorter cap is a paid cancellation, not a leaked completion.

This is a documentation correction identified during separate internal review. It
does not silently replace the frozen protocol, change a reported outcome, or
claim a new preregistration. A separate internal implementation rebuilt the 18 exact
values from a separate handwritten kernel and unnormalized hypothesis masses;
maximum discrepancy with the executed results was 1.11e-16 (ordinary floating
point). The source and original result hashes in `evidence/validation.json`
remain the applicable identities.
