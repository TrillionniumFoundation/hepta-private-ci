# Exact Library security-reproduction source custody (2026-11-05)

This isolated Draft contains **two exact original Library Python source objects**. It is a source-preservation checkpoint, **not a claim that the full Library has been migrated or that product gates passed**.

| Source | Original SHA-256 | Git Blob SHA-1 |
| --- | --- | --- |
| `hepta_git_replace_local_repro.py` | `edf46036fde23390464f87d9e12aa07114988173a0d2fed03b097e63dc3ed98a` | `4eccd59fa5ddbc1f2fb29c25e6ac68096bf8393f` |
| `hepta_privileged_timeout_regression.py` (original Library basename `hepta_privileged_timeout_regression(1).py`) | `010a5764cb729fa3dda1c7564baa34faac4dc2e315012bb2e04f92a58c041057` | `c09a1f00ef5b5ea14888b48f3aebd8834546d4dd` |

## Reproduce

Run using Python 3 with Git on a disposable Unix-like host; the timeout test creates a temporary `sudo` shim and does not require root:

```bash
python -m py_compile audit/library_recovery_20261105/hepta_git_replace_local_repro.py audit/library_recovery_20261105/hepta_privileged_timeout_regression.py
python audit/library_recovery_20261105/hepta_git_replace_local_repro.py
python audit/library_recovery_20261105/hepta_privileged_timeout_regression.py
```

The first script demonstrates why Git replace refs and assume-unchanged can deceive an unguarded object-versus-worktree comparison. The second script demonstrates a historical timeout bytes/JSON failure and invalid UTF-8 failure, then exercises defensive handling. On 2026-11-05 both scripts exited 0 locally (and `py_compile` passed); this is not an end-to-end CI or release qualification.

Source policy: no archived raw logs, private workspace dumps, large evidence blobs, model weights, or identifying Gmail addresses are copied here. The source files are referenced by their **original already-present Git Blob IDs**, preserving their exact bytes, not reconstructed text.

Historical frozen migration scope: 6,116 candidates / 5,887 previously verified / 229 unresolved in the re-computed 2026-11-05 snapshot, *before* this path-level source custody. The live Library and original dot-host worktrees still need independent verification. **HOLD / NO LIBRARY PURGE.**
