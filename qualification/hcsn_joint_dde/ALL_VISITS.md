# Same-law continuation requalification on all original retained positions

The original #6073 audit rejected 14,336/14,336 continuation values from
12 arms / 384 training rows. Its 80-digit references, posterior laws, original
error values, source identities and 1% scaled-error limit remain unchanged.
Original raw archives and sidecars were restored by exact hash, not regenerated
with new weights. This stage evaluates the joint candidate from #6129 on those
same reconstructed laws; it starts no model training or original C2 process.

The candidate's perpetual value follows its actual spatial/delay/reset flow.
For each old uniform cell, the piecewise-linear nodal value is integrated over
the entire original density. The old exponential tail is integrated from 4.8
through the new endpoint 8, with permanent active escape beyond 8. Initial
remaining-time uniform cells use exact exponential discount means. This is
backward-value quadrature on the original laws, not a claim that old cell masses
can be supplied directly as nodal rollout states.

All 14,336 positions pass the original unchanged 0.01 limit at 128/256/512
intervals. The maximum scaled error is respectively 0.000609560302,
0.000182203415 and 0.000047225549. The supplementary conservative sum
`(|candidate-finite_continuum|+|finite_continuum-halfline|)/max(1,|halfline|)`
also passes every position, so spatial/reset and upper-tail errors cannot hide
each other through cancellation. The independent half-line formula agrees with
every retained original 80-digit value to 3.56e-15. A separate implementation
cross-checked all 43,008 grid/visit rows, with maximum value difference 3.56e-15.

`all-visits-attempt002` is the complete final source-guarded execution. Its
three compressed arrays preserve every per-visit identity, candidate, original
reference, finite-continuum value and error. `audit_visits.py` requires the exact
original summary SHA and checks all trace/audit identities before evaluation;
source and input hashes must remain unchanged. The first preliminary execution
is preserved separately and has no source-before/after guard. It receives no
final-source execution credit.

Read-only array verification (zero model calls):

```sh
python -B -m qualification.hcsn_joint_dde.verify_retained_values qualification/hcsn_joint_dde/evidence/all-visits-attempt002
```

This closes the **retained fixed-law continuation-value defect for this new
candidate** on the exposed original population. It does not validate migrating
those laws into rollout state, observation filtering, full-network gradients,
original training replay, future tasks, equal-cost quality or adoption. The
candidate's upper compartment remains nonreturning. Numerical arrays cannot
grant product or scientific authority. Overall status remains **HOLD_NO_GO**.
