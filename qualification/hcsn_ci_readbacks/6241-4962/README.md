# Partial hosted readback for #6241 head4962

The existing successful initial-amplitude [run43200740354 / job131123196305](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43200740354/job/131123196305) at exact source `4962e28c1ffa073e5e994194f3b5785659af236c` adds a separate 39 basis DDE forwards plus 2 reported uniform-oracle forwards and zero optimizer updates. Probe wall/CPU: 9.160633599 / 8.614676007 seconds; peak RSS423980KiB. Runtime is Python3.12.16, Torch2.8.0+cpu, one CPU thread.

This evidence commit preserves the complete decoded job log, GitHub run/jobs/artifact API metadata, a JSON substring of the logged result, and all13 original source blobs. Fresh current-source Git blob identities match the prior independently SHA256-witnessed exact894 sources, and the logged source hashes agree before/after. No model source head was changed and no rerun/native dispatch was requested.

**ZIP byte/SHA256 and raw NPZ/member readback remain UNKNOWN_PENDING_EXECUTOR.** Artifact13936125116 is advertised as11597B, SHA256 `1dd17c8ac54cab00242af1d7ce88a1cefcde24c7ecaf3ba8634fd1bdcf978e7c`. The local executor is unavailable. No ZIP, raw artifact RESULT/CALLS, or NPZ is fabricated here. `LOG-RESULT.json` is explicitly extracted from the decoded job log; it is not the raw artifact member.

`RECOVERY_POINTER.json` freezes the same existing artifact identity and the read-only continuation steps. Recovery must fetch existing bytes and must not repeat any numerical/model/native job. The archiver performs zero candidate/DDE/model/Torch/optimizer executions. The existing39+2 CI calls remain separate from prior native and hosted attempts.

Scope remains the bounded fixed-physics/support initial-amplitude fixtures. No n512, full-network, complete training, normalization-vector or adoption qualification is added. HOLD_NO_GO. All paths are under `qualification/hcsn_ci_readbacks/6241-4962`, outside model-source workflow paths.
