# Arm-isolated model residency: Hepta Neuron Q24 synthetic A/B study

**Status: research-only, non-authorizing, inherited from Draft PR #1823.**

## What is being fixed?

The earlier five-arm native probe was running **one requested arm** per
process but constructing and retaining **all five arm configs and both
legacy/prepared variants**, even when unused. Linux `VmHWM` measures the
peak memory of the *whole process*, so its reported RSS was contaminated
by unneeded model graphs and by construction-time allocation peaks.
Previous native timing and Checkpoint receipts remain useful synthetic
mechanism evidence, but previous reported process RSS **cannot** be
interpreted as each chosen model's own resident memory.

## What this branch changes

- Use a mutually exclusive Rust `Configs` enum with nine choices:
  V1 and separate legacy/prepared modes for V2, V3, SSM and minGRU.
  Each process builds exactly one selected enum variant.
- Do not construct or free unused V1/V2/V3/SSM/minGRU model configs.
  Do not preconstruct legacy and prepared together. V1's legacy and
  prepared probes are intentionally the **same unchanged V1 mechanism**.
- Build all needed immutable model-owned edge vectors once, *before*
  the timed Tick loop, and record `model_config_setup_micros`.
- Preserve the selected model/normalizer/generation digests,
  identical frozen fixture Q24 weights, independent per-Cell state and
  exact previous Checkpoint frontier computation.
- The native receipt must declare `single_selected_config_resident=true`
  and `simultaneous_legacy_and_prepared_config_resident=false`.
  The A/B verifier fail-closes if either invariant is missing/false.
- A/B runner hashes the executable and input trace both **before and
  after** 40 isolated processes; changing bytes reject without a
  fabricated successful performance report.
- Retain all 40 raw receipts, local receipt digests, trace/binary SHA,
  and derived ratios, then reproduce them with the independent structural
  verifier. This is NOT signed target-host evidence.

## Acceptance and limitations

The fixture CI must complete 20 pairs = 40 fresh processes across
5 mechanisms and 64, 256, 1,024 and 4,096 logical Cells. Each pair
must match exactly on the frontier digest. V1 remains unchanged.
Source tests reject mode/config mismatches, unknown arms, altered
binary/trace bytes, forged memory-residency flags, cross-generation
checkpoints and other invalid inputs.

Measure, but do not prejudge, the latency / throughput / RSS tradeoff.
The synthetic kernel creates one shared model per process and
independent logical Cell checkpoints. **It is not a full inference
service**: the measured Linux peak RSS still includes the Rust process,
allocator, event inputs, transient buffers, code pages and checkpoint
memory, not just private model weights. Model preparation is outside
the per-Tick p99 but its wall duration is reported separately.
A 40-process single-host study is neither a statistical confidence
interval nor an independently attested target host, and cannot prove
microbatching, trained model quality, actual shared Encoder residency,
production WAL/CAS, recovery or future-window NDU uplift.

This follow-on must stay Draft until #1765, #1803, #1823 and this
branch pass their exact-source focused tests and the independent
production prerequisites are satisfied. It never changes V1 journals,
`main`, production routes, selected artifacts, a live Cell split or
any final-use authority.
