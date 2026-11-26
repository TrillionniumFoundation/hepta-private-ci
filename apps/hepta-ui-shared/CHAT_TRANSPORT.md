# Agent conversation transport

This is ordinary App Server conversation authority, selected through the existing
Agentd SessionIngress. It is distinct from the model-only Hepta inference worker:
it does not mint or bypass VerifiedExecutionPlan, signed final-use tokens,
operator-mutation permissions, or privileged Hepta execution gates. The read-only
native gateway is unchanged. Windows registrar/AuthBus work is untouched.

## In-repository composition

`codex-hepta-matrixd::chat::AgentChatSession` reuses the existing per-Agent
connection bootstrap with the separate `hepta-ui-chat` client identity. Agentd
checks agent identity/generation; bootstrap checks ready/not-fenced and the exact
App Server home. Each command rechecks Agentd health. This is existing generation
fencing, not a claim of atomic revocation between a health observation and dispatch.

The trusted host pins project and workspace; every thread read, resume, send and
cancel must match those plus the persistent `hepta-ui-chat` thread source. List
filters are revalidated, not treated as authorization. Persistent history remains
owned by App Server. The UI never concatenates or rewrites model history.

Send uses atomic `thread/queue/reconcile`, stable client-message identity and the
existing canonical payload SHA256. The queue service wakes loaded threads. An
uncertain send is reconciled with the same ID and text using ReconcileOnly; it
never authorizes a new admission. A Missing reconciliation result is only current absence: it cannot prove that an earlier uncertain request will never admit later. Hosts must retain the original operation ID and text, and must not enable a replacement send. Queued and persisted are observations, not
completion. Cancellation acknowledges a request, not confirmed interruption.
Create is intentionally not automatically retried after an unknown response.

Timeline reads bounded item pages and the latest turn metadata. Messages are
returned chronological within the page, with `activeTurnId` only for an observed
InProgress turn. The owner retains at most 50 connection-local live message observations (16 KiB each) from actual agent-message delta/item lifecycle notifications. There is no causal sequence shared with read RPCs: persisted item rows and latest-turn metadata always take precedence over cache entries. Cached text only fills missing rows for the authoritatively observed active turn after a separate bounded complete active-turn item window proves those IDs absent. Proof includes all raw item kinds, checks the exact turn and excludes paginated/oversized/duplicate windows. The latest persisted page reserves one slot for live text; cache insertion never drains, replaces or displaces authoritative rows. A partial active-turn window suppresses live inserts until stronger evidence is available; durable polling continues. Cached state never overwrites a persisted body or turn status. Latest-page polling merges those observations for the scoped active turn; it does not wait for final persistence or invent text. Completed observations replace deltas. Any omitted display content ends with the explicit text `[Display truncated: additional message content omitted]`; the marker is included within the 16 KiB cap and survives later delta chunks. Both hosts render it as ordinary accessible message text. There is no false full-text claim or invented continuation cursor for one oversized item. Older history pages never receive live inserts. Polling is the browser/native delivery mechanism, not a claim of SSE. Tool approval requests
are rejected, never auto-approved; responses expose `approvalRequired` so the UI
can direct the user to an authorized approval surface. Disconnect/lag fences the
connection; reconnect must create a fresh host session and resume the conversation.

## Native host

`hepta-agent-chat-host SOCKET AGENT GENERATION PROJECT WORKSPACE SESSION` is a
first-party JSON-lines stdio host. Local process/UDS access is the authority;
SESSION is correlation only. It does not listen on a network port, perform login,
issue credentials, provision an agent or create trust material.

Native `--chat-config ABSOLUTE_JSON` supplies `host_sha256`, `agentd_socket`,
`agent_id`, `generation`, `project_id`, and `workspace`. The adapter executes only
its installed sibling `hepta-agent-chat-host[.exe]` after checking its pinned
SHA256, using the existing bounded non-symlink local file reader. The installation
and operator configuration are trusted and must not be concurrently replaced:
this check is not a substitute for installation-directory access control and
cannot make an attacker-writable installation safe against path replacement.
Verification is chunked/cancellable on a worker, never on the render thread.
Queues have capacity 8, exchanges have a 15-second watchdog, and session replacement
cancels and reaps the child off the render thread. Closing transport does not claim that a remote turn was interrupted; that requires an explicit Cancel and later terminal observation. A failed/unknown request is
surfaced; drafts and exact reconciliation identity belong to the UI host.

