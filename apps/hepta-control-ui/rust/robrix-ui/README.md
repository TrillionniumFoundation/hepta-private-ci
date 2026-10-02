# Hepta Robrix-derived UI

This is the canonical UI implementation under development. It adapts runtime-used
Robrix source at `f2208f16184e1b2d8307dc9f98375e47b1fcd677`, using its pinned
Makepad `337566c8b25d47f7e4fff6a202157b65bf183330`. See `UPSTREAM.json` for exact
source regions, hashes and modifications, and `licenses/ROBRIX-MIT.txt` for the
copyright/permission notice. No Matrix protocol or SDK implementation is included.

The same Rust widget modules build for native and WASM. Conversation navigation,
virtual message timeline and composer are primary; Console is an internal tab.
The Console currently reports its unported operational controls. It does not
pretend those controls are preserved by a placeholder. Existing native owner,
recovery and platform implementations remain in their original crates for reuse.

`presentation.rs` reads the existing bounded `ChatWorkspace` and applies fenced
local actions. It does not introduce a runtime, credentials, a signer, a message
ledger or an authenticated bridge. Sending remains unavailable without external
owner composition. Queue acknowledgement is never model completion. Local drafts
are not transcript messages. Core observer fixtures must remain visibly fixtures.

## Commands and evidence limits

From `apps/hepta-control-ui`, `npm run build` produces the Makepad Web package,
`npm run dev` builds and serves it locally, and `npm start` serves that artifact.
The build resolves the pinned Makepad checkout from Cargo metadata, verifies its
tracked bytes and compiles that checkout's packaging tool. It rejects an
unqualified nightly instead of silently claiming reproducible output. Current
recorded compile input is nightly `1.101.0-nightly (c36f14571 2026-10-01)`;
this is a build input record, not host qualification.

Native: `cargo +1.95.0 run --manifest-path rust/Cargo.toml -p hepta-robrix-ui
--bin hepta-robrix`. Linux requires the official Wayland/X11/ALSA development
libraries. This cloud's native check stopped at missing `wayland-client.pc`;
package installation was not permitted by its filesystem/root environment.

Pure presentation tests use repository `just test`, package `hepta-robrix-ui`,
`--no-default-features --lib`. Disabling graphics for these tests does not qualify
the renderer. Standard `wasm32-unknown-unknown` check and no-threads release
packaging have succeeded locally. Actual browser/native pixels, keyboard/IME,
assistive technology, light-theme parity and mobile Web input remain unqualified.
The pinned framework disables mobile Safari/Android keyboard binding; this is a
real implementation gap, not a supported mobile-chat claim.

## Web runtime inventory

Application layout, state and event logic are Rust. The WASM package contains
Makepad's JavaScript platform/ABI loader, input, WebGL and browser integration.
That framework glue is distinct from application UI logic. The owned packaging
step removes automatic crash uploads, removes the viewport zoom restriction (actual canvas pinch behavior remains unverified), externalizes the
bootstrap and keyboard CSS, and retains a restrictive CSP. Static bridge emission
is required because upstream runtime `new Function` conflicts with that CSP;
this packaging acceptance remains under review until the browser tests pass.

International fonts currently contribute about 49.5 MB of the package; first
qualification preserves them. Font coverage/loading optimization and complete
third-party font notices remain review items. No production deployment is
qualified by a compile or by old egui/DOM screenshots.
