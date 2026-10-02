# Hepta Conversations

The current application is an actual Robrix-derived Rust/Makepad UI in
[`rust/robrix-ui`](rust/robrix-ui), shared by native and Web targets.
[CHAT_DESIGN.md](CHAT_DESIGN.md) is the normative design: Conversations first,
with Console as a secondary tab inside the chat application.

This replaces the unpublished egui/semantic-DOM direction at `6a94f019aeee`.
The derived dock, adaptive shell, conversation rows, timeline and composer are
registered in the Makepad application. Source mappings, exact upstream revisions
and attribution are in [`UPSTREAM.json`](rust/robrix-ui/UPSTREAM.json) and the
[retained MIT notice](rust/robrix-ui/licenses/ROBRIX-MIT.txt).

## Build and run

From this application directory, `pnpm dev` builds and serves the Makepad Web
app, `pnpm build` writes `dist/`, and `pnpm start` serves an existing build on
localhost:4175 by default. These entrypoints are wired in source; final package
and browser verification remain subject to the status below. The server
serves static files only and is not a live chat/backend service.

See the [Rust integration guide](rust/README.md) for prerequisites and native/Web
crate commands. `pnpm build:legacy-dom` is an explicit compatibility build, not
a Robrix preview. Application UI logic is Rust; generated Makepad browser
JavaScript is framework boot/render/input glue.

## Current status

The adaptation is in progress. Widget state/actions are still being connected.
The production principal/signer bridge is absent, so local drafts are not live
chat and Send must remain unavailable with an explanation. Console currently
contains a placeholder; operational controls have not been ported into this host.

Latest reported checks on 2026-10-02:

- Standard `wasm32-unknown-unknown` Rust check passed
- Twelve presentation-only tests passed with the Makepad UI feature disabled
- Native check is blocked by missing Wayland development metadata; installation
  attempts were denied by filesystem/root permissions
- The unsupported WASM clock call was repaired by a recorded, isolated platform
  patch; the corrected artifact starts and yields its actual bridge schema
- Static bridge emission and 17 targeted helper tests passed. An actual-artifact
  check constructed the generated classes and encoded/freed a message. The
  packaged bridge checks schema equality without runtime JavaScript evaluation
- Earlier no-threads packaging succeeded; fresh final package/build verification
  and browser checks are pending
- Native rendering and successful packaged browser startup remain unvalidated

These are intermediate results, not product or release completion. Existing
Console/DOM/egui test receipts and CPU fixtures do not qualify this new host.
The UI continues to use existing core state and authorization contracts; no
new runtime, credentials, signing authority or Matrix service behavior is added.
