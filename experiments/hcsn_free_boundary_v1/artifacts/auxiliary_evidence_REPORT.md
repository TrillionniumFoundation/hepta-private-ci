# Auxiliary evidence archive

The completed auxiliary evidence is archived and has been physically restored and verified. No scientific experiment was rerun. The running `results/study001/` and `results/conditional001/` trees were excluded, and their outcomes were not inspected for this task.

## Bundle identity

| Item | Value |
|---|---|
| Manifest | `auxiliary_evidence.json` |
| Format | Deterministic POSIX tar, xz, consecutive parts in manifest order |
| Members | **14,162 regular files** |
| Original member bytes | **93,122,699 bytes** (88.81 MiB) |
| Compressed archive bytes | **9,921,604 bytes** (9.46 MiB) |
| Parts | **10** |
| Parts 0000–0008 | 1,048,576 bytes each |
| Part 0009 | 484,420 bytes |
| Manifest file bytes | 3,173,804 bytes |
| Complete compressed archive SHA-256 | `f30f7c22a2de8d37ed4e8f704fb3fd815719e64ec1fcdba6872c07e8ad545259` |
| Manifest SHA-256 | `d84c5eff167f64a412c4f5c77a10bac393b14c3c8c2f52b37c09c89dfce41193` |
| Verification receipt SHA-256 | `aaa3903d034b465a93d9901d7f16612bd8a72a330793fe2ee1f5c0ff40c6022e` |

The manifest records every part's size, SHA-256 and Git blob SHA-1, and every member's original logical path, size and SHA-256. Archive members start with `results/...` or `data/native003/...`; there is no staging-directory wrapper in the archive. Bytecode and `__pycache__` directories are excluded by the published archive utility. No symlink members were accepted.

## Included groups

| Logical group | Files | Original bytes |
|---|---:|---:|
| `results/analysis_preflight001.json` | 1 | 2,839 |
| `results/closure001.json` | 1 | 20,837 |
| `results/oracle_validation.json` | 1 | 23,453 |
| `results/fast_solver001/` | 1 | 653,909 |
| `results/flow_repair001/` | 3 | 167,192 |
| `results/moving_flow001/` | 5 | 948,229 |
| `results/native001/` | 91 | 186,857 |
| `results/native002/` | 2,739 | 39,053,742 |
| `results/native002.process.log` | 1 | 147 |
| `results/native003/` | 10,847 | 48,098,777 |
| `results/native003.orchestrator.log` | 1 | 159 |
| `results/native003_adversarial001/` | 138 | 133,036 |
| `results/native003_adversarial001.log` | 1 | 237 |
| `results/native003_development001/` | 86 | 191,090 |
| `results/review001/` | 169 | 2,080,880 |
| `results/scaling001/` | 55 | 1,086,032 |
| `results/scaling002/` | 18 | 351,752 |
| `data/native003/` | 4 | 123,531 |

Saved development, failure, and superseded/nonfinal records remain included with their original labels. Inclusion means the files were stable and completed; it does not promote exploratory or superseded results into confirmatory evidence. Reproduction sources inside the evidence are included, notably `results/native003/receipt_audit.py`, `results/review001/recompute_audio_cache.py`, and `results/review001/review_real_splits.py`. The four fresh-data files are `fresh_mnist.npz`, `fresh_mnist.json`, `generation_receipt.json`, and `generation_stdout.txt`.

## Actual restore verification

The published, unmodified `archive.py` was used for both packing and restoration. Staging used hardlinks in a separate scratch directory, avoiding an extra copy of the source evidence. The actual first restoration targeted a newly created empty `/tmp/hcsn-auxiliary-restore-autux3qu` directory.

`archive.py restore` verified the part hashes, concatenated archive hash, declared member names and sizes, and every restored member hash. A separate check then compared the complete physical file inventory and independently rehashed all **14,162 restored files** and the corresponding **14,162 original files**. All matched. All **38 original frozen files** were also checked against the original freeze and remained unchanged.

An initial additional inventory assertion used different sorting conventions for `Path` components and full strings. The archive restoration had already succeeded; there were zero missing and zero extra files. The comparison was corrected to use one ordering, the published restore verifier was run again, and all independent file/hash checks passed. This verification detail is preserved in [auxiliary_evidence_VERIFICATION.json](auxiliary_evidence_VERIFICATION.json); neither `archive.py`, the archive manifest, archive parts, nor any completed result was changed in response.

After verification, only this task's newly created restore directory and hardlink staging directory were removed to recover disk space. The original evidence, other workspaces, archive parts, manifest, verification record, and process logs remain intact.

## Restore command

From the repository root, with all ten parts adjacent to the manifest:

```bash
python experiments/hcsn_free_boundary_v1/archive.py restore \
  --manifest experiments/hcsn_free_boundary_v1/artifacts/auxiliary_evidence.json \
  --destination /tmp/hcsn_auxiliary_evidence_restore
```

The command creates the original `results/...` and `data/native003/...` hierarchy under the destination. It refuses to overwrite differing files and accepts already-identical files. The verification receipt records the exact command and destination actually used during this task.

## Result-report entry points

These paths refer to members after restoring the archive:

| Topic | Entry points |
|---|---|
| Original four-channel native causality fixture | `results/native001/SUMMARY.json`, `ADDENDUM.json`, `SOURCE_IDENTITY.json` |
| Frozen hand-policy deployment study, including its negative result | `results/native002/REPORT.md`, `REVIEW.json`, `COST_SCENARIOS.json` |
| Trained price-conditioned native heads | `results/native003/REPORT.md`, `REVIEW.json`, `TRAINING_LOCK.json`, `COST_SCENARIOS.json` |
| Ordinary fixed-prefix adversarial audit | `results/native003_adversarial001/REPORT.md`, `REVIEW.json`, `SELECTION_LOCK.json` |
| Data/source independent checks | `results/review001/audio_cache_review.json`, `real_data_review.json`, `source_review.json` |
| Scalar oracle and mean-state closure | `results/oracle_validation.json`, `results/closure001.json` |
| Distributional-flow and moving-boundary extensions | `results/flow_repair001/results.json`, `results/moving_flow001/results.json`, `results/moving_flow001/REFINEMENT.json` |
| Fast scalar-root solver | `results/fast_solver001/RESULTS.json` |
| Streaming/scaling measurements | `results/scaling002/summary.json`, `performance.json`, `streaming.json`; earlier `results/scaling001/NONFINAL.md` is preserved |

Human-readable companion documents in the source package are `NATIVE.md`, `CLOSURE.md`, `FLOW_REPAIR.md`, `MOVING_FLOW.md`, `FAST_SOLVER.md`, and `SCALING.md`. These package-level source documents are outside this evidence-only archive and remain separate repository files.
