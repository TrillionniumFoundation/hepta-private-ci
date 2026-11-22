# Reproduce the HCSN integration evidence

The completed findings are in [RESULTS.md](RESULTS.md). The frozen execution
source is commit `abb3e5012c5f48e3cb42759785429cb1d496acb3`; later commits add
verification scripts and evidence, not changes to the executed model.

## Verify and extract

`evidence.zip` contains 513 entries and 3,055,428 bytes: 512 individually hashed
files plus `MANIFEST.json` itself. Its SHA256 is:

```text
e27ae1925f3524f978d278fec64ac5961a131c513c3bcc7cea64021ab5bba992
```

Verify this hash before extraction. `MANIFEST.json` inside the archive records
each included file's size and SHA256. The archive contains `source/`, `study/`,
`validation/`, `fixtures/` and `provenance/`. Preserve this original copy.
The three adjacent verifier Python files in this directory are byte-identical
to their executed versions under the archive's `validation/` directory.

The published `verification.json` and `selected_replay.json` omit the repetitive
individual check list. Their `full_record` fields identify the complete record
inside the archive by path and hash. `summary.json` is the complete original
posthoc summary. `RESULTS.md` adds the scientific interpretation after verification;
the archived plotting script reproduces the numeric tables and figure, but not
all later editorial clarifications.

## Independently verify saved predictions and selected states

The recorded posthoc environment is CPython 3.12.3, PyTorch 2.8.0+cpu and NumPy
2.5.4. These two commands need no CSV download, network access, model training,
conditional refit, SciPy, ncps, Matplotlib or Ruff. The replay runs CPU FP64 and
sets one intra-op/inter-op thread. It uses saved P4 inputs and candidate states;
the first script independently recomputes stream metrics from saved predictions.

Set these three paths to your interpreter, extracted archive and a **new** study
copy. Run the second command only if the first succeeds:

```bash
HCSN_AUDIT_PYTHON=/absolute/path/to/qualified/python
HCSN_EVIDENCE_ROOT=/absolute/path/to/extracted-evidence
HCSN_RECHECK_STUDY=/absolute/path/to/new-recheck-study

cp -a "$HCSN_EVIDENCE_ROOT/study" "$HCSN_RECHECK_STUDY"

PYTHONDONTWRITEBYTECODE=1 "$HCSN_AUDIT_PYTHON" \
  "$HCSN_EVIDENCE_ROOT/validation/validate_flow_study.py" \
  "$HCSN_RECHECK_STUDY" \
  --source-root "$HCSN_EVIDENCE_ROOT/source"

PYTHONDONTWRITEBYTECODE=1 "$HCSN_AUDIT_PYTHON" \
  "$HCSN_EVIDENCE_ROOT/validation/replay_selected_flow.py" \
  "$HCSN_RECHECK_STUDY" \
  --source-root "$HCSN_EVIDENCE_ROOT/source"
```

The expected results are 3,954 artifact checks with zero failures, followed by
15 adaptation trials with zero replay failures, 30 forward calls and 30 cache
hits. All outputs go to the copy's `POSTHOC/` directory. The replay reads the
first verifier's `POSTHOC/verification.json` and `summary.json`, so do not move
them to a separate `--output` directory. It reconstructs only KEEP and selected
states, not every intermediate candidate, and makes no test-set model queries.
Costs from this verification are additional; do not subtract them from training.

Historical `LAUNCH.json` commands and the archived `FORMAL_DRIVER.py` and
`POSTHOC_DRIVER.py` contain the original host's absolute paths. Preserve them as
provenance; do not run those historical drivers on another host. The commands
above use explicit roots and do not execute the saved command strings.

## Rerun the original frozen study

Retraining is separate from evidence verification. The source CSV is not bundled.
Obtain UCI Room Occupancy Estimation (dataset 864, DOI `10.24432/C5P605`, CC BY 4.0)
and verify `Occupancy_Estimation.csv` has 931,630 bytes and SHA256
`c090ee5c94b61762bfec9d22767864490b51030f98cca030f02822468db25d9c`.
The full study additionally used SciPy 1.16.3, ncps 1.0.1 and threadpoolctl 3.6.0.
Use the frozen source with the archived `SOURCE_MANIFEST.json`, `STREAM_PLAN.json`
and `ADAPTATION_PLAN.json`; invoke `qualification.hcsn_scale.study_launcher`
with the CSV, a new output directory, those three paths and `--child-timeout 1200`.
Keep CPU FP64, one numerical thread, deterministic settings and the plan bytes.
The launcher refuses an existing output directory, verifies source before/after
every child, retains all costs and performs no automatic experiment retries.
Hardware, runtime and corpus history still limit comparability of a new run.

## CI context

The successful exact-source HCSN workflow is run `45007458768`. The separate
`repository_ci_context.json` records the full-repository status at
2026-11-22 10:05:39 UTC for that source commit, including inherited blockers,
the identical 131-file Prettier warning set and additional unattributed timeouts.
It is an as-of record, not a claim that the final evidence commit or every
repository workflow passed. `BUNDLE.json` binds these deliverables and their hashes.
