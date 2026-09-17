# runtime.supervisor signed-intent recovery ceremony

This runbook is the break-glass, pre-start recovery path for a non-terminal `supervisor-signed-intent.json`. It is intentionally separate from the supervisord RPC surface because supervisord fails startup closed while the signed mutation outcome is unresolved.

## Safety properties

The ceremony never infers success from process liveness or from merely observing the target release. It requires exact durable identity and state witnesses. A live process is fenced by exact lease adoption; a lease is removed only after the exact identity is observed missing. A rejected adoption leaves the lease untouched. Both the main agent and its generation-bound Matrix companion must be fenced before resolution.

`resolve` requires the operator to repeat the durable grant digest, the intent's expected control revision, the current FleetRegistry lifecycle generation, the current release-state generation, and the authority epoch. The current release must exactly match the target for `commit` or the source for `abort`. The lifecycle must be `failed` or `stopped`, and both process leases must already be cleared.

## Procedure

1. Stop supervisord and prevent an automatic restart by the service manager.
2. Run `hepta-supervisor-recovery inspect --fleet-root <root> --agent-id <uuid>`. Record the full JSON output in the incident/change record.
3. Run `hepta-supervisor-recovery fence --fleet-root <root> --agent-id <uuid>`. If either outcome is `kill_requested`, run the same command again after the exact child has exited. Do not proceed until both process leases are absent in `inspect` output.
4. Independently decide whether the authorized operation is being acknowledged as committed or aborted. This is an operator/authority decision, not a supervisor inference.
5. Re-run `inspect` immediately before resolution and use its current lifecycle and release-state generations. Use the grant digest, expected control revision, and authority epoch from the durable signed intent.
6. Run `hepta-supervisor-recovery resolve ... --outcome commit` only when `current_release == target_release`, or `--outcome abort` only when `current_release == source_release`.
7. Run `inspect` once more and retain the terminal journal JSON as evidence. Only then re-enable supervisord.

Example resolution command:

```text
hepta-supervisor-recovery resolve \
  --fleet-root /absolute/fleet \
  --agent-id 018f... \
  --outcome abort \
  --grant-sha256 <64-hex> \
  --control-revision <n> \
  --lifecycle-generation <n> \
  --release-state-generation <n> \
  --authority-epoch <n>
```

## Failure handling

If exact adoption is rejected, a process lease changes identity, the journal is truncated/corrupt, the FleetRegistry generation changes between inspect and resolve, the release-state generation changes, the authority epoch differs, or the current release is neither the signed source nor signed target, stop the ceremony. Preserve the files and escalate for manual incident analysis; do not delete leases or the signed intent to force startup.

The recovery tool is not a release selector, candidate evaluator, or production authority. It only fences exact local process identities and records an explicit terminal acknowledgement for an already-authorized signed mutation.
