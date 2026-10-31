# Restore and run the qualified native policy after cloning

The bundled executables are for **Linux x86-64** (`x86_64-unknown-linux-gnu`).
Restoration requires Python 3.11+ and the checked-out Rust source files; it does
not require the original scratch directory, Rust compiler, or cached `.rlib`
paths. Running the Python qualification also requires the experiment's existing
NumPy, SciPy and PyTorch environment.

Run the following from the repository root. Each output directory must be new;
the tools deliberately refuse to overwrite existing evidence.

## 1. Restore the exact qualified executables

```bash
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.native.restore \
  --bundle experiments/analytic_event_neuron/round8_contract_closure_20261031/evidence/native_binary_bundle \
  --output /tmp/hepta-r7-native-restored
```

This verifies the three binary archive parts, the reassembled gzip SHA256,
inventory parts, every member size/SHA256, and the cloned Rust sources. It then
extracts only ordinary verified files into a new private directory and sets the
two native executables to mode `0755`. Symlinks, hard links, traversal paths,
duplicate members, inconsistent sizes and excessive archive sizes are rejected.
No tar-provided executable permission or arbitrary absolute path is trusted.

The restored files include:

- `/tmp/hepta-r7-native-restored/executables/r7-native-policy`
- `/tmp/hepta-r7-native-restored/executables/r7-native-policy-tests`
- `/tmp/hepta-r7-native-restored/build/BUILD_ATTEMPT03.json`: the **unchanged**
  historical source build receipt.
- `/tmp/hepta-r7-native-restored/RESTORED_BUILD_RECEIPT.json`: a new, explicitly
  path-rebased reference receipt. It retains the original binary/source hashes
  and binds the original receipt's SHA256, while updating the two executable
  paths. Historical commands remain labelled as historical; this is **not a
  fresh build**.

## 2. Run one short native smoke

This executes one real native model-port decision and closes its owner; it does
not run the full 480-rollout qualification.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python - <<'PY'
from experiments.analytic_event_neuron.round7.task import generate_episode, initial_state
from experiments.analytic_event_neuron.round8_contract_closure_20261031.native_policy import NativePolicy

with NativePolicy(
    "experiments/analytic_event_neuron/round7/evidence/fits_primary/first_passage_none_11.json",
    binary="/tmp/hepta-r7-native-restored/executables/r7-native-policy",
    owner_dir="/tmp/hepta-r7-native-restored/smoke-owner",
    seed=44, head=1, deployment="mean",
) as policy:
    action, prediction = policy.act(initial_state(generate_episode(314)))
    print({"action": action, "q": prediction["q"],
           "native_checkpoint": prediction["native_receipt"]["native_checkpoint"]})
PY
```

## 3. Re-run the complete native qualification when needed

The explicit rebased receipt works with the unchanged qualification entry point.
The frozen model JSON files must be present in their repository paths. The
qualified kernel remains `r7-finite-v1`; restoration does not install the
independent Brownian research kernel.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.analytic_event_neuron.round8_contract_closure_20261031.native_validation \
  --binary /tmp/hepta-r7-native-restored/executables/r7-native-policy \
  --build-report /tmp/hepta-r7-native-restored/RESTORED_BUILD_RECEIPT.json \
  --output /tmp/hepta-r7-native-new-qualification
```

To run the original `just test`/nextest entry point against the restored test
executable, use `native/workflow.py test` with the same rebased `--build-report`
and a new workflow directory. That operation needs `just`, `cargo-nextest` and
the specified Rust toolchain, but does not rebuild the native application.

For numerical semantics, acknowledged recovery limits, complete cost accounting
and the measured persistent-broker optimization, see `../NATIVE_CONTRACT.md`.
