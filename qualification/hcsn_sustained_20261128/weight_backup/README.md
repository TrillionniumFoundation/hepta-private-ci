# Cross-host weight recovery

This finite backup covers the current RSICD caption study and the separate full-epoch CREMA-D billion-parameter study. The source is the ai395 local NVMe filesystem. The copy is on the desktop local ext4 filesystem. The service first checks the pinned SSH host key, the source system identity and the distinct destination system identity. No remote cloud storage is involved.

## Scope

The fixed roster contains 36 immutable RSICD weights (four encoders, three seeds and three training budgets), 12 final RSICD optimizer/resume states and six complete one-billion-parameter epoch checkpoints (two architectures and three seeds). A large checkpoint becomes eligible after its fit record reports 312 updates over 4,984 unique examples and verifies the finalized file's size and SHA-256. The source model files remain owned by the original studies.

Each transfer resumes into a private partial file, verifies the complete input SHA-256 and uses an atomic rename. On both machines, PyTorch opens the weights on the CPU and verifies a canonical digest of the sorted names, tensor dtypes, shapes and numerical bytes. The full optimizer container is separately identified by its whole-file digest whenever copied. The destination uses mode 0600 for weights and mode 0700 for their directories. The capacity budget reserves future required models, 5% of disk space or at least 8 GiB, and selects a model-only copy when a full optimizer package would exceed the budget. For the RSICD final resume fallback it checks the separately restored 900-second model. Each receipt identifies the selected representation. Complete original optimizer states remain on the source.

## Service and recovery

The desktop user service is named `hcsn-weight-backup-1140569.service`. The installed unit has `Restart=on-failure` and user lingering enabled. It uses one CPU thread, low CPU and I/O priority, a single writer lock and the existing SSH host identity. It exits upon completing this specific roster. The serve route and executable hashes are checked on startup.

On the destination, inspect `systemctl --user status hcsn-weight-backup-1140569.service` and `status.json` below the private destination directory. To resume the same task, run `systemctl --user start hcsn-weight-backup-1140569.service`. The owner waits behind an already running copy. The completion file records all 54 receipt hashes, each fallback, both study selections and the originating ledger. The service writes this file only after the six full epochs and all their eligible peers have been resolved. Read `complete.json` to establish finality.

See `launch.json` for exact task directories, enrollment disk figures and identity digests. The timestamped `initial_status.json` and `first_verified_checkpoint.json` preserve early observed copies while the training programs continue.
