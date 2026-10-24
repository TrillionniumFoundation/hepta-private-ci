# Bounded generation execution through the existing worker

`GenerationDriver` implements the existing `ModelDriver` interface. It executes
the actual frozen v6 neural model through `InferenceWorker::run`; it does not
turn an earlier experiment row into an execution receipt. Its CPU subprocess
is a model backend, not another inference owner, authority issuer, artifact
selector, or daemon service.

The trusted host supplies one immutable `GenerationRegistrationV1` before
constructing the worker. The registration fixes the Python executable, source
root, checkpoint directory and basename, model identity, complete model pins,
and timeout. A request cannot select a path, executable, shell command, model
checkpoint, or output location. This is a POSIX research backend; the Python
implementation uses the platform's process resource measurements.

## Exact scope and identities

The `hepta-infer-core` generation contract admits one public observation:
56×28 pixels and a same-sized missingness mask, eight public tokens, a latent
noise seed, the content-control flag, and at most eight named neural actions.
It accepts only the implemented text+image output set. Unknown fields,
unimplemented modalities, nonfinite values, foreign pins and malformed shapes
reject. The wire preserves float32 bit patterns; it does not reinterpret these
latent values as Neuron's Q24 feature contract.

The decoder emits eight token positions, including BOS, even when rendering
stops at an earlier EOS. Both request and reservation token limits must cover
all eight before any process invocation or cached observation is returned.

The registration separately binds:

- Serialized checkpoint bytes, frozen snapshot identity and configuration.
- Actual tensor parameters. Controlled snapshots use a domain-separated
  composition of the base and gate parameter hashes; their semantic snapshot
  identity remains a different field.
- `conditioned.py`, `data.py`, `neural.py`, `observer.py`, `owner_worker.py`, and
  `plan_training.py`. The source digest includes each name and file hash.
- Python executable bytes, Python/Torch/NumPy/Pillow versions, and the reported
  CPU platform tuple. These local identities are not remote attestation or
  proof of unique hardware identity.

The backend uses the registered checkpoint loaders with the expected file hash.
The subprocess runs in Python isolated mode and reads source instead of an
ignored source-tree bytecode cache. Source/checkpoint/runtime pins are checked
before invocation and after successful execution. These checks establish local
custody under the registered host; hashes alone do not authenticate a principal.

Every successful result contains the actual latent states, backend state keys,
plan identity, raw emitted token IDs, rendered UTF-8 caption and PNG bytes.
State zero is after encoder/initial-plan execution; subsequent states correspond
to the explicitly requested actions. Caption rendering and 8-bit PNG encoding
use the same emitted outputs as v6. No target labels, observer scores, training,
caption repair, or image permutation enter this execution path. The Rust
contract also verifies preserved state components for modality-only actions.

## Measurements, failures and retries

This deliberately cold-starts the model for each new request. `load` validates
the registration; it does not claim a resident model process. The retained
subprocess wall time includes process creation, imports and model loading; it
does not include all outer owner/journal work. The child records its own timed
execution and peak RSS. These are measured units, not FLOPs or energy estimates.

Capture is bounded to 256 KiB stdout and 16 KiB stderr, with explicit truncation
flags, and the host timeout is at most 60 seconds. The process record retains
request/model pins, exit code, diagnostics and raw captured bytes even on
failure. Nonzero child exit is failed execution; timeout, failed process start,
or invalid successful output is indeterminate. Missing RSS on a failed process
is not a measured zero, even though the older worker field requires a numeric
placeholder. Exact in-process retries reuse the same retained process evidence.

The integration test invokes the real `DurableInferenceControl` lifecycle:
submit, reserve, assign, worker execution, settle, exact retry and journal
recovery. Its authority is explicitly supplied by the isolated test fixture.
All generation evidence remains `deny_all`. The test retains process records
and owner journals in unique `owner-evidence-*` directories under its fixture
root, including failed and timed-out cases.

## Verification and remaining engineering gates

Prepare fixtures using the repository's pinned Python environment:

```sh
python -B -m experiments.multimodal_output_portfolio.v6.owner_worker_tests --prepare-fixture /absolute/fixture-root
HEPTA_GENERATION_TEST_FIXTURE=/absolute/fixture-root/fixture.json \
  just test --locked -p codex-hepta-infer-worker-host --test generation_owner_execution --run-ignored only --test-threads 1
```

Run `just` from `codex-rs`. The explicit integration target is ignored by generic
test runs because it requires the prepared Python/Torch fixture. Five separate
cases cover legacy, conditioned and controlled model execution, loader failure
and timeout, within the normal per-test timeout. CI runs them explicitly and
retains the complete fixture/evidence directory. The initialized
tiny models prove execution and custody mechanics, not trained-model efficacy.

This driver does not implement `NeuronFeatureDriver`, calibrated intuition,
online NDU policy selection, authenticated learning-ledger admission, or Agentd
startup activation. Those gates require an explicit bounded latent projection
and prediction profile, real calibration/OOD artifacts, current selected-model
and authority wiring, and durable production evidence ownership. No missing
calibration or authority is replaced by a fixture success value.
