# Scoped native CI timeout budget verification

Date: 2026-10-19. Base: `2be5fc052ae7b2e9fb08c68a3ae7e5a218ad37d5`.

## Observed failure and limits

[Original scoped job 117665655613](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39114831266/job/117665655613)
ran from 2026-10-18 12:06:04 to 12:51:04 UTC and concluded `cancelled`.
Its dependency-test step remained unfinished, and its artifact-retention step did not run.
The job-log endpoint returned HTTP 404 `BlobNotFound` at 2026-10-19 00:54:48 UTC;
the run artifact listing returned zero artifacts. The exact final compiler/test phase
and a direct cancellation message are therefore unavailable.

[CI required job 117680130373](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39114831266/job/117680130373)
reported `CI dependencies did not succeed: hepta-scoped: cancelled` and exited 1.
Rejecting that incomplete dependency is the required behavior.

The fixed workflow had a 40-minute job limit while `hepta_ci_exec.py` defaulted
to 3,600 seconds. The observed 45-minute lifetime is consistent with that outer
limit followed by GitHub's documented five-minute forced-cancellation window.
This attribution is an inference, not a recovered cancellation log.
See [GitHub cancellation behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation).

## Configuration change

Only two workflow lines change: the scoped job limit becomes 75 minutes, and its
single executor invocation explicitly passes `--timeout-seconds 3600`.
The executor wraps the entire dependency planner and its one `just test --locked`
invocation, including compilation and every selected test; it does not allocate
a separate hour to each package. The 15-minute outer allowance covers setup,
identity checks and artifact retention. The previous setup took 54 seconds.

The dynamic package selection, child arguments, locked dependencies, upload step,
scope rules and terminal failure policy remain identical. This budget does not
guarantee completion within an hour or artifact delivery after an infrastructure failure.
Changing a workflow still selects `full_repo=true` under the existing scope policy.
No exception is added to avoid that broader CI; a full-repository run does not
itself prove that the scoped branch was executed.

## Local verification

At 2026-10-19 01:08:37–01:08:49 UTC:

- All 71 existing Python tests passed, with no failures or skips: executor records,
  real process deadlines and retained output, terminal-gate rejection, and scope policy.
- PyYAML parsing and full document comparison accepted only the two intended changes;
  the executor child command, `always()` uploader and required fan-in were unchanged.
- All nine inline Bash blocks passed `bash -n`.
- Official actionlint 1.7.12 passed. Shellcheck and Pyflakes were unavailable.
- All ten relevant workflow, implementation and test input hashes stayed unchanged
  during verification. No Rust build, remote job rerun or merge was performed.

The tests use short real child-process deadlines and disposable Git repositories.
They are not a substitute for successful required remote CI on the candidate.

Validation receipt SHA-256: `5ce3f40c980f5c055401306e5306bda407c0a5216f22dc10946790e2075cbcbf`.
Workflow SHA-256: `96eb7f9ea698ea353c757c3ba9f4a82a3ea448b45f676a208e09187748f4b9e3`.

## Retained original evidence

[Manifest](scoped-native-timeout-2026-10-19/manifest.json) records the exact bytes
of the original diagnosis, required-job failure log, retrieval limitations and
local validation records. This is a selected evidence set; absolute paths in
the original receipts describe their execution location. The records remain
unchanged, including their original pre-publication and source identities.

The original [validation receipt](scoped-native-timeout-2026-10-19/validation-01/receipt.json)
and [71-test log](scoped-native-timeout-2026-10-19/validation-01/python-tests.log)
qualify the two-line workflow change. Copying these records does not execute
another test or change the historical cancelled result.
