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

The shared chat widgets consume the bounded Rust workspace and preserve its
room/principal action fences. The production principal/signer bridge is absent,
so local drafts are not live chat and Send remains disabled. Console identifies
its unported operational controls; the tab is not functional parity with the
retained native Console implementation.

Latest observed checks on 2026-10-03:

- Standard WASM checks, pinned no-threads release packaging, and the strict-CSP
  static bridge build have passed. Native display/OS qualification is still
  blocked; the cloud native check lacked Wayland development metadata
- Exact-head and prospective-merge Rust compatibility passed at `24472794`.
  [Its actual Makepad browser run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37104412555)
  failed and remains failed evidence. Chromium/Firefox produced all three
  default theme screenshots without application script errors; this does not
  qualify the populated timeline, CJK/emoji pixels or WebKit presentation
- Runtime-used widgets now include the real three-theme selector, role-aware
  message layout and shared desktop/narrow editor instances. Fresh source
  `7c568089` adds scroll/reflow separation, a disabled circular send control,
  viewport overflow regression and fixture-only resource lifecycle diagnostics
- Thirteen projection tests and eighteen static-bridge/pixel regressions passed
  locally for that source. Browser wheel/resize/Jump and font lifecycle checks
  require fresh actual-host results; model probes do not qualify pixels
- The initial glyph-block defect was traced to WASM instance-layout padding and
  repaired with exact-type regressions. CJK/emoji rendering remains intermittent:
  valid font bytes, fallback and raster probes pass. An actual-WASM callback
  regression traced missing delivery signals to detached JavaScript views after
  large-body memory growth. The packaging fix refreshes views before each message;
  fresh browser pixels remain required. The current browser gate stays strict
- Real OS input methods, assistive technology, native rendering, mobile Web
  keyboard support, live chat composition and font redistribution are unqualified

These are intermediate results, not product or release completion. Existing
Console/DOM/egui test receipts and CPU fixtures do not qualify this new host.
The UI continues to use existing core state and authorization contracts; no
new runtime, credentials, signing authority or Matrix service behavior is added.
