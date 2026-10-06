# HEPTA Rust UI product foundation

The shared application is implemented in Rust/Makepad under `rust/robrix-ui`.
`rust/core` owns bounded presentation/chat state. `rust/web` remains an internal
Rust compatibility member so the imported workspace and locked build graph stay
coherent; it is not the default product entry. Generated Makepad JavaScript and
the static WASM loader are platform boot/render/input glue.

See [RUST_ARCHITECTURE.md](RUST_ARCHITECTURE.md) for the current implementation
inventory, startup paths, owner boundaries, extension points and verification map.

## Product status

This candidate replaces the product gateway's handwritten `GET /` interface
with the verified Rust bundle. The gateway snapshots and hashes its selected
assets before serving them; the manifest digest selects bytes and is not signing
authority. The old read-only runtime API remains a separate legacy adapter.

With an explicit bundle, the gateway can serve the UI even when legacy runtime
state is missing. `/healthz` and `/api/hepta/runtime` then return 503, while the
additive `/api/hepta/owner-status` returns actual `not_attached` until an existing
production host is explicitly wired. The no-bundle startup path still requires
compatible existing runtime state. It does not fall back to a handwritten JS UI.

The principal/signer/Agentd bridge is absent. Drafts and owner-fixture messages
are not live chat. Send and Console mutations remain disabled. No native host,
old signed gateway-v2 backend, private-state crate, or old backend history is
imported. The two native resource catalog/license files are shared font contract
inputs, not an installed native application.

See [PORT_SOURCE.json](PORT_SOURCE.json) for exact imported source identities,
[CHAT_DESIGN.md](CHAT_DESIGN.md) for the visual design, and
[UPSTREAM.json](rust/robrix-ui/UPSTREAM.json) with the retained licenses for
Makepad/Robrix provenance. Historical source descriptions in the imported
workspace describe that earlier branch, not qualification of this product tree.

## Build and run

