# Rust control UI migration candidate

This additive candidate starts from ui.control PR #1069 head
`5c0bbe30e4a5d408c430e8ab1fcc25638042d82a`. The existing JavaScript product
entrypoint and package API remain active until the Rust browser and caller
parity gates pass. An additive candidate is not production activation.

## Architecture decision

Use one platform-neutral Rust controller/projection library with small host
adapters. The existing native eframe application remains the only native UI
framework. Its OS effect journal, credentials, updater and final-use authority
are not moved into the shared presentation core.

The browser renderer uses Rust `web-sys` semantic DOM operations. Pinned eframe
0.36.2's WebRunner drops `accesskit_update` in `web/app_runner.rs`; its optional
web screen reader uses speech synthesis rather than a semantic accessibility
tree. Canvas would therefore discard the current DOM/ARIA/keyboard/axe
contract. No second frontend framework is introduced.

Browser authentication stays at same-origin `/api/ui-control/v1/` with existing
cookies, fresh CSRF tokens and backend authorization. No browser keyring,
loopback credential bridge, wildcard CORS, durable effect executor or grant
issuer is added. Backend admission and terminal evidence remain authoritative.

## Stages and stop conditions

1. Freeze exact JS canonical/hash/session/recovery behavior in differential
   fixtures and retain the actual product caller inventory.
2. Implement the portable Rust session/snapshot/confirmation/reservation core;
   all async effects have opaque current-session tickets and reservations
   precede dispatch. Raw caller-owned `terminalObserved` cannot create a fact.
3. Add Rust HTTP/Web Locks/storage and semantic DOM adapters preserving behavior.
4. Run differential, host fault, actual WASM/three-browser/axe, and artifact
   checks on this explicit candidate. Existing JS execution is not Rust proof.
5. Only after parity, switch actual callers, regenerate source mappings and
   qualify the immutable source and deterministic merge. Retire handwritten
   product JS only when every named caller has migrated. Current JS remains.

Native path dependencies and shared palette/controller integration wait for
both branches to converge. Neither this core nor browser routes can reinterpret
native OS-capability operations as browser start/stop requests.

## Parity matrix

| Boundary | Required evidence |
|---|---|
| Canonical JSON and hashes | Actual-JS differential vectors: safe integers, negative zero, decimal rounding, NFC, astral UTF-16 key order, duplicate fields and all bounds |
| Session and snapshot | Owned copies, permission revision, expiry/revocation, high-watermarks, coherent generation/digest, late callback fences |
| Intent and confirmation | Exact action/target/reason/operation, session/principal/permission, target revision/digest and displayed snapshot; Cancel-first keyboard modal |
| Operations | Synchronous reservation, duplicate sharing without redispatch, capacity across principals, late ACK ownership, authenticated terminal lookup |
| Recovery | Existing record/directory schemas and namespace, atomic import, Web Locks denial, crash transitions, delayed admission, no unresolved-ID loss |
| Transport | Exact origin/base, cookie inclusion, fresh CSRF, redirect rejection, 64 KiB request and streamed 1 MiB response, strict UTF-8, body deadline, no retries |
| Browser | Existing roles/labels/tables/dialog/live alerts, focus retention/restoration, redaction, incremental keyed rows, BFCache/pagehide, three engines and axe |
| Qualification | WASM plus generated glue inventory, narrow wasm-unsafe-eval CSP, exact-source and synthetic-merge evidence; independent acceptance remains external |

## Bounded local checks

Prerequisites: repository Rust toolchain, wasm32-unknown-unknown standard library,
wasm-bindgen-cli exactly 0.2.128, existing locked npm test dependencies.

From repository root:

- `node apps/hepta-control-ui/rust/core/tests/generate-differential.mjs --check`
- `just test --manifest-path ../apps/hepta-control-ui/rust/Cargo.toml --locked`
- `cargo clippy --manifest-path apps/hepta-control-ui/rust/Cargo.toml --locked --all-targets -- -D warnings`
- `cargo clippy --manifest-path apps/hepta-control-ui/rust/Cargo.toml --locked --target wasm32-unknown-unknown -p hepta-control-web -- -D warnings`
- `node apps/hepta-control-ui/tools/build-rust.mjs`
- `UI_CONTROL_CANDIDATE=rust npm exec --prefix apps/hepta-control-ui -- playwright test --config apps/hepta-control-ui/playwright.rust.config.mjs`

Set CARGO_BUILD_JOBS=2, CARGO_INCREMENTAL=0 and a dedicated CARGO_TARGET_DIR to
bound local resource usage. The standalone nextest local profile has no retries
or skips. Bindgen's generated JavaScript loader/ABI is inventoried separately
from handwritten product logic. CSS, HTML and fonts are static presentation
assets. The candidate fixture server adds only `wasm-unsafe-eval`, not broad
`unsafe-eval`, and serves WASM with `application/wasm`.

The isolated build creates `dist-rust`; it does not replace `dist`. Production
CSP deployment and public package ABI cutover remain a separate review gate.
