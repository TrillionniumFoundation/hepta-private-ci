# Repeated 5 × 4 Q24 A/B Mechanism Study — Research Only

This is a **downstream Draft-only** qualification of the arm-isolated
resident model experiment (#1837). It does not change V1 journal/wire, a
selected production Cell, training, NDU final-use, routing or `main`.

## Strict motivation

The original 40-process A/B study gives **one** legacy/prepared pair for
each of 5 mechanisms and 4 Cell counts (64, 256, 1,024, 4,096).
At 4,096 synthetic Cells, its per-Tick p99 favored prepared
V2/V3/SSM/minGRU, but one pair is insufficient to claim a consistent
benefit or a statistically certified production p99 target.

The arm-isolated runner now loads **exactly one** selected model and
mode per fresh process, with model preparation cost reported separately
from hot Tick cost. The repeated runner builds on that, instead of
comparing results from unrelated earlier CI machines.

## Execution protocol

Run the same compiled Rust binary, pinned input file, all registered
arm/scale combinations, **three** separate repetitions (optional
preregistered five). Each repetition:
- hashes the executable and Q24 Trace both before and after the 40
  fresh subprocesses, rejecting any mutable bytes;
- alternates whether legacy or prepared runs first per arm and Cell
  scale; additionally swaps the order between successive rounds;
- retains all original 40 process JSON receipts and their locally
  computed hashes, verifies 20 exact checkpoint-frontier pairs, and
  independently recomputes the receipt-derived ratios;
- rejects any changed model binary hash, source input hash, or
  unexpected arm/scale/count, even if reported latency looks better;
- verifies the **same checkpoint frontier across repetitions** for
  each arm/scale; different frontiers fail closed.

Thus three rounds = **120 fresh subprocesses**, **60** paired
checkpoint comparisons and **120** raw child receipts retained.
The existing initial 40-process smoke runs separately in the same CI
job, so the job executes at least 160 synthetic child processes,
besides unit tests, if no step fails.

### Descriptive statistics

For each arm/scale, record the minimum, median and maximum of:
- exact legacy/prepared p99 ratio (above 1 = prepared faster);
- process peak RSS ratio (not model weight bytes);
- throughput ratio (above 1 = prepared higher throughput);
- observed unpaired p99 nanoseconds, setup microseconds, total wall
  microseconds and peak process RSS bytes.

`p99_prepared_faster_in_all_repeats` indicates the observed directional
outcome only. It does not grant any acceptance or promotion right.
These 3–5 measurements are **not** independent task outcomes and
cannot support a reliable 95% confidence interval, causal performance
claim, production SLA or power/energy estimate. The runner reports
**no fabricated confidence interval**.

## Local invocation

```sh
cd codex-rs
cargo test --locked -p codex-hepta-neuron --all-targets
cargo clippy --locked -p codex-hepta-neuron --all-targets -- -D warnings
cargo build --locked -p codex-hepta-neuron --bin neuron_shadow_mechanism_probe
python3 ../qualification/neuron-gated-sparse-v3/repeat_prepared_pair.py \
  --binary target/debug/neuron_shadow_mechanism_probe \
  --trace ../qualification/neuron-gated-sparse-v3/fixture_q24_trace.json \
  --repetitions 3 --report /out/repeated-q24-fixture.json
```

## Production blockers (unchanged)

Model preparation remains outside the timed Tick loop. Linux
`VmHWM` includes allocator, code, input, state/Checkpoint and OS
cost—not only the selected private model. The service's actual Encoder
+ Head, worker scheduling, microbatching, GPU, signature checking,
Artifact CAS, WAL, recovery, CNS route, selected Cell generation,
negative migration and independent future-window NDU remain
**unmeasured** by this synthetic fixture.

Strict production promotion needs a signed active A0 census,
real trained and reloaded 2K/8K/16K/64K/262K private Cell
weights, matched frozen Encoder / data / optimizer / tuning budget,
real future-label and OOD/Brier/ECE outcomes, independently verified
target host at 64/256/1,024/4,096 Cells and Selector/Executor final-use
authorization with generation-fenced migration and rollback.

**Permanent decision in this experiment: `NO_PROMOTION`.**
