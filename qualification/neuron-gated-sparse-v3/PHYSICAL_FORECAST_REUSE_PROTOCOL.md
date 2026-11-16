# A3: deduplicate physical candidates before forecasting

Research-only; stacked on Draft PR #2032 / #2019 / #1979 / #1884.
Neither selected V1, Cell Owner, checkpoint, CAS, CNS nor final-use
authorization may be modified or promoted from this research.

## Execution

The physical_tensor_identity.py shared helper hashes the exact named
safetensors tensor values, shapes and dtypes. It ignores descriptive
serialization metadata but always rechecks each pinned physical file SHA.
Model alias groups are scoped to **arm/kernel + canonical tensor digest**.
Different arms never share computations.

The pre-outcome, label-free precommit_future.seal now checks all twenty
physical model files, materializes the lowest-cap member of each unique
group, executes that group's Torch surrogate once per input source
sequence group, and fans the exact same case probabilities out to the
original twenty (cap,arm) labels. After computing scores, it independently
rehashes every physical candidate and its canonical tensor fingerprint.
Any changed physical model aborts sealing. No future outcome file is
opened by the sealing command.

The existing forecast-seal.v2 retains all original model and case keys
for backward signed-review compatibility. Its additive
physical_tensor_reuse_observation, version forecast-physical-reuse.v2,
records nominal candidate slots, distinct models per source sequence
group, total source sequence groups, total actual surrogate model
forward calls, avoided duplicate forwards, avoided model graph loads,
and a deterministic list of tensor-identified aliases. It always
records native_q24_parity_verified=false, ndu_eligible=false and
production_qualification=false.

**Synthetic 16-channel case:** 20 nominal file slots, four unique
models and six independent input source groups produce
4*6=24 actual surrogate forward invocations, not four total.
(20-4)*6=96 repeated forward invocations and 16 model graph loads
are avoided. This is only an illustrative synthetic research execution,
not measured production Encoder throughput or RSS.

## Independent signer and future review

The dedup_prospective_gate.py signed reviewer recomputes every
physically pinned alias group, checks identical case predictions and
future/OOD metrics for repeated tensors, and validates the additive
pre-outcome execution/alias claim against the actual physical bytes.
A forged total, grouping or production authority bit fails closed.
Legacy v2 seals that lack this additive field retain research-only
compatibility; missing reuse metadata cannot be called reuse evidence.

The selected V1 baseline remains independently supplied and untrained.
This study does not establish true target-host time, future NDU,
native Rust equivalence, probability calibration, Cell split, effects
or production model superiority. Distinct physical models do not
automatically make private-parameter budgets fair.

## Test and qualification

Run the actual-byte, synthetic future-feature and no-authority
negative suites:

    python -m unittest discover \
      -s qualification/neuron-gated-sparse-v3 \
      -p test_physical_forecast_cache_gate.py -v
    python -m unittest discover \
      -s qualification/neuron-gated-sparse-v3 \
      -p test_dedup_prospective_gate.py -v

Only the pinned physical CPU job may claim the Torch/safetensors
tests executed; the A0-only job may explicitly skip them.
Native Cargo/rustfmt/strict Clippy and forty separate Q24 subprocess
replays must pass at this exact source SHA before even considering
physical native inference parity. Future/heldout/OOD NDU, negative
transfer, A0 selected Owner and A4 64/256/1024/4096 target-host
full-request measurements remain BLOCKED.

NO_PROMOTION / NO_PRODUCTION_CUTOVER.
