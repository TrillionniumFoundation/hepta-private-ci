# Rust UI implementation and integration guide

## Scope and evidence identity

This guide describes the Rust product foundation at source tree
`d346231a4a06c45aa43e6dae138de61e0ace017f` (published UI candidate
`7cfd974786905ef1f4c5d0beae9c502d83e29c8b`). It is a source navigation and
integration guide, not a build receipt or platform acceptance. Changes to this
document do not transfer earlier screenshots or test results to a new candidate.

Application layout, widgets, themes, state projection and event handling are
Rust/Makepad. The browser artifact also contains Makepad JavaScript for WASM
loading, ABI messages, WebGL and browser input. Node/Python wrappers build,
verify and serve that artifact. “Rust application UI” does not mean “no JavaScript
shipped”. The old unexported `src/*.js` files are compatibility/test oracles;
they are not the default application renderer.

## Module position and source inventory

`ui.control` owns this application root. Its registered ownership, denied
capabilities and delivery gates remain in the module registries. This concrete
inventory supplements the historical JavaScript operation map; it does not
change that map's completion flags or claim that its coverage includes Rust.

- [rust/core/src/chat.rs](rust/core/src/chat.rs) and its `chat/` modules:
  bounded local conversation state. Drafts are not transmitted messages.
- [rust/core/src/owner_view.rs](rust/core/src/owner_view.rs): strict, bounded
  owner-observation parser and ticket-fenced state; preserves unsigned 64-bit
  generations and always appends the no-current-authority caveat.
- [rust/core/src/runtime_view.rs](rust/core/src/runtime_view.rs): independent
  legacy schema-v5 runtime reader and bounded failure states.
- [rust/robrix-ui/src/presentation.rs](rust/robrix-ui/src/presentation.rs):
  deterministic local action projection, without a principal, signer or writer.
- [rust/robrix-ui/src/app.rs](rust/robrix-ui/src/app.rs): application event and
  lifecycle integration; browser RuntimeClient is WASM-specific.
- [rust/robrix-ui/src/robrix/home.rs](rust/robrix-ui/src/robrix/home.rs): shared
  desktop/compact navigation and read-only Console. At this baseline it renders
  observations in wrapping labels, not the proposed richer status cards.
- [rust/robrix-ui/src/runtime_status.rs](rust/robrix-ui/src/runtime_status.rs):
  explicit-refresh browser HTTP sequencing, deadlines, cancellation and widget
  publication. Native default text states that no owner bridge is installed.
- [rust/robrix-ui/src/native_host/mod.rs](rust/robrix-ui/src/native_host/mod.rs)
  and [render.rs](rust/robrix-ui/src/native_host/render.rs): optional
  `native-host` presentation seam for an externally supplied existing owner.
  The product does not compose that owner simply by compiling these modules.
- [tools/build-robrix.mjs](tools/build-robrix.mjs) and
  [tools/serve-robrix.mjs](tools/serve-robrix.mjs): verified WASM packaging and
  static preview. Framework transformations and exact-input guards live under
  [rust/robrix-ui/patches/](rust/robrix-ui/patches/).
- [tools/run-product.py](tools/run-product.py): invokes a supplied source-built
  product executable with the verified UI bundle and its derived manifest hash.
  The backend remains in
  [codex-rs/hepta-native-gateway](../../codex-rs/hepta-native-gateway/), outside
  this standalone UI workspace.

`ui.native` retains its separate `apps/hepta-native` registration and legacy
adapter map. Two native font catalog/license inputs and an optional renderer
trait are not a completed native product port. Enabling `native-host` does not
create an authenticated host implementation or install a native application.

## Supported startup paths

