# Hepta research continuation — 2026-10-29

This branch contains newly implemented shared-boundary Call–Put dynamics,
explicit associative memory, registered experiments and reproducible evidence.
Public disclosure of the code, checkpoints, raw data and evidence was
explicitly authorized by the user.

## Current evidence

- [Implementation and mathematical scope](experiments/call_put_stable_flow/README.md)
- [Frozen 60-candidate study protocol](research_evidence/hepta_stable_flow_20261029/formal_run001/protocol.json)
- [Numerical qualification and retained failures](research_evidence/hepta_stable_flow_20261029/numerical_qualification/README.md)
- [Trained-checkpoint diagnostic contract](experiments/call_put_stable_flow_appendix/README.md)
- [Inference-cost contract](experiments/call_put_stable_flow_appendix/RUNTIME.md)
- [Preregistration evidence archive](research_evidence/hepta_stable_flow_20261029/releases/hepta_stable_flow_preregistration_20261029.tar.gz)
- [Independent archive readback audit](research_evidence/hepta_stable_flow_20261029/independent_review/release_preregistration_audit.json)

The formal training run is in progress. Validation selection and test scoring
remain locked until all registered candidates finish. The preregistration
archive contains 186 source/data/evidence files and excludes the growing
training outputs. It is not a completed-experiment archive.

The archive is 1,425,167 bytes, SHA-256:

```text
0047e9ec766a67d8d0530006231cd6624225e656436286d8019eeff5d7c7d4e3
```

Verify it without installing PyTorch or rerunning experiments:

```bash
python -I -S experiments/call_put_stable_flow_analysis/release.py verify \
  --archive research_evidence/hepta_stable_flow_20261029/releases/hepta_stable_flow_preregistration_20261029.tar.gz
```

After extracting into a fresh directory, run the package's own verifier:

```bash
python -I -S EXTRACTED/experiments/call_put_stable_flow_analysis/release.py \
  verify-tree --root EXTRACTED
```

## Historical recovery limitation

The previous unpublished checkout and raw archives were removed by workspace
maintenance before publication could execute. Two genuine complete reports
and original verification receipts were recovered and are preserved
[with exact hashes and the missing archive identities](research_evidence/hepta_callput_recovery_20261029/README.md).
Those reports retain their original wording, including a superseded permission
blocker. Permission is now resolved; missing historical bytes are a separate
issue. New experiments have new identities and do not reconstruct the missing
historical commit or raw measurements.

An original `Hepta_CallPut_Followup.bundle` would restore the lost Git objects.
An original `Hepta_Complete_Research_Evidence.zip` would restore the scientific
files, but does not by itself restore the lost Git commit identity.
