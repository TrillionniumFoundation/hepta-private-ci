# Second pinned incident and explicit runtime profiles

This is a new development feature. The old Ruff contract, qualification outputs
and publication bridge remain immutable. Ruff's evaluator and qualification CLI
now accept an optional controller-supplied runtime profile and expose an attempt
ledger; their source versions have changed. Old source hashes do not describe
this extension. The default Ruff binary pins and original 76-test gate remain.

## Codec source and independent intent

The second case is the already exposed `media-false-green` incident at
`a88f2832f2a1a4d3734c1c88f76977dcc9b98ff1`. Its seven Python files, workflow and
MANIFEST were fetched at that exact failing commit. The seven Python files total
68,309 bytes. This round newly verified the MANIFEST at the failing ref; the
older catalogue had verified it only at the fixed ref. This new check does not
alter the old catalogue.

The subject is the workflow's selected test entrypoint plus an optional
`qualification/ndu-dmgp-shadow/run_codec_acceptance.py` implementation. A candidate
can change only the original test step's single-line `run` value to the registered
runner command, and supply an arbitrary runner implementation. The rest of the
workflow and all original helper/test/MANIFEST bytes remain pinned. This narrow
workflow selection is validated statically. The executor runs the selected local
Python entrypoint; **it does not execute GitHub Actions, checkout, apt provisioning,
the complete workflow or the historical 107-test suite**.

The outer observer and exact 21-test manifest are independent of the candidate.
The unchanged tests remain co-located with helpers so historical discovery works;
candidate admission cannot edit them, and all source is checked after execution.
The observer records what the candidate actually runs. It does not run a separate
successful suite to excuse a candidate that executes zero or fewer tests.

Each attempt uses three fresh workspaces. `missing_ffmpeg` and `missing_ffprobe`
expose only the remaining named tools in a private PATH. They must exit nonzero,
without timeout or signal; this is fail-closed behavior under missing tools, not
proof that the missing tool caused the refusal, and not 21 semantic successes.
`provisioned` must run each original ID exactly once and pass all 21 with no skips,
expected failures, omissions or duplicate execution. The fixed no-promotion
MANIFEST fields must remain false. Binaries still exist elsewhere on the host:
PATH filtering is a trusted-code environment profile, not hostile-code isolation.

## Interface

```sh
python3 -B scripts/memory_cell_evaluation/codec_executor_v2.py describe
python3 -B scripts/memory_cell_evaluation/codec_executor_v2.py inputs \
  --fixture /absolute/original-nine-file-root --output /absolute/new-input-view
python3 -B scripts/memory_cell_evaluation/codec_executor_v2.py evaluate \
  --fixture /absolute/original-nine-file-root --candidate /absolute/candidate.json \
  --output /absolute/new-attempt --python /absolute/python \
  --ffmpeg /absolute/ffmpeg --ffprobe /absolute/ffprobe --openssl /absolute/openssl
```

Candidates retain schema `hepta.memory-cell.implementation-candidate.v1` and a
`files` list of complete UTF-8 file replacements. Zero to two unique permitted
paths are accepted. A zero-edit candidate reproduces the original task. The
source-only `inputs` export contains exactly the nine original files and task
metadata, never the historical fixed runner or resolution evidence. Known fixed
runner bytes appear only in explicit qualification controls.

## Qualifying another runtime before generation

Both Ruff and codec `evaluate`, their qualification CLIs, and codec `inputs`
accept `--runtime-profile FILE --runtime-profile-sha256 SHA`. Both arguments are
required together. The controller freezes this file before qualification and
model generation; the candidate cannot set or override it. Its exact schema is:

```json
{"schema":"hepta.memory-cell.runtime-profile.v1","task_contract_sha256":"exact contract SHA256","tools":{"python":{"bytes":1,"sha256":"64 lowercase hex digits"},"ffmpeg":{"bytes":1,"sha256":"64 lowercase hex digits"},"ffprobe":{"bytes":1,"sha256":"64 lowercase hex digits"},"openssl":{"bytes":1,"sha256":"64 lowercase hex digits"}}}
```

Codec requires exactly those four tools; Ruff requires exactly `python` and
`ruff`. Actual CLI executable bytes must match. A profile cannot change source
hashes, test IDs, limits or admission rules. The controller must run the explicit
known-fix and negative qualification under this same profile and gate all later
generation on its success. Every attempt records the profile hash. Hash binding
alone does not prove that qualification occurred first: chronology is enforced
by the controller/workflow, not asserted from a self-supplied profile. A new
environment's success is new local qualification, not historical OS equivalence.

## Attempt costs and limitations

Every admitted or refused attempt retains submitted request metadata, bounded
candidate bytes when readable, command/return-code/raw stream evidence, source
inventories and a cost ledger. Codec's direct worker uses Linux `wait4` for
per-child CPU, wall duration and max-RSS. The worker records actual nested
`subprocess.run` commands, CPU deltas, wall durations and output hashes/bytes.
Nested costs are attribution only and **are not added again** to the outer
waited-child total. Unobserved subprocess mechanisms and killed descendants are
not individually attributed. Output retention is capped at 256 KiB per nested
stream and 4 MiB per observer, with explicit truncation; at most 512 nested
process calls are admitted. Sources and candidate bytes are counted separately
from existing tool binary bytes and retained outputs. Source-byte counts mean
logical loaded payload, not repeated hash reads or complete filesystem I/O.
Parent process CPU and whole-attempt wall duration are measured through the
final inventory; final receipt serialization and external orchestration are
excluded. Parent CPU assumes the supported serial CLI, not a concurrent server.
Virtual address limits are not physical-memory measurements.

Optional `--accounting` for codec (`--accounting-file` for Ruff) supplies schema
`hepta.memory-cell.external-accounting.v1` with exactly `model_calls`,
`input_tokens`, `output_tokens`, `training_tokens`, `tokenizer_id`,
`tokenizer_sha256`, and `receipt_sha256`, plus `schema`. Unknown values are null.
Counts must be nonnegative integers; booleans are rejected. These external values
remain explicitly caller-declared, not measured or attested by this executor.
The executor calls no model. Whole-host CPU, dollars, dynamic-library bytes,
model-base storage and peak transient storage remain unknown; no full-system
compression or equal-total-cost claim follows from this ledger.

Candidates remain trusted Python under the same UID/interpreter. There is no
anti-monkeypatch proof, filesystem/network sandbox, or parent-death guarantee.
Group timeout cleanup operates while the parent survives. Binary hashes do not
pin the full OS, standard library or dynamic-library closure. No results here
constitute independent future evidence, a strong retrieval comparison, production
source authorization or a complete memory-system qualification.
