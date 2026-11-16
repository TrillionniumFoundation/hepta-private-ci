# First-feedback hit-delay-reset interval — HOLD

This separately frozen candidate stacks on
[#6331](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6331).
It closes one narrow method-of-steps gap on a small finite fixture: the same
CTMC active state produces the actual lower-hit flux during the first segment;
after one deterministic delay, that flux drives the active reset source and an
explicit returned accumulator during the second segment.

The full interval state tracks current active, delayed driver, nonreturning
upper, cumulative lower hit, occupation, returned lower hit, and pending lower
hit. Positive, signed-mirror, and zero-delay fixtures must uniquely round every
final output.

## Explicit boundary

This covers exactly two delay-length segments and the first feedback. It does
not cover a third cycle, arbitrary histories, a general DDE solver, or the
full state domain. It does not load N256, execute a current-state dynamic,
model, Torch, optimizer, or training workload, or qualify the 18,225,028-visit
provider. It does not prove migration, adaptive-DDE backward, full-network task
benefit, or production adoption.

Historical RED and UNKNOWN records remain unchanged. Global status remains
`HOLD / NoUpdate / all_closed=false`.
