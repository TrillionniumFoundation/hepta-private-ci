# Durable evaluation focused evidence, 2026-11-05

Both normal and `-O` Python runs passed **20/20** focused tests, with exit code 0.
The nine inventoried Python source files were identical before and after both runs.
This capture followed the separate typed-output repair; `typed_json.py` is included
in both this inventory and the durable experiment-family implementation binding.

- `run.json`: exact commands, UTC times, exit codes, environment, log hashes and scope.
- `normal.log` and `optimized.log`: complete captured stdout/stderr.
- `source-hashes.before.json` and `source-hashes.after.json`: SHA-256 source identities.

The tests exercise the actual isolated evaluator as a synthetic positive control,
eight independent processes competing for one slot, abrupt process exit after
reservation/running/completion, retained recovery, request rebinding, source reuse,
changed callbacks across looks, and freezing every candidate before any result.
Unknown or cancelled operations remain consumed and cannot automatically replay.

This is focused protocol evidence on a modified working copy based on
verified upstream `f88b826d3c22b5f89fd350dab4813be2855a2f93`. The local Git snapshot
was `ae4b786893c719c617fc41be0b624a3e60e49b24`; it is not the upstream commit.
The source inventories identify the modified working copy used in this capture.
It is not a full-suite execution, remote CI result, real-model efficacy experiment,
complete measured cost comparison, whole-authority rollback defense, or production
authorization. Synthetic ledger costs in these controls are not operating bills.
The parent integration stage records its own final source freeze and full test runs.
