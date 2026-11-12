# Original visit-897 source-migration VJP, N128 stage 1

Status before the single admission: `HOLD / INTENT / NOT_EXECUTED`.

This is a separately frozen, one-law experiment based on exact source commit
`994def0b188c5105d0ceb9ace281af7f4bd0e3b2` from Draft #6253. It advances one
specific missing edge: the transpose from the authentic 25 source probability
coordinates and 25×4 signed-content coordinates through the original exact
migration into an N128 continuous finite-DDE adjoint.

It is not a claim about the full posterior domain, state migration between
observations, trainable delay/support/physics, a second delay cycle, N512,
adaptive-BDF instruction differentiation, fullnetwork training, task benefit,
or production use. Global status remains `HOLD`; historical failures and
`UNKNOWN` entries are unchanged.

## Immutable inputs

- #6223 `SELECTED_ORIGINAL_LAW.json`, SHA-256
  `7a4b7485bf224b5e343f2c17fccf4ea7ca2dfdd06121810d16c503134f9e92fb`:
  seed 37, arm `c0_b1`, update 24, position 1, visit 897, 25 probabilities,
  and 25×4 signed contents.
- #6234 N128 metadata, SHA-256
  `8f4f77b8ba2bc1d1e3012f64ce9614711d178503601878e091b3db8e7eadaf09`,
  and N128 NPZ, SHA-256
  `fda047c1a8fce3cc042246b5249859cd0a0ba449647460ba9e0a39592386ff7d`.
- Exact migration source, SHA-256
  `0e85587433dee39f583fe2c1409e127c75498c96928640890936fadaa12de517`.
- Fixed original physics, graded geometry, phase supports, delay 0.2, and the
  recorded first-cycle query `T=0.02 < delay`.

The exact rational lift is recomputed once and must reproduce the immutable
N128 NPZ arrays byte-for-byte after the specified FP64 conversion. The raw API
does not normalize. A separate client-side graph uses `softmax(log p)` and
`content = p * mark` to test the normalized-law chain explicitly.

## One execution denominator

The unique identity and idempotency key are both
`hcsn-original-visit897-source-migration-vjp-n128-stage1`.

- exactly 42 actual N128 forward calls;
- exactly 2 continuous finite-DDE adjoint calls;
- exactly 0 optimizer updates;
- exactly 10 fixed directions, each with central finite differences at
  `2e-4` and `1e-4` (40 forwards), plus one raw and one normalized Torch graph
  (2 forwards and 2 adjoints);
- all 125 migration-transpose coordinates retained and compared with an
  independent Fraction-based transpose;
- single thread, 900 second child timeout, 3 GiB address-space limit, 4,096
  reverse accepted steps, 100,000 reverse RHS calls, 50,000 sparse-Jacobian
  nonzeros, and 16,000,000 retained adjoint scalars.

Directional gates are evaluated separately, never by cancellation or
averaging: `abs(error) <= 2e-8 + 1e-3*abs(fine_fd)`. Ordinary relative error is
reported only when `abs(fine_fd) >= 1e-10`; below that floor the absolute gate
is used and the coordinate remains explicitly ineligible for relative claims.
The exact migration-transpose coordinate gate is `5e-13` absolute.

## Negative controls and stop rule

Before numerical admission, zero-forward/zero-adjoint guards reject wrong
visit/arm bytes, selected-law or migration hash mismatch, uniform or N512 node
substitution, a mutable lift cache, a nonzero lower atom, and trainable
delay/support/physics requests. A scaled raw source must preserve its 1.25 total
mass, proving the raw path did not silently normalize.

Any source/input mismatch, missing independent static `CLEAR`, resource limit,
nonfinite value, BDF failure, call-counter `UNKNOWN`, denominator mismatch, or
gate failure produces `RED_STOP_NO_READMISSION`. The same key is not rerun and
no mesh, direction, finite-difference scale, tolerance, or budget is tuned.

## Interpretation

A pass grants only one authentic visit-897, one-law, N128, first-cycle scalar
loss VJP through fixed migration and fixed continuous-DDE physics. It does not
combine with #6248, #6253, #6234, or any other lineage to manufacture a wider
qualification.
