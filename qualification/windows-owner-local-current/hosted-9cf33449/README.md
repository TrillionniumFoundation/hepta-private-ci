# Exact owner-local source qualification

This evidence-only branch preserves product source 9cf33449107981ee2ca4de486be8ffaaa37dfc61 unchanged. All four jobs of original workflow 41705418271 completed successfully on that exact source.

| Actual native platform | UDS | Matrixd | Fleet | Automation | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Windows 2025, MSVC | 14 | 31 | 36 | 25 | 106 |
| macOS 15 | 10 | 31 | 42 | 25 | 108 |
| Ubuntu 24.04 | 10 | 31 | 42 | 25 | 108 |

All 322 original library cases passed with zero failures or skips. Every case was independently read from original nextest JUnit, counted against the log summary and checked against the required test names in the exact source harness. All three original scoped Clippy commands succeeded. Each artifact binds 286 input paths, independently read from the exact Git source; before and after hashes agree. These are 286 distinct paths verified in four artifacts, not 1,144 distinct source files.

The Linux native prerequisite built the pinned official D-Bus 1.16.2 client and ran its real identity probe. All 52 commands exited zero and all seven recorded inputs match exact Git bytes. The identity output covers the wire ABI, pidfd identity, ordinary-FD rejection, peer UID/PID and high-FD closure.

Original Bazel committed-lock check, update and repeated check all succeeded. The generated MODULE.bazel.lock is exactly the committed 1,701,389-byte file, SHA256 1a58f7d1fcbfe850d18a01c19faf15c941dfd229cb8caeb406dbe8ce8c99522e. All four original UDS, Matrixd, Fleet and Automation targets actually executed and passed; none was reported as a cached test. This artifact has original full command logs but no individual Bazel test XML, so no per-case Bazel count is asserted.

The four original GitHub ZIP archives are preserved as seven raw binary parts, each at most 384000 bytes. Concatenation reproduces the GitHub digest and size exactly; ZIP CRCs passed. No archive content is executed by the restore or verification scripts.

## Restore and verify

From a clone containing the tested commit, choose a fresh output directory:

```bash
python3 PATH/restore.py --output /tmp/owner-local-original-results
python3 PATH/verify_all.py --repo . --artifacts /tmp/owner-local-original-results
```

Replace PATH with this directory. The verifier reads the exact Git blobs and the original archived logs, metadata and XML only. It does not invoke Cargo, Bazel or a native binary.

This is scoped exact-source qualification. The private-state and Agentd successor, original complete CI, scientific acceptance and production admission remain separate. No older failure is erased. DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO remains in effect.
