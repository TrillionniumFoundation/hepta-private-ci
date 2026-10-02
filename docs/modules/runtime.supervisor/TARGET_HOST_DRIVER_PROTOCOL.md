# runtime.supervisor target-host fault-driver protocol

The repository does not emulate privileged target-host faults. The manually
dispatched target-host workflow invokes an independently installed executable
on a labelled self-hosted runner. That executable must run the scenarios in
[`TARGET_HOST_PROFILE.json`](TARGET_HOST_PROFILE.json) against 256 real managed
processes and produce one receipt accepted by
`scripts/hepta_supervisor_external_receipt.py target`.

The workflow invokes:

```text
DRIVER execute \
  --profile ABSOLUTE_TARGET_PROFILE \
  --binary ABSOLUTE_HEPTA_SUPERVISORD \
  --output ABSOLUTE_TARGET_RECEIPT \
  --lane source-head|final-merge \
  --source-sha SHA \
  --base-sha SHA \
  --merge-candidate-sha SHA \
  --tested-sha SHA \
  [--final-merge-sha SHA] \
  --workflow-sha SHA \
  --workflow-run-id DECIMAL \
  --workflow-run-attempt DECIMAL \
  --cargo-lock-sha256 SHA256
```

The driver must be an absolute, regular executable owned by the target-host
operator. It must not modify the checkout. It owns process-manager integration,
filesystem fault injection, ENOSPC devices/volumes, system-manager restart,
clock fixtures and privileged PID-reuse stress. Each scenario must preserve its
raw log and durable snapshots as content-addressed artifacts referenced by the
receipt.

The receipt is closed-world. Every frozen scenario and SLO is mandatory. A
driver may report a failure, but may not turn an unavailable facility into a
passing skip. The workflow validates the receipt, checks a clean checkout and
uploads all raw material even when validation fails.

The workflow validates with `target --bind-current-run --binary ABSOLUTE_BINARY`.
It compares source/base/tested/merge identities, workflow SHA, run and attempt,
actual host OS/architecture, Cargo.lock digest and the daemon digest captured
before fault injection. A previous run or an earlier attempt is not evidence
for the current invocation. Replacing the daemon during the driver run fails
validation. Operator drivers must emit `workflow_run_attempt` and support its
argument; an older driver that omits this binding cannot pass the current lane.
