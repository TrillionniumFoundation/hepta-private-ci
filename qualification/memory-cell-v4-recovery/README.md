# V4 interrupted-delivery recovery

Workspace maintenance removed the local V4 checkout before its full archive was
uploaded. The surviving two bundle parts and figure were anchored first. A
separate read-only GitHub Actions task then verified the complete older V1/V2
and V3 bundles and salvaged complete, individually hashed V4 objects.

**Partial recovery: 190 original final-commit files / 30,434,818 bytes.**
There are 32 missing tree/blob entries; some represent whole
directories. Only 155 of the original 6181 formally
sealed output files are currently present and hash-verified. The remaining
6026 are absent. The full original V4 source tree, source snapshot and
formal evidence are **not** restored. Job success means the recovery procedure
completed; it does not change that conclusion.

The recovered historical [RESULTS](recovered-final/qualification/memory-cell-v4/RESULTS.md),
[QUALIFICATION](recovered-final/qualification/memory-cell-v4/QUALIFICATION.json),
and [MEASURED_SUMMARY](recovered-final/qualification/memory-cell-v4/MEASURED_SUMMARY.json)
are exact original bytes, not a fresh re-verification of missing artifacts.
They already reported all_blockers_closed=false and production_admitted=false.
Only a declared subset of small recovered files is mirrored here. The original
formal MANIFEST is retained losslessly in ORIGINAL_FORMAL_MANIFEST.json.

- Original final evidence commit: `3c509f9bb9a9724cddbe6a917c728e022582fefe`.
- Original executed source target: `6206dfba0a3219534dd1a0274431bf48fd23673c`.
- Recovery control source: `c7aba9a0b06d3483257891b6d743b74fc7594604`.
- [Actual recovery run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40464059557).
- [Complete recovery artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40464059557/artifacts/12716196009),
  SHA-256 `1c0e080770ed1658649fd5928a3a57650f7cb71d5f08c5613976e209d0c76859`.
  GitHub retention currently expires 2026-11-10 06:56:53 UTC.

RESTORED_INDEX.json maps each of the 190 exported files to its original commit
path, Git object identity and SHA-256. RECOVERY_STATUS.json records missing paths,
the precise formal coverage, all mirrored-file identities and scope limitations.

The artifact's bare salvage store references a runner-specific alternate object
directory. Exported files are portable; further Git reads require rebuilding the
base from the included older bundles and repointing that alternate. No training
or old result generation was run. Never fill missing historical outputs from
reported metrics and present them as the old experiment.

New V5 work is an explicitly new study built on recovered V3 code and the four
verified saved numerical memories/layout. It does not overwrite missing V4
history or claim that the missing typed-memory, maintenance and structure
experiments have been recovered.
