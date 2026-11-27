# Independent Ubuntu 22 runner attempt

The registered native and two-runner qualification jobs on `ubuntu-24.04`
remained queued with no executed steps at the 2026-10-24 14:27 UTC observation.
Their cause is unknown. The budget standard-library job on `ubuntu-slim`
completed; that does not establish that the required VM jobs can start.

This candidate changes only three `runs-on` values to `ubuntu-22.04` and adds
the exact candidate branch to the existing relay push trigger. GitHub lists
Ubuntu 22 as a supported VM runner image. This is a separate infrastructure
attempt, not a replacement of the queued attempts or a new scientific seed.

## Frozen behavior

- Preserve the original two queued run IDs: native `40098746892`, relay
  `40097234072`.
- Preserve native source, source authorization and the 96-update adapter recipe.
- Preserve relay source, 256-update training, controls, 32 target cold-worker
  reads, evidence exchange, withdrawal and restart-replay checks.
- Preserve original job timeouts, CPU-thread settings, dependencies and base
  artifact pins. The actual OS image and runtime identity are collected by
  each execution rather than claimed identical across images.
- Preserve every failure, partial run, raw answer and measured cost from each
  attempt. No outcome changes the registered scoring or permits a model retry.

## Qualification boundary

Independent hosted jobs provide separate execution environments. They do not
attest that the underlying physical hardware differs. The artifact relay does
not prove direct cross-host mTLS, multi-host quorum, immediate revocation before
delivery, or a complete authority availability model. Completion of these jobs
does not close the original distributed or production gates.

The native implementation and relay implementation are byte-identical to the
components in integrated candidate `3906c552223448a01702ac6eb3bc3c38c24cb5ab`.
Only the workflow environment and trigger differ. Actual completion must be
recorded against the newly published candidate commit.

References:

- [GitHub runner image specifications](https://docs.github.com/actions/using-jobs/choosing-the-runner-for-a-job)
- [Runner isolation and timeout limits](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
