# browser.servo Servo pin audit

**Predecessor pin:** `84bcc9ac701874fa9819e5cdee06356b961d736c` (2026-09-04)  
**Qualification candidate:** `5cc5bd32d02619acdec5736055515e38c5840ce1` (2026-09-18)  
**Candidate state:** source-selected, reviewed candidate lock committed, exact-head qualification pending

## 1. Decision

The Browser/Servo source candidate is frozen at `5cc5bd32d02619acdec5736055515e38c5840ce1`, but it is not
called qualified until the exact repository head produces a locked dependency
receipt, successful real Browser E2E, reproducible byte-identical worker builds,
SPDX SBOM, and the required target-host evidence.

The previous pin remains provenance only. Deployment qualification must reject a
build receipt whose Servo pin, source SHA, Cargo.lock, worker digest, or SBOM
does not match the selected exact head.

## 2. Upstream delta

GitHub comparison reports the candidate is 239 commits ahead of the predecessor
and zero commits behind. This is a broad requalification, not a narrow patch.
The delta touches Browser-relevant areas including:

- `components/config/prefs.rs`;
- `components/net/*` HTTP loading, cache, fetch, websocket and resource code;
- constellation/event-loop/pipeline code;
- script/document/input handling;
- HTML form and input controls;
- Servo embedding and WebView-adjacent code;
- Cargo dependency resolution.

Because these areas overlap navigation, proxy routing, observation, form typing
and worker lifecycle, compile success alone is insufficient.

## 3. Input/WebView deadlock fixes

Two upstream changes after the predecessor are specifically relevant to
embedder lifecycle risk:

- `1a753c521c73912c43408a13f7b9b72b39989d0c` (2026-09-16) drops pending
  WebDriver events when closing a WebView so a receiver is not left hung.
- `5cc5bd32d02619acdec5736055515e38c5840ce1` (2026-09-18) queues
  `EmbedderMsg::InputEventsHandled` unconditionally, closing the remaining
  iframe-removal deadlock/CRASH path described by upstream issue #48128.

The current Hepta click/type implementation uses fixed worker-owned JavaScript
(`element.click()`, value/input/change mutation) rather than WebDriver input
events, so these commits are not treated as proof of a Hepta bug. They are
treated as evidence that WebView/input lifecycle code changed materially and
must be covered by the candidate E2E before promotion.

### 3.1 Post-freeze upstream review (2026-09-19)

At review time Servo `main` is `c34536fd90687e36c062cab708545affacb8694b`,
six commits ahead of the frozen `5cc5bd32d02619acdec5736055515e38c5840ce1`
candidate and zero commits behind. The six post-freeze commits are:

- `561bb95631374bb4323e54ac1cc67dd91cdd73d1` — servoshell context-menu stroke only;
- `1c6b500494f3359350641fb28fe3891a1d6bb07f` — safer rooting for ByteLengthQueuingStrategy callback values;
- `55c0e7698f72e0733b9628bf9a36dc7ac2a7d85c` — rustls-native `TlsSecurityInfo` types and related net/devtools serialization;
- `58c86d000a0a8ec1e5ba8c52ba8ac736d26b52d2` — visible image selection;
- `b820a9679a784877f91b4acc90c2c6e849f18d3b` — Android Kotlin build-output ignore;
- `c34536fd90687e36c062cab708545affacb8694b` — safe sequence conversion for tee cancellation reasons.

The compare touches `Cargo.lock`/workspace dependency metadata, layout/script
code and net files including `components/net/connector.rs`,
`components/net/http_loader.rs` and shared net types. The TLS change alters
security-info representation/serialization, not the public proxy-preference
surface used by Hepta, and none of the six commits supersedes the
`InputEventsHandled` deadlock fix at the frozen candidate.

The freeze therefore remains at `5cc5bd32...` for this qualification cycle.
Moving the pin now would invalidate the already reviewed candidate lock and
restart locked-build, real-E2E, reproducibility and SBOM evidence. The next pin
refresh must rerun the complete promotion oracle below; this review is not a
claim that arbitrary future upstream commits are compatible.

