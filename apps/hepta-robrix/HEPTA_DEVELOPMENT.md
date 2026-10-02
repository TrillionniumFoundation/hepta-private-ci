# Hepta on Robrix: development contract

## Foundation

The application is a fork of upstream Robrix v1.0.0-beta.1, commit
`2e9194caddb842eb9697d6dfa774c398ddea25d0`. `UPSTREAM_PROVENANCE.json`
records immutable imported bytes; it is not a manifest of current patched bytes.
Keep the MIT license, asset attribution, and third-party notices. Upstream
packaging is historical input, not authorization to sign or publish as Robrix.

Native and browser must render the **same actual Robrix Makepad widget tree**:
App, AdaptiveView, HomeScreen, RobrixDock, room list, RoomScreen, timeline and
composer. Do not replace these with DOM/CSS or egui lookalikes. Platform adapters
may differ for execution, storage, media, and authentication. Console is a
secondary dock destination with persisted navigation and mobile behavior.

Matrix owns Matrix identities, room IDs, encryption, timeline and delivery state.
A Hepta agent conversation must never be cast into a Matrix room. The independent
Agentd transport is optional integration work, not a replacement Matrix backend.
Console readiness must not imply Matrix login, or vice versa. Preserve existing
authorization, cancellation and exact-generation checks at backend boundaries.

## Dependency and storage safety

The imported SDK 0.18 is not an acceptable production dependency. Crypto must
meet RUSTSEC-2026-0318 (fixed >=0.19.0); the candidate uses exact SDK family
0.19.1 and the existing reviewed Hepta anymap3 patch at the canonical
`codex-rs/third_party/matrix-sdk-0.19.1` path. Rust 1.96 is the minimum.
Makepad and Robius git dependencies are pinned to imported lockfile commits.
Update provenance and qualify the entire family when changing these pins.

Native uses the SDK SQLite backend. Browser must use the SDK IndexedDB backend
and browser-compatible executor; browser session secrets must not be stored in
localStorage. Browser authentication/persistence limitations must be explicit.
No test may open a real user database or use an existing account. Migration
qualification uses synthetic state and a disposable test homeserver. Back up
paired native state before any separately authorized installed-host migration;
never run an older SDK against upgraded stores.

## Build and acceptance gates

1. Compile the actual imported application with the upgraded native dependency
   graph. Record exact source and lockfile, and preserve errors as evidence.
2. Compile the same application through the pinned Makepad WASM tool. Its
   `--bindgen --no-threads` mode is a candidate, not a proven Robrix web target.
   Do not treat Makepad example success as Robrix application success.
3. Run actual widget fixtures on both targets, including narrow and short
   viewports, keyboard/IME, accessible text/control exposure, zoom and focus.
4. Exercise login cancellation, restore/logout/account isolation, real Matrix
   sync, E2EE send, failed/unknown delivery, retries and offline reconnect.
5. Exercise Console dock save/restore/repair and resize without losing state;
   then qualify the configured headless Hepta adapter independently.

The older custom WASM/DOM and egui UI test receipts are retained historical
experiments. They cannot qualify this Robrix-based application. A successful
compile is not live-account or deployment acceptance. No merge, deployment,
production signing or credential creation is part of this work.

## Current feasibility boundaries

Upstream Robrix has no qualified web CI lane in the imported release. Its
unconditional Tokio multithread runtime, SQLite, filesystem persistence and SSO
local callback server need platform adapters. Makepad itself includes a real web
backend and wasm-bindgen packaging, which is necessary but not sufficient.
Browser SSO requires an explicit redirect/origin contract before availability;
unimplemented native services must report unavailable rather than fabricate
success. TSP is an upstream experimental extension and needs separate dependency
and signature compatibility qualification after the SDK upgrade.

## Verified upstream patch retirement

The imported Robrix store-encryption override is no longer necessary: upstream
[PR 6976](https://github.com/matrix-org/matrix-rust-sdk/pull/6976) merged on
2026-09-07 as `2c2cf6e7028ac71cce996104b0ab343db8602992`. Registry
matrix-sdk-store-encryption 0.19.1 records source commit
`b18166c68bb958a21f0bca8b2d8320cb53583362` and retains the `serde_bytes`
attribute on `EncryptedValue.ciphertext`. No cryptographic source is patched.

The release's original TLS feature selection differs from current Robrix main.
This candidate explicitly selects the SDK native rustls provider and the shared
Hepta rustls security floor; the browser uses its platform fetch implementation.

## Browser account lifecycle and current limits

Browser-only SDK handles remain thread-local; there are no unsafe Send/Sync
implementations. Local UI actions and cache queues are bounded and fenced by
account epoch. Per-account tasks and registered SDK callbacks are aborted on
authority replacement; queued requests also carry their originating epoch.
Long-lived login/control loops remain alive while individual login/restore
attempts are cancellable. Session persistence checks its originating authority
and cannot erase a newer account's metadata after an old restore fails.

Upstream password-login Cancel remains disabled. Task cancellation and shutdown
fences do not constitute a user-visible Cancel feature. Browser SSO and
path-backed attachment upload/share remain explicit unavailable capabilities
until their platform adapters are qualified. Real browser test execution,
linked Makepad packaging, rendering and accessibility remain separate gates
from successful native/WASM type-checks.
