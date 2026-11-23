# Four-amplitude Adam recovery on Torch CPU 2.10

Candidate `b0bc5cf5bea7cb1aa4a320c5b87d884e9e083b70` binds two fixed
geometries, four initial-amplitude tensors, the original baseline archive and
the true remote workflow. The controller and actor accepted the sealed
descriptor in source-only mode and each refused a stale identity and a changed
inventory digest. These six source-only checks incurred zero optimizer updates.

Before the hosted artifact became available, the retained-value inspector was
exercised on the complete original #6253 archive. It decoded 17 checkpoint
payloads and checked 13 losses and nine four-tensor update events. It reads
checkpoint records without importing Torch. Its upstream implementation and
strict reader are from `qualification/hcsn_ci_readbacks/6253-actual001/independent-review/`
at `de4ef594bfefec05a64fc2ae3b717a640a57b263`. The current inspector accepts the
independently obtained artifact SHA, source SHA, run ID and job ID as inputs.
Additional checks bind eight distinct PIDs, nonces, terminal statuses, actual
exit codes and the exact total numerical work to that run.

Once a downloaded archive is in `WORK/ORIGINAL.zip`, run
`python unpack_evidence.py WORK` and `python inspect_retained.py --help`.
Use the candidate's frozen `CURRENT_SOURCE.json` and original NUMPY001 archive.