## Browser integration boundary

The browser uses the same DTO at same-origin POST `chat/request` under its existing
ui-control base URL, cookie/CSRF, AbortSignal, deadline and response-byte limits.
The production ui-control HTTP deployment is external to this repository. Its
trusted authenticated handler must bind each principal to an explicitly configured
AgentChatSession and route decoded/validated requests. It must never accept agent,
project, workspace, executable or authority configuration from the request body.
`AgentChatSession::into_http` supplies the in-repository composition. It requires
an implementation of `ChatCookieAuthenticator`; there is no default verifier.
The verifier must check the existing cookie session's expiration/revocation on
every request. The adapter checks the configured principal, exact Origin, CSRF,
method/media type, frame size, schema and session/generation before dispatch.
Pass the frontend session ID/generation separately to `AgentChatSession::connect`;
Agentd spawn generation remains in the trusted `MatrixAgentdConnectArgs`. These
are distinct namespaces and are not inferred from untrusted command bodies.
Authenticated presentation-session issuance must be independent of the Console's
`runtime.read` capability. A successful session/connect can bootstrap chat even
when the runtime view is unavailable. If the external deployment refuses session
issuance without runtime.read, it must separate that policy before browser chat
can serve chat-only principals; this adapter does not manufacture anonymous or
fallback credentials.
No new HTTP listener or unverified deployment authentication is manufactured here.
Missing endpoints remain unavailable; the browser must not report connectivity
until a correctly scoped response succeeds. Native stdio is not browser transport.

## Provisioning and validation limits

Packaging must install the first-party host beside native and supply its digest,
existing Agentd socket/generation, existing project/workspace and local access.
Nothing is deployed, merged, logged into, or activated by this change. Fixture-only
validation does not establish live account access or production qualification.

### Local validation, 2026-10-02

- Shared DTO core tests: 5 passed.
- Owner library, binaries and test targets: Cargo check passed.
- Full matrixd library run: 39 passed; 2 local Unix-socket bind tests failed with
  EPERM in the execution environment, including the pre-existing owner-health
  test. A permitted escalated rerun produced the same platform restriction.
- Final fixture subset after scoped Clippy fix: 39 passed, those 2 socket cases
  explicitly excluded. They remain enabled in source for a socket-capable runner.
- Scoped `just fix`, repository `just fmt`, and `just bazel-lock-update` passed;
  lockfile stayed unchanged. Unrelated baseline formatter churn was discarded.
- No live service/account/model invocation was used. Full initialized Agentd/App
  Server end-to-end UDS qualification still requires a socket-capable runner.

### Hosted qualification layers

The UDS suite uses real sockets and the production AgentChatSession, AgentdClient
and RemoteAppServerClient. Both Agentd and App Server peers are scripted protocol
fixtures; this layer proves adapter boundaries, not actual Core queue execution.
A separate narrow `codex-queue-extension::queue_service` selection exercises the
real durable queue/state runtime and Core against local HTTP response fixtures:
exact-once admission, competing owners, caller abort, post-start ambiguity,
rollout recovery, digest/payload drift, raw-store bypass prevention and persisted
reconciliation. Neither layer is live provider acceptance or full deployment
qualification. Both exact-source hosted layers must pass before acceptance.

The earlier hosted transport run
[37002772605](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37002772605)
passed 47 owner tests and 5 wire tests at `66042cccc9e35fcb04194613ea0435d0f865dadd`,
including every local-socket case blocked in the initial execution environment.
That head predates the independent-review cache/page fixes and is not final
acceptance evidence. The reviewed fix has 9 focused local regression passes;
the exact updated head must rerun the transport suite and the added real queue
layer. More than 50 persisted items in the active turn suppresses transient live
inserts (not all conversation history): bounded authoritative polling continues.
