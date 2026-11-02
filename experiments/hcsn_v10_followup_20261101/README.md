# V10 source and evidence

This continues the exact V9 source tree published in draft PR #4581.
`baseline/V9_PUBLICATION_VERIFIED.json` maps the local commit history to the
byte-equivalent GitHub commits. The older V9 blocked-delivery receipt remains
historical evidence; the V9 publication subsequently succeeded.

Read `REPORT_ZH.md`, `ACCEPTANCE.json`, and the four component reports.
All original scientific gates remain unchanged. This does not activate production.

Before examining all frontend weights/predictions, restore their original bytes:

```bash
python -m experiments.hcsn_v10_followup_20261101.publication.transport restore \
  --manifest experiments/hcsn_v10_followup_20261101/publication/MANIFEST.json \
  --destination .
```

See `publication/README.md` for the exact supported CLI and transport boundary.
Selected weights and selected old-test predictions are also stored directly.
Transported originals remain separately enumerated with their hashes and sizes;
recovery does not change their original NPZ compression or contents.

The runtime is the same declared Python 3.12 / NumPy 2.3.5 / SciPy 1.17.0 /
Torch 2.15.0+cpu used for the new V9 ordinary models. Each worker CONFIG.json
retains its actual command. Reconstruct inherited v3/v8 assets using
`../hcsn_v8_execution_20261101/REPRODUCE.md`, preserving all pinned identities.
The local read-only Torch path is environmental, not a source dependency.

For a new AV run, use a fresh output directory; run candidate prepare, then
the independent `persistent_av.root_precheck check`, then its sealed `evaluate`
entry point. Never edit an evaluated source or reuse an old output directory.
The direct candidate evaluator alone does not verify the complete input seal.

Other component reproduction instructions:

- `frontend/README.md`: finite historical frontend search and cache adapter.
- `persistent_av/REPORT_ZH.md`: finite-path filtering / ordinary HMM scope.
- `control/REPRODUCE.md`: bounded multi-READ MPC and raw / forward replays.
- `economics/REPORT_ZH.md`: delegated cgroup requirements and unexecuted kernel
  success profile; current environment cannot qualify the memory/energy gate.
- `review/REPORT_ZH.md`: independent numerical / record audit and separate
  actual neural-forward replay, with failed-auditor source snapshots retained.

`COST_LEDGER.json` charges enclosing workers once and includes failed attempts.
It is a measured-work lower bound, not complete training/deployment investment.
No unknown cost or unavailable energy/memory measurement is replaced by zero.
