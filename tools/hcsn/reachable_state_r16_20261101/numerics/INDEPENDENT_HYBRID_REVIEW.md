# Independent review: Q24 and interval fallback

Reviewed source: hybrid commit `44443bbdc2b6e6695bdca2ec728e923c7cdbea22`,
with unchanged native dependency `4c51e9a068a887fcf80573628e7692a1f84f9c18`.
This is an independent source and mathematical-contract review, not a new
execution or an independent claim that the formal qualification runs passed.
Those outcomes are recorded separately by the qualified runner.

## Review decision

No remaining blocking defect was identified in the stated profile: exact
integer-weight fixture, fixed 80-digit outward-rounded interval arithmetic,
four addressed filter states, a fixed supplied public tape, and restoration
from a trusted checksum-verified complete snapshot. Two concrete pre-freeze
findings were fixed: reusing an output namespace could overwrite evidence,
and an unqualified 20-digit entry point did not guarantee exact conversion of
every Q24 center. The final driver rejects existing output directories and
the interval model requires exactly the registered 80-digit precision.

The source entry point itself checks native dependency hashes and the format
of the hybrid commit. The external qualification guard supplies the otherwise
missing new-source hash check before launching formal seeds. The reviewer
read [HYBRID_QUALIFICATION_PUBLICATION.json](HYBRID_QUALIFICATION_PUBLICATION.json):
all 13 hybrid/native source and protocol hashes match, and the limitation is
explicit. Frozen source was not edited to insert a guard after publication.

## Integer error accounting

Native apportionment computes its L1 rounding radius with exact integer
discrepancies. Stochastic contraction gives the propagation bound

\[
\delta_{next}\leq\delta_{prior}+\max_i\delta_{kernel,i}+\delta_{round}.
\]

For observation with positive approximate evidence, normalization error is at
most twice the unnormalized L1 error divided by approximate evidence. The
integer expression has the correct scale:
`ceil(2 * uncertainty_units * SCALE^2 / evidence_counts)` plus new rounding.
Capping at two is valid for normalized probabilities. WRITE preserves the
existing radius; it does not clear an uncertainty budget.

Structural support is tracked independently of zero Q24 counts. A supported
observation with zero approximate evidence requests more precision, rather
than becoming impossible or receiving epsilon mass. Transition/observation
memory mutation is committed only after their checks pass.

These bounds apply to the normalized rational fixture represented by imported
integer weights. They do not certify upstream floating matrix exponentials or
a continuous PDE. Original float64 comparisons remain separately measured
diagnostics with the stated slack and source-conversion error.

## Interval fallback and event ownership

Fallback replays the actual past public prefix from the retained interval cache,
using directed rounding for positive matrix products, observation evidence,
normalization and simplex intersection. The exact fixture state is enclosed
through these operations under the declared arithmetic and positive-evidence
conditions. A wide enclosure or unavailable positive lower evidence is refused.

For a proposed Q24 center q, the new radius bounds

\[
\sum_i\max(q_i-l_i,u_i-q_i),
\]

rounded upward in Q24 units. At 80 decimal digits every Q24 center is represented
exactly. Midpoint quantization may be approximate because its resulting center
is checked against the enclosing intervals afterward. A smaller radius is not
inherited merely from restarting a process.

When native precision is refused, the accepted prefix is retained, replay
catches up to it, and the refused operation is applied once by the interval
path. The next native process begins after that operation. Event indices,
clocks, support and radii are checked; dropped/repeated events and inconsistent
reentry are rejected.

## Recovery and cost boundaries

The bundle carries model identity, complete tape identity, fixed error profile,
cursor/clock, native counts/support/radii, interval endpoints/cache identity,
and cumulative recorded costs. Restore checks model/tape/profile consistency
and reconstructs the native checkpoint bytes. It does not repeat simplex
tightening on the restored interval cache, preserving its endpoints exactly.

The complete public tape is still retained. Qualification eventually replays
every consumed event with 80-digit intervals to certify visited states and
complete the recovery cache. A small number of fallback triggers does not mean
only that many events pay high-precision work. This is not evidence of cheaper
execution than an all-high-precision solver or of history-free recovery.

Outer child CPU includes the driver and its waited-for native descendants.
Replay/native component timers are nested and must not be added again.
The cumulative checkpoint CPU snapshot excludes some later artifact writes and
is marked as a lower bound; its byte counter explicitly excludes the RUN
receipt written afterward.

Checksums and model/tape binding detect corruption and mismatched trusted
artifacts. They do not authenticate an owner, stop recomputed checksums, or
reject an older valid snapshot. New initialization without RESTORE is possible.
“Restart does not reset the bound” therefore refers to correct restoration of
the same trusted state, not a production anti-rollback or economic-credit
guarantee. Pending planner actions, native planning, network replay and owner
authorization remain outside this profile.

## Source identities reviewed

| File | SHA-256 |
| --- | --- |
| interval_replay.py | `b8e7070bb6179c1c4657857c7aa14df485e1f1f0824fbfb2a6c241d83c66fcef` |
| hybrid_driver.py | `b20b9d4ddb2c857fb139b8e59ed4299673f78342c6ecd19e6fe900808cb2549e` |
| validate_hybrid.py | `207ef2df41f0c7ad80c8027374a2e625c863f4d2764e904f89464aeab3f039e8` |
| test_interval_replay.py | `aa80a4ac2506cbaf4b2918a299253dbaf84c53da82be8a8e21ea159972c788d1` |

The exact-Fraction test source was inspected. It independently updates rational
probabilities and checks interval endpoints/radii, rare supported observations
without epsilon, and byte-preserving restore. This review did not count the
implementation's own test run as another independent execution.
