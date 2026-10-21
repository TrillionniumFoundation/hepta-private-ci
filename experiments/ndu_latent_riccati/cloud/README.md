# Dedicated execution route

`DISCOVERY.json` contains a read-only observation of the existing project route.
The declared route is the `trillionnium-android-gpu` runner group with
`self-hosted`, `linux`, and `x64` labels; existing workflows additionally require
the assigned runner name to be `desktop`. This declaration is not evidence that
the runner is the user's intended cloud environment or that it executed a job.

At the recorded observation, both the previous experiment run `39589317563`
and the trusted `main`-branch availability probe `39526325715` were queued with
`runner_id=0` and no steps. The exact scheduling cause is unavailable. The
accessible connector does not expose runner administration, and no separately
verified project SSH or cloud execution entry was found. No new probe, external
job, scheduler change, or cancellation was made during this discovery.

## Concrete workflow recommendation

`launch.py` implements the guarded execution path. `ndu-latent-riccati.yml` is a
workflow template for `.github/workflows/ndu-latent-riccati.yml`; its location in
this directory does not activate it. The registered request must contain
`protocol_sha256` matching the bytes of the experiment's `protocol.json`.
The launcher invokes `run_experiment.py --output ABS --execution-tier
dedicated-cloud`; the main entry point is responsible for the oracle and audit.

Use a separate experiment workflow on the registered research branch, triggered
only by an explicit run request after source and protocol publication. Reuse the
existing declared runner selector; changing the selector cannot establish the
identity of the intended environment. Do not enable a generic hosted fallback.

The workflow should execute these steps in order:

1. Record the actual runner assignment and verify the expected repository,
   branch, event, runner name, environment, OS, and architecture.
2. Check out the exact request commit with credentials persistence disabled.
3. Verify the protocol and source manifest, and select the explicitly pinned
   interpreter. Use an isolated temporary virtual environment if dependencies
   need installation; preserve existing project environments.
4. Collect the interpreter, PyTorch, NumPy, SciPy, CPU/GPU, and source receipts.
   Set a writable `MPLCONFIGDIR` for plotting. CPU execution is sufficient for
   the small mathematical and continuous-latent mechanism experiment, but this
   is not evidence about large-model GPU scaling.
5. Run the oracle, preregistered training/evaluation, and independent audit with
   a bounded job timeout. A successful process exit does not imply that the
   scientific efficacy gates passed.
6. Upload complete or partial outputs and logs with `if: always()`. Record
   separately implementation validity, scientific conclusions, and verified
   target execution.

The existing repository pins for checkout and artifact upload can be reused:

- `actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd`
- `actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f`

## Remaining closure evidence

The execution blocker closes only after an actual intended-environment receipt,
source-pinned execution, complete artifacts, and independent result verification
are obtained. A queued timestamp, published workflow, or local CPU result does
not close it. Restoring eligibility/availability of the existing route or
identifying an already configured project-bound callable entry is the necessary
external step. These observations do not imply that the configured cloud does
not exist.

## Local runtime finding

The default interpreter has Python 3.12.14, NumPy 2.3.5, and SciPy 1.17.0, but no
PyTorch. The prior pilot receipt points to an existing separate interpreter with
PyTorch 2.5.1+cpu and NumPy 1.26.4, but without SciPy or matplotlib. These are
observations of local runtimes, not instructions to modify the old environment
and not dedicated-cloud receipts.
