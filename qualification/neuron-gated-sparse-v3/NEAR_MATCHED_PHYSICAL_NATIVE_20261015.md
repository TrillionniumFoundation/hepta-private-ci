# Eight physically trained near-matched Hepta Adapter/Cell experiments

**Research only · Draft · DENY_ALL · NO_MODEL_PROMOTION · NO_MAIN_MERGE.**

This child of the frozen #2361 geometry proof implements an **executable
physical-weight path**, not an architectural winner and not production readiness.
The original V1 journal/selected weights, Agentd Worker, CNS, Final-use, generation
fence and data-authority boundaries are unchanged.

## Actual scope

All eight research models use the same 32D synthetic Q24 input feature ABI.
They allocate an independent *trainable* dense 32→h F32 Adapter, the original
temporal surrogate (V2/V3/Diagonal SSM/low-rank minGRU), private F32 binary
Head, and a physically resident h-dimensional I64 Q24 identity projection.
No padding tensors or claims based on budget labels are permitted.

| Budget | V2 (h; scalars) | V3 | Diagonal SSM | minGRU |
|---:|---|---|---|---|
| 2,048 | 58; 2,031 | 53; 2,015 | 55; 2,036 | 45, rank 2; 2,026 |
| 8,192 | 234; 8,191 | 215; 8,171 | 221; 8,178 | 182, rank 2; 8,191 |

The 16K/64K/256K nominal bands remain **structurally impossible with the
declared bounded operators**. The Rust CLI rejects those tiers and any h/rank
combination outside the eight registered physical realizations.

## Reproducible study with Rust 1.95 and CPU PyTorch

Start at repository root; install the pinned CPU PyTorch and safetensors
versions from the new workflow. Then run:

~~~sh
python qualification/neuron-gated-sparse-v3/near_matched_physical_fixture.py \
  --output-dir /tmp/hepta-near-match-input \
  --receipt /tmp/hepta-near-match-fixture.json

DATA_SHA="$(sha256sum /tmp/hepta-near-match-input/train.json | awk '{print $1}')"
python qualification/neuron-gated-sparse-v3/near_matched_physical_train.py \
  --train-data /tmp/hepta-near-match-input/train.json \
  --train-sha256 "$DATA_SHA" --output /tmp/hepta-near-match-models \
  --synthetic-canary --steps 8

cd codex-rs
cargo fmt -p codex-hepta-neuron -- --check
cargo test --locked -p codex-hepta-neuron --all-targets
cargo clippy --locked -p codex-hepta-neuron --all-targets -- -D warnings
cargo build --locked -p codex-hepta-neuron --bin neuron_near_matched_q24_shadow
cd ..

BINARY="codex-rs/target/debug/neuron_near_matched_q24_shadow"
BIN_SHA="$(sha256sum "$BINARY" | awk '{print $1}')"
TRACE_SHA="$(sha256sum /tmp/hepta-near-match-input/trace.json | awk '{print $1}')"
python qualification/neuron-gated-sparse-v3/near_matched_physical_native_oracle.py \
  --binary "$BINARY" --binary-sha256 "$BIN_SHA" \
  --trained-root /tmp/hepta-near-match-models \
  --trace /tmp/hepta-near-match-input/trace.json --trace-sha256 "$TRACE_SHA" \
  --output /tmp/hepta-near-match-review.json
~~~

The actual actions run the same steps on a fresh Ubuntu host and retain sanitized
JSON reports only. The original shadow workflow also registers the new
physical research job, so the new Action's default-branch registration state
cannot silently omit all verification.

### What a complete native receipt would demonstrate

1. Eight true safetensors file creations/reloads with all shape, dtype, exact
   physical parameter counts and cryptographic hashes checked.
2. Sixteen fresh, independent **OS processes**, each invoking actual Rust
   signed-Q24 affine projection, the original deterministic Q24 temporal kernel
   and quantized Q24 binary Head.
3. Exact input/weight identity and per-event matching **independent Python
   integer** Adapter projection and Head logit, with identical two-process
   native checkpoint chains. Neither native nor Python can grant authority.

### What even a green dedicated workflow would NOT demonstrate

The shared Encoder is **not physically invoked**; training labels are synthetic.
The Torch F32 surrogate and the native temporal Q24 model are not independently
full-forward equivalent. Parameter *counts* within 2% do not imply equal
training FLOPs, model residency or task utility. There is no original selected
A0 no-change verification, signed original Control/CNS receipt, future-window
NDU, negative-transfer measurement, calibrated OOD/abstention, independent
device signing, 64/256/1024/4096 target-host request load, WAL/recovery or
final-use authorization.

**Passing the mechanism test never changes the selected V1 Cell.**

## Exact-source qualification

The current development environment has CPU PyTorch/safetensors and previously
exercised an independent eight-file research training prototype, but lacks
rustc/Cargo. Do not mislabel local synthetic Python tests, source writeback or
queued GitHub Actions as a passing exact-source native execution.

Observed Actions configuration initially failed before any job due to
runner.temp being referenced at job-level env. It was repaired by resolving
the runner temporary directory inside an actual step. The latest exact-HEAD
CI run, not the earlier invalid workflow, is controlling.
