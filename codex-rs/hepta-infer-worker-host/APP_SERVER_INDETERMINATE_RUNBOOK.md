# Hosted App Server indeterminate-operation runbook

This runbook applies only to `HostedAppServerWorker`. It does not authorize a
new provider call, release an unknown reservation, or reinterpret missing usage
as zero.

## Invariants

1. The durable request ID, Agent identity/generation, model, prompt binding,
   App Server session/thread and runtime.codex request digest are immutable.
2. Once a dispatch has been written, process loss, timeout or transport loss is
   accepted-or-unknown. A retry with a new thread or request ID is forbidden.
3. Only exact App Server history or an independently signed provider receipt may
   refine terminality or usage.
4. A provider receipt never upgrades `NativeOwnerAuthority`. Provider completion
   and owner authorization remain independent facts.
5. An indeterminate operation retains its local reservation. Capacity is not
   recovered by age, restart, log rotation or operator assertion.

## Triage

1. Stop automatic retries for the request ID.
2. Preserve the private native journal, worker binary identity, authority
   configuration, Agent generation and the original prompt input.
3. Read `native_metrics_snapshot()` and record:
   - current/oldest indeterminate operations;
   - held reservations;
   - reconciliation attempts, successes and failures;
   - terminal records with missing usage;
   - authority denials and journal-capacity refusals.
4. Verify that the durable record contains an exact runtime.codex dispatch. A
   `Reserved` record has no provider dispatch and must follow the pre-dispatch
   error path instead.

## Resolution path A: exact App Server history

Invoke `AppServerModelDriver::resolve_indeterminate` with the same durable
request ID and exact original prompt. The method:

- validates the current Agent/model identity;
- reconstructs and verifies the original runtime.codex request digest;
- issues `thread/read` only for the durable thread;
- never issues `turn/start`;
- settles only an exact matching terminal observation.

No exact terminal evidence leaves the operation indeterminate and the slot held.
A terminal result without a matching usage observation remains terminal with
`observed_output_tokens = null`.

## Resolution path B: signed provider terminal/usage receipt

When App Server history is unavailable, obtain a receipt from the independently
operated provider-receipt issuer. Verify it with `ProviderReceiptVerifier`, then
apply it through `resolve_with_provider_receipt`.

The receipt must bind the exact request, principal, worker generation, model,
thread, turn, provider, runtime.codex request/payload/source-admission digests,
terminal correlation, terminal status, output bytes and optional cumulative
usage. Retain the signed receipt and returned witness SHA-256 in the evidence
archive; the native journal retains the normalized terminal/usage facts.

A later receipt may monotonically add missing usage, but it cannot change an
already observed terminal status, output or correlation, reduce usage, or
upgrade owner authority.

## Prohibited resolutions

Do not:

- submit another `turn/start`;
- change the request ID or prompt and call it a retry;
- mark an operation not-sent because its process disappeared;
- convert missing usage to zero;
- free a reservation using a TTL;
- accept an unsigned provider screenshot, log line or operator statement;
- use provider terminality as proof of current owner authorization.

## Escalation and closure

An operation closes only when the journal contains an exact terminal observation
or an independently governed policy records a permanent unresolved/quarantine
outcome outside the execution-success path. Permanent unresolved records remain
visible in capacity and audit reporting. Production activation requires a named
owner, alert thresholds, provider receipt retention, signer-key custody,
revocation procedure and a rehearsed incident exercise.
