# Request-bound transport admission and local final-use fences

## Scope and claim boundary

This increment extends the existing `FederationWireTransportV2` and product
bridge. It retains canonical `execute_once`, Agentd/Memory composition,
pre/post-I/O authority observations, physical-send revalidation, half-budget
owner discovery, explicit `legacy-v1`, and the single durable wire owner.
`CAPABILITY_STATE.json` remains authoritative. Source changes and test presence
are not execution, selected-host acceptance, activation, promotion or release.

## Local time observations

The adapter samples its clock after obtaining the client owner, then prepares
the durable query using that observation. It samples again after preparation
and before invoking `exchange_once`. Expiry or regression at that boundary
prevents network entry. A prepared attempt is retained rather than erased or
resent, including when a clock error prevents dispatch.

On response arrival, time is sampled after obtaining the client owner again.
The observation must not precede dispatch, not merely the earlier preparation
observation, and owner-lock waiting cannot reuse an older timestamp. After response
admission and terminal persistence, a final local observation must remain
monotonic and precede both the query deadline and body expiry. Otherwise the
adapter returns no usable evidence, retaining any committed terminal fence.
These checks do not replace canonical authority checks or claim that synchronous
store writes are interruptible. Store latency and owner-lock contention still
require selected-host capacity and cancellation-tail measurements.

## Exact-attempt preflight before terminal mutation

`FederationProductClientV1::admit_response_for_query` checks the original query
and exact response peer, query binding, scope, purpose and generation before
calling durable wire admission. The ordinary V2 transport uses this entry.
The existing general client response API delegates to the same private
preflight/commit implementation; it does not create a second replay owner.

A correctly authenticated response for another pending query is rejected by the
request-bound entry without consuming that other query's replay or terminal
state. Its original response remains admissible for its rightful attempt.
Expired response bodies are rejected before mutation even when the outer
frame and channel are still current. The additional query-binding check does
not clone or hash the evidence vector again. No authority decision is cached.

## Maintenance through the composed transport

`FederationWireTransportV2::maintain_expired()` exposes the existing bounded
client maintenance without consuming or extracting the wrapper. The caller
schedules maintenance explicitly, the wrapper samples its owner clock, and the
same durable client commits cleanup before installing state. It neither sends
nor retries a query and creates no independent maintenance task or database.
The existing per-call cleanup budget and live replay/cancellation fences remain.

## Qualification and regressions

Candidate branch pushes and dispatches now run both exact-head and
deterministic-merge jobs, including dispatch from main with a distinct explicit
source SHA. Reusable PR qualification remains supported. Main alone has no
distinct current-base candidate and is not mislabeled as such.
Both jobs use the same source expression and canonical command matrix. Merge
construction binds `FETCH_HEAD` from an explicit base-branch fetch rather than
reusing a potentially stale tracking ref. Permissions remain read-only, and
qualification never repairs its own source or changes success flags.

The adapter regression suite adds preparation expiry and rollback with zero
exchange calls; response-clock regression relative to dispatch; expiry during
terminal persistence; body expiry; wrong-attempt response nonconsumption; and
bounded maintenance through the wrapped client with zero exchange calls. These
are repository-local logical fixtures, not two independently provisioned hosts.

Commit source/tests/docs/workflow first, rebind only `IMPLEMENTATION_MAP.json`
to that exact source commit and tree, then qualify the frozen map-bound head and
its current-base merge. A successful upload is not successful qualification.
The selected secure transport, deployment credentials, production recovery
backend, two real hosts, target SLOs, independent review and operator acceptance
remain separate gates and are not granted by this development increment.
