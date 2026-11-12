# Fixed-profile retained-posterior continuation audit — HOLD

The fixed profiles are v2 exponential 512 (`stretch=6`, `L=8`), near800/1024
with 800 intervals through `0.5`, and near960/1024 with 960 intervals through
`0.48`. No mesh or threshold is selected from this audit's outcomes.

The auditor reads every probability posterior from all twelve original
journals, checks their identities against the original root SUMMARY, and
joins every one of the 14,336 positions to the published original reference
array by arm and visit index. The primary gate remains the original 1%
scaled continuation error against that published reference. A new 80-digit
round-trip-decimal closed-form reference is independently compared to the
original. It retains the actual journal physics, including
`mu=-0.11999999999999998` rather than the synthetic `-0.12` used elsewhere.

Each retained reconstructed prior law has four continuation values:

- A: half-line continuum on the original uniform16/exponential-tail/uniform8
  phase law, with the same fixed unquantized reset policy.
- B: finite continuum on that same original law, with a permanently active,
  nonreturning upper escape boundary.
- C: finite continuum on the initial law after the declared nodal lift,
  retaining B's same **unquantized deterministic reset point**.
- D: actual candidate `GradedJointModel.perpetual()` on the lifted initial
  law; its CTMC also randomizes the reset point to adjacent actual nodes.

`C-B` is initial-law migration, `B-A` is the upper nonreturning truncation,
and `D-C` **combines CTMC spatial transport discretization and reset-point
randomization**. C is not a reset-matched nodal continuum model; D-C must
not be described as pure CTMC error. These signed terms telescope to D-A.
Their absolute sum, plus any new-versus-published reference drift, is retained
as a conservative non-cancelling budget rather than allowing cancellation
to hide component costs.

The original exponential tail is retained in A and integrated to infinity;
its finite/migrated/candidate contributions are separately recorded. Full
per-basis values permit inspection of coarser far-grid costs. The summary's
"whole far cells" use original cells starting at least at 0.5, plus the tail;
the crossing original cell `[0.3,0.6]` is explicitly excluded from that
particular subtotal. The full-law gate includes every cell. Differences
between near profiles also change near-grid resolution and therefore do not
isolate a single far-coarsening mechanism.

This executes fixed-law backward continuation only. It performs no training,
optimizer step, original observation-filter replay or forward DDE rollout,
and does not qualify actual filtered trajectories, gradients, task quality
or production adoption. Frozen candidate sources and original inputs are
hashed before and after execution. All 14,336 numerical rows per profile,
384 source-line identities and every unique-physics basis evaluation are
retained for read-only arithmetic review.
