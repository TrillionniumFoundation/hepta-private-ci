# Reproduce Round 7

This guide separates restoration of the original evidence, verification of its
frozen inputs, re-execution of the original models, and a new training study.
It is an output document added after the scientific freeze; it is not an
amendment to the frozen protocol.

## 1. Checkout and working directory

Use the published commit on
`research/analytic-event-joint-value-20261030-r7` that contains this guide,
`FROZEN_MANIFEST.json`, and the complete `evidence_bundle` parts. Pin that commit
for a replay. The `main` branch is a different implementation profile.

Run every command below from the **repository root**, the directory containing
`experiments/`. The recorded workspace root was
`/workspace/scratch/08bf0b785298/hepta-research`; a new checkout can have any
location. Do not change into `round7/` and run these files directly: use module
invocation so their package imports resolve.

```sh
cd /path/to/hepta-private-ci
HEPTA_R7=experiments/analytic_event_neuron/round7
```

The parent files `analytic.py`, `reference.py`, `native_adapter.py`, and
`__init__.py` in `experiments/analytic_event_neuron/` are also required. Their
hashes are bound by the frozen manifest; a partial checkout must include them.

## 2. Restore the complete evidence with one command

The repository bundle consists of `evidence_bundle/BUNDLE_MANIFEST.json` and
`part-00000.bin`, `part-00001.bin`, and so on. Each part is a raw binary slice
of a gzip-compressed USTAR archive. Parts are 524,288 bytes except the last.
The command assumes `python3` selects Python 3.12; use `python3.12` instead if
that is the appropriate executable on the new machine.

```sh
python3 -m experiments.analytic_event_neuron.round7.artifact_bundle unpack --bundle experiments/analytic_event_neuron/round7/evidence_bundle --output experiments/analytic_event_neuron/round7/evidence
```

This extraction uses the Python standard library only. It does not download
an interpreter, Python packages, compiler, model weights, or a native binary.
It verifies every part, the compressed archive, and each member's SHA256,
length, type, and mode before publication. It restores the historical native
executable's executable permission. The manifest preserves development
failures, superseded temperature fits, all final fits, raw confirmation data,
broker artifacts, and native traces. `__pycache__` and the bundle's own output
directory are excluded.

The default limits are 2 GiB compressed archive, 4 GiB unpacked file content,
1 GiB per member, 50,000 members, and 32 MiB for the manifest. Restoring requires
space for a temporary compressed copy and a verified staging tree in addition
to the parts. An existing target is accepted only when its existing members
match the declared evidence. Different bytes, unexpected members, symlinks,
and existing files with multiple hard links are rejected. Nothing is silently
overwritten. The caller must exclusively control the target during restore;
this is not a sandbox against concurrent hostile filesystem modifications.

Keep the manifest and all parts together. A missing or altered part is a failed
integrity check, not a reason to change a recorded hash. The extraction command
is implemented and tested in [artifact_bundle.py](artifact_bundle.py) and
[test_artifact_bundle.py](test_artifact_bundle.py).

## 3. Python environment

The recorded environment is in [ENVIRONMENT.json](evidence/ENVIRONMENT.json):

| Component | Recorded value |
| --- | --- |
| Python | 3.12.14; Python 3.12 is required for this replay profile |
| PyTorch | 2.9.1+cpu |
| NumPy | 1.26.4 |
| SciPy | 1.17.0 |
| Platform | Linux x86_64, glibc 2.39 |
| Torch threads | 1 |
| CUDA | Not used; unavailable in the recorded environment |

The model, study, and audit CLIs set one Torch CPU thread. The scientific arrays
and model are FP64. Version equality does not guarantee identical wall times or
bitwise identical floating-point execution on every different CPU/platform.

