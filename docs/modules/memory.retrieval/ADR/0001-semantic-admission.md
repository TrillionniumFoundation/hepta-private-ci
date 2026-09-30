# ADR 0001: Admission, polarity and zero-effect semantics

Status: implemented in the source candidate; execution/acceptance pending.

Keep zero `minimum_activation` legal for experiments, but require positive activation independently of that threshold. Rejecting every zero threshold would unnecessarily remove a valid ablation configuration; permitting zero activity to produce support is never valid. Ignore zero-weight synapses in expansion, settling and contradiction semantics while retaining immutable graph provenance.

Apply the score floor to the policy-admitted view before coverage/OOD/conflict and HNMF seeding. Keep original union/count receipts so admission filtering does not impersonate source exhaustion. The invariant is below-floor noninterference, not unconditional monotonicity under arbitrary new admitted evidence.

Represent contradiction evidence as proposition digest, complete generation-vector digest and explicit polarity. Conflict reports do not assert either side. Opaque historical groups cannot be upgraded by guessing polarity. Compute confidence using activation-weighted fixed-point arithmetic; do not call the result calibrated probability without independent data.

Regression obligations: all input permutations; zero threshold with no zero support; zero-weight edge neutrality; same-side evidence; opposite-side conflict; below-floor poison; mixed generations; active/population/candidate/count ceilings; activation-weighted confidence. Property grids supplement, but do not constitute a proof over every possible valid policy.
