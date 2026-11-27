# Common executor: exposed Ruff development incident

This Linux-only executor accepts a complete replacement for one implementation
file in an already exposed historical repair task. It performs actual Ruff and
unittest execution. It does not choose a repair, call a model, learn a policy, or
establish future-task superiority. The original task is a real repository lint
failure; its 76 semantic tests exercise a finite research controller, not a
natural-domain benchmark.

## Frozen judge inputs

`ruff_contract.json` contains only the failing commit, 17 original file hashes,
76 exact test IDs, executable hashes, limits, and the allowed implementation path.
The executor pins the contract's exact SHA256. `describe` reads only this contract:

```sh
python3 -B scripts/memory_cell_evaluation/ruff_executor.py describe
```

The candidate document is UTF-8 JSON with exactly this shape:

```json
{"schema":"hepta.memory-cell.implementation-candidate.v1","files":[{"path":"experiments/multimodal_output_portfolio/v4/counterfactual_audit.py","content":"complete replacement Python source"}]}
```

Only that literal implementation path is admitted. Duplicate keys, extra files,
test edits, path escapes, oversized inputs and added lint suppression comments
are rejected. Patch parsing is not implemented. The outer judge is separate from
the repairable implementation: 13 unchanged test modules are copied separately,
while the full candidate fixture retains all 17 original paths. Only the allowed
implementation may differ. Original, baseline, candidate, judge and executor
source inventories are checked again after execution.

This is a **new development judge version**. The historical lint command was
`ruff check --no-cache experiments/multimodal_output_portfolio/v4/counterfactual_audit.py`.
The original 17-file fixture contains no Ruff configuration. The new command adds
`--isolated --output-format=json` to freeze Ruff's default rules and diagnostic
format, independent of ancestor/user configuration. It also introduces the
explicit no-new-`noqa`/`ruff:`-suppression admission policy. Every admitted
evaluation first runs the unchanged source in its own copy and requires exactly
the original F401 and E731 diagnostics; any other failure cannot qualify it.

The historical semantic command was `python -B -m unittest discover -s
experiments/multimodal_output_portfolio/v4 -v`. The new wrapper runs the unchanged
test workload in an isolated Python interpreter, recording discovered, started,
completed and outcome IDs. The parent requires each of the 76 IDs exactly once
and successful, with no skips, failures, errors, expected failures or unexpected
successes. It does not accept a text `Ran 76 / OK` summary. The wrapper's argv is
different; no equivalence to the complete historical OS/runtime is claimed.

## Execution and evidence

```sh
python3 -B scripts/memory_cell_evaluation/ruff_executor.py evaluate \
  --fixture /absolute/original-17-file-root --candidate /absolute/candidate.json \
  --output /absolute/new-output --ruff /absolute/pinned-ruff \
  --python /absolute/pinned-python
```

The output's parent must exist. The output directory is acquired exclusively;
an existing output is never overwritten. Raw bounded candidate input, command
requests, stdout, stderr, return codes, timeout status, wall time, child CPU
delta, file hashes, per-test receipts and final refusal/success are retained.
Oversized requests retain only a bounded prefix and a refusal reason. Every
failed attempt counts as an attempt. Limits are 90 wall seconds, 30 CPU seconds,
512 MiB virtual address space (not a physical RSS budget) and 4 MiB per output
file per child. Each child is pinned
to the first CPU available in the parent's affinity set; the actual CPU is in
its receipt. This bounds Ruff's available parallelism under the memory cap.
The parent kills and
reaps its process group on timeout and cleans up remaining group members while
the parent remains alive. Parent death supervision is not implemented here;
termination of the parent can leave a blocked child alive.

These controls serve trusted development proposals, **not hostile Python**.
Candidates share a Unix user and can execute Python in the judge interpreter;
there is no filesystem/network isolation, anti-monkeypatch proof or protection
against descendants that deliberately escape the process group. Missing or
incomplete receipts and detected source drift fail closed. Executable hashes
pin the two binaries, not the complete standard library, dynamic libraries or
OS. CPU deltas and cumulative child max-RSS are limited local measurements, not
a complete token, training, storage, energy or monetary meter.

## Qualification

`test_ruff_executor.py` requires explicit original fixture and known historical
fixed source paths. Its fixed-source hash belongs only to qualification; neither
the fix nor its outcome is in `describe` or the source-only contract. The gold
case is a positive control, not an independently predicted repair.

```sh
python3 -B scripts/memory_cell_evaluation/test_ruff_executor.py \
  --fixture /absolute/original-17-file-root --known-fix /absolute/old-fixed-file \
  --output /absolute/new-qualification-output --ruff /absolute/pinned-ruff \
  --python /absolute/pinned-python
```

Controls include actual original lint failure, known fix with 76 semantic passes,
a lint-clean wrong implementation, a skipped-test implementation, source/path
refusals, duplicate-output preservation, a bounded Python timeout and an injected
stderr-open failure that must still retain a process receipt. Synthetic
negative controls are executor checks, not additional incidents or task families.
No model, training, Rust build, network fetch or package installation is needed.
Run qualification before final repository formatting; preserve any failed
development run, and do not rerun tests after formatting.
