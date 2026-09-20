# browser.servo Servo pin audit

**Historical predecessor:** `84bcc9ac701874fa9819e5cdee06356b961d736c` (2026-09-04)  
**Immediate predecessor candidate:** `5cc5bd32d02619acdec5736055515e38c5840ce1` (2026-09-18)  
**Selected qualification candidate:** `b5a1f5e6ec6f8685d40cd389802ced7abe4980f6` (2026-09-19)  
**Candidate state:** source-selected; b5a1 dependency lock generation/review/commit pending; exact-head locked qualification not yet established

## 1. Current decision

The earlier 2026-09-20 decision to keep `5cc5bd32...` frozen for the current
qualification cycle is **superseded** by the repository's later exact-source
selection of `b5a1f5e6ec6f8685d40cd389802ced7abe4980f6`.

The change is deliberate rather than an automatic upstream update. The
post-`5cc5...` window contains `07777aaa24af690a52648f1cd7e575659310cee8`,
which hardens access to `Servo` from `WebView` against double-borrow hazards
and changes the same public `WebView::load()` surface used by the Hepta worker.
Leaving that change outside the selected candidate would require an explicit
compatibility justification; the current source instead absorbs it and
restarts the lock/build/E2E/SBOM qualification chain.

The committed worker `Cargo.lock` is still predecessor evidence. It does not
contain the selected b5a1 Servo revision and must not be relabelled or patched
by hand. The first exact-head worker run must generate the b5a1 candidate lock
from the selected manifest, retain those exact bytes as evidence, and identify
them as `generated-candidate`. After review, those exact bytes must be
committed. Only a later exact-head run that reports
`cargoLockCommitted=true` may establish locked compile/test, real-E2E,
reproducibility and SBOM evidence for the selected candidate.

No source selection, generated lock, CI definition or author statement is a
qualified worker artifact, target-host receipt, operator acceptance, promotion
or release decision.

## 2. Relevant upstream delta

GitHub comparison recorded b5a1 as 13 commits ahead of the immediate
`5cc5bd32...` candidate and zero commits behind. Browser-relevant changes in
that window include:

- `07777aaa24af690a52648f1cd7e575659310cee8` — avoids double-borrow
  hazards when accessing `Servo` from `WebView`;
- `55c0e7698f72e0733b9628bf9a36dc7ac2a7d85c` — moves TLS security
  information to rustls-native types and changes net/devtools serialization;
- `31f660d20c55444d352b83611328f68a2d0c2582` — makes layout image loads
  participate in document load completion;
- `531762343d4e6789d718c513ebfaeee9ea811a6d` and related script/rooting
  changes;
- `b5a1f5e6ec6f8685d40cd389802ced7abe4980f6` — the selected upstream
  main identity for this qualification cycle.

The older `84bcc9ac...` -> `5cc5bd32...` jump was itself a broad
requalification window touching network loading/cache/fetch, pipeline and
script/document/input paths. Those historical changes remain relevant
provenance, but `5cc5...` is no longer the current qualification candidate.

Because the combined history overlaps navigation, proxy routing, TLS/network
types, semantic observation, form/input behavior and embedding lifecycle,
compile success alone is not a promotion oracle.

### 2.1 Post-selection upstream review (2026-09-21)

After b5a1 was selected, Servo `main` advanced to
`e6a6850437c659c07e65402a97049a09efb23a0e`, 10 commits ahead of b5a1 and
zero commits behind. The reviewed window includes:

- `08ac5f466f90e1c38599f6861914843147659b44` — `surfman@0.14.0`;
- `04dcdfaf9a2b65dcf4dc0362097ab852a49449bc` — rooted/traced
  EventListener/EventHandler callback conversion;
- `626c51bc0083d81132c25d55e3dc78c212ad37b3` — RoutedPromise/WebGPU
  listener relocation;
- `addf39ddea3b4a75775e09ccf123bf0c623a5907` and
  `d29763b95954edd0e9592529d2ddc54cbe16197d` — safer JS/DOM conversion
  paths;
- `e6a6850437c659c07e65402a97049a09efb23a0e` — further mechanical
  `reflect_dom_object` migration;
- Cargo manifest/lock updates plus WPT metadata and script-level changes.

The compare does not show another direct `WebView::load()` fix, a change to
the proxy-preference API used by Hepta, or a new net connector/HTTP loader
change comparable to the already-absorbed b5a1 window. The selected pin
therefore remains b5a1 for this qualification cycle instead of chasing
upstream during lock generation. This is not a compatibility claim for
`e6a6850...`: the 10-commit window is recorded as the next pin-refresh
review set, with the `surfman` dependency and script/callback changes
requiring compile/behavioral requalification if adopted.

## 3. Hepta embedding relevance

