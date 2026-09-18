# `intuition.policy` fast-path benchmark qualification

## Scope

The fast-path gate measures the **authenticated qualified decision path**, not only the inner
argmax/assignment selector. Each timed operation therefore includes canonical scorer-output and assignment
binding, six qualification-envelope verifications, V2 complete-request binding, calibrated
policy gates and receipt construction.

The benchmark lives at `codex-rs/hepta-intuition/tests/fast_benchmark_gate.rs` and is executed in
release mode by `.github/workflows/hepta-intuition-policy.yml`.

## Method

For each candidate-set size `1`, `16`, `64` and `128`:

1. build a fully authenticated current-generation fixture;
2. perform 20 untimed warmup decisions;
3. run 400 timed qualified decisions;
4. clone input ownership before resetting measurement counters, so cloning is not charged to the
   policy operation;
5. record per-decision wall latency;
6. count allocations and allocated bytes performed by the decision call using the benchmark
   binary's isolated counting global allocator;
7. report p50, p95, p99, aggregate throughput, maximum allocations and maximum allocation bytes;
8. fail CI if any hard budget is exceeded.

The benchmark binary is separate from the library. `codex-hepta-intuition` itself remains
`#![forbid(unsafe_code)]`; the test-only allocator uses the standard `System` allocator with
explicit unsafe delegation solely to observe allocation counts.

## Hard budgets

| Candidates | p99 latency | Minimum throughput | Max allocations | Max allocated bytes |
|---:|---:|---:|---:|---:|
| 1 | 5 ms | 200 decisions/s | 64 | 64 KiB |
| 16 | 8 ms | 100 decisions/s | 96 | 192 KiB |
| 64 | 15 ms | 50 decisions/s | 160 | 512 KiB |
| 128 | 25 ms | 25 decisions/s | 240 | 1 MiB |

These are qualification ceilings, not target medians. CI also prints p50 and p95 so regressions
can be detected before the hard p99 ceiling is crossed.

## CI command

```bash
cargo test --locked --release --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-intuition --test fast_benchmark_gate -- --ignored --nocapture
```

A successful run emits one `FAST_BENCH` line per candidate count containing all measured values.
The benchmark is `#[ignore]` under ordinary debug `cargo test` and is explicitly enabled by the
qualification workflow.

## Interpretation

The gate is intended to catch algorithmic and allocation regressions in the bounded fast policy.
The largest supported request is 128 candidates, matching the crate bound. Because GitHub-hosted
runners are shared infrastructure, the latency ceilings deliberately include substantial headroom;
they should not be presented as a target-host real-time SLA.

A production release still requires target-host qualification. If a target host needs a tighter
SLA, its deployment profile should add a stricter benchmark while retaining these repository
ceilings as the baseline regression gate.

## Regression policy

A budget may be changed only with all of the following in the same change:

- benchmark evidence from exact-head code;
- explanation of the algorithmic/allocation change;
- updated `FAST_BENCHMARK.md` values;
- review of the 128-candidate worst case;
- no weakening of candidate completeness, artifact authentication or slow-path semantics to buy
  latency.

Performance is subordinate to qualification correctness. A fast result produced from an
unauthenticated profile, incomplete candidate set or unqualified score batch is not a valid fast
path.
