# Execution05 resource-threshold wording erratum

Recorded at: 2026-10-30T13:44:26.085295+00:00
Frozen source commit: `7544b0a57a3b5624f3f2190449efeb84854b414d`.

## Correction

Earlier stage-integrity observation commentary called 2.25 GiB the next-worker admission gate. That wording was incorrect. The numerical capacity samples remain the original observations, but a sample below 2.25 GiB does not by itself establish that a science worker is blocked or has failed.

The frozen execution05 supervisor defines `RAM_GATE=1,879,048,192` bytes (1.75 GiB) and `DISK_GATE=2,415,919,104` bytes (2.25 GiB). Its `gate()` is called at initial startup, aggregate-analysis capacity admission, and finalization capacity admission. The source has exactly these three calls. It requires three consecutive satisfactory samples, separated by the original interval. Neither constant is a universal per-worker runtime floor.

The controller admits a new worker using the original `memory_admission(selected_reservation, margin, pending_growth(root))`, then `verify_job` and `storage.check()`. The reservation can depend on previously observed family peaks. The physical storage condition is available bytes at least **256 MiB plus the current filesystem-rounded allocation**, with at least **2,000 available inodes**. The original logical RAW and C-evidence caps and memory/pending-growth checks also remain. Execution05 backpressure waits around these original constraints; it does not replace them with a 2.25 GiB worker threshold.

The supervisor's archival heartbeat separately requires at least **258 MiB** of physical free space, **2,000 available inodes**, and its original **1 GiB effective RAM margin**. Its OOM and absolute deadline checks remain independent conditions.

The earlier `worker_gate_headroom` label used for arithmetic against 1.75 GiB should likewise be read as distance from the supervisor's fixed RAM-gate constant. It is not a substitute for the current worker's actual reservation and pending-growth admission calculation.

## Interpretation and preservation

The rapid disk-capacity declines observed during A29 were real sampled values and matter to whole-pipeline capacity, including future analysis, finalization, archiving and readback. The mistaken next-worker label is corrected by this additive sidecar. Original samples, cleanup reason/completion receipts, source files, and scientific evidence are unchanged.

A completed deletion receipt records the operation observed at its own time. It does not establish that the same pathname remains absent indefinitely. Later filesystem existence observations must be reported separately, even when they disagree with the earlier completed-retirement state. This erratum neither asserts present absence of retired paths nor infers why a path may later exist.

This threshold correction does not establish the cause of the execution05 failure or the execution-service disconnection. Those causes require separate process and failure evidence. No scientific task, observer, supervisor, upload or ACK was restarted by this correction.

## Exact source identities

```json
{
  "backpressure_adapter": {
    "bytes": 40624,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_recovery05_git/operational/parameter_field_recovery05/resource_backpressure.py",
    "sha256": "8c179f68253c4c6559b76b18ca1afd7109fa99a6e39fae4c150514fe97267bca"
  },
  "resource_contract": {
    "bytes": 13484,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_recovery05_git/experiments/parameter_field_fullstudy_20261029/resource_v2.py",
    "sha256": "079b326b6d42cb9dccac2cbe8e872cb30e221169f6e0f650469e2a53774624bf"
  },
  "supervisor": {
    "bytes": 51312,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_recovery05_git/operational/parameter_field_recovery05/supervisor.py",
    "sha256": "e91ddc38e374f37c379618cbf89bb05a46e265a5e9865afbe3d47a585934661b"
  },
  "worker_controller": {
    "bytes": 21330,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_recovery05_git/experiments/parameter_field_fullstudy_20261029/launch_v2.py",
    "sha256": "7423f368c7ec8fd39a666c575f91e36f69da78bd1ec6cdc39f3afbe8224332e3"
  }
}
```
