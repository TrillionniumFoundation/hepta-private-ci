# Digital-cell mechanism continuation, 2026-11-01

This research follows PR #4540 at `012bcf3505cb9306d9cef094a1acc3ca34c978be`.
Historical `digital_read_before_20261031` sources, models and confirmation remain
unchanged. Final scientific conclusions are in `REPORT_ZH.md`; source, model and
confirmation identities are separate records. Production adoption is not enabled.

## Four concrete experiments

1. **Known terminal values.** `models.py` supplies a common structured head with
   STOP zero and binary submission values `1-2b` / `2b-1`. All five inherited
   families retain paired free-head and structured-head candidates. The learned
   head shrinks from seven to four rows, removing 99 parameters. Both actual
   allocated and structurally active counts are reported. Ordinary refractory
   flags make another 64 input weights unreachable; its three extra physical
   coordinates are also inactive. These are disclosed differences, not a claim
   of equal statistical capacity.
2. **Input and evidence.** Sustained drift, one completion-time impulse and an
   explicit-time evidence accumulator share the task clock, observed packets,
   common public fields, action legality and fees. The impulse is a declared
   bounded projection, not a continuous Brownian observation model. Cell-only
   information probes distinguish event signs, merged signs and reset effects;
   the shared public last observation remains available to every learned head.
3. **Propagation and native time.** `renewal.py` defines a separate upwind finite
   CTMC with reset/refractory, signed within-interval hits and multiple renewal.
   The same generator defines multi-horizon predictions, first-hit quantities,
   expected counts and sampled paths. It is not silently substituted for the
   inherited interval cell used in the efficacy matrix. `renewal_native.rs`
   persists clock, state, pending jump/destination, RNG and counts. Explicit
   context switching invalidates the pending event under the new generator.
4. **New confirmation.** TRAIN/validation development precedes frozen formal
   sources and fits. Every formal model is published before IID/OOD creation.
   Four prespecified contrasts on two splits use independent fit means and eight
   Bonferroni Student t intervals. Old confirmation is not used for training,
   sample selection or efficacy reuse.

## Policy-state supervision and exact policy expectation

`training.py` retains the old conditional nonlinear supervised objective on
cell-independent behavior rows. An on-policy variant collects a single actual
greedy-visit snapshot halfway through training, then samples half of each batch
from those recorded realized states. Those rows use one-hot observed latent
indices; they never use unconditional `prefix_mass` to represent autonomous
policy occupancy. Further parameter updates can make the snapshot stale.

`exact_policy.py` independently includes action selection probabilities in the
joint task × cell path mass, on a declared one-to-three-interval finite task.
Its gradient checks establish the mathematical contract, not convergence or
efficacy of the separate six-interval supervised training experiment.

## Budgets and interpretation

The main matrix has 20 candidates at 240 updates × 128 states. A supplemental
four-candidate matrix uses a common 16 process-CPU-second learning allowance,
including actual greedy-state collection and fitted-target computation. Complete
updates can overshoot the allowance and every overshoot is reported. Fixed and
value controllers reuse each candidate's same final fitted checkpoint, with
independent runtime caches for measured execution. Model structures, input
information and physical parameter differences remain explicit.

Full child-process `wait4` receipts cover imports, setup, data creation, training,
diagnostics, serialization and shutdown. Candidate-level timings are nested
scopes and must not be added again to those totals. Failed development attempts
are retained and charged. CPU measurements are not hardware energy and do not
establish production latency or throughput.

The planning rule uses only three development fit differences and a disclosed
1.25×SD heuristic. The 16-fit study cap can be below the normal-approximation
requirement; that outcome is reported as unmet planning power. Individual worlds
or decisions never replace independent fits in the uncertainty calculation.

## Reproduction

Python 3.12 with NumPy, SciPy and CPU PyTorch is required. Exact observed versions
and commands are in the process receipts. `renewal_native.rs` needs only Rust's
standard library; pass an installed `rustc` to its execution scripts.

```bash
python -m tools.hcsn.digital_mechanisms_20261101.launch development \
  --fits 101 103 107 --workers 3 --root /tmp/digital-development \
  --protocol tools/hcsn/digital_mechanisms_20261101/protocol.json

python -m tools.hcsn.digital_mechanisms_20261101.analyze plan \
  --protocol tools/hcsn/digital_mechanisms_20261101/protocol.json \
  --development /tmp/digital-development --output /tmp/digital-plan.json
```

Formal fit IDs are recorded in the final protocol. Use `launch train` with that
list and a new output directory. `freeze.make_model_freeze` binds source, model,
training-data, cost and coverage receipts. Publication verification must be
recorded before `launch confirm`; the runner rejects changed frozen inputs.
Only generate a new confirmation after completing those steps.

Evidence archives consist of bounded base64 volumes and paged hash indexes.
Restore each `*.manifest.json` with:

```bash
python -m tools.hcsn.digital_mechanisms_20261101.freeze restore \
  --source PATH_TO_MANIFEST --destination NEW_EMPTY_DIRECTORY
```

Restoration verifies every volume, member and original byte. Original timestamps
are not recreated. Historical absolute paths remain in raw receipts; the analysis
uses the restored relative evidence structure and does not reopen those old paths.
Regenerating cohorts from the registered seeds creates new local paths. Equal-CPU
training is time-stopped, so its update count and fitted weights need not be
bit-identical on a different host.

## Preserved development failures

The first three DEV workers reached the third fitted candidate but failed while
serializing a NumPy boolean diagnostic. Their partial artifacts, source bytes,
stderr and full CPU receipts remain in the failed-development archive. The next
development version fixes the boolean conversion and an independently found
fixed/value lazy-cache accounting asymmetry. It keeps the same DEV seeds; these
are development reruns, not fresh independent confirmation. A small actual-read,
three-family training/visit/execution smoke then succeeded before the full rerun.

The repository formatter split one native `use` statement without changing its
bindings. Earlier numerical/native evidence retains its actual pre-format source
hash. The distinct frozen-model native experiment records its own current source,
compiler, binary, model, process and checkpoint identities.
