# E5 retained-source readout, 2026-11-18

This readout applies the existing E5 accounting to the actual retained Run02
records. It introduces no new training framework and runs no model inference.
Independent source growth remains **BLOCKED**.

## Material and boundary

The recovered `PREPARED_RECORDS.json` contains nine authored repository tasks:
six training records (A6) and three previously used selection records (B3).
Its 72,723 original bytes hash to
`8dc94d1a2baefe9f03f26bc52292731f4b4d75104d9c920dd8566d2f8a13724b`.
`SOURCE_RECORDS_PROJECTION.json` preserves original identity, permission and
split fields, plus the SHA-256 of each canonical task input. It binds the raw
file path and the remote observation archive. Task text, answers and model
traces were not regenerated or exported into this projection.

Only A6 enters this readout; B3 remains excluded from training accounting.
The original source/budget implementation is pinned at
`eb56c51e4e73b0d466795b257a547ab93a0baa63`:

- `scripts/cell_experiments/circuit_study_v2.py::source_growth_plan`
- `scripts/cell_experiments/source_metrics_v3.py::source_growth_metrics`

It unions declared source groups when task, lineage, input or source identity
overlaps. This is conservative provenance accounting. It does not authenticate
users or estimate statistical effective sample size.

## Observed accounting

All six training records come from one project,
`TrillionniumFoundation/hepta-private-ci`. They reference six different source
files. File paths are not independent users or projects.

| Grouping and requested groups | Fixed total updates | Fixed updates per source | Status |
| --- | ---: | ---: | --- |
| Project, 1 | 224 | 224 | READY_FOR_DIAGNOSTIC |
| Project, 4 / 16 / 64 | — | — | BLOCKED: only one project group |
| File source, 1 | 224 | 224 | READY_FOR_DIAGNOSTIC |
| File source, 4 | 224 | 896 | READY_FOR_DIAGNOSTIC |
| File source, 16 / 64 | — | — | BLOCKED: only six file groups |

These are planned budgets from the existing protocol, not executed training
curves. No new independent sources, authenticated users or task executions were
added. Capability, adoption, forgetting and full-system cost remain unknown.
The file-source diagnostic must not be reported as a four-user growth result.
The complete output, including both requested budget regimes and each blocked
point, is in `E5_SOURCE_GROWTH_READOUT.json`.

## Reproduce

From the repository root with Python 3:

```bash
python3 qualification/cell-experiments-v3-20261116/operations/e5-source-readout-20261118/replay_readout.py --check
```

The command first checks the exact retained projection bytes, then recomputes
both groupings using the existing source metrics and compares the entire
result. Without `--check`, it prints the recomputed JSON. It does not execute
tasks, alter the recovered raw material, or grant source admission.

The existing source-metric tests and the replay command are recorded in
`VALIDATION.json`. Their fixtures verify accounting behavior; they supply no
new scientific samples. Actual independent, authorized records and subsequent
executions are still needed to populate the blocked project-level curves.