From this application directory:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm start
```

The static developer preview listens on localhost:4175. It does not authenticate
users or dispatch business operations. `npm run dev` rebuilds first. `npm test`
uses the pinned Rust1.95.0 standalone workspace and nextest. `npm run desktop`
uses the resource-complete staged shared renderer; native platform development
libraries are required. This is separate from the unported product native host.

UI stable checks use Rust1.95.0 plus the WASM standard target. The owned packager
requires exact `nightly-2026-10-02`, rust-src, and
`rustc 1.101.0-nightly (c36f14571 2026-10-01)`. Hosted UI checks retain
just1.58.0/nextest0.9.146. Select the UI toolchain explicitly; the product backend
remains Rust1.96.0 with its existing lock. Do not change that backend pin.

The builder verifies SDK patches, lockfiles, generated bridge and source/resource
identities. The preview rejects stale artifacts. Do not bypass source guards.
All theme/layout/interaction logic remains Rust.

## Fonts and resource preparation

Latin is followed by unmodified Noto Sans SC Regular/Bold, complete WenKai
tertiary fallback and emoji. Rare/out-of-subset characters can retain the prior
face; this is not uniform pan-CJK sans. The new pair is16,874,504 bytes under a
17,000,000-byte cap. Immutable hashes, provenance, copyright and OFL1.1 are in
`rust/robrix-ui/resources/fonts/`.

`npm run build` and `npm run desktop` prepare the same verified cache. Set
`HEPTA_CJK_FONT_CACHE` for a shared cache; use `HEPTA_FONTS_OFFLINE=1 npm run build`
or `python3 tools/run-desktop.py --offline` after preparation. Missing/corrupt
resources fail explicitly. Browser font loading fetches packaged assets over
same-origin HTTP from the selected verified bundle; it does not use a runtime
third-party font service. Build-time font downloads are byte-bounded with atomic writes; the60-second timeout is per socket operation,
not a whole-transfer deadline. Each desktop invocation retains its own staged
resource tree for the child lifetime. Direct unprepared native Cargo builds
fail a missing/length diagnostic; the supported wrapper verifies full hashes.

## Verification boundaries

The source branch had actual three-theme wide/compact browser fixtures and
disabled-click/draft-retention evidence at97c0631364cd6e731d0fdf89fbceaa9b34e4d258.
Those results do not qualify this product port. The source+merge product workflow
must rebuild and recapture the exact new tree. SDK tests do not replace pixels.

IME routing guards observed preedit for composer/search, navigation/edit keys,
stale owners and outside pointer events. Physical IME, inside-field selection
cancellation, hidden cached-page focus, full touch lifecycle and assistive
technology remain platform tests. Pointer-capacity exhaustion is fail-closed
and restart-only. Room switching retains text but still resets caret/selection.
No native-window/package or real owner integration success is claimed here.

Existing `src/*.js` files are authority-free legacy protocol/test oracles with
no package exports. They are not used by the Rust builder or default preview.
The gateway entry no longer uses the handwritten JS shell. These unexported
oracles are compatibility test material, not a parallel product interface.

## Build and preview lifetime

The owned browser build/preview wrappers currently require POSIX `flock` and
Python 3. The kernel lock descriptor is inherited by mutating compiler children;
parent interruption cannot permit a second writer while a child is still alive.
The last descriptor closing releases ownership automatically. The persistent
lock file is not an ownership sentinel and must never be removed to unlock it.

Preview startup recovers any interrupted publication, briefly holds a shared
lock while checking every manifest hash and loading bounded immutable buffers,
then releases the lock before listening. Existing previews keep their selected
snapshot through rebuilds; a second preview may start on another port. Restart a
preview to display a newly built version.

Builds clear only their internal generated package under exclusive ownership,
then verify unique same-filesystem staging against `patches/web-asset-paths.json`.
An fsynced journal pins the new and previous manifests before either rename.
Startup recovery verifies retained resources and completes only recognized
publication states; unknown paths, symlinks or changed pins fail closed.
Interrupted cleanup may leave an inert owned backup, without blocking later
builds. Journal initialization failure leaves the previous artifact usable.
The unused Lunar archive retains immutable provenance but is not packaged.

## Read-only product entry and completion ledger

Build the owning Rust UI, then use a source-built product executable:

```sh
python3 tools/run-product.py --hepta /absolute/path/to/hepta --state-root /absolute/state/directory
```

The wrapper prepares the current bundle and derives its digest automatically;
`--no-build` reuses only a source-current bundle. This does not initialize state,
create keys, attach a writer, or qualify the old release/install handshake.
The task-only `ui_product_preview` Rust example invokes the same gateway entry;
`tools/run-product-preview.py` supplies an empty temporary state directory for
honest missing-owner browser tests. It creates no SQL/HMAC fixture or owner.

- Implemented Rust views: responsive conversations, local drafts, theme/input
  controls, and a read-only Console. Refresh observations is an explicit GET-only
  action; opening/resizing Console does not initiate owner scans or polling.
- Legacy observation: the existing schema-v5 runtime DTO is still supported, with
  a 256 KiB client cap. Oversize/malformed data is unavailable, never truncated.
- Modern owner observation: `hepta.owner-lease-observation.v1` carries only
  `not_attached`, a generation/disposition observation, or a fixed failure enum.
  Its client cap is 4 KiB. JSON integer generations stay unsigned64 through raw
  bytes and Rust serde; JavaScript Number conversion is unsupported. This wire
  range is not a claim that SQLite accepts every u64 generation.
- Actual owner composition: a higher-level adapter must supply a weak link to an
  already-open host. The gateway adds no Agentd dependency and does not bootstrap
  one. Idle providers retain no strong host reference. An active async inspection
  temporarily retains its upgrade; its two-second response deadline is not SQL
  cancellation or owner-shutdown proof. A timed-out scan retains its single-flight
  permit until completion, returning Busy to further requests instead of spawning
  additional scans. Dispositions are point-in-time metadata, not current authority.
- HTTP boundary: loopback Host/optional Origin checks cover assets and APIs. They
  prevent browser-origin confusion and are not user authentication. Commands,
  signing, principal admission and production chat remain unavailable.
- Fixture demonstrations: rendered fixture transcripts are not live owner wiring.
  A real NotAttached response is not a fixture success-state or production readiness.
- Platform/evidence limits: bundle loading is currently Unix-only; Windows needs
  its own anchored reader. The new status view requires current source/merge
  browser captures. Physical IME/accessibility, native product closure, installed
  packaging and room caret/selection retention remain open.
