# Initial-law migration research stage — HOLD

`migration.py` adapts an original reconstructed law to the frozen joint-flow
solver's input. It does not change the solver, train a model, or certify a
filtered trajectory. The original coefficients remain untouched.

```python
basis = MigrationBasis(
    old_endpoint, old_active_cells, old_tail_rate, delay, old_phase_cells,
    spatial.endpoint, spatial.intervals, actual_nodes=tuple(spatial.nodes),
)
lift = basis.lift()  # cache only for this identical complete basis
law = migrate(basis, probability, signed_content, identity="visit-identity", lift=lift)
active, content, phase = law.solve_inputs()
```

Every uniform source cell is integrated analytically against the piecewise
linear hat functions of the **actual** target nodes. Positions below the first
interior node `x1` map to `x1`; positions beyond the target endpoint map to the
upper escape coordinate. There is no lower-boundary atom or immediate hit.
For positions at least `x1` and below the upper endpoint, nodal rounding is
nonnegative and preserves the mean. An initial uniform cell `[0,w]`, with
`x1 <= w`, acquires mean shift `x1²/(2w)`. This shift cannot be avoided by a
nonnegative distribution on nodes whose minimum is `x1` when the source mean
is smaller than `x1`. It is an approximation, not a claim of exact-law rollout.

The exponential tail is retained. Its density times each actual linear hat is
integrated with 80-digit decimal arithmetic. The part beyond `L` has mass
`exp(-rate*(L-old_endpoint))` and is mapped to the explicitly nonreturning
upper coordinate. Its expected overshoot is that mass divided by the rate.
The upper coordinate also receives the below-`L` part of its last hat; these
two contributions must not be confused. The tiny decimal row-closure
remainder is reported and assigned to the upper coordinate, giving an exactly
unit-sum rationalized lift row. It does not alter or normalize the old input
coefficients. Changing to an upper escape model is a declared truncation,
not a returning-tail equivalence.

Uniform remaining-time cells become exact-support rational `Packet`s, using
the same probability and signed content totals. The spatial probability and
every signed mark use the same linear map. Exact conservation assertions
refer to the decimal round-trip rationalization of supplied finite input
scalars. Conversion to FP64 is a separate, measured step; no bitwise FP64
sum equality is claimed. The report includes a conservative Wasserstein-1
bound from nodal rounding, lower folding and upper overshoot. The maximum
target cell width makes this bound deliberately coarse on graded grids.

The nine tests cover ordinary and graded 256/512-node lifts, exact totals,
signed marks, mean preservation away from the lower fold, nonzero retained
tail, exact phase support, changed-node cache rejection and invalid inputs.
Original source hashes, test streams, exit, wall/CPU and peak RSS are retained
in the accompanying execution record. These are adapter tests. They do not
establish first-hit/renewal accuracy, rare-tail relative accuracy, autograd,
full training-domain state transport, energy savings or production adoption.
