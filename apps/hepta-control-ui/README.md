# HEPTA Rust UI product foundation

The shared application is implemented in Rust/Makepad under `rust/robrix-ui`.
`rust/core` owns bounded presentation/chat state. `rust/web` remains an internal
Rust compatibility member so the imported workspace and locked build graph stay
coherent; it is not the default product entry. Generated Makepad JavaScript and
the static WASM loader are platform boot/render/input glue.

## Product status

This foundation is a selective source port from UI draft #1415 into the current
product. It does not yet replace the product gateway's existing `GET /` status
shell. That route must serve this verified Rust bundle and retain its existing
read-only runtime view in a separate integration slice. A new preview alone is
not product completion.

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
resources fail explicitly. There is no runtime HTTP font fetch. Downloads are
byte-bounded with atomic writes; the60-second timeout is per socket operation,
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
Their removal/deprecation and the old gateway UI entry must be handled with the
production entry slice, preserving read-only API compatibility tests.

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
