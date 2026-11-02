# Replay

From the repository root, first restore R20 native raw evidence with tools/hcsn/native_runtime_r20_20261101/restore_evidence.py and restore its exact executable aliases with restore_binaries.py, following that component BINARY_RESUME.md. R22 SOURCE_FREEZE.json gives all required original input hashes.

Use a fresh output path:

```sh
python -m tools.hcsn.auth_recovery_r22_20261102.meter --output /tmp/hcsn-r22-auth-new-replay
python -m tools.hcsn.auth_recovery_r22_20261102.audit --output /tmp/hcsn-r22-auth-new-replay
```

The fixture key is intentionally public. These are bounded correctness tests, not deployment instructions. The checker requires OpenSSL. Both negative witness exits are expected; the top-level verifier and independent checker must exit zero. The original four task worlds remain R20 worlds.
