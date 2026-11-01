# Prospective secondary trained-cell information probe

Publish and remotely verify `probe.py`, `plan.json` and this file before running.
The registration receipt must contain a verified 40-character remote commit and
the SHA-256 values of these three files under keys `probe.py`, `plan.json` and
`README.md`. The model seal is the same all-model/source/TRAIN-data seal used
by main confirmation. The runner verifies all 384 sealed models and main
source/data identities before and after selecting its 96 fitted-cell models.
No confirmation cohort, label or outcome is an input.

```sh
PYTHONPATH=/tmp/hcsn-torch-runtime OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python -m tools.hcsn.digital_mechanisms_20261101.secondary_retention.probe \
  --training /absolute/formal_training \
  --model-seal /absolute/model_seal.json \
  --registration /absolute/secondary_registration.json \
  --output /absolute/new_secondary_run
```

Required registration structure:

```json
{
  "verified_remote_commit": "actual remotely verified 40-character commit",
  "files_sha256": {
    "probe.py": "actual SHA-256",
    "plan.json": "actual SHA-256",
    "README.md": "actual SHA-256"
  }
}
```

The receipt is supplied by the publication workflow; the offline runner does
not itself authenticate GitHub. A missing/mismatched receipt refuses execution.

## Meaning of the probe

A balanced hidden label produces one noisy observation at reliability `.85`.
The observation has already completed at time zero. Each candidate propagates
the two observation-conditioned distributions separately. For sustained input,
these distributions use different drivers; mixing class distributions before
propagation under one shared driver would be incorrect. Impulse candidates
inject once at time zero and use a neutral subsequent interval law.

Every horizon records class-belief information recoverable by the exact Bayes
decoder from the selected cell view. Accuracy and Brier are calculated under
the declared joint distribution, not estimated from additional task examples.
The process remains the fitted finite interval approximation. The horizons
are sequentially composed on the registered interval partition; no continuous
semigroup or exact within-interval event-time claim is made.

For each fresh-event branch, the raw joint mass retains the active source bin
and newly emitted sign. Source-only, source-plus-driver, event sign and forced
reset information use **the identical event-selected population within that
model/interval**. Selection is diagnostic conditioning on a future event, not
information available to the deployed policy before it occurs. Different
models may select different event populations and event probabilities.
Here "before" means the reported interval's starting cell state, conditioned
on a fresh event within that interval; it does not mean the infinitesimal state
immediately preceding a continuously timed threshold hit.

Under sustained drive, event sign can gain information relative to source cell
alone because the remembered driver is an additional input during the
interval. Accordingly, source-alone-to-sign data processing is checked only
for impulse models. Joint source/sign coarsening and sign-to-reset checks apply
to both. Source-plus-driver supplies the appropriate upstream information
bound for sustained drive. Equal reset removes sign dependence while retaining
the selected population's possibly unequal class prior; chance accuracy need
not equal `.5` after such selection.

Forced signed/equal resets are declared diagnostic kernels, not an assertion
that natural recovery occurred immediately or at no task cost. Current
refractory-sign views include old as well as freshly emitted events; the
fresh-event branch is recorded separately to avoid conflating them.

This secondary probe adds evidence about **fitted cell dynamics**. It does not
establish whole-policy maximal information, arbitrary multi-observation memory,
neural-head calibration, causal utility, generalization or production
qualification. Main-study contrasts, thresholds, model selection and
confirmation remain unchanged. Report every fit/candidate/horizon, including
zero-event cases and failed runs; do not use these outputs to tune the frozen
models.

The actual policy head continues to receive public time, schedule information
and the last observed symbol/reliability. Loss of information in the isolated
cell is therefore not loss of all information available to the whole policy.
Sustained drive can repeatedly introduce this public evidence into the cell.

The supervisor retains full worker CPU/RSS/exit status, logs and partial
per-fit compressed records. Mass, same-population and data-processing
invariants run on the actual registered models. There is no separate probe
execution before source registration.
