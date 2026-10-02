# Chat-first Rust desktop continuation

This continuation changes the application hierarchy, not merely its palette.
The default screen is Chat. A 64 logical-pixel workspace rail exposes Chat and
Console. Wide layouts use the same shared 280-pixel conversation column as the
Rust web host; narrow layouts use a conversation list and selected-conversation
Back flow. A bottom-pinned composer remains reachable at 150% scaling.

## Source and claim boundary

`apps/hepta-native/CHAT_REDESIGN_CANDIDATE.json` binds the exact committed source
and shared Rust inputs. It is a new, unqualified implementation candidate.
`CURRENT_SOURCE.json`, `CANDIDATE.json`, the v6 implementation map and prior
platform/security receipts retain their original historical identities. They
must not be promoted or interpreted as evidence for this continuation.

The shared presentation contract is owned by `ui.control` under
`apps/hepta-ui-shared`; native consumes it without claiming duplicate ownership.
The chat owner executable is a separately built first-party dependency. Native
configuration pins its exact executable digest. Candidate composition requires
the corresponding chat-owner implementation; renderer fixtures alone do not
establish authenticated end-to-end chat.

## Owner boundaries and failure behavior

- Chat uses a separate bounded stdio adapter for the first-party chat host.
  Agentd SessionIngress, project/workspace/source scoping, generation health and
  app-server queue reconciliation remain the authority path.
- Runtime diagnostics retain the existing read-only, signed native gateway.
  Its MAC contract has not been expanded to accept chat mutations.
- No configuration is invented. Missing configuration produces a visible setup
  shell. Console preflight failure does not construct a console runtime.
- Only explicitly classified connection-level I/O unavailability permits late
  chat-only fallback. Authentication, integrity, updater rollback, state,
  permission and indeterminate failures remain fatal.
- The Console fallback displays its exact blocker and setup guidance. Correct
  configuration and restart explicitly; no privilege or credential is created.
- Chat drafts remain local until Send. Queue admission does not imply a rendered
  message. Only observed owner messages enter the timeline. An exact persisted
  submission receipt may clear only its original unchanged draft.
- Reconnect checks the same pending operation through Reconcile; it does not
  blindly replay an uncertain Send. Newer room selection rejects stale timeline
  responses. Tool approvals are surfaced and never auto-approved here.

## Validation

Local tests exercise empty/offline content, observed fixture timelines,
keyboard composer input, AccessKit labels, room/tab draft preservation,
connection-independent setup, state-reduction retries, stale selection and
small/150%-scaled viewports. The diagnostic source-export workflow has an
explicit Linux-only `native_chat_only` mode for these tests and Xvfb raster
captures. Its fixture-only screenshots are rendered-layout evidence, not native
security qualification or installed acceptance. It does not run Windows
registrar or AuthBus work, contact live accounts, or send live messages.

Canonical multi-platform qualification, packaged chat-host composition and
security acceptance remain pending. Do not merge, deploy or release based on
these UI diagnostics.
