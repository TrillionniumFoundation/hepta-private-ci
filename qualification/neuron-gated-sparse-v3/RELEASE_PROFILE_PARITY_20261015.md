# Release-profile Q24 Cell mechanism control (research only)

**Status:** DRAFT · SHADOW_ONLY · DENY_ALL · no model selection, main merge,
model install, CNS route change or Cell split.

## Why this exists

The historic native 5-arm × 4-scale matrix used the debug build
(target/debug/neuron_shadow_mechanism_probe). Reporting its p99/RSS
numbers as optimized deployment costs would be misleading. This additive
experiment preserves the historic debug path and runs a second exact-source
Cargo release binary over the **same frozen 32D Q24 trace**, 8 events/Cell,
64/256/1024/4096 logical Cells and the five unchanged, **untrained**,
synthetic mechanisms (V1/V2/V3/Diagonal SSM/low-rank minGRU).

The original five nominal parameter ceilings are **not** physically
equal-size model comparisons; see FIVE_TIER_GEOMETRY_PREFLIGHT_20261015.md.
Do not conflate the 20 mechanism-only runs with 20 trained model weights.

## Executable source-bound steps

Run in codex-rs with Rust 1.95.0 and the checked-in Cargo.lock:

~~~sh
cargo test --locked -p codex-hepta-neuron --all-targets
cargo clippy --locked -p codex-hepta-neuron --all-targets -- -D warnings
cargo build --locked -p codex-hepta-neuron --bin neuron_shadow_mechanism_probe
cargo build --locked --release -p codex-hepta-neuron --bin neuron_shadow_mechanism_probe

python3 ../qualification/neuron-gated-sparse-v3/run_shadow_probe_matrix.py \
  --binary target/debug/neuron_shadow_mechanism_probe \
  --trace ../qualification/neuron-gated-sparse-v3/fixture_q24_trace.json \
  --report /tmp/debug-q24-fixture.json
python3 ../qualification/neuron-gated-sparse-v3/run_shadow_probe_matrix.py \
  --binary target/release/neuron_shadow_mechanism_probe \
  --trace ../qualification/neuron-gated-sparse-v3/fixture_q24_trace.json \
  --report /tmp/release-q24-fixture.json
python3 ../qualification/neuron-gated-sparse-v3/verify_build_profile_parity.py \
  --debug-matrix /tmp/debug-q24-fixture.json \
  --release-matrix /tmp/release-q24-fixture.json \
  --output /tmp/new-parity-report.json
~~~

The existing Actions workflow runs these commands on one CI run and
archives the debug matrix/cost, release matrix/cost and an independent
20-pair parity report. The source CI command builds --release; the Rust
binary separately emits its compiler_debug_assertions_enabled boolean.
The reviewer requires true for each DEBUG probe and false for each RELEASE
probe. **This flag is not cryptographic attestation of optimizer flags**:
inspect the actual job log for the exact command, source SHA and artifacts.
No meaningful results are inferred from queued or skipped jobs.

Every paired arm/Cell result must match the trace digest, event count,
width, temporal parameter count and **exact Q24 checkpoint frontier digest**,
while recording both p99/RSS/throughput values. Faster but state-divergent
Release output fails. The independent JSON reader rejects duplicate keys,
nonfinite numbers, symlinks, oversized artifacts, mutated inodes and
output overwrites. The unit tests are synthetic protocol checks, not proof
of actual Rust release execution.

## Remaining blocking evidence

None of these fixtures load real shared Encoder weights or learned Heads,
train a Cell, execute production worker queues, perform Artifact CAS/
Final-use/CNS/WAL, certify power-loss recovery or demonstrate future-window
NDU. Compiler profile parity and faster p99 do not establish learning.
Full-model realized size, authenticated E0 no-change, fair real tasks and
four-scale target-host lifecycle are separate gates.

**Every output says NO_MODEL_PROMOTION; NDU and production remain false.**
