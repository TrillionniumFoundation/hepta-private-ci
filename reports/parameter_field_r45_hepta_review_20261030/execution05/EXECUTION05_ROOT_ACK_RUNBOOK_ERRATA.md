# Execution05 root ACK runbook erratum

Recorded at: 2026-10-30T13:04:50.350558+00:00

Frozen source commit: `7544b0a57a3b5624f3f2190449efeb84854b414d`.
This sidecar records the operational correction outside the frozen Git source and RAW evidence.

## E01: `prepare-readback` requires `--upload-stdout`

Section 4 of the frozen `ROOT_ACK_RUNBOOK.md` incorrectly calls `--upload-stdout` optional and omits it from the command example. The frozen `archive_io.py` CLI declares this flag with `required=True`. The internal helper's optional parameter does not make the CLI argument optional.

The correct command shape for every stage is:

```text
VENV -B ARCHIVE_IO prepare-readback
  --work-directory STAGE_WORK
  --upload-wait4 STAGE_WORK/upload_step/WAIT4.json
  --upload-stdout STAGE_WORK/upload_step/helper.stdout.log
```

Use the exact `stdout.path` from the already successful upload's actual `WAIT4.json`; its descriptor must match that receipt. For the actual A17 upload, that path is:

```text
/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_archive_io/01_A-17/upload_step/helper.stdout.log
```

The first actual A17 metadata preparation exited 2 during argument parsing, with empty stdout. Its original INTENT, WAIT4, stdout and stderr remain at the first engineering directory. Argument parsing failed before `prepare_readback` executed, so that attempt did not invoke a remote action or produce the readback plan.

Root used the existing successful upload evidence and measured the corrected metadata invocation in a new engineering directory, `01_A-17_prepare_readback02`. Its actual wait4 reports exit 0 and `command_success=true`. The successful upload was not replayed to repair this local CLI omission. Completed preparation and its receipts remain preserved.

This correction changes neither science nor the archive protocol, the original 17 barriers, the required independent readback, the supervisor identity checks, nor ACK publication authorization. SOURCE and RAW were not edited to record this erratum.

## Exact evidence descriptors

```json
{
  "corrected_metadata_preparation_wait4": {
    "bytes": 1845,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_archive_io/_engineering/01_A-17_prepare_readback02/WAIT4.json",
    "sha256": "abd1223f7c58fdea71f05fb097b54fcf86420661557e308493ff76f407125183"
  },
  "first_metadata_preparation_stderr": {
    "bytes": 302,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_archive_io/_engineering/01_A-17_prepare_readback/helper.stderr.log",
    "sha256": "3d1f55372f8baa6f11f2ab3c8a73195523d75c29c132c8f19217ba0c8d4ca952"
  },
  "first_metadata_preparation_wait4": {
    "bytes": 1806,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_archive_io/_engineering/01_A-17_prepare_readback/WAIT4.json",
    "sha256": "de9f4a56fbe3cdb6e0af0fbfdb9356247cfe4d9f14880dc9dd1a01948bfb3939"
  },
  "frozen_archive_adapter": {
    "bytes": 22851,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_recovery05_git/operational/parameter_field_recovery05/archive_io.py",
    "sha256": "27459ed53282fce7f6a381c11da49347bcfb2e8f94c10865808843d19255d09f"
  },
  "frozen_runbook": {
    "bytes": 10922,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_recovery05_git/operational/parameter_field_recovery05/ROOT_ACK_RUNBOOK.md",
    "sha256": "bf53033fec7622e1c1dfa762ade46e9899647e95ab8c437b994d04decc1d6d66"
  },
  "original_successful_upload_wait4": {
    "bytes": 1787,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_archive_io/01_A-17/upload_step/WAIT4.json",
    "sha256": "268eeba4c32f38fa4f947dbf69c939c0c538fb4c82aeb95a96647781e2070b1b"
  },
  "upload_stdout": {
    "bytes": 2189,
    "path": "/workspace/scratch/178ced6a501f/fullstudy_execution05_ops/root_archive_io/01_A-17/upload_step/helper.stdout.log",
    "sha256": "66cb22908e6d7c8f5a9733c3f78e7b94078fd0064a16ee8d417d134f1de8b24d"
  }
}
```
