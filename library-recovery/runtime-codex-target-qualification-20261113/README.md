# Preserved runtime.codex target qualification procedure

Status: **SOURCE_ONLY_HOLD**.

`original-workflow.yml` preserves the original workflow bytes and file mode
from commit `3f40cc95c9fb7843dd1c4100aa42ad290832b498`. `SOURCE_CUSTODY.json` binds its original path,
Git blob, size and SHA-256. The copy is outside `.github/workflows` and is
not an active GitHub Actions workflow.

The active workflow retains an explicit failing HOLD result on a hosted runner.
It does not check out or execute candidate code, request the protected environment,
read target inputs, invoke the provider or driver, or attest a qualification receipt.

## Source findings

The original sequence checked the configured driver digest, then executed
candidate-owned Python planning code on the same self-hosted runner before
invoking the driver. Candidate-owned Python also verified the resulting evidence.
The workflow source alone establishes neither isolation of that code from the
driver and protected inputs nor an independent verifier for the observations.
This audit did not inspect secret values or execute the target workflow.

The original helper accepted supplied boolean assertions and digest-shaped
strings as claims about a real provider, independent issuer, process identity,
trusted time and anti-rollback state. Hashing a supplied observation file does not
authenticate those claims. Local schema diagnostics must retain this limitation.

## Restoration boundary

A future implementation needs a reviewed boundary for candidate execution and
protected target resources, a binding to the driver actually consumed, and
independent authentication and completeness checks for the original evidence.
The preserved procedure is source history, not a qualified target-host run or a
deployment permit. No protected-environment settings were changed by this repair.
