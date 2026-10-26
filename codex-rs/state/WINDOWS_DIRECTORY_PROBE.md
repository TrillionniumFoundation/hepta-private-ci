# Windows directory durability diagnostic

This development probe runs only the exact State test
`sqlite_recovery::windows::tests::directory_probe::records_native_directory_flush_capability`.
The independent `hepta-windows-directory-probe.yml` diagnostic job is dispatch-only,
uses Rust1.96.0 MSVC and the original pinned repository test runners, and selects
one test with one thread and zero retries. It does not run or modify the original
91-case Windows workflow or the Operator26/Shadow31 product oracles.
The new manual collector is ignored in ordinary State suites because it requires
an explicit external output. This diagnostic explicitly executes its exact name
with `--run-ignored only`; a skip, empty selection or wrong test fails collection.
An exact diagnostic-branch push event registers the new workflow with GitHub;
the sole job rejects push events and remains skipped, without a runner. This
registration event is recorded separately from the single native dispatch.

The test creates a new owned scratch root and an atomically private leaf using
the existing State fixture primitive. The unchanged State identity/security
implementation validates full128-bit file IDs, exact owner/DACL bytes, local
NTFS ancestry and no reparse points. A retained original directory anchors all
comparisons. Modes compare ordinary read, BACKUP_SEMANTICS read, read/write, and
read/write plus OPEN_REPARSE_POINT. Each mode follows a new owned child write and
real file sync. The output records actual open errors, full16-byte ID and volume,
raw security descriptor and digest, State privacy admission, Rust sync and direct
FlushFileBuffers return/error, and before/after identity/DACL checks. The original
State directory-sync primitive is exercised separately without replacement.

Two labelled API-sequence probes model Operator and Shadow create/write/file-sync
and ordinary-parent-open/sync steps on owned files. They are not execution of the
actual Operator26/Shadow31 cases, nor proof those modules are repaired. No signer,
credential or real business file is read. Cleanup targets only this test's root
and retains its actual result; diagnostic output stays outside the checkout.

`HEPTA_WINDOWS_DIRECTORY_PROBE_OUTPUT` must name a fresh absolute output file.
The workflow runner sets it under its own new diagnostics directory. A collector
PASS means only facts were collected. The Python assessor separately requires
the writable/reparse-safe mode's real flush, full identity and private DACL, plus
the unchanged State sync result. Unsupported modes remain explicit failures in
the trace. A missing capability keeps the diagnostic job red. Even a supported
mode grants no product authority or sudden-power-loss qualification. A shared
backend and unchanged original case runs are subsequent work.

The first actual run40412971928 collected native read/write flush support, but
its wrapper failed because Nextest printed singular `Starting 1 test`. The raw
failed receipt and absent source/tool-after records remain unchanged. The exact
stdout excerpt and archive provenance under `.github/fixtures/windows-directory-probe/`
regress both singular/plural grammar and exact terminal identity. The collector
now retains actual after facts in a finally path on failure; it never invents
them from source-before. This parser repair does not rerun or qualify the old job.
