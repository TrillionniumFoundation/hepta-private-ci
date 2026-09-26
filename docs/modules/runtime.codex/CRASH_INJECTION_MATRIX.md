# runtime.codex crash-injection matrix

This matrix is the repository-side fault contract for the named `runtime.codex` product caller. It is deliberately stricter than a happy-path integration test. Every row represents a distinct crash or acknowledgement window and must retain exact operation identity across reopen. A passing repository receipt proves only the named candidate and host used by the receipt; it does not prove a target deployment, real provider, independent acceptance, activation, promotion, or release.

## Global invariants

1. One durable operation identity can cross the physical `turn/start` boundary at most once.
2. A definite pre-effect abort is legal only while the same live process still owns the non-serializable, one-shot abort proof for the exact local dispatch revision.
3. Agentd and the local inference journal must agree on the exact dispatch/request digest. Same identity and same semantics are idempotent; reused identity with different semantics is a hard conflict.
4. After effect entry, timeout, cancellation, transport loss, process death, or missing acknowledgement are reconcile-only. They never imply “not sent”.
5. Terminal success requires exact thread, turn, session, generation, App Server version, Codex home, connection, request and response correlation plus final owner readiness.
6. A late provider completion may be retained as a provider fact but cannot upgrade a locally cancelled, timed-out, fenced, or quarantined boundary to success.
7. Any unresolved effect continues to own capacity until terminal evidence or an independently authorized quarantine resolution is durably committed.

## Injection table

| ID | Injection point | Required local journal state | Required Agentd owner state | Replay posture | Required evidence/test |
| --- | --- | --- | --- | --- | --- |
| RCX-CRASH-01 | Before durable native admission | no record | no run or admitted-only record owned by upstream coordinator | fresh admission permitted | unit test: rejected request leaves no dispatch |
| RCX-CRASH-02 | After admission, before local dispatch prepare | reserved, no dispatch | `Admitted` or `ContextAttached` | no provider replay question exists | durable reopen test |
| RCX-CRASH-03 | During local dispatch write or fsync | predecessor record or fenced store; never a partial valid dispatch | unchanged | fail closed | journal torn-write/fault-injection test |
| RCX-CRASH-04 | After local dispatch prepare, before Agentd `mark_dispatched` RPC | prepared dispatch with live abort proof | `ContextAttached` | same live process may abort; reopen is reconcile/repair only | kill/reopen test at RPC entry |
| RCX-CRASH-05 | RPC request written, response lost before caller knows outcome | prepared dispatch | either `ContextAttached` or exact `Dispatched` | query exact run state; never issue a second physical send permit | owner-RPC lost-ACK test |
| RCX-CRASH-06 | Agentd commits `Dispatched`, caller crashes before receiving response | prepared dispatch | exact `Dispatched` bound to dispatch digest | reopen reconciles owner state; no fresh `turn/start` | duplicate-owner/restart test |
| RCX-CRASH-07 | Agentd commits `Dispatched`, final owner/ingress check fails before effect | local `Released` only after one-shot abort succeeds | exact `CancelledBeforeEffect` through digest-bound abort transition | fresh operation only; same operation closed | exact cross-owner abort test |
| RCX-CRASH-08 | Cognitive final-use revalidation fails after owner dispatch | local `Released`, no turn id | exact `CancelledBeforeEffect` | no physical request | tombstone/correction race test |
| RCX-CRASH-09 | Cancellation/deadline observed before `VerifiedUseToken::enter` | local `Released`, pre-effect reason retained | exact `CancelledBeforeEffect` | no physical request | cancellation/deadline race test |
| RCX-CRASH-10 | Revocation frontier or authority epoch changes before entry | local `Released`, stale witness retained for audit | exact `CancelledBeforeEffect` | obtain a new grant only for a new/live attempt while policy permits | revocation-head race test |
| RCX-CRASH-11 | Immediately after token entry, before socket write is observable | accepted-or-unknown; abort proof destroyed | `Dispatched` | reconcile only | injected pause/kill at effect-entry handoff |
| RCX-CRASH-12 | Partial socket write | indeterminate | `Dispatched` | reconcile only | transport short-write/connection reset test |
| RCX-CRASH-13 | Full request write, App Server response lost | indeterminate | `Dispatched` | same-connection `turn/started`, then `thread/read`; no new start | lost-ACK test |
| RCX-CRASH-14 | Exact `turn/started` observed, local `native_started` persistence fails | store fenced; turn must be interrupted where possible | `Dispatched`/`Cancelling` until reconciliation | no replay | persistence-failure injection after start |
| RCX-CRASH-15 | Process dies after start but before terminal event | durable turn id when available, otherwise indeterminate dispatch | unresolved after dispatch | reopen original generation and `thread/read(includeTurns=true)` | restart/reopen test |
| RCX-CRASH-16 | Terminal event observed, local settlement write fails | terminal fact retained in diagnostic path; store fenced | unresolved until exact terminal reconciliation | no replay | settlement fsync/failure test |
| RCX-CRASH-17 | Terminal local write succeeds, Agentd terminal RPC response is lost | terminal local observation | terminal or unresolved exact owner record | query/reconcile exact owner transition | owner terminal lost-ACK test |
| RCX-CRASH-18 | Owner readiness/generation is lost concurrently with provider completion | provider completion retained; boundary quarantined/non-success | owner loss is sticky | no replay | terminal-vs-owner-loss interleaving test |
| RCX-CRASH-19 | App Server history is unavailable after process loss | durable indeterminate/quarantined operation | `Indeterminate` | no automatic release or replay | quarantine protocol test |
| RCX-CRASH-20 | Two workers race the same run/revision | one exact winner; loser cannot retain a send permit | one exact `Dispatched` record | loser reconciles or aborts before effect | concurrency stress/property test |
| RCX-CRASH-21 | Stale revision attempts abort, cancel, terminal or resolution | unchanged | unchanged | reject | stale-revision stress test |
| RCX-CRASH-22 | Same operation id reused with different payload/request/dispatch digest | unchanged or quarantined conflict | unchanged or conflict | never execute | semantic-conflict test |

## Required execution modes

The matrix must be exercised in four modes:

- deterministic unit tests for every pure transition and digest invariant;
- process-level tests using real Agentd and App Server processes with a controlled provider;
- restart tests that close and reopen every durable store involved;
- target-host tests with the independently operated issuer and selected real provider.

Repository CI may satisfy only the first three modes. The fourth remains an external qualification gate.

## Receipt requirements

Each execution retains machine-readable records containing exact source SHA, tested SHA, tree, ordered parents for synthetic merges, command, host/toolchain identity, log digest, observed pass/fail counts, and claim ceiling. A skipped, cancelled, missing, dirty, under-floor, or failed record is never a pass. The exact-head and synthetic-merge receipts are generated by `scripts/runtime_codex_receipt.py` and must be attested by the workflow identity on protected pushes.
