# runtime.codex fault matrix

This matrix is the repository-side acceptance contract for the composed Codex App Server boundary. It records source behavior and focused test obligations; it is **not** target-host execution evidence, activation, independent acceptance, promotion, or release.

| Fault / observation | Required result | Retry posture | Durable behavior |
| --- | --- | --- | --- |
| Exact `TurnStatus::Completed` for the bound thread/turn | `AdapterStatus::Succeeded` | `RetryPosture::Never` | settle only with exact terminal correlation |
| Exact `TurnStatus::Failed` | `AdapterStatus::Failed` | `RetryPosture::Never` | preserve failure and observed usage |
| Exact `TurnStatus::Interrupted` | `AdapterStatus::Interrupted` | `RetryPosture::ReconcileSameOperation` | never convert interrupt into success or blind replay |
| `InProgress` supplied as completion | reject observation | none | durable state unchanged |
| Wrong thread / wrong turn terminal event | correlation error | none | durable state unchanged |
| Wrong App Server connection, version, codex home, session, generation, protocol, payload or source-admission digest | correlation / binding error | none | no success receipt |
| Missing product transport binding | `ProductBindingRequired` | none | no terminal receipt |
| Exact App Server overload `-32001` before handler admission | `AdapterStatus::Overloaded` | `SafeBeforeAdmission` | durable rejection may release the slot |
| Invalid request / method-not-found / invalid params (`-32600/-32601/-32602`) | `AdapterStatus::Rejected` | `Never` | durable rejection; do not reinterpret as execution |
| Internal or otherwise unclassified `turn/start` JSON-RPC error | `AdapterStatus::Indeterminate` | `ReconcileSameOperation` | hold/reconcile; no blind replay |
| `turn/start` transport loss or timeout after write-ahead dispatch | native `Indeterminate` | reconcile same operation | hold the durable slot; same-connection reconciliation may recover an exact `turn/started` |
| Same-connection reconciliation finds no exact started turn | native `Indeterminate` | reconcile same operation | no new `turn/start` |
| Restart/reopen after unknown acknowledgement | `thread/read(includeTurns=true)` recovery only | reconcile same operation | require exact stable `client_user_message_id` and original `UserMessage` content |
| Recovery finds same client id with different input | hard correlation conflict | never replay | hold/quarantine |
| Recovery finds multiple exact turns | hard duplicate-effect conflict | never replay | hold/quarantine |
| App Server history is unavailable after process loss | remain indeterminate | never infer “not applied” | external policy/evidence is required before release |
| Final-use authority is absent, malformed, denied, expired, revoked, forged, stale, or nonce-reused | reject before physical `turn/start` | none | release only while no effect crossed the boundary |
| Authority endpoint/revocation head rolls backward | reject | none | fail closed |
| Cancellation/deadline changes after durable write-ahead but before external effect and the live one-shot abort proof still exists | definitive local pre-effect stop | none | consume abort proof and release |
| Process dies after write-ahead so the in-memory abort proof is lost | accepted-or-unknown | reconcile same operation | recovery cannot downgrade to “unsent” |
| Cancellation after turn admission | `NativeBoundaryStatus::Cancelled` | reconcile terminal facts | interrupt; a late Completed event remains a provider fact but does not upgrade the boundary to success |
| Runtime deadline after turn admission | `NativeBoundaryStatus::TimedOut` | reconcile terminal facts | interrupt; late terminal facts remain observable |
| Provider event lag/disconnect / unexpected observation error | `NativeBoundaryStatus::Quarantined` unless a stronger cancelled/timed-out fact exists | no blind replay | persist stop/cancel intent and reconcile |
| Agent owner readiness/generation/ingress is lost | sticky owner loss; success authorization is denied | no blind replay | provider terminal facts may be retained, but boundary remains quarantined/non-success |
| Adapter receipt attempts to grant model/provider authority | impossible by construction in this module | none | receipts remain `AuthorityPosture::DENY_ALL` |

## Correlation contract

The runtime.codex request identity binds the operation, thread, actual v2 method, final payload and lease payload, one absolute deadline, source-admission digest, Agent generation, App Server session, stable client user-message identity, exact user-input digest, App Server v2 protocol, initialized server version, codex-home digest, and connection identity. Terminal receipts additionally bind the exact turn and terminal response digest.

The durable native journal stores the request/correlation material before the physical `turn/start` await. Legacy journal records with missing modern correlation fields may be replayed for compatibility, but they cannot be upgraded into newly qualified runtime.codex success.

## Witness boundary

Production terminal/rejection observations are created from the bounded `RemoteAppServerClient` path. Callers cannot promote an ambient `terminal_observed: bool` or arbitrary response digest into success. This is a process-local type/provenance boundary, **not** cryptographic App Server process attestation; target-host qualification must still establish the Agentd/App Server process, socket, generation, and local trust boundary.

## Final-use boundary

The worker obtains an independently signed exact-binding grant from the configured final-use authority port, synchronizes the issuer-provided monotonic revocation head, claims a non-constructible `VerifiedUseToken`, rechecks cancellation/deadline/owner ingress, consumes the token at final-use entry, and durably records the authority witness/request binding before the network await. The worker does not hold the issuer private key. `VerifiedUseToken::enter()` rechecks expiry and the worker-local monotonic revocation head; a fresher head must arrive through the independently qualified target-host authority/revocation-distribution path.

## Required repository tests

The focused source matrix includes:

- `codex-rs/hepta-codex-adapter/src/lib_tests.rs`: terminal status separation, correlation, overload, recovery conflict cases.
- `codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs`: deadline binding and late terminal evidence.
- `codex-rs/hepta-infer-core/src/native_control_tests.rs`: durable write-ahead, unknown-outcome slot retention, live abort proof, replay compatibility.
- `codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs`: real caller status/owner/cancel/deadline behavior.
- `codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs`: reopen/no-replay and explicit pre-start rejection.
- `codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs`: signed exact-binding grant, peer identity, revocation rollback, and denial.

These source tests do not replace a target-host Agentd + App Server + provider fault run.

## External qualification gates

Repository source cannot self-certify:

1. deployed final-use issuer identity, signer-key custody, peer/socket ACLs, trusted time/revocation distribution, and anti-rollback recovery;
2. authenticated target-host Agentd/App Server process/generation/socket identity;
3. a real model/provider terminal stream under the selected deployment;
4. delegated external-tool terminality and acknowledgement-loss behavior;
5. operational resolution/quarantine policy for indeterminate effects when App Server history is unavailable;
6. independent acceptance, activation/canary, promotion, and release.
