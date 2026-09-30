# KG execution postflight closure — 2026-09-27

Parent guide: `docs/modules/knowledge.graph/TECHNICAL.md`.
Candidate narrative: `qualification/knowledge-graph/EXECUTION_20260927.md`.
Fixed base: `a126987b84737dbc2ee2592442a314117bddb4a2`.
Branch: `work/kg-abc-execution-20260927` (PR #1110).

## Changes and claim boundary

The measurement-fixture path fix in `a1ca5cf3fe3afa1d65439fc436d0dc1116457b77`
resolves the temporary executable path before constructing the synthetic Cargo
artifact. It corrects the macOS `/var` versus `/private/var` alias mismatch without
removing executable-digest drift, missing-artifact, skipped-test or actual-count
rejection. This is a harness portability fix, not a native performance result.

The execution matrix now also runs `scripts/hepta_kg_execution_audit.py` in an
`always()` postflight step. Its expected inventory is profile/lane-specific. It
rejects missing, duplicate, unknown or malformed command records, nonzero exit
codes, missing logs, zero-test or partial native runs, zero-test Python runs,
changed source/tree identity and dirty tracked source. Explicit crash/history
checks must run exactly one test with no ignored tests. Each present log is
SHA-256 bound with its byte length. The source/base must be ancestors of the
actual tested commit; the existing deterministic merge action remains responsible
for constructing the fixed-base merge candidate.

Command and tee exit statuses are both preserved. A failing command records its
failure but the wrapper explicitly returns to the caller so other checks can run.
The aggregate job and the postflight still fail. Repository-wide implementation
map failures remain required failures; this change does not rebind unrelated
module provenance or convert global failures into warnings.

`execution-audit.json` is an observed local CI inventory. It is not a signature,
an independent oracle, or a grant. Its `completeAndPassed` field applies to one
lane/profile on the stated commit only. All required matrix lanes must separately
complete. `targetHostQualified`, `independentAcceptance` and `release` remain
false; ordinary test logs cannot change them. An externally killed worker may
prevent even an `always()` step from finishing: absent audit/artifact is missing
evidence, never successful qualification.

## Actual local verification

Before committing this change, the 13 tests in
`scripts/test_hepta_kg_execution_audit.py` were executed with Python unittest and
passed. A separate real-subprocess CLI smoke check created a temporary Git
repository, accepted a clean source-head fixture, then rejected the same fixture
after a tracked source edit. These tests deliberately use synthetic execution
logs. They validate the checker only; they do not prove Rust, SQLite, crash,
Agentd, target-machine latency or storage performance.

Reproduce the checker tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p test_hepta_kg_execution_audit.py -v
```

## Preserved B/C implementation boundary

The candidate retains validated immutable generations, incident-edge indexing,
transaction-local generation/support-index caches and indexed/reference tests.
The writer still computes a bounded complete canonical generation. The
`revision_facts_v1` representation stores revision facts and generation receipts;
it does not copy every physical node/edge for each generation. No runtime
incremental-writer promotion is made by this change.

Native history, crash, concurrency and release-measurement steps remain in the
matrix. Hosted-CI regression caps remain distinct from a preselected target
CPU/storage acceptance profile. Current successful native and target-host
receipts must be obtained before A/B/C can be marked fully accepted. Prior
queued/skipped/failed runs and the checker tests above are not substitutes.
