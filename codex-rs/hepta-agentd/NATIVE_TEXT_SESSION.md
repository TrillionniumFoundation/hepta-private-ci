# Original Root → native UI → Agentd text session

This entry uses the existing Root authority service, its installed writer
registration, its canonical issuer key/policy/sequence/store, the existing
Agentd control socket and one existing App Server thread. It starts no Agentd,
creates no thread and installs no trust or authority from renderer input.

## Trusted startup inputs

The trusted launcher must already have authenticated the human, opened the
original Root state and registered the original daemon/writer. Its original
Agentd must have both `--authbus-trust-file` and
`--authbus-checkpoint-file`; the public issuer key, epoch and allowed thread
must match the installed Root signer. An App Server readiness observation
does not imply that these inputs exist.

The same original Root initializer accepts an exact text policy:

- subject: the registered Agent ID;
- destination: `DeploymentFinalUseIssuer::text_destination(existing_thread)`;
- scope: `DeploymentFinalUseIssuer::text_scope(registered_agent_id)`;
- lifetime: a bounded original policy, at most 300000 ms.

These are deployment registration inputs, never RPC fields that add policy.
An existing issuer is opened with its original pinned key. Missing policy or
state is refused; startup never initializes or replaces it automatically.

The trusted launcher writes one additional Root-owned mode0600, single-link
JSON registration in the existing protected configuration directory. Its
`HostAuthorityTextUiRegistration` fields are:

| Field | Source |
|---|---|
| `schema_version` | `1` |
| `socket_path` | Distinct private UI lane; parent is Root:peer-gid mode02710 |
| `peer_uid`, `peer_gid`, `peer_pid` | The actual launched UI process; UID must equal original Agentd owner UID |
| `boot_id`, `process_start_ticks` | Actual captured UI process lifetime |
| `principal_id`, `session_id` | Already authenticated human/session; restricted nonempty ASCII IDs |
| `permission_revision` | Original registered writer lease revision |
| `expires_at_ms` | Human session expiry, no later than the original writer lease |
| `route.control_socket`, `route.codex_home` | Exact original registered Agentd paths |
| `route.agent_id`, `route.spawn_generation` | Original registered Agentd identity |
| `route.thread_id`, `route.app_server_session_id` | Existing original App Server thread/session |
| `can_interrupt` | Explicit trusted-launcher permission for this thread |

The launcher retains the UI child and opens its pidfd before any client
connection. It passes that descriptor by inheritance; the service checks
kernel credentials and the descriptor's actual PID/lifetime. The file is not
accepted from an ordinary UI lane and cannot create a human identity itself.

## Start the existing service and UI

Run the original entry with its original daemon pidfd on stdin and the
additional pre-held UI pidfd on an inherited descriptor numbered at least 3:

```text
hepta-authority-host serve-session \
  --config ORIGINAL_ROOT_CONFIG \
  --registration ORIGINAL_DAEMON_REGISTRATION \
  --owner-pidfd-stdin \
  --text-ui-registration AUTHENTICATED_UI_REGISTRATION \
  --text-ui-pidfd INHERITED_UI_PIDFD
```

The launcher starts UI first in the waiting state so it can retain that exact
child's pidfd. After Root binds the optional lane, UI Refresh retries the same
endpoint. Desktop uses `TRILL_UI_CHAT_SOCKET` and `TRILL_UI_CHAT_ROOT_PID` only
as endpoint hints; its worker requires the actual UID0 peer and a successful
live Root hello. Those variables contain no principal, key, grant or thread.
The original Root session's bounded lifetime is unchanged by reconnect.

`AgentdTextWorker::start_authenticated` receives the route from that hello,
connects through the original Agentd `session_ingress`, and verifies the
existing App Server session/thread/home before emitting `Authenticated`.
Only this event installs the original `ChatWorkspace::OwnerSession`.
`Connected` and ordinary Session/health observations never enable Send.

## Send, stream, cancel and recover

UI `Submit` prepares one exact Root signature. `Prepared` contains only the
original signature's correlation metadata. The shared original ChatWorkspace
must accept the exact text and return its original dispatch ticket before UI
queues `Dispatch`. Only then does the worker call
`AgentdClient::submit_authbus_text`. All later duplicate/unknown attempts use
the original retained envelope and status/Core `ReconcileOnly` lookup.

Original App Server notifications supply assistant text, tools and artifacts.
Tool/artifact representations are inert timeline observations, not UI-issued
effects. Approval requests requiring an unavailable original approval channel
remain unavailable; no automatic approval is inferred from text permission.
Cancellation uses the original queue delete/turn interrupt and is not shown
as completed until the original owner reports its terminal state.

Reconnect fences old physical subscriptions, preserves exact signed inputs and
reconciles them against the same original thread. Replayed deltas without an
original replay cursor are suppressed while authoritative turn snapshots are
used. Missing Root at startup or failed reconnect keeps the command worker
alive for explicit retry; it does not replace an unknown message identity.

## Bounded references with durable retirement

At most 32 unresolved signature references occupy the original issuer record.
The same record retains a monotonic text-intent watermark, atomically with
each signature and the original signing sequence. New numbers may skip an
unissued gap; a missing number at or below the watermark can never be signed.
Thus removing a proven terminal reference cannot resurrect its old input.

Root handles retirement by independently connecting to the registered
original Agentd/App Server, using only lookup/ReconcileOnly, and requiring
both the original AuthBus QueueAccepted receipt and original Core terminal or
cancelled outcome. UI JSON cannot supply that proof. The same issuer CAS frees
only that reference, leaving AuthBus/Core history untouched and preserving the
watermark. Lost retirement ACKs are idempotent. Unknown outcomes remain
retained; neither TTL nor an LRU evicts them. UI separately acknowledges
receipt consumption before its transient worker correlation is released.

Tests distinguish protocol fixtures, original-store tests and actual
Agentd/App Server process tests. Fixture keys or model responses are not
evidence that a deployment has its real Root registration or model configured.
