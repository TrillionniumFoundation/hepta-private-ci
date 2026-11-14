# Equal-updates core002: direct-root evidence archive

The explicitly sealed `results/equal_updates_core002/` directory has been archived and verified. This package preserves the new training records, the initial incomplete audit and its analyzer snapshot, the final `analysis002` outputs, and the final cost/provenance explanations. The archive task did not modify source, scientific results, or registration, and did not rerun training or evaluation.

**This archive uses the study directory itself as its logical root.** Its members are names such as `COMPLETE.json`, `runs/...`, and `analysis002/...`. Restore it to `experiments/hcsn_free_boundary_v1/results/equal_updates_core002`.

## Bundle identity

| Item | Value |
|---|---|
| Manifest | `equal_updates_core002_evidence.json` |
| Contract | `hcsn-evidence-bundle.v1` |
| Members | **407 regular files** |
| Original member bytes | **13,616,469 bytes** (12.99 MiB) |
| Compressed bytes | **4,904,848 bytes** (4.68 MiB) |
| Parts | **2** |
| Part 0000 | **4,194,304 bytes** (4 MiB) |
| Part 0001 | **710,544 bytes** |
| Manifest bytes | **72,567** |
| Complete compressed archive SHA-256 | `9e384d4e7514de87e938fdec45bbb38d03e13ca92358b3faf985cd061fccf0f0` |
| Manifest SHA-256 | `771914ebfaecadf609f8abec33c1680bcb149e4172195bb75cf69cdaa0a3fa15` |
| Verification receipt SHA-256 | `84d872e4c37b09347eea74fc1889ba5ed63b4ece4f17eaf5ece94307fcf9d7b5` |

| Part | SHA-256 | Git blob SHA-1 |
|---|---|---|
| `equal_updates_core002_evidence.tar.xz.part0000` | `ad3d5d361c8b5770b84ca57d3e268f1ab2e6233919100ffd043dceb905b4da9d` | `b0420cd67e78bd700c75db09626ea6025cbf8311` |
| `equal_updates_core002_evidence.tar.xz.part0001` | `3fbba4838e14c55e138d324cedbade18619ccde1e91bd2e80264b03f8d525283` | `2553bfa357bb0dc2911fe269d61c92339ba33dd1` |

The manifest supplies exact sizes and SHA-256 values for every member. Bytecode and `__pycache__` are excluded under the existing archive contract; no symlink member was accepted. The output `artifacts/` directory is outside the archived root, so the archive does not include itself.

## Preserved evidence and reading order

| Entry point | Role |
|---|---|
| `README.md` | Final navigation and scope |
| `analysis002/REPORT.md` | Final analysis report |
| `FINAL_AUDIT.md` and `FINAL_AUDIT.json` | Final cost, audit and provenance explanations |
| `analysis002/ANALYSIS.json`, `analysis002/TABLE.csv`, `analysis002/COMPUTE.csv` | Final machine-readable analysis |
| `analysis002/EXECUTION.json` and `analysis002/process.log` | Final analysis execution evidence |
| Top-level `REPORT.md`, `ANALYSIS.json`, `ANALYSIS_EXECUTION.json` and log | Preserved initial incomplete audit |
| `analysis001/INDEX.json` and `analysis001/equal_updates_core002_analysis.py` | Initial-audit index and analyzer source snapshot |
| `runs/` and `process_logs/` | Training, checkpoint, prediction and execution records |
| `REGISTRATION.json`, `REFERENCE_PREFIX_AUDIT.json`, `STUDY001_KEEP_ABSOLUTE.txt` | Registration and reused-baseline dependency evidence |

The archive contains 366 files under `runs/`, 18 process logs, seven files under `analysis002/`, two under `analysis001/`, and 14 top-level files. The initial audit evidence remains distinct from the final analysis. The study's reused main-study baseline material is available through the separate `study001_evidence` archive and repository source.

The source owner explicitly sealed this directory after an independent read-only review, and supplied the final source/artifact hashes below. Each was checked before and after archiving:

| File | Final SHA-256 |
|---|---|
| Repository `equal_updates_core002.py` | `d78fb409d07c0cef5c72469a492f34af9a0d76577841e2d5823e661cd71a6c57` |
| Repository `equal_updates_core002_analysis.py` | `c1ea6191864476f1a7237e14272e8803d8445b8bdfea6ca3e74fdd9984166668` |
| `FINAL_AUDIT.json` | `5ab8e8f4259a79b7b67819df4de89df457fffe248035d54682736dbdc1b95338` |
| `FINAL_AUDIT.md` | `4a58658d106a1127ca8170cedadadaa6fbd8c2d05b7dfa3f3727979254a7f727` |
| `analysis002/REPORT.md` | `fd17b3fa9e91a1a8b8277c0d9d58ab252a2d3597c2e74d6f6cabd03e3cf19f53` |

The final analyzer binding in `FINAL_AUDIT.json` is **post-audit provenance**, not a pretraining registration. The original training protocol and numerical outputs remain unchanged. The earlier analyzer snapshot is included with SHA-256 `33df5f8420a1ac0f1c67a6b536633984714b99e896904bf225eb918091f4ff04`.

## Actual verification

The streaming archive utility packed the study root directly, with no hardlink staging or temporary source tree. An actual `archive.restore` then targeted the same existing study directory. `TemporaryFile` was explicitly prohibited during this restore, and all 407 members were successfully verified and reused without duplicate extraction.

After restore, an independent pass checked every source member's size and SHA-256 against the manifest. All source inodes, modification times, sizes, file membership, owner-supplied final hashes, and the 38 original frozen source files remained unchanged. Both subprocesses exited zero. The archive task performed no deletions or space-triggered cleanup.

| Measured subprocess | Complete CPU seconds | Wall seconds | Peak RSS |
|---|---:|---:|---:|
| Direct-root streaming pack | 5.030368 | 5.039975 | 120,560 KiB |
| Existing-file restore verification | 0.427091 | 0.428021 | 32,308 KiB |

These `os.wait4` measurements include each child process's startup, imports and I/O. The driver's independent source-hash checks are separate. They are archival costs, distinct from the scientific costs preserved in the study's reports.

## Restore command and destination

From the repository root, with both parts adjacent to the manifest:

```bash
python experiments/hcsn_free_boundary_v1/archive.py restore \
  --manifest experiments/hcsn_free_boundary_v1/artifacts/equal_updates_core002_evidence.json \
  --destination experiments/hcsn_free_boundary_v1/results/equal_updates_core002
```

The logical root differs across these bundles:

| Bundle | Example member path | Restore destination |
|---|---|---|
| `equal_updates_core002_evidence` | `COMPLETE.json`, `runs/...` | `experiments/hcsn_free_boundary_v1/results/equal_updates_core002` |
| `study001_evidence` | `results/study001/...` | `experiments/hcsn_free_boundary_v1` |
| `auxiliary_evidence` | `results/...`, `data/native003/...` | `experiments/hcsn_free_boundary_v1` |

The [verification receipt](equal_updates_core002_evidence_VERIFICATION.json) records the exact actual source root, restore destination, commands, measurements, source hashes and member checks. No source or result inside the sealed study directory was changed by this archival task.
