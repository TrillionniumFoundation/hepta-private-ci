# Signed uniformization output interval — HOLD

This separately frozen candidate closes one narrow arithmetic gap above
[#6327](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6327):
for a finite Metzler generator whose uniformized transition is substochastic,
it proves an exact rational enclosure of each output from a signed binary64
input vector and certifies a binary64 result only when both enclosure endpoints
round to the same value.

The proof propagates the signed partial Poisson series directly. The omitted
signed remainder is bounded by the exact input total variation multiplied by a
positive geometric tail majorant. Multiplication by the independently enclosed
positive exponential uses all four endpoint products, so intervals crossing
zero remain valid.

## Frozen small controls

- generator: two-state absorption, `[-1, 1; 0, 0]`
- duration: binary64 `0.5`
- signed vectors: `(1, -0.25)` and `(-1, 0.25)`
- highest included Poisson index: 15 for both signed controls
- positive outputs: `3fe368b2fc6f960a`, `3fc25d340e41a7d8`
- negative outputs: `bfe368b2fc6f960a`, `bfc25d340e41a7d8`
- maximum interval width:
  `1575960260693827269121 / 1113144144521982925822806448411628911296`

Normal and optimized-mode tests each execute the two successful signed fixture
proofs. Rejection tests do not count as successful proof executions.

## Explicit boundary

This stage does not load an authentic N256 input, run a current-state packet,
execute a dynamic/model/Torch/optimizer/training workload, or qualify the
18,225,028-visit provider. It does not support non-substochastic augmented
channels, arbitrary history, migration, second-cycle feedback, full-network
training, task benefit, or production adoption.

Historical RED and UNKNOWN records remain unchanged. Global status remains
`HOLD / NoUpdate / all_closed=false`.
