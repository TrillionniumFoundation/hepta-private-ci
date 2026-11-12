# N128 first-step full-state comparison

Status at source freeze: **HOLD / INTENT_NOT_EXECUTED**.

This is a new, separately frozen, bounded experiment based on exact #6280 head
`df2da40353696a4bd2f23c9bb7efa92b5cbc4fbf`. It consumes the authentic #6264
N128 input and roster and executes only the first transition from `t=0` to
`t=.001`.

The candidate uses the #6264 CSR graph primitives. A separate dense oracle
reconstructs the spatial/reset/phase equations without importing the candidate
implementation. Each path performs two SciPy matrix exponentials: one for the
undiscounted state and lower-hit mass, and one for discounted hit/occupation
integrals. The comparison covers all 18,528 warm-1 coordinates: 1,320 current
state coordinates and 17,208 packet coordinates. The candidate's canonical
container is also required to survive dump, fresh load, and dump with identical
bytes and identical coordinate rows.

A local development run after writing the implementation observed 18,528/18,528
bitwise-equal coordinates, four total matrix exponentials, and no Torch or
optimizer operation. That run was not precommitted and grants no qualification.
Only the source-bound hosted admission declared here can become evidence for
this exact stage.

Even a successful hosted run is limited to this input, this N128 graph, and this
first step. Later warm/coarse/cold times, second-cycle feedback, arbitrary
histories, N256/N512 dynamics, full-network training, finite-domain
qualification, asynchronous complete cost, C2 full replay, and HPCA external
custody remain open. The #6247 rare-return negative result, old OOM/killed
attempts, and all historical `UNKNOWN` remain unchanged.
