# N256: complete multistep state with event-time reset

**Execution completed:** the single precommitted study and independent reader
passed. See [RESULTS.md](RESULTS.md) for all actual values, costs and unchanged
limits. The specification below is retained as the pre-execution record.

This is a new finite-model successor to the unexecuted v3 sparse full-roster
candidate. It preserves the published #6742 sparse/dense bitwise failure and
does not invoke the protected original full-roster entry point. The new source,
runtime, costs and numerical criteria have separate identities.

## Three concrete repairs

1. `_extended` passed a tuple of row values to `scipy.sparse.csr_matrix`. SciPy
   interprets a tuple as a sparse constructor specification. The new code passes
   a nested row list. A synthetic control retains the original exception.
2. The original occupation selector used `selectors[1:, 1] = 1`. A parent prefix
   contains a realization of a release signal, not the active cell mass. The
   selector must exclude *all* parent coordinates and include every active node
   and the permanent upper-escape coordinate. With no parent, the old code also
   missed the first active node. Independent scalar integration exposes both.
3. The original packet lacked the target reset law at emission time. If reset
   parameters changed before delayed release, past events were routed using the
   new reset. Each new packet carries its own immutable reset tuple; fragments
   retain it. The wire state persists that tuple and preserves numerical packet
   order. An explicit future-reset mutation control demonstrates the distinction.

The legacy occupation/reset counterexamples apply only the constructor repair
in memory, so the two subsequent defects can actually execute. No legacy source
file is modified. `DEVELOPMENT.json` separates these exposed developer controls
from the forthcoming precommitted scientific run, including the first real
failure and its incomplete process-cost observations.

## Complete state and its finite scope

The candidate propagates five channels: probability and four independent signed
contents. Its two active generations, three permanent upper-escape coordinates,
two cumulative hit/discounted-hit channels and three occupation channels retain
the original 2,600 state coordinates. Waiting releases are exact exponential
signal packets under fixed interval physics, with deterministic delay `0.2`.
This bounded two-generation implementation rejects an interval ending at or
after `0.4`; third and later active generations are not silently dropped.

For a packet with realization `(alpha, G, output)`, its release signal is
`alpha exp(G s) output`. The parent realization is retained in an augmented
linear system to drive the active finite CTMC. It is excluded from active
occupation. Probability and signed content use the same linear propagation.
Lower-hit signals create delayed packets with event-time reset snapshots;
upper escape is permanently active and cannot return.

The original 14 warm/coarse/cold snapshots contain 18,225,028 base coordinates.
Persisting all 185 packet reset snapshots adds 47,175 coordinates. Saving current
nodes and reset adds 512 per capsule, or 7,168. The new complete denominator is
**18,279,371**, not the original denominator. Maximum packet generator order is
511, maximum augmented action order 514, maximum packet count 22 and the wire
cap is 32 MiB per capsule. Sparse computation does not imply sparse wire storage:
the canonical wire retains every dense generator coordinate.

## Frozen execution and independent checks

`REQUEST.json` and `SOURCE_FREEZE.json` bind the exact new source and local
runtime. No authentic N256 propagation has occurred at this source-only stage.
The runner creates a unique output directory and refuses to overwrite it. Each
lane is a new interpreter with one numerical thread, CPU affinity 8 and a 4 GiB
address-space limit applied before `exec`. It checks at least 4 GiB of current
MemAvailable. Local ancestor cgroup limits are not exposed; their absence is
recorded and is not represented as the original allocation or custody contract.
The scientific lanes are sequential, each capped at 600 seconds. No benchmark
speedup, energy or GPU conclusion is intended.

The planned run includes:

- The original eight warm queries through `0.36` and the three coarse queries.
- A genuinely fresh process loading the saved `0.201` complete state and
  continuing to `0.28` and `0.36`, without loading original initial-state data.
- Twenty-two independent remaining-packet integrals at the warm final state to
  check complete probability and signed-content balance.
- A separate method-of-steps BDF reference at two tolerances. It assembles the
  generator independently and evolves active probability/content, escape, hit,
  discounted hit and occupation directly. It never uses packet realizations.
- A separate reader that visits all saved tensor coordinates, verifies the old
  topology and new denominator, requires exact warm/cold canonical bytes, and
  checks the declared finite-model comparisons.

The new finite-model criteria are absolute `5e-10` for warm/coarse state
composition, `1e-8` for the independent BDF state/reference stability and `1e-9`
for complete signed/probability balance. They are frozen before this new run.
They do **not** replace the original sparse/dense bitwise requirement, which
remains RED. BDF comparison checks this finite CTMC; it does not establish the
continuous diffusion limit, rare relative-tail accuracy or full-network AD.

All process starts, stdout/stderr, full child wall/CPU/RSS costs, failure statuses,
full capsules, BDF meshes and values are retained. The reader executes no model
or optimizer. Research status remains `all_closed=false` until the other
scientific, training and task-benefit requirements have actual evidence.