### 3.2 Current upstream review (2026-09-20)

Servo `main` has since advanced to
`b5a1f5e6ec6f8685d40cd389802ced7abe4980f6` (2026-09-19T17:17:51Z),
13 commits ahead of the frozen `5cc5bd32...` candidate and zero commits
behind. This post-freeze window includes Browser-relevant changes:

- `07777aaa24af690a52648f1cd7e575659310cee8` — avoids double-borrow
  hazards when accessing `Servo` from `WebView`;
- `55c0e7698f72e0733b9628bf9a36dc7ac2a7d85c` — moves TLS security
  information to rustls-native types and changes net/devtools serialization;
- `31f660d20c55444d352b83611328f68a2d0c2582` — makes layout image
  loads block the document load event;
- several promise/rooting changes in script, including
  `531762343d4e6789d718c513ebfaeee9ea811a6d` and
  `b5a1f5e6ec6f8685d40cd389802ced7abe4980f6`.

The WebView double-borrow change is directly relevant to Hepta's embedding
surface and must be included in the next pin-refresh review. It is not silently
pulled into the current qualification cycle: changing the selected pin now
would invalidate the reviewed worker `Cargo.lock` and restart locked-build,
real-E2E, reproducibility and SBOM evidence. The current cycle therefore stays
frozen at `5cc5bd32...`; promotion remains blocked until that exact candidate
passes its oracle, and the next refresh must explicitly evaluate these 13
commits rather than treating upstream `main` as automatically compatible.

## 4. Proxy compatibility

The selected Servo source exposes `Preferences.network_http_proxy_uri`,
`network_https_proxy_uri`, and `network_http_no_proxy` through
`ServoBuilder::preferences`. Hepta uses those public preferences to point the
sandboxed worker at a loopback relay. That relay can reach only the private
profile Unix socket; the host-side `GrantScopedEgressBroker` binds the profile network grant by
resolving each admitted origin once, rejecting disallowed address classes and
freezing the exact DNS/IP answer set under the profile grant digest. Later
requests never re-resolve those names and can connect only to the frozen
addresses.

No direct external network namespace is granted to Servo.

## 5. Rust/toolchain compatibility

Both predecessor and candidate Servo workspace manifests declare
`rust-version = "1.88.0"`. The Hepta worker remains Rust 2024 edition with
`rust-version = "1.88"`. Dependency resolution is nevertheless re-generated
for the candidate because 239 upstream commits can change the lock graph.

The generated candidate `Cargo.lock` from the selected dependency graph has
been reviewed and committed. Exact-head qualification must now report
`cargoLockCommitted=true` and bind that lock digest into the retained build
receipt; deployment qualification remains closed until those exact-head checks
succeed.

## 6. Promotion oracle

The candidate pin can replace the predecessor in a qualified deployment only
when one exact source SHA establishes all of the following:

1. `cargo check --locked` and worker unit tests on the candidate graph;
2. complete Browser Node tests;
3. real Bubblewrap/prlimit isolation probe;
4. real Servo `open -> navigate -> observe -> type -> observe -> click ->
   observe -> close` E2E;
5. grant-scoped egress permits the admitted origin, binds HTTPS CONNECT to the
   exact authority/port, and denies ungranted subresource and redirect targets;
6. two simultaneous profiles prove cookie persistence within A and absence of
   A's cookie in B;
7. a revocation update started after final-use entry remains blocked until the
   real Servo worker reaches the dispatch admission boundary;
8. crash recovery remains indeterminate until an exact trusted persisted-effect
   receipt is supplied;
9. a bounded 32-cycle real-worker RSS/FD soak completes without unbounded FD
   growth;
10. two release builds are byte-identical;
11. dynamic-library closure, deterministic SPDX 2.3 SBOM and checksummed build
    receipt are retained;
12. the committed candidate `Cargo.lock` matches the selected dependency graph
    and the exact-head build receipt reports `cargoLockCommitted=true` before
    trusted target deployment qualification.

Target-host soak, cross-profile storage isolation, independent operator
acceptance, promotion and release remain separate evidence/decision gates.
