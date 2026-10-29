# Hepta research continuation — 2026-10-29

This branch contains newly implemented shared-boundary Call–Put dynamics,
explicit associative memory, registered experiments and reproducible evidence.
Public disclosure of the code, checkpoints, raw data and evidence was
explicitly authorized by the user.

## Current evidence

- [Implementation and mathematical scope](experiments/call_put_stable_flow/README.md)
- [Mathematical analysis and limits](experiments/call_put_stable_flow_analysis/ANALYSIS.md)
- [Frozen 60-candidate study protocol](research_evidence/hepta_stable_flow_20261029/formal_run001/protocol.json)
- [All 60 candidates and 300 weight checkpoints](research_evidence/hepta_stable_flow_20261029/formal_run001/candidates)
- [Independent complete-training audit](research_evidence/hepta_stable_flow_20261029/independent_review/training_complete_integrity_audit.json)
- [Numerical qualification and retained failures](research_evidence/hepta_stable_flow_20261029/numerical_qualification/README.md)
- [Trained-checkpoint diagnostic contract](experiments/call_put_stable_flow_appendix/README.md)
- [Inference-cost contract](experiments/call_put_stable_flow_appendix/RUNTIME.md)
- [Preregistration evidence archive](research_evidence/hepta_stable_flow_20261029/releases/hepta_stable_flow_preregistration_20261029.tar.gz)
- [Independent archive readback audit](research_evidence/hepta_stable_flow_20261029/independent_review/release_preregistration_audit.json)

All 60 registered training candidates have completed, with all 300 budget
checkpoints independently audited and publicly preserved. The successful
training orchestration took 4,977.18 wall seconds; its 60 children used
18,077.66 total CPU seconds, of which 17,401.72 seconds belonged to the defined
training-update clock. Validation selection began only after the complete
training seal was written. Selection, numerical checks, primary test scoring,
inference timing and the final scientific report are still being completed.
No held-out performance or general architectural advantage is asserted here.

The preregistration archive contains 186 source/data/evidence files and excludes
training outputs. It is a prior snapshot, not a completed-experiment archive.

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
