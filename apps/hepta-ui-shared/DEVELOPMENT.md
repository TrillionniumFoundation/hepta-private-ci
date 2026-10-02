# Hepta messaging design contract

## Product hierarchy (normative)

Hepta is a conversation application. The initial destination MUST be Chat, never
a runtime dashboard. Desktop and browser MUST use this same Rust contract and
information architecture: workspace rail, searchable conversation list, selected
conversation identity, message timeline, composer. Console is a secondary tab
within this application; it retains authenticated runtime tools and their existing
confirmation and recovery safeguards.

Do not implement a second independent UI design for browser and desktop. Shared
presentation state and logical pixel/RGB tokens live in `chat.rs`, consumed by
Rust WASM (`hepta-control-core`) and the Rust native host. Host-specific rendering
is appropriate for semantic DOM versus egui; product navigation and state semantics
are not host-specific. JavaScript in browser output is generated WASM glue and a
minimal loader only. Application views, transitions and rendering remain Rust.

## Reference and visual decisions

Primary reference: https://github.com/project-robius/robrix and
https://robrix.app/images/robrix-dock.png (inspected 2026-10-02).
The inspected image has a room list at left and docked message timelines with
persistent composers at right. Adopt its conversation hierarchy, not its branding
or an unrelated dashboard. Hepta's palette is restrained dark navy with cyan
focus/selection accents; text contrast and explicit state words take precedence
over decorative effects. No fake online indicators, unread counts, messages,
avatars implying real users, or fabricated successful operations.

## State and interaction invariants

- `AppTab::Chat` is the default; repeated tab selection is idempotent.
- An unavailable messaging transport is not an empty authenticated inbox and is
  never presented as a ready messaging product. Show its actual limitation.
- Only backend-observed conversations populate the list and backend-observed
  message bodies populate the timeline. Test fixtures are qualification only.
- Room changes preserve unsent drafts by conversation. Late timeline responses
  must match room, session generation, and `selection_epoch` before rendering.
- Session replacement clears conversations, timeline, selection and all drafts.
  Navigation may remain. Never persist message text or credentials in web storage.
- Disable send without authenticated readiness, valid selection, bounded nonblank
  text, or while an attempt is in flight. An ambiguous send must be reconciled by
  its original idempotency identity; never retry as a new message automatically.
- Cancellation is an observed protocol action, not merely hiding local output.
- Preserve scroll/focus while applying updates. Use native controls and labels,
  44-logical-pixel controls, keyboard operation, visible focus and narrow layouts.
- Runtime console confirmation, stale revisions, identity binding and operation
  recovery are unchanged security boundaries. Switching tabs cannot grant authority.

## Qualification and provenance

Both hosts MUST include `apps/hepta-ui-shared/` in their immutable-source manifests
and qualification inputs. Do not relabel old console screenshots or frozen source
receipts as evidence for this redesign. Native source manifests/candidate gates
need coordinated updates before any release qualification claim.

Run shared behavior tests through `just test`; run WASM/native compile and lint;
exercise browser and native snapshots for chat, selected room, empty, unavailable,
loading, offline, errors and secondary console. Test repeated clicks, keyboard
navigation, dismissal, stale responses and draft retention. Browser fixture tests
are not deployed authenticated backend qualification.

Local Chromium currently cannot launch due to the platform's Unix socket
restriction; browser assertions in those attempts did not execute. Use the existing
head/merge hosted browser qualification lane and inspect its exact-source images.
All unrun/platform-blocked/real-backend-unavailable coverage must remain explicit.

## Messaging backend integration

`chat_transport.rs` is the versioned shared request/response boundary. Both hosts
validate exact response/session/generation/command/thread/operation identities
before applying data. Browser uses cookie-authenticated same-origin POST
`/api/ui-control/v1/chat/request`, CSRF, bounded JSON and existing abort deadlines.
The native adapter uses the Rust chat owner process backed by the exact-generation
Agentd SessionIngress and existing App Server conversation APIs. These are ordinary
agent conversations, not Matrix homeserver room discovery or a bypass around a
Hepta execution plan. Server approval requests are declined and surfaced explicitly.

Queued, persisted, cancelled and unknown outcomes remain distinct. A queued
acknowledgement never fabricates a timeline message. Actual timeline reads determine
visible content and active turns. Polling only reads while the current document is
visible, connected and in the Chat tab. Pending text/operation IDs are memory-only;
closing or replacing the session loses local reconciliation context. A production
host must compose and qualify the authenticated browser route; this repository's
Node fixture is test-only and is not a deployed chat service.

### Current bounded product limits

The UI currently displays the latest bounded page (up to 50 conversations / 50
messages); older-page browsing, attachment upload, rich rendering and docking are
not implemented. Do not describe this as full Robrix feature parity. Drafts and
uncertain send identities are tab/process memory, not durable offline delivery.

Browser chat starts after authenticated session issuance, without waiting for the
optional console snapshot. Missing `runtime.read` disables console reads locally;
authentication refresh does not grant that permission. Existing `ui.control.v1`
validation still requires at least one known runtime permission, so a principal
with zero runtime permissions needs an explicit backend session-contract extension.
No unknown permission or invented unauthenticated bootstrap is accepted here.
