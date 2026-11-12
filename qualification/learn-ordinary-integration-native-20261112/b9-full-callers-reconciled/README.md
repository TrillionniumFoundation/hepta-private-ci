# Reconciled original b9 complete caller scan

The durable ai395 job `1a1ceafdd3e-2564-17b8` finished on 2026-11-12 at 07:51:36 UTC and was read back after transport recovery. It ran the unmodified complete repository caller verifier for 900.461536 seconds and exited 1. The execution was neither timed out nor cancelled. Source stayed clean at local `b9d00ed288e6056f47c3617b2eec36cabe25e2ec`, tree `cf6955ee9a05c9709d2c02b7467f445e4abbc089`, equal to the published source tree at `bfa82689b26150929a5ffdb55ee4b153d545550e`.

The exact 184-byte failure in `command.log` identifies the unproved `readback` receiver in `state_circuit_task.rs` under boundary `q24_task_original_ledger_readback`. It is not a native test result or a timeout. The raw manifest and log were read back with provider file hashes; the log SHA-256 is `7ef2f38c65361f15e2ad4613e10d829b5239f4672e96dcf865b5d2d208177102` and the manifest SHA-256 is `c110e50b97f03e30a9f55e74fcf3c467f69e98bd291c8652f542aa39a6aadb57`.

This resolves the prior UNKNOWN observation for this job only. The earlier cloud 399 scan and the h Outcome-macro mutation remain unknown. A later source correction and its verification require their own exact source identities.

For recovery provenance, the independent Root import job `1a1ceca2684-2564-184a` also returned a durable failed terminal state: cherry-pick could not determine a committer identity. Its exact stderr is retained separately; it did not run a test or imply loss of the preserved source bundle. No job was restarted or cancelled during reconciliation.

Full ordinary A-to-C positive, NoUpdate and daemon-plus-Root cold-restart qualifications remain 0 / 0 / 0.
