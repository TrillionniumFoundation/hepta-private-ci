# Rust control UI migration candidate

This additive candidate starts from ui.control PR #1069 head
`5c0bbe30e4a5d408c430e8ab1fcc25638042d82a`. The default browser build now selects the Rust/WASM semantic-DOM host after
three-engine head and merge parity. The legacy Node package API remains as a
compatibility/reference boundary, and is not copied into the browser artifact.
A source entry cutover is not production activation.

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

The isolated command creates `dist-rust`; `npm run build` creates the default
Rust browser in `dist`. Neither artifact includes legacy `src/` application code.
Both use pinned wasm-bindgen 0.2.128, locked Cargo inputs, and exact per-asset
SHA-256 inventories. The existing Node-facing public API is compatibility/reference
code and remains available without implying that it is the active browser UI.

## Deployment boundary and rollback

Deployment is not performed or authorized by this source change. The reverse proxy
must serve the exact same-origin artifact with `application/wasm` for `.wasm`,
`no-store`, existing CSRF substitution and authentication/isolation headers intact.
The v2 security profile permits `wasm-unsafe-eval` only in `script-src` and only when
the bound build manifest identifies `rust-wasm-v1`. It still rejects generic
`unsafe-eval`, inline code, blob/external script origins and broader connections.
CSP cannot restrict compilation to one WASM hash by itself: exact candidate asset
verification, same-origin serving and immutable versioned deployment are required.
Do not relax CSP to work around a mismatched artifact or browser incompatibility.

For a source/build rollback, use a separate clean worktree at the frozen JS parent
`5c0bbe30e4a5d408c430e8ab1fcc25638042d82a`, install its locked npm dependencies and
run its original `npm run build`. Requalify that exact artifact and the matching
JavaScript CSP before any authorized redeployment. Do not mix HTML/glue/WASM
versions, erase durable recovery records, or replay mutations during rollback.
Public package ABI migration and production activation require separate evidence.
