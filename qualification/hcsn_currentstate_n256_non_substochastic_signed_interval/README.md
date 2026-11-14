# Non-substochastic signed output interval — HOLD

This separately frozen candidate closes one narrow arithmetic gap above
[#6328](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6328):
for a finite Metzler operator whose uniformized transition is nonnegative but
has a row sum above one, it proves an exact rational enclosure of each output
from a signed binary64 input vector. A binary64 result is emitted only when
both enclosure endpoints round to the same value.

The uniformization rate is the exact maximum of every diagonal loss and every
row's off-diagonal sum. The induced row-vector L1 bound is therefore the exact
maximum transition row sum. The omitted signed Poisson series is bounded by
the exact input total variation multiplied by a positive geometric majorant
with that norm growth included. Multiplication by the independently enclosed
positive exponential uses all four endpoint products.

## Frozen small controls

- operator: two-state finite Metzler fixture, `[-1, 2; 0, 0]`
- duration: binary64 `0.5`
- exact uniformization rate: `2`
- non-substochastic transition maximum row sum: `3/2`
- signed vectors: `(1, -0.25)` and `(-1, 0.25)`
- highest included Poisson index: `20` for both signed controls
- positive outputs: `3fe368b2fc6f960a`, `3fe12e9a0720d3ec`
- negative outputs: `bfe368b2fc6f960a`, `bfe12e9a0720d3ec`
- maximum interval width:
  `279663698773638873515681730647227 /`
  `2902208444147038002441321532090673874847861833728`

Normal and optimized-mode tests each execute the two successful signed fixture
proofs. Rejection tests do not count as successful proof executions.

## Explicit boundary

This is not an authentic augmented current-state channel. It does not load an
N256 input, run a packet or serializer, execute a dynamic/model/Torch/optimizer/
training workload, or qualify the 18,225,028-visit provider. It does not prove
arbitrary unbounded positive growth, arbitrary history, migration, second-cycle
feedback, adaptive-DDE backward, full-network training, task benefit, or
production adoption.

Historical RED and UNKNOWN records remain unchanged. Global status remains
`HOLD / NoUpdate / all_closed=false`.
