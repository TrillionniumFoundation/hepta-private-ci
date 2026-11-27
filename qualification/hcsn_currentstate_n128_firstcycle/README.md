# N128 first-cycle full-state comparison

Status at source freeze: **HOLD / INTENT_NOT_EXECUTED**.

This separately frozen successor uses exact #6281 source
`eaaac2a9bd0d3d637406af00b3cbb0ed0edcc1f0`. It consumes the authentic #6264
N128 input and roster and advances the first cycle through `t=.2`, before any
generation-2 packet is released.

The candidate uses the #6264 CSR graph primitives. A separate dense oracle
reconstructs the spatial/reset/phase equations without importing candidate
code. The five warm capsules at `0/.001/.02/.16/.2` contain 401,278 total
coordinates. Every capsule must match its authentic roster denominator, compare
coordinate-by-coordinate, and survive canonical dump/fresh-load/dump with
identical bytes.

A post-development local run observed 401,278/401,278 bitwise-equal coordinates,
five byte-exact cold containers, and 11 segments/22 matrix exponentials on each
implementation. It was not precommitted and grants no qualification. Only the
source-bound hosted admission declared here can become evidence for this stage.

Even a successful hosted run does not cover the release of generation-2 packets
at and after `.2`, the remaining warm/coarse/cold paths through `.36`, arbitrary
histories, N256/N512 dynamics, full-network training, finite-domain
qualification, asynchronous complete cost, C2 full replay, or HPCA external
custody. All earlier negatives and `UNKNOWN` remain unchanged.
