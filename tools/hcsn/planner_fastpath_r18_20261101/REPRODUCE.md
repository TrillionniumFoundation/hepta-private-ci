# Reproduce the frozen engineering campaign

Use a fresh checkout of the published source with every `SOURCE_MANIFEST.json` path present, the exact `PUBLICATION.json` receipt, and no existing `confirmation_02` output. The source must match remote freeze `43bed3e4821bfe967e7f9e830e4559b62436daa0` before opening the formal namespace.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.planner_fastpath_r18_20261101.campaign
```

Eight child workers separately verify source and model identities and write create-only raw archives, exact comparison records, preparation/cache metrics and wait4 receipts. Any behavior/state mismatch returns nonzero after preserving evidence. A second invocation in the same directory refuses existing files; use another clean checkout instead. Replaying the same namespace is engineering reproducibility, not new independent efficacy evidence.

The development profile and all three candidate versions are retained. V1's 53 action differences remain failures; V2 and V3 differential fixtures are bit-identical and are not counted as fresh formal confirmation. Profile/differential internal timings are nested inside their full child receipts and must not be added again.

Cache preparation measured inside execute is already included in execute CPU. Per-arm law construction is recorded separately and added once for the incremental comparison. Memory metrics count the inherited law caches together with wrapper cache references, deduplicating arrays per arm; they are not process RSS or globally bounded production memory. Linear reuse estimates and prior-hardware shared training illustrations are explicitly not measured 100/1,000-use or same-hardware lifecycle results.

`confirmation_01` retains the separately frozen V3 run: exact behavior passed, but the all-six value-policy cost gate failed because free/anchored was 0.9094 rather than at most 0.90. Final V4b uses a new namespace and `confirmation_02`; old and new confirmation costs/results are not pooled to make its decision. V4 and V4b development use the same deterministic fixtures and do not add independent scientific samples.

The memory diagnostic raw archive is transported in three bounded parts. Restore its exact logical bytes before rerunning memory raw audits:

```sh
python -m tools.hcsn.planner_fastpath_r18_20261101.restore_artifacts
```

The restorer verifies each part and the full logical SHA256, refuses differing existing files and permits an already-identical original. TRANSPORT_ROUNDTRIP.json records fresh-directory reconstruction. The original227,474B file may be omitted from the remote Git tree; transport parts are each at most80,000B. Top-level ARTIFACT_MANIFEST.json distinguishes these logical originals from published transport files.

`independent_raw_audit.py` is a byte-identical copy of the independent reviewer implementation. Its `run()` imports no planner/executor helper and rechecks all formal raw data; the CLI creates its receipt without overwrites, so use a fresh checkout or call `run()` and save to a new path for another audit.