The worker owns one Servo / one WebView per profile generation and directly
uses public embedding APIs including `WebView::load()`, JavaScript evaluation,
load status, navigation callbacks and proxy preferences. The b5a1 selection
therefore requires the same real-worker behavioral qualification as any other
embedding-affecting upstream advance.

The current Hepta click/type/focus implementation uses fixed worker-owned
JavaScript rather than WebDriver input events. Upstream WebDriver/input fixes
are not treated as proof that Hepta had the same bug; they are treated as
evidence that adjacent lifecycle code changed and must be covered by the exact
candidate E2E.

## 4. Proxy and public HTTPS compatibility

The selected Servo source exposes
`Preferences.network_http_proxy_uri`, `network_https_proxy_uri`, and
`network_http_no_proxy` through `ServoBuilder::preferences`. Hepta points
those preferences at a loopback-only relay inside the sandbox. The relay can
reach only the profile-private Unix socket, and the host
`GrantScopedEgressBroker`:

- resolves each admitted origin once for the profile network-grant generation;
- rejects private/special destinations in production;
- freezes the exact DNS/IP answer set under the grant digest;
- never re-resolves per request;
- binds HTTP to the exact origin;
- binds HTTPS CONNECT to the exact authority/port and validates bounded
  ClientHello SNI before opening an upstream TCP connection.

The Servo worker has no direct external network namespace.

Trusted target qualification no longer treats a host-only broker TLS client as
sufficient public-network evidence. It must drive the exact built worker inside
Bubblewrap through a real `https://example.com` navigation, observe the
resulting granted public origin through Servo, retain the broker binding
evidence, and separately prove ungranted/profile-scope escape denial. Servo
still performs end-to-end certificate validation inside the CONNECT tunnel.

## 5. Rust/toolchain and lock state

The selected Servo workspace and Hepta worker are qualified with the pinned
Rust 1.88 toolchain declared by the worker workflow. Advancing from 5cc5 to b5a1
changes the dependency graph, so the old lock cannot establish b5a1 inputs.

Current lock ceremony:

1. exact-head worker workflow sees that the committed lock does not contain
   b5a1;
2. it preserves the predecessor lock as provenance, removes it from the build
   input, and runs `cargo generate-lockfile` for the selected manifest;
3. it records the generated lock bytes/digest in the worker evidence artifact;
4. a reviewer inspects those exact bytes and commits them without regeneration
   or substitution;
5. a fresh exact-head worker run must recognize the lock as `committed`,
   use `--locked` throughout, and emit `cargoLockCommitted=true` in the
   build receipt.

Until step 5 is terminal-success, the b5a1 artifact remains qualification
pending.

## 6. Promotion oracle

The selected b5a1 pin can enter a qualified deployment only when one exact
source/artifact chain establishes all applicable items below:

1. the reviewed b5a1 `Cargo.lock` is committed and the build receipt reports
   `cargoLockCommitted=true`;
2. `cargo check --locked` and worker unit tests pass on the selected graph;
3. complete Browser Node tests and syntax checks pass;
4. the real Bubblewrap/prlimit isolation probe passes on the retained host;
5. real Servo
   `open -> navigate -> observe -> type -> observe -> click -> observe -> close`
   E2E passes;
6. grant-scoped egress permits only the admitted origin and denies ungranted
   subresource/redirect/profile-scope escape;
7. two simultaneous profiles prove cookie and localStorage separation and
   independent HTTP cache state;
8. a revocation update cannot advance through the same FinalUseAuthority fence
   before the real worker dispatch/rejection boundary;
9. post-process-loss terminalization accepts only an Ed25519-authenticated
   receipt from the configured observer and rejects stale observer generation,
   stale observation time, frontier substitution and excessive future time;
10. profile expiry and explicit owner close both contain hostile background
    fetch/timer/navigation;
11. the worker namespace exposes no non-loopback listener;
12. trusted Linux target qualification proves real public DNS and
    certificate-validating HTTPS through the actual sandboxed Servo
    worker/private relay/production broker;
13. a bounded 32-cycle worker soak remains within the selected RSS/FD growth
    ceilings;
14. two independent release builds are byte-identical;
15. dynamic-library closure, deterministic SPDX 2.3 SBOM and checksum-bound
    build/target receipts are retained.

Target evidence must bind the exact source SHA/tree, reviewed worker digest,
Cargo.lock, kernel and launcher identities. Independent remote-business
terminal receipts, operator acceptance, activation, promotion and release
remain separate authority/evidence gates.

## 7. Capability and platform boundary

Current admitted Browser effects are `navigate`, `click`, `type`,
`focus`, `scroll` and `wait`. `credential`, `upload` and
`download` are explicitly out of scope for this release and fail before
final-use authority or worker admission; a future release must separately
version and qualify their secret/file broker and terminal-observer semantics.

The current product target is Linux. macOS/Windows require equivalent
filesystem/network/process/resource isolation implementations and exact-host
qualification before entering supported scope.
