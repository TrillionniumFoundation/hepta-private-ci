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

When the archived original is in `WORK/ORIGINAL.zip`, run
`python unpack_evidence.py WORK` and `python inspect_retained.py --help`.
Use the candidate's frozen `CURRENT_SOURCE.json` and original NUMPY001 archive.

## Hosted execution and independent readback

[Run 45111212131, job 137483750375](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45111212131/job/137483750375) passed on the pinned CPU runtime. The original 986,525-byte ZIP in this directory matches its GitHub artifact SHA-256 `e2a02c10f197f8cdd6feba81963814e73e658b6992bea7c91292631c53409065`. All 66 archive members passed CRC and byte checks. The independent reader decoded all 17 PT/pending payloads, checked each loss and adjoint against the retained independent baseline, and reconstructed 36 per-tensor parameter updates. Both geometries matched exactly on the complete first- and second-step state and next stochastic loss, target, output and four gradients.

Eight actors made 13 forward and 13 adjoint calls and completed 9 Adam updates. Eight updates belonged to the positive paths. The ninth was deliberately written to a pending file and interrupted before replacement. The old published checkpoint survived byte for byte. The missing-Adam control exited 42 before any numerical call. The crash control exited 73 after its update. The complete child process tree took 35.765 seconds wall and 35.475 seconds CPU.

The numerical result applies to four learned initial tensors at the two fixed geometries. Full-network optimization, cross-runtime recovery, energy, task generalization and financial-model boundary parameter training require their own measurements.