If these packages are already installed, no package installation is needed.
For a separate new environment, prepare Python 3.12 first, then install the
recorded dependencies. The CPU wheel index follows the official
[PyTorch instructions for version 2.9.1](https://pytorch.org/get-started/previous-versions/):

```sh
python3.12 -m venv /tmp/hepta-r7-env
. /tmp/hepta-r7-env/bin/activate
python -m pip install numpy==1.26.4 scipy==1.17.0
python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
```

Package installation is an optional environment-preparation step and may need
network access or an existing wheel cache. Bundle extraction itself is offline.
No torchvision or torchaudio package is used by this study.

Verify the selected interpreter before testing or replay:

```sh
python - <<'PY'
import platform
import numpy
import scipy
import torch
assert platform.python_version().startswith("3.12.")
assert torch.__version__ == "2.9.1+cpu"
assert numpy.__version__ == "1.26.4"
assert scipy.__version__ == "1.17.0"
torch.set_num_threads(1)
print(platform.python_version(), torch.__version__, numpy.__version__, scipy.__version__)
print("torch threads:", torch.get_num_threads())
PY
```

In the original managed workspace, the primary Python 3.12 interpreter reused
installed packages through
`PYTHONPATH=/tmp/convergence-smollm-runtime/lib/python3.12/site-packages`.
That path is a property of the recorded workspace, not a required path in a
new environment. Use the prepared interpreter's own installed packages instead
of assuming that temporary directory exists.

## 4. Verify the scientific seal and run the 45 tests

The seal was created at `2026-10-31T02:23:47.523187+00:00` and binds 108 files,
including scientific sources, the protocol, required parent modules, and all
60 registered checkpoints. Verify it after extraction:

```sh
python - <<'PY'
from pathlib import Path
from experiments.analytic_event_neuron.round7.study import verify_freeze
root = Path("experiments/analytic_event_neuron/round7")
receipt = verify_freeze(root)
print("verified inputs:", len(receipt["manifest"]["files"]))
print("frozen manifest SHA256:", receipt["sha256"])
PY
```

`confirmation_started: false` in the immutable manifest describes the original
pre-confirmation seal. It is not a live process-status flag. Do not edit that
field or recompute the seal merely because a replay is now being run.

```sh
python -m unittest discover -s experiments/analytic_event_neuron/round7 -t . -p 'test_*.py' -v
```

The original [TEST_RECEIPT.json](evidence/TEST_RECEIPT.json) records **45 tests,
0 failures, 0 errors, and 0 skips**, with unchanged source hashes during testing.
This includes the existing-hardlink extraction regression. The independent
continuous-model accuracy gates in `numerical_audit.json` are a different
evaluation and include failures. Passing implementation tests does not close
those approximation or production-promotion gaps.

Do not run `freeze.py` again in this frozen directory. It deliberately rejects
an existing seal. A changed scientific input requires a new study version.

## 5. Re-execute the original 60 models and 108,800 trajectories

Choose a fresh replay output directory; the commands reject existing outputs
so prior evidence remains intact. For example:

```sh
HEPTA_R7_REPLAY=/tmp/hepta-r7-replay-01
python -m experiments.analytic_event_neuron.round7.study --root "$HEPTA_R7" --output "$HEPTA_R7_REPLAY/confirmation" --count 512 --stress-count 256
python -m experiments.analytic_event_neuron.round7.statistics --root "$HEPTA_R7" --confirmation "$HEPTA_R7_REPLAY/confirmation"
```

The study loads the **original frozen weights**. It does not train them again.
It repeats the registered external and internal RNG namespaces, task parameter
mixture, legal-action rules, and deployments:

| Evaluation | Calculation | Trajectory records |
| --- | --- | ---: |
| Nominal | 5 fitted seeds × 512 fixtures × 26 arms | 66,560 |
| Three stresses | 5 fitted seeds × 256 fixtures × 11 arms × 3 regimes | 42,240 |
| Total | All registered executions | 108,800 |

These records are paired arm executions, not 108,800 independent fitted models.
Inference retains five fitted-seed clusters. The exact identity gate checks
the complete registered arm/fit/episode grid, external and internal seeds,
receipt counts, and raw compressed-file hash. A partial run is not a valid
smaller confirmation set.

A replay using the same weights and random streams is a reproducibility check,
not new independent statistical evidence. Runtime measurements, compressed-file
headers, paths, and other execution metadata can differ. Verify archived files
against their original hashes; compare a newly executed run as a new execution
receipt, not by expecting every timing-bearing byte to match the original.
Do not pool repeated replays to increase the reported sample size.

The five superseded temperature fits remain in the evidence, including possible
copies under their original paths. `study.checkpoint_path` uses explicit
registration; only `fits_temperature_corrected` is eligible for that model.
A missing corrected checkpoint must fail, never fall back to a retained legacy
file. [REGISTERED_CHECKPOINTS.json](evidence/REGISTERED_CHECKPOINTS.json) binds
the exact 60 eligible paths and hashes.

## 6. Re-run the conditional, broker, and native bridge audits

These are separate audits, not extra primary-confirmation observations:

```sh
python -m experiments.analytic_event_neuron.round7.audits --root "$HEPTA_R7" --output "$HEPTA_R7_REPLAY/audits" --artifact-root "$HEPTA_R7_REPLAY/runtime_artifacts"
python -m experiments.analytic_event_neuron.round7.native_bridge --manifest "$HEPTA_R7_REPLAY/audits/native_manifest.json" --artifact-root "$HEPTA_R7_REPLAY/runtime_artifacts" --output "$HEPTA_R7_REPLAY/native_bridge"
```

The audit evaluates all five registered D fits at the 40 declared scripted
public/internal prefixes, with 64 conditional continuations per legal action.
It resamples future truth/evidence and future internal RNG correctly while
preserving the conditioned state. It also runs the sixteen actual broker cases
and writes new terminal artifact receipts and a current-path native manifest.

Archived native manifests contain the **absolute artifact paths of their
original execution**. Preserve their bytes for integrity verification. On a
different checkout path, rerun the broker audit to generate a manifest for the
new paths, as above. Do not edit the old manifest or rewrite its hashes to make
it appear to describe a new execution.

The bundle includes the historical Linux native executable with SHA256
`b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179`
and its original build and restoration receipts. **No Rust binary was freshly
built in Round 7.** The `fresh_build` field inside the historical build receipt
refers to that earlier build. New bridge receipts explicitly report reuse.
The original Rust formatting attempt returned `just: command not found`, and
Rust tests were not run in this partial research workspace; see the environment
receipt. Python tests are not substitutes for a new native build qualification.

The typed native call writes its own journal. Each subsequent sparse feedback
pair starts a separate state and does not update that typed checkpoint. The
Gaussian parameters passed to this old adapter are an explicit posterior-based
proxy, not the learned Round 7 cell or weights installed in Rust. Outputs retain
`DENY_ALL`, abstention, and their unqualified calibration status.

## 7. New training is a new study

`learning.py` can fit models again, but doing so creates new experimental
artifacts. It does not reproduce the original evidence simply by overwriting
the registered JSON files. Use an isolated new checkout/study version and new
output directories. Keep the original frozen sources, protocol, checkpoints,
and raw observations intact.

The final design consists of 20 base fits (clocked, first passage, continuous,
direct; five seeds each), 5 corrected temperature fits, 30 first-passage group
freezes, and 5 clocked boundary freezes. A fresh implementation of the corrected
design therefore has **60 eligible fits**. The original history has **65 formal
successful attempts** because the five pre-correction temperature fits were
retained and excluded, plus six earlier smoke fits and a pre-fit failure.
Do not deliberately reactivate the rejected operator merely to make a new
study's attempt count equal 65.

The earlier development source revisions were not all snapshotted. Their saved
checkpoints, data, curves, failure notes, and available timers are retained,
but the current source is not an exact executable reconstruction of every
early smoke revision. This limitation is recorded in
[DEVELOPMENT_LEDGER.json](evidence/DEVELOPMENT_LEDGER.json). It does not change
which final sources and sixty checkpoints are bound by the scientific seal.

The registered schedule is 256 training trajectories, 64 development
trajectories, grid 15, FP64, 100 regression epochs (Adam, learning rate 0.02),
dev-only regression checkpoint selection, and 30 fixed joint-control epochs
(Adam, learning rate 0.003). Control temperature is 0.12, and both auxiliary
weights are 1.0. The full graph contains 738 public states for the eight training
presets. See the frozen protocol and per-fit metadata for exact definitions.

For a new claim or changed design, declare its data/RNG namespaces and analysis
before generating fresh confirmation data, register its new checkpoint hashes,
run the required independent checks, and seal its own sources. The current
programs intentionally contain the Round 7 fixed namespaces and cannot be
relabeled as an independent new confirmation study without versioning those
definitions. A same-seed retraining is a training-reproducibility experiment;
it is not additional confirmation evidence for a new hypothesis.

## 8. Read the training and cost evidence correctly

[TRAINING_AUDIT.md](TRAINING_AUDIT.md) and
[TRAINING_AUDIT.json](evidence/TRAINING_AUDIT.json) independently compare the
60 saved checkpoints with reconstructed seeded initializations. They verify
nominal scalar counts, exact freezing, logged gradients, and the pretraining to
control-return curves. Their training-only conclusions do not use confirmation
outcomes and do not establish architecture superiority.

Formal batch receipts include data/oracle setup, model/optimizer setup,
training, and checkpoint serialization. Per-fit training timers cover a
narrower component and must not be added to those inclusive totals. Jobs ran
concurrently: summed wall job-seconds are not elapsed makespan. Early smoke
fits and the initial pre-fit failure lack complete process timing, and formal
timers exclude interpreter startup/imports. These missing costs are unknown,
not zero. Registered utility coefficients are separate from measured CPU/wall
cost; no energy or monetary interpretation is implied.

## 9. Reproduce the separate post-freeze optimal-controller diagnostic

The independent reference in
[posthoc/independent_joint_optimal.py](posthoc/independent_joint_optimal.py)
was added after the 108-input seal. It is a deterministic diagnostic of the
already fixed cells, not an additional preregistered primary comparison.
Its source hashes and four separate test results are recorded in
[JOINT_OPTIMAL_DIAGNOSTIC.json](evidence/JOINT_OPTIMAL_DIAGNOSTIC.json).
The independent review is
[INDEPENDENT_JOINT_OPTIMAL_REVIEW.json](evidence/audits/INDEPENDENT_JOINT_OPTIMAL_REVIEW.json).
Keep these source files from the same published commit as the evidence;
they are deliberately outside the original scientific seal.

Run its four tests explicitly, separately from the original 45-test suite:

```sh
python -m unittest experiments.analytic_event_neuron.round7.posthoc.test_independent_joint_optimal -v
```

The four tests cover explicit private-world enumeration of the full-cost
reference, forced STOP and current-versus-future fees, independence from the
learned Q head and agreement with the frozen policy evaluator, and repeated
events with reset/recovery and occupancy-based fee accounting. Their original
receipt records four tests, zero failures, and zero errors. They do not
retroactively change the original 45-test receipt or its freeze.

To recompute the diagnostic, choose a new output directory under the replay
root. The command runs those four tests itself and checks the original
scientific seal before and after its calculation:

```sh
python -m experiments.analytic_event_neuron.round7.posthoc.independent_joint_optimal --root "$HEPTA_R7" --output "$HEPTA_R7_REPLAY/joint_optimal/JOINT_OPTIMAL_DIAGNOSTIC.json"
```

Both the requested JSON path and the sibling `JOINT_OPTIMAL_TABLES.jsonl.gz`
must be absent. The command does not retrain models, consume confirmation
trajectories, or overwrite the original evidence. It holds each checkpoint's
encoder, drive, transition law, grid, noise, voltage boundary, reset, and
recovery fixed, and optimizes only the action controller under the registered
task and neural utility-proxy fees. The Bellman reference does not use the
learned Q head. Current event fees are charged before the action phase;
`q_star_after` excludes that already incurred fee while including current
compute and all future fees.

The archived full tables are lossless, not a selection of favorable states:

| Artifact | Contents |
| --- | --- |
| `JOINT_OPTIMAL_DIAGNOSTIC.json` | 738 ordered public states, all eight nominal configurations, 25 checkpoint identities, 200 checkpoint/configuration summaries, source and test receipts, and the table-line index |
| `JOINT_OPTIMAL_TABLES.jsonl.gz` | 25 JSON Lines, one for each of five modes and five fitted seeds; each line retains all 738 public states × 17 internal states |
| `q_star_after` | Four action values in `READ`, `WAIT`, `REPAIR`, `STOP` order; illegal actions are `null` and excluded from maximization |
| `advantage_act` | Best legal `REPAIR`/`STOP` value minus best legal `READ`/`WAIT` value; unavailable comparison groups are `null` |
| Actions and occupancy | Optimal and learned-head greedy actions, plus the sparse deployed-policy occupancy needed to reconstruct expected action regrets |

The 17 internal states are 15 active voltage nodes followed by the two
refractory states. Occupancy is averaged over the eight nominal configurations;
some full-table states are never visited by the learned policy. REPAIR can
itself reveal information, so the two action groups are a declared grouping,
not a universal separation between information gathering and acting.

The original compressed table is 3,347,656 bytes with SHA256
`533e70fc5ab62447d58b3ee44f61596437df8698fa68e6b39a3b5e1bc4a3b568`.
The diagnostic's `full_tables.index` records each uncompressed line's length
and SHA256. Verify the restored original table without rerunning the optimizer:

```sh
python - <<'PY'
from pathlib import Path
import gzip
import hashlib
import json

root = Path("experiments/analytic_event_neuron/round7/evidence")
report = json.loads((root / "JOINT_OPTIMAL_DIAGNOSTIC.json").read_text())
table = root / report["full_tables"]["path"]
assert table.stat().st_size == report["full_tables"]["bytes"]
assert hashlib.sha256(table.read_bytes()).hexdigest() == report["full_tables"]["sha256"]
with gzip.open(table, "rb") as stream:
    for item in report["full_tables"]["index"]:
        line = stream.readline()
        assert len(line) == item["uncompressed_line_bytes"]
        assert hashlib.sha256(line).hexdigest() == item["uncompressed_line_sha256"]
        row = json.loads(line)
        assert (row["mode"], row["seed"]) == (item["mode"], item["seed"])
    assert stream.read(1) == b""
print("verified all 25 full-table records")
PY
```

A new execution can have a different gzip header, runtime receipt, or path;
compare its canonical uncompressed table records and numerical results with
the archived reference instead of expecting its complete compressed file to
have the same hash. These are FP64 finite-law expectations with recorded
roundoff, not a continuum QVI solution, an architecture-wide optimum, proof of
optimal voltage thresholds, physical energy accounting, or new primary
confidence intervals. The original confirmation conclusions remain unchanged.
