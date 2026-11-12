# Visit-897 N128 source-migration VJP numerical successor

Global status: **HOLD / NoUpdate / all_closed=false**.

This is a separately frozen numerical successor to the authoritative static
source-tree CLEAR in Draft #6265 at
`859d0f75119b792c035af54c9872b5fb7636eca6`. It does not inherit numerical
qualification from any failed predecessor. The four predecessor RED records
remain explicit in `REQUEST.json`; unrelated negative and `UNKNOWN` records are
unchanged.

## Exact admitted question

For the authentic #6223 visit-897 law (seed 37, arm `c0_b1`, update 24,
position 1), test the transpose from 25 source probabilities and 25×4 signed
contents through the exact immutable migration into the fixed #6234 graded
N128 first-cycle continuous finite-DDE scalar-loss adjoint. The recorded query
is `T=0.02 < delay=0.2` with fixed physics, geometry, delay and support.

The raw API does not normalize. A separate client graph uses
`softmax(log p)` and `content=p*mark` to check the normalized-law chain.

## Frozen denominator and gates

The unique identity and key are in `REQUEST.json`. One branch-creation push and
GitHub run attempt 1 are admitted. The exact denominator is:

- 42 actual candidate forwards: two analytic graph forwards plus 10 fixed
  directions × two finite-difference scales × two signs;
- two continuous finite-DDE adjoints and two Torch backward attempts;
- zero optimizer updates;
- all 125 migration-transpose coordinates retained and compared with an
  independent `Fraction` reconstruction;
- exactly the ten named directions and scales `2e-4`, `1e-4`.

Every direction is gated separately by
`abs(error) <= 2e-8 + 1e-3*abs(fine_fd)`. Relative error is reported only for
`abs(fine_fd) >= 1e-10`; below the floor the coordinate is not relatively
qualified. The independent transpose tolerance is `5e-13` absolute for each
of 125 coordinates. Averaging and error cancellation cannot pass a gate.

## Source, resource and mutation closure

Before importing the candidate, the workflow must bind every hash in
`SOURCE.json`, the exact #6265 parent, the original law, N128 metadata/NPZ and
`qualification/hcsn_initial_law/migration.py`. It must run the repository's
pinned `just 1.51.0` formatter against the #6265 base and leave a clean tree.

The child is single-threaded and capped at 3 GiB address space, 900 CPU seconds
and 1000 wall seconds. The host must expose at least 4 GiB `MemAvailable`
immediately before the child starts. Reverse work is additionally capped at
4096 accepted steps, 100000 RHS calls, 50000 sparse-Jacobian nonzeros and
16000000 retained adjoint scalars. Raw output, stderr/stdout, exact source bind,
resource preflight, result arrays and controller costs are uploaded even on
failure.

The twelve zero-numerical guards reject wrong identity/input bytes, uniform or
N512 substitution, mutable lift, lower atom, trainable delay/support/physics,
and silent normalization. Live Torch input signatures and saved values reject
metadata, storage or `.data` mutation before backward.

## Terminal semantics and non-qualification

Any source mismatch, format mutation, missing resource headroom, dependency
drift, nonfinite value, BDF failure, call denominator mismatch, gate failure,
signal, timeout or unknown counter is terminal for this key. There is no retry,
replacement key, mesh/direction/scale/tolerance tuning, or partial-pass claim.

A pass grants only this one authentic law, N128, fixed first-cycle scalar-loss
VJP. It does not grant N512 scalability, a migration-wide/full-prior domain,
trainable delay/support/physics, second-cycle feedback, adaptive-BDF program
reverse, fullnetwork training, task benefit, finite-domain qualification,
production adoption, or global closure.