Run application commands from `apps/hepta-control-ui`, not the repository root.
The authoritative script names are in [package.json](package.json).

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm start
```

This builds and serves the static developer preview on localhost:4175.
`npm run dev` rebuilds first. A static preview is not the product gateway and does
not compose the owner endpoints or enable operations. `npm start` verifies and
serves a source-current artifact; restart it to observe a later build.

```sh
npm run desktop
# After verified font preparation, and with required Cargo inputs cached:
python3 tools/run-desktop.py --offline
```

The desktop wrapper verifies font resources, copies the standalone workspace to
an invocation-owned staging directory, and runs the shared Rust renderer using
Rust 1.95.0 and `--locked`. It retains staged resources until the child exits.
Direct unprepared `cargo run` is not a resource-complete supported preview.
Native platform development libraries remain prerequisites. This command runs a
renderer preview, not a qualified installed product or attached native owner.

```sh
python3 tools/run-product.py --hepta /absolute/path/to/hepta --state-root /absolute/state/directory
```

Supply a source-built executable and an existing state directory. The wrapper
builds the bundle, verifies production/non-fixture identity and source currency,
and invokes `--serve-ui` on loopback port 7373 by default. `--no-build` only reuses
a verified source-current artifact; `--listen` selects the bind address. It does
not initialize runtime state, generate credentials, or attach a writer. Bundle
loading currently requires the reviewed Unix/POSIX anchored reader.

The task-only [tools/run-product-preview.py](tools/run-product-preview.py) uses
`HEPTA_GATEWAY_EXAMPLE` to select a source-built `ui_product_preview` executable
and supplies an empty temporary state directory. It exercises the real gateway's
missing-owner path without creating a database, key or owner. That evidence is
not a successful attached-owner session or installed-package qualification.

### Toolchain and resource contract

- Node >=22 is declared by the application package; Python 3 and POSIX `flock`
  are used by the owned browser build/preview lifetime wrappers.
- Stable UI checks use Rust 1.95.0 and `wasm32-unknown-unknown`. Backend Rust 1.96.0
  is separate; do not change the backend pin to build this UI.
- WASM packaging requires `nightly-2026-10-02`, rust-src and exact rustc
  `1.101.0-nightly (c36f14571 2026-10-01)`, as guarded by the SDK patch contract.
- [README.md](README.md#fonts-and-resource-preparation) describes verified font
  preparation, the offline cache, byte limits and licenses. Build-time retrieval
  is distinct from browser delivery of packaged font assets. Keep HTML, WASM,
  generated bridge and fonts from the same verified build.

## Owner, read-only and lifecycle boundaries

With an explicit verified bundle, the gateway serves the Rust UI even if legacy
runtime state is absent. In that degraded case `/healthz` and
`/api/hepta/runtime` return 503; `/api/hepta/owner-status` can return HTTP 200 with
actual `not_attached`. Without a bundle, the pre-existing startup path still
requires compatible runtime state. There is no handwritten-JavaScript UI fallback.

The owner API is `hepta.owner-lease-observation.v1`, with a 4 KiB client limit.
The independent legacy DTO has a 256 KiB client limit. Invalid, oversize or failed
responses become unavailable, not truncated success. Generation values pass as
raw HTTP bytes into Rust serde; converting them through JavaScript Number would
lose the full u64 contract.

Refresh performs owner then legacy GET requests, one active request at a time,
with a five-second deadline per request. Opening or resizing the Console does
not poll. Repeated refreshes during an active sequence are ignored/disabled.
Navigation away, background, shutdown or epoch changes cancel/reset observations;
request IDs and reader tickets prevent stale completion from restoring old data.
No-request is different from an actual `not_attached` observation.

The server's weak owner adapter must be supplied by a higher layer that already
owns an open host. It neither opens stores nor acquires authority. An active
inspection temporarily upgrades that weak reference. Its two-second response
deadline does not cancel underlying owner work: an unfinished scan retains the
single-flight permit and subsequent reads receive Busy until completion.
See [owner_status.rs](../../codex-rs/hepta-native-gateway/src/owner_status.rs).

Host/optional Origin validation is a loopback browser-origin boundary, not user
authentication. Every observation is point-in-time metadata, including an Active
lease disposition. It never grants current write authority. Send, principal
admission, signing, Agentd dispatch and Console mutations remain unavailable.

## Extension points and required constraints

1. Visual composition belongs in Rust widgets and typed presentation. Preserve
   both desktop/compact paths, wrapping, scroll containers, lifecycle handling
   and the authority caveat. Derive new cards from typed states, not by parsing
   human-readable status strings. Proposed cards are not implemented here.
2. Owner integration belongs in the existing higher-level owner composition.
   Supply a bounded adapter to an already-open host; do not teach the UI/gateway
   to open a store, synthesize a lease, create keys or reinterpret observations
   as permission. Live chat requires its own authenticated writer composition.
3. Native integration must implement the existing `NativeHost` trait while
   retaining its readiness, rendered-identity and safe-close contracts. The
   optional renderer's native limitations text must survive future visual work.
4. Browser/platform changes belong in verified packaging transformations with
   exact SDK identities and source guards. Keep CSP and transport constraints;
   do not patch Cargo cache files or mix generated outputs across builds.

## Verification map and remaining qualification

The following are source/test navigation references, not claims they passed on
this candidate:

- `npm test`: pinned nextest checks for `hepta-control-core` and
  `hepta-robrix-ui` with `--no-default-features --lib`; includes
  [owner_view_tests.rs](rust/core/src/owner_view_tests.rs),
  [runtime_view_tests.rs](rust/core/src/runtime_view_tests.rs) and
  [presentation_tests.rs](rust/robrix-ui/src/presentation_tests.rs).
- [e2e/robrix-product-status.spec.mjs](e2e/robrix-product-status.spec.mjs):
  owner/runtime read behavior and missing-owner product screenshots.
- [e2e/robrix-host.spec.mjs](e2e/robrix-host.spec.mjs): actual renderer-host
  interaction coverage; fixtures must remain labeled as fixtures.
- [test/product-console-audit.test.mjs](test/product-console-audit.test.mjs)
  and [test/test_run_product.py](test/test_run_product.py): source/launcher
  diagnostic-audit and launcher regressions. Guards do not replace execution or
  pixel review.
- [.github/workflows/ui-product-foundation.yml](../../.github/workflows/ui-product-foundation.yml):
  candidate-specific build/test/evidence workflow. Inspect its exact source and
  merge-candidate runs before asserting qualification.

Still open: actual attached-owner composition; principal/signer/Agentd chat;
final-source visual and interaction acceptance; native product closure and
installed packaging; physical IME and assistive-technology checks; mobile input;
room-switch caret/selection retention; and a Windows anchored bundle reader.
A diagnostic stopped before completion is not acceptance. Missing-font/time-out
investigations, OCR success or compilation alone cannot establish typography,
accessibility, full visual finish, production readiness or release authority.

Historical module-map `productExecutionComplete`, deployment, acceptance and
production flags remain false. This guide neither flips them nor replaces
required independent evidence. Qualification, product completion and release are
separate decisions.
