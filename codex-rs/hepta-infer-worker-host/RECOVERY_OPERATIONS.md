# Native inference reconcile-only operation

This runbook describes repository behavior, not an independently accepted
provider-resolution service. It complements `FINAL_USE_AUTHORITY_PORT.md`.

## Command and identity

Use the same `hepta-infer-worker --profile native-app-server` arguments as the
original operation, with `--reconcile-only`. Supply the original prompt on stdin,
the original request ID, Agent ID/generation, model, Agentd socket, timeout and
context query. An intelligence operation also needs its original four
`--intelligence-*` values. Do not paste prompts or credentials into CI logs.

The CLI retains its protected authority-configuration requirement. The library
`AppServerModelDriver::reconcile_only` never requests another grant and never
calls `reserve_native` or `turn/start`. It reads the existing operation and
compares its full source binding before any provider-history lookup. The local
control owner still locks the journal and owns every settlement write.

## Outcomes

| Existing state | Reconcile-only behavior |
| --- | --- |
| Unknown request ID | Error; no new operation is admitted |
| Reserved, no durable dispatch | Error; no dispatch or automatic release |
| Persisted pre-dispatch stop/rejection | Return the recorded error without execution |
| Immutable terminal observation | Return it unchanged, including unknown token usage |
| Possibly dispatched with exact surviving history | Use the existing authenticated thread-history adapter, then settle through inference.control |
| Possibly dispatched with absent/ambiguous history | Preserve indeterminate status and held reservation; no replay or inferred zero usage |
| Changed prompt/context/identity/generation/intelligence binding | Conflict before history lookup; journal observation remains unchanged |

The normal duplicate-run path uses the same reconcile-only implementation once
the record has left Reserved. This removes an alternate recovery entrypoint that
might accidentally grow replay behavior later.

## Unresolved operation procedure

Preserve the original journal, provider identity and request ID. Record only safe
operation identifiers, generation, state and whether token usage is unknown in
operational diagnostics. Do not delete, truncate, replace or clone the journal to
free capacity. Do not switch to a new request ID as an automatic retry. A held
reservation is intentional when physical execution cannot be disproved.

When matching App Server history becomes available, run reconcile-only against
the same identity again. The absence of history, a process death, an expired
lease, a timeout or a provider support statement without authenticated exact
operation binding is not terminal negative evidence.

If history is permanently unavailable, quarantine the operation and escalate to
the inference.control/provider owner. The repository currently has no approved
external terminal/usage amendment or forced-resolution protocol. This runbook
does not invent one, authorize a refund, or label operator acknowledgement as a
physical terminal observation. A later protocol must bind original operation,
provider, generation, payload, usage evidence and immutable audit lineage.

## Retention and monitoring boundary

The current hosted profile uses an ephemeral App Server thread. Qualification
must establish how long exact history survives disconnect, worker restart and
App Server restart. A retention change is a separate lifecycle/privacy contract,
not a transparent recovery optimization. No fixed TTL proves non-execution.

Operators need indeterminate count/age, held-capacity and journal-capacity
alerts, reconcile outcomes, missing-usage counts, authority-denial counts and
cancellation-to-interrupt latency. The complete durable metrics/age surface and
trusted late usage reconciliation remain implementation gaps; the current
request journal has not been silently upgraded to fabricate those facts.
The fixed turn-start acknowledgement grace remains unchanged by this patch.

## Regression evidence

`native_reconcile_tests.rs` covers missing/reserved requests, changed input,
legacy unknown dispatch after reopen and persisted pre-dispatch stops. Existing
`native_run_control_tests.rs` continues to cover duplicate/reopen/rejection and
intelligence digest bindings. These names identify source tests, not a pass
receipt. Read exact source/merge CI and product-process evidence before adoption.
