# Native Cell physical-node qualification

This directory contains executed research code and complete evidence for a replicated native numerical Cell on main and x230. Read [NETWORK_REPORT.md](NETWORK_REPORT.md) for the 32-trial stronger local baseline, original-owner cancellation, same-parameter generation-3 reload, costs and limitations. The measured distributed organization does not beat the pure-local baseline.

The worker links the original Cell implementation from PR #4290. `network_study.py` is the first 18-trial study; `network_followup.py` adds the pure-local arm; `network_lifecycle_probe.py` performs the four separately owned lifecycle phases. `native-worker/Cargo.lock` is the actual executed worker lock.

## Restore exact evidence

Run the provided `restore_evidence.py` against a new output directory. It joins the listed base64 parts, verifies archive and inner manifest SHA-256 values, rejects unsafe tar paths, and verifies every extracted file. It does not start a worker or execute an external effect.

```bash
python3 qualification/cell-meta-network/restore_evidence.py /tmp/hepta-cell-network-evidence
```

Raw timing fields and repeated-input scope are preserved. This code is not a production meta network or a standalone general agent. The P3 system-level net-benefit gate remains open.
