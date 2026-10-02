# memory.federation signing-horizon audit — 2026-10-02

## Source and completion assessment

Reviewed PR #1298 source `147a713abc93ff8d61b73d54c33fd0fb922bc37e`, the latest
federation candidate returned by the repository search, stacked on #1283/#1282.
No newer remote-payload or Agentd-network composition was found. This audit does
not repeat the previous cancellation, packet-size, or expired-body fixes.

The technical guide, V2 hardening guide, and wire core/recovery/product guides
correctly distinguish the local read-only composition from the wire candidate.
`ProductReaderTransport` captures a local `RetrievalRequest` and local memory
batch; `Agentd::attach_federation_after_generation_fence` composes local owner
layouts. The wire body carries only query and evidence identities/digests. It
cannot yield model-visible cross-host memory content or full remote final-use
revalidation by itself. Existing production/activation claims remain false.

## Cycle 1: reproduce and repair

Two regressions fail on the reviewed source:

1. With a directional request key expiring before the canonical query deadline,
   `begin_query` persisted pending intent and returned a signed packet whose
   frame expired before its query body. The receiving product host rejects it.
2. With a directional response key expiring before response-body expiry,
   `complete_query` persisted terminal state and returned a packet the receiving
   product client rejects. The sender had declared completion without producing
   an admissible response.

Both are deterministic, synthetic-key, in-process reproductions. They do not
contact real peers or use production credentials.

The existing pre-commit frame callbacks now verify the canonical body horizon
against the actual sealed frame expiry. Typed `OutboundHorizonRejected` errors
distinguish this from packet capacity rejection. No V2 bytes, canonical digest,
durable snapshot schema, owner, retry policy, or credential grant is changed.
The tests compare the entire durable snapshot before and after rejection.

## Cycle 2: boundary controls and independent review

Added positive controls for a query deadline exactly at its signing horizon and
for a response expiry exactly at its horizon, through the real product host and
client. The response control compares the entire decoded canonical response.
An independent source review confirmed the callbacks run before the existing
commit and requested the query-boundary control, which is included.

Re-reviewed peer/context identity, exact attempt and body binding, revoked
credential completion, stale expiry, cancellation and deadline fences, replay
and duplicate attempts, durable pre-commit/ambiguous-commit behavior, restart
snapshots, and local memory consumer composition. No further actionable defect
was found in that reviewed scope. This is bounded source/local verification,
not independent security acceptance or an assertion that every path is proven.

## Executed local verification

- Original source plus two negative tests: both fail before repair
- Wire crate: 101 tests passed, zero skipped (97 existing plus four regressions/controls)
- Canonical V2 dependency through the wire manifest: 31 passed, zero skipped
- Canonical explicit legacy-v1 surface: 35 passed, zero skipped
- Package-scoped `just fix` and all-target strict Clippy passed with Rust 1.95.0
- Repository `just fmt` ran with writable tool caches; unrelated existing Python
  formatting churn was excluded from this focused change
- Standalone wire formatting passed

Tests use `just test`/nextest. Because the standalone wire workspace has no
`local` profile and the parent workspace's overrides name unrelated packages,
a temporary external config containing only `[profile.local]` was supplied.
This does not skip any wire tests. Public host/client error-enum consumers are
confined to the wire crate in the reviewed repository and compile under the
all-target check. No dependency or lockfile changes are needed.

## Remaining gates

Hosted checks on the final source and deterministic base merge, compile-fail
doctests, full Agentd/owner/extension execution, target capacity/SLO acceptance,
and real two-host partition/restart/revocation qualification were not newly
established by this audit. Prior receipts do not qualify changed source.

The next substantive implementation layer still needs bounded remote request
resolution and serving-owner principal/scope/purpose grant checks, authenticated
model-visible payload and full remote final-use revalidation, a selected
transport and deployment credential owner, and Agentd remote serving. Keep
independent acceptance, activation, promotion and release separate. A digest-only
round trip cannot replace those gates.
