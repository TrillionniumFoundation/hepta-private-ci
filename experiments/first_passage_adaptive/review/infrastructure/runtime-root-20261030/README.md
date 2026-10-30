# Runtime owner repair verification

This package retains fresh checks after restoration of the transient workspace.
The source baseline is `9b71cf4e65194593d5e0fb2a507026d21527a740`.
`ROOT_RECOVERY_FINDINGS.json` explains the ownership, migration, historical
materialization and Darwin publication changes. `SOURCE_IDENTITY.json` records
the final local source bytes after scoped Clippy and canonical formatting.

## Observed local results

| Scope | Result |
| --- | --- |
| Research Python suite | 50 passed |
| Historical native bridge | 9 passed, using the original pinned owner source |
| Holdout CAS owner library | 128 passed, 0 skipped |
| Selected memory migration and recovery cases | 2 passed; 277 other tests not selected |
| Selected automation migration case | 1 passed; 17 other tests not selected |
| Complete Fleet owner library | 42 passed, 0 skipped |
| Scoped canonical `just fix` | Exit 0 for Fleet, memory, automation, holdout evaluation and operator acceptance |
| Canonical `just fmt` | Exit 0; six files formatted |
| Frozen scientific source identity after formatting | All 39 hashes match |

The Clippy log retains existing test-style warnings. Exit 0 does not mean that
the owner crates have no warnings. No tests were rerun after fix or format;
integrity checks of the retained evidence and frozen source are separate.

The initial unrestored-data Python run, missing-tool attempts and the Fleet
ENOSPC failure are preserved alongside successful later runs. The shared-target
queue artifact failure and its unresolved metadata origin are retained in the
sibling `runtime-holder-20261030` package. No environment failure is counted as a
passing test. Only completed, reproducible caches or byte-identical sparse
working copies were reclaimed, with explicit receipts; source objects, logs and
other tasks' data were preserved.

## Retention and reproducibility

The archive contains 32 explicitly selected original logs and receipts.
`retained/manifest.json` binds every member and each bounded archive part.
`VERIFICATION.json` records the actual pack check, restoration to a fresh
directory, and verification of the restored bytes. No compiled executable or
build cache is included.

From the repository root:

```sh
python3 experiments/first_passage_adaptive/retain_evidence.py check --manifest review/infrastructure/runtime-root-20261030/retained/manifest.json
python3 experiments/first_passage_adaptive/retain_evidence.py restore --manifest review/infrastructure/runtime-root-20261030/retained/manifest.json
python3 experiments/first_passage_adaptive/retain_evidence.py check --manifest review/infrastructure/runtime-root-20261030/retained/manifest.json --include-restored
```

Restoration recreates the archived evidence. It does not train a model, open a
new confirmation, execute a rollout or rerun a native test. Earlier snapshots
remain historical evidence; exact submitted bytes require their own hosted CI.

## Acceptance boundary

The Linux Fleet result supports the changed publication sequence and rejection
of an unsealed catalog root. Native Darwin behavior still requires macOS CI.
The complete queue owner, Windows-specific platform contracts, Mac process and
PTY behavior, and previously blocked repository targets remain new-head CI
gates. Production activation stays disabled. Scientific models, seeds and both
favorable and unfavorable confirmation outcomes are unchanged.
