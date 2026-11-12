# Visit-897 N128 source-migration VJP AST-count successor

Global status: **HOLD / NoUpdate / all_closed=false**.

This is a separately frozen successor to Draft #6268 at
`bdb904e546d5817cb11097cb9ca6f3f88a6f6bec`. It does not inherit numerical
qualification from that failed predecessor or from #6265's static CLEAR. All
seven predecessor RED/UNKNOWN records remain explicit in `REQUEST.json`;
unrelated negative and `UNKNOWN` records are unchanged.

Draft #6268 run `43277019131` / job `131388014924` passed the corrected five
provenance checks and then stopped before candidate import because an older AST
guard called `.count("migrate")` on a `set`. GitHub reports no artifact for that
run. Its unique key is burned and its zero numerical counters remain retained.
This successor keeps the membership set and separately counts exactly two
direct `migrate(...)` AST calls in the frozen source, one for the baseline
freeze and one for runtime transformation. Requiring exactly two does not
weaken the prior at-least-two intent. No original byte gate is dropped or
weakened.

## Original-byte justification for the minimal fix

The #6266 source/input closure was complete. Its first mismatch was
`active[1]`: the stored value is `0x1.c429240cecba4p-11`, while the predecessor's
pre-rounded FP64 matrix product produced `0x1.c429240cecba3p-11` (one ULP
lower). The predecessor disagreed at 45/129 active values and 177/516 signed
content values, with maxima of one active ULP and two content ULPs.

The recovered #6234 exporter source calls the immutable `migrate(...)` API,
which accumulates decimal-round-trip inputs and exact lift weights as
`Fraction` values and converts only final scalars to FP64. Repeating that exact
path matches all stored active and content bytes. The original arrays are
little-endian C-order FP64, their nodes and ordering match the current graded
generator, and all selected-law, JSON, NPZ and migration-source hashes match.
The RED was therefore an arithmetic-path mismatch, not a source, order,
dtype/endianness or semantic migration mismatch.

This successor changes no input, node, threshold or denominator. Both the
baseline freeze and the candidate runtime source-to-amplitude transform call
the same original exact `migrate(...)` path. The float lift remains only the
declared adjoint representation and is independently checked against the exact
rational transpose.

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
`SOURCE.json`, the exact #6268 parent, the original law, N128 metadata/NPZ and
`qualification/hcsn_initial_law/migration.py`. It must run the repository's
pinned formatter against the exact #6268 base and leave a clean tree.

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
