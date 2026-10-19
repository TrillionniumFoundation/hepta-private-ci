# runtime.codex troubleshooting

## `turn/start` response or transport is unknown

Do not issue a fresh `turn/start`. Keep the local slot and Agentd run unresolved. First inspect same-connection `turn/started`; after reopen, use `thread/read(includeTurns=true)` with the exact stable `client_user_message_id` and original user input. A mismatch or duplicate match is a hard conflict. Missing ephemeral history enters the quarantine protocol.

## Agentd dispatch acknowledgement is unknown

Do not consume the local pre-effect proof and do not send to App Server. Query the same run identity and expected revision. If Agentd committed the exact opaque pre-effect permit, continue only through exact reconciliation. If the result cannot be authenticated, hold the operation.

## Final fence rejects after Agentd dispatch

The worker must call `RunAbortBeforeEffect` with the exact process-local permit digest and revision, validate the Agentd `Cancelled` receipt, and only then consume the local abort token. Any acknowledgement ambiguity is held; it is not proof that the owner did not commit.

## Effect-entry acknowledgement is unknown

The request may be authorized to cross the effect boundary. Do not classify it as unsent and do not replay. Reconcile the Agentd run and App Server/provider evidence under the original operation identity.

## Owner readiness/generation/ingress is lost

Owner loss is sticky for the attempt. Provider terminal facts may still be retained, but success is denied and the boundary remains quarantined or non-success. A later healthy response does not retroactively authorize the attempt.

## Authority endpoint failures

Check, in order: protected config permissions, socket path ancestors, socket owner/mode, connected peer UID/process identity, signer ID/key, authority epoch, revocation head, nonce replay state, trusted clock, response bounds, and issuer timeout. Never weaken a failed check to restore service.

## Capacity does not release

List unresolved native records and Agentd runs. A post-dispatch or process-loss record intentionally retains capacity until exact terminal evidence or an independently signed quarantine release is applied. Do not edit the journal or delete the record manually.

## Event lag or disconnect

Persist cancellation/stop intent, interrupt the bound turn, retain late terminal facts during the bounded grace period, and classify the boundary as quarantined unless a stronger cancelled/timed-out fact already exists. Track event-channel lag and disconnect counters before increasing any buffer.
