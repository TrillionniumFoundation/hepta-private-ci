# Rust UI integration on current Hepta main

This change selects the existing Robrix-derived application and its read-only
gateway boundary onto current Hepta main. Chat and Console use the shared
Rust/Makepad renderer. An absent production owner remains `not_attached`; fixtures
cannot establish an owner, principal, signer or device-control permission.

## Frozen inputs

| Input | Commit | Tree |
| --- | --- | --- |
| Main base | `f8c9419df6ddeb36ff8b522a50219981fb8d9345` | `15c9d6ea07bf3832de82825a6cc1e8c958dd3d45` |
| Selected UI/font source, [#2884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2884) | `ec1ab573a68d383cca4b42826a59e2e2a5c34882` | `0d5d43ec34c05eecc58657819724046bb49756bc` |

The selected source is stacked on #1423 and #1418. This main integration selects
paths from its tree; it does not merge that older branch history. The historical
`PORT_SOURCE.json` remains unchanged as the earlier import record. Robrix and
Makepad upstream commits, original blobs, transformed blobs and licenses remain
in `rust/robrix-ui/UPSTREAM.json` and the owned SDK patch manifests.

## Selected file boundary

| Paths selected from the frozen UI source | Purpose |
| --- | --- |
| `apps/hepta-control-ui/**` | Shared Rust workspace, renderer, resources, owned package tools, browser regressions and provenance; 197 tracked source files before main adaptations |
| `codex-rs/hepta-native-gateway/Cargo.toml` | Existing workspace serde, SHA-256 and Unix descriptor capabilities needed by bounded status and verified assets |
| `codex-rs/hepta-native-gateway/src/lib.rs` | Explicit UI bundle options and read-only owner composition, retaining the legacy entry |
| `codex-rs/hepta-native-gateway/src/http_transport.rs` | Bounded response streaming and accepted-byte accounting |
| `codex-rs/hepta-native-gateway/src/http_origin.rs`, `src/http_origin_tests.rs` | Loopback Host/Origin boundary |
| `codex-rs/hepta-native-gateway/src/owner_status.rs`, `src/owner_status_tests.rs` | Weak read-only owner projection and bounded asynchronous inspection |
| `codex-rs/hepta-native-gateway/src/ui_bundle.rs`, `src/ui_bundle_reader.rs`, `src/ui_bundle_tests.rs` | Immutable manifest selection, path/size/digest validation and actual HTTP tests |
| `codex-rs/hepta-native-gateway/src/organ_request_tests.rs` | Existing gateway tests adapted to optional presentation state |
| `codex-rs/hepta-native-gateway/examples/ui_product_preview.rs` | Real gateway executable used by browser CI |
| `apps/hepta-native/resources/NATIVE-ASSETS.json`, `resources/notices/Noto-Sans-CJK-2.004-OFL.txt` | Existing shared font contract inputs; no product native host is imported |
| `.github/workflows/ui-product-foundation.yml`, `scripts/test_ui_product_foundation_ci.py` | UI-owned source/base-merge execution and strict dependency-trigger regression |
| `scripts/hepta_ci_module_paths.py`, `scripts/test_hepta_ci_module_path_scopes.py` | Bounded lexical proof and negative controls for literal module paths required by the gateway dependency closure |
| `docs/modules/ui.control/TECHNICAL.md` | Current implementation and execution boundaries |

The main root `Cargo.lock` receives only the three gateway dependency edges to
already-locked `rustix 1.1.4`, `serde 1.0.228` and `sha2 0.10.9`. No package
version or external checksum is selected from the old backend lock. Cargo's
locked build and the canonical Bazel lock generation/check remain required.

Fleet, Memory, Supervisor, production initializer, issuer/journal replacements,
global CI workflows, root Rust toolchain changes and the old backend Cargo.lock
are outside this selection. The canonical dependency helper receives only the
module-path scan adaptation described below. The synthetic merge action and
other canonical CI helpers retain their main implementations.

## Canonical adaptations

The gateway build reads the exact release channel in
`codex-rs/rust-toolchain.toml`, rejects moving aliases, invokes that toolchain and
checks the compiler reports the selected release. Its build receipt hashes the
same tracked toolchain manifest before and after compilation. The backend now pins Rust1.96.0 for Rama0.3 compatibility; the main import base
used Rust1.95.0. Standalone UI checks still select Rust1.95.0, and Makepad retains its separately verified
`nightly-2026-10-02` compiler. No host or Desktop OS pin changes.

`scripts/hepta_ci_dependencies.py` on main provides the existing owners, edges,
embedded inputs and opaque-input fields used by the UI closure regression.
Its prior whole-file test treated an inline module anywhere in a file as making
every `#[path]` in that file ambiguous. This rejected three existing gateway
dependencies even though their literal path attributes were file-level siblings
of the inline tests. The selected `hepta_ci_module_paths.py` performs a bounded
lexical scan before the existing exact-tree path resolution. It handles comments,
strings and delimiters, while actual nested paths, conditional or unknown module
attributes, macro tokens, unsupported syntax and exceeded bounds remain opaque.
Computed includes, build scripts and old-graph unknown inputs retain their
original conservative selection. Both UI lanes execute the selected scope tests;
the strict dependency-input coverage assertion remains unchanged.

The lexer and its scope tests are selected byte-for-byte from the frozen UI
source listed above. The source stack's Git-object reader and the remainder of
its dependency helper are not imported.

`scripts/hepta_ci_exec.py` supplies the canonical source/base/tested identity
receipts and retains its main implementation.

## Current product source map

| Responsibility | Implementation | Real verification entry |
| --- | --- | --- |
| Chat navigation, composer and Console tab | `rust/robrix-ui/src/app.rs`, `src/robrix/` and `src/presentation.rs` | Core/presentation nextest suite; `e2e/robrix-host.spec.mjs`, `e2e/robrix-sidebar.spec.mjs` |
| Bounded chat state and owner-facing presentation | `rust/core/src/chat_owner.rs`, `src/chat_timeline.rs`, `src/owner_view.rs` | Core owner/projection tests; explicitly labelled fixture rendering |
| Explicit Console reads and cancellation | `rust/robrix-ui/src/runtime_status.rs` | `e2e/robrix-product-status.spec.mjs` against the actual gateway executable |
| Existing-owner observation | Gateway `OwnerStatusProvider::from_weak` and `run_native_gateway_with_owner_status` | Gateway owner-status nextest tests; absent-owner real browser cases |
| Verified static assets and strict delivery | Gateway `UiBundle::load`, `ui_bundle_reader` and `http_transport` | Real Rust socket tests, browser response completion and manifest-byte checks |
| Font ownership and actual use | Owned Makepad font/network patches and strict browser audit | Same-version browser transport controls; optional Rust adoption/parse/natural-glyph diagnostics; normal screenshot checks |
| Shared native presentation seam | `rust/robrix-ui/src/native_host/` | Retained interface only; this import does not establish a product native owner or installation |

Without `--ui-bundle` plus `--ui-manifest-sha256`, startup continues to require
`HeptaRuntime::open_existing`. With both options and a verified manifest, the UI
may start while legacy state is unavailable. Legacy health/runtime endpoints
then return 503, and the independent owner projection returns `not_attached`.
The default CLI does not create an owner as a side effect. The optional weak
adapter only inspects an existing higher-level owner; it cannot reopen a store
or grant authority. Refresh is explicit, bounded and cancelled on navigation,
background or epoch change. Send and Console mutations remain disabled.

## Evidence boundary and remaining integration

The frozen font source has a successful real Rust/Makepad source/base UI run,
[39201727153](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39201727153).
That run records real gateway font completion and browser pixels for its exact
tree; it does not qualify this new main integration. This branch needs its own
clean source and base-merge Rust, locked backend, resource and browser execution.
The optional diagnostic recorder is disabled during normal product rendering.

Production principal/signing/Agentd composition, authority-bound chat submission,
device operation dispatch through the existing owners, installed native packages,
physical IME/touch and assistive-technology acceptance remain distinct obligations.
No imported fixture or historical qualification record closes them.

## Review candidate validation

The default browser matrix now uses the same one-worker software-GL scheduling
as the populated fixture matrix. All six default cases, three engines, deadlines,
pixels and semantic assertions remain required. The next exact source and merge
lanes must determine whether the observed Firefox WebGL2 startup failure recurs.

A separate temporary CI job invokes the original `just bazel-lock-update` and
`scripts/check-module-bazel-lock.sh` using the existing pinned Bazel setup. It
retains the actual generated lock, source identities, inputs, raw generation
exit and complete diff for review. The actual generation and original drift
check succeeded for source `85c03628f108290a02ae1ee48a6b5711352cbc38` in
[run 39212179711](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39212179711),
job `117927821291`. The generated lock has SHA-256
`94f6143d2e1f68d59fa9cbfd223a676a8dddf61fe8ec92b5219ecd0ac67f29d0`,
identical to the input lock; the lock diff, complete tracked diff and tracked
status are all empty. No lock update is needed for those exact Cargo inputs.
The ordinary source-bound UI job and repository blocking checks remain required
for the subsequent source candidate.
