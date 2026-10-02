# Actual Robrix hosted qualification

The `hepta-robrix-qualification.yml` workflow checks out the immutable PR head
(or dispatch commit), with read-only repository permissions and no persisted Git
credentials. It never publishes a production app, signs a release, imports
upstream administrative workflows, opens a real account, or exercises the paused
Windows registrar/AuthBus lanes.

Two independent Ubuntu jobs produce evidence named for that exact commit:

- Native: execute the actual Console lifecycle/dock/fixture tests, link the real
  Robrix binary, and capture its login and Console widgets under Xvfb at
  1180×760, 520×760 and 800×560.
- Browser: execute the actual application wasm-bindgen tests (all thirteen named
  storage/session/account-epoch tests must appear as passing), link/package via
  the pinned Makepad tool, and capture the real WASM canvas in a fresh context
  for each scene/viewport. External requests during capture fail the test.

Native Rust is 1.96.0. Web Rust is nightly-2026-10-01 with rust-src. The Makepad
build tool is checked out at 493d23a7630f487d29912dd73f2cbb5b639b74ca; a recorded,
fail-closed tool-only patch selects that nightly at its two invocation points
and retains Robrix's `ruma_identifiers_storage="Arc"` cfg in Makepad's replacement
RUSTFLAGS. The actual tool generates the custom target specification, rebuilds
std, applies its own link flags, and packages its JS/resources. It is not
approximated by a generic wasm cargo build. wasm-bindgen CLI/test-runner 0.2.129
is downloaded from the official release and verified by SHA-256.

The artifacts include source commit/tree/app-tree, compiler versions, lock hash,
preserved upstream license hashes, build/test logs, tool patch and package file
hashes. Upstream notices remain unchanged; this is not a refreshed dependency
license audit. Fixture screenshots are not live-account, security, installed
acceptance, or visual-layout acceptance. Inspect the pixels before judging the
layout. Console is read-only and browser Console operations remain unavailable.

Missing, failed, zero, or ignored expected tests cannot count as execution.
There is no `continue-on-error`, fallback renderer or old DOM/egui qualification.
A failed hosted run preserves available diagnostics but does not qualify the
application. The scripts being linted or unit-tested locally does not mean the
hosted builds, browser tests, or screenshots have run.

Generated application packages and fonts are not uploaded by this qualification workflow. Only screenshots, test logs and manifests are retained while the migrated dependency and font redistribution review remains pending. Pinned Makepad also contains automatic same-origin browser error reporting; disable that path before any real-account or production acceptance. CSP and static ABI qualification remain separate from these no-account fixture checks.

## Failed hosted checkpoint and bootstrap diagnostics

Run 37028292769 at source 9456604a2d04a977d4e0919c63ee99937a7ea7fd did
not qualify either rendered platform. Native tests/linking passed, but the old
`xdotool --pid` selector timed out. Pinned Makepad sets WM_CLASS and supports a
`RESOURCE_NAME` instance override; its X11 implementation does not set
_NET_WM_PID. Capture now uses a unique per-launch resource instance, a live
process, and the exact account-free fixture title. Ambiguous matches fail. Each
hosted capture has its own fresh Xvfb session; process and window-tree diagnostics
are retained even on failure. The original 60-second selection bound is unchanged.

The browser receipt stopped at `Loading scripts...`, before test output. The
plain runner's timeout did not expose the underlying JavaScript error. The test
adapter now runs the official wasm-bindgen interactive server and observes its
unchanged generated test page with Playwright, retaining page errors, console,
requests, and actual DOM test results. It keeps the 120-second execution budget
and all thirteen required application tests. It does not mock Makepad imports,
replace application modules, or imply that the plain runner supplies Makepad's
production host bridge. A bootstrap failure remains a failure, with a precise
receipt for the next repair. Test WASM/generated JS stay outside uploaded evidence.

Failed artifact SHA-256 receipts:
- Native artifact 11236788344: 768736086cb55e367aef9c92d61165a871b9d24a6622308a87369655855a3635
- Browser artifact 11236886903: f05d2af69ec0cbc280139eeb24d36b1d1d7c09a06e8b8936934d566a9adb9437

## Confirmed second-run causes and bounded adapter repair

Run 37035006929 at 29f64edab494f9977eda9ede9c12eb83019dfc57 proved the
native process was running; its ICCCM WM_NAME contained a Latin-1 middle dot
(byte B7). Treating all xdotool output as UTF-8 was invalid. The acceptance path
now reads WM_NAME through libX11, uses its declared STRING (ISO-8859-1) or
UTF8_STRING encoding strictly, and rejects unsupported types or invalid UTF-8.
Exact title, unique resource instance, and process liveness remain mandatory.
Only diagnostic text uses escaped bytes. Official x11-utils supplies xwininfo.

Browser page errors established an unresolved bare `env` import in the generated
test glue. `makepad_test_bridge.py` applies the pinned Makepad493 packager's real
`--bindgen` env/instance transformations and constructs the unchanged upstream
`init_env` and `WasmBridge`, bound to the actual WASM instance/memory, before
returning exports to the unchanged test runner. Raw Makepad exports are retained
by the official runner's `WASM_BINDGEN_KEEP_LLD_EXPORTS` option. Both upstream
bridge and packager source bytes are SHA-256 pinned; generated glue shape changes
fail closed and each transformed input/output digest is recorded. No substitute
env functions are supplied. All thirteen original tests and the existing deadline
remain mandatory; the linked full-app Makepad package/canvas gate is still separate.

Second failed artifact SHA-256 receipts:
- Native 11240541155: c1c61519cbb69915aa887cde945691a01f2013c27487e0d56ec05ec5500d2269
- Browser 11239920537: cb24a98b57517da76c8ab974de6efc3ebf15ea21db4486ac4569572bcc26ecf4

## Multi-import generator correction

Run 37042402947 established the actual native pass: nineteen scoped application
and read-only Console tests plus six real-widget screenshots. Preserve that
receipt; subsequent browser adapter work changes no native/application source.
The browser adapter rejected generated glue before executing tests because it
incorrectly required exactly one raw `env` namespace/mapping pair. The pinned
wasm-bindgen generator enumerates raw imports individually, including repeated
module names. Official CLI0.2.129 reproduction with two distinct `env` functions
and a non-env module confirmed two env pairs and preserved the other module.
The guard now requires a bounded, complete, unique alias-to-mapping bijection,
matching the pinned Makepad packager's removal of all raw env entries. It still
rejects missing, unmatched, duplicate aliases or changed initializer syntax.
Actual application glue hashes and bounded import/initializer excerpts are now
recorded before transformation, including on rejection; full generated assets
remain unuploaded. Adapter errors abort the request and are preserved directly.
The earlier failed artifact did not contain generated glue bytes, so the hosted
rerun remains necessary to qualify the full application test harness.

Browser failed artifact11243835391 SHA-256:
b3cbbbad8008ac318ee9816f9a685f31bae8bbbc56f4ef0d72ca068af53189b6.
Native successful artifact11243007240 SHA-256:
274726db5c62a5727417729f134aac157b133171072f4d405375011d3a365bf0.

The existing real login widget is a ScrollYView with vertical scrolling enabled
and its scrollbar intentionally hidden. Clipping in the initial 800×560 capture
alone is not a reachability defect. Qualification additionally captures that
verified fixture window after six wheel-down ticks, then PageDown and six Tabs.
No Enter, credential input, login click, or SSO submission is issued. The input
exercise is recorded separately; lower-control reachability stays pending pixel
review of the before/after images. No application layout change is made.

## Dependency resource packaging compatibility

Run37046992519 passed all13 original browser regressions and linked the release
WASM, but its91-file package omitted every Makepad dependency resource. Serving
that package root was correct; the files were missing. Pinned Makepad's build
scripts write .path markers three parents above OUT_DIR. With the pinned Cargo
layout that is release/build/, while its packager reads release/. The tool-only,
SHA-guarded compatibility helper supports both locations and rejects ambiguous,
relative, or escaping marker/source paths. The permitted source root comes from
exact-revision Cargo metadata, not an arbitrary directory. Missing markers never
count as resolved dependencies; required package assets then fail qualification.

The unchanged packager copies the real dependency JS/CSS/resources. Qualification
checks their bytes against both the compiled dependency checkout and the pinned
Makepad tool checkout (including the original bindgen worker prefix and original
small-font omissions). Relative bootstrap URLs must resolve inside the package;
asset hashes are checked again before serving. Missing resources fail before
browser startup, and runtime HTTP/page failures retain diagnostics immediately.
No full package or font files are uploaded; their paths and hashes are evidence.

Native run37046992519 succeeded. Pixel inspection of its800×560 login before/after
wheel captures confirms all six SSO icons and the signup button become visible.
The keyboard capture is visually unchanged; keyboard-focus reachability is not
claimed. No account or message action was taken and no layout/theme change made.

Run 37054634861 again executed all 13 browser regressions and finished release
compilation, then failed packaging. The pinned Makepad parser treats Cargo tree
section headings as dependency names (`build-dependencies]`). The exact-source
patch now excludes only the actual `[build-dependencies]` / `[dev-dependencies]`
structural rows before that parser. Strict marker names and all existing resource
checks remain. Before the heavy build, a standalone integration test compiles the
actual patched parser with the marker helper and tests the real Makepad v2.0.0
Git dependency row, `makepad-platform.path`, both marker layouts, and rejection
cases. Rejected names receive bounded escaped diagnostics.

Run 37061391402 exposed a second upstream contract issue: shell_env_cap appends
stderr to stdout, so real duplicate-package warnings were parsed as dependencies.
The exact guarded Cargo-tree call now uses Makepad's real shell_env_cap_split;
stderr is retained in logs, nonzero exit and malformed stdout fail explicitly.
It uses the pinned nightly Cargo with --locked --offline. The prebuild integration
executes this actual helper against the full Robrix graph (Git/repeated/build/dev
rows and duplicate-package warnings), rejects the old concatenated output, and
executes a real missing-package error. No dependency graph build is required.
Current native screenshots were inspected at all three sizes; short-login wheel
scrolling reveals the lower controls. Browser app rendering remains pending.

Run 37063912800 created the real release package successfully; the verifier then
incorrectly required raw JS bytes. Pinned cp_brotli minifies bootstrap JS and may
fall back to a raw copy when a destination parent does not yet exist. Validation
now accepts only the exact raw source or exact output of that pinned Rust
minify_js function, extracted under the full upstream source SHA guard. The
bindgen worker prefix is included before transformation. CSS and dependency
resources remain exact raw copies. All six real transformed bootstrap modules
are syntax-checked before the heavy app build; hashes record each transform.
This compatibility preflight is not app execution. Package hashes are saved
before resource validation so a failure preserves byte-level diagnostics.


## Pinned web startup correction

Run 37067849794 passed packaging and all 13 browser regressions, then the real
canvas startup panicked at Makepad web.rs:128: window zero was indexed before
Startup had created any window. The pinned JS contract creates Cx, sends one
ToWasmInit, then binds resize/input; no earlier initialization message is missing.
The explicit patch in patches/makepad-493d23a-web-startup.patch preserves raw
browser geometry for Startup, creates the real scripted window, then applies its
DPI override once. Duplicate init and missing-window startup/resize fail explicitly.
Native event ordering is unchanged. Three new tests run on real Makepad Cx,
WindowHandle, window pool and DPI conversion, in addition to the 19 application
native tests. They cover initial creation, repeated startup, idempotent resize and
no-window errors. Hosted WASM compilation and actual canvas remain mandatory.
Both upstream files are SHA-checked before applying the committed patch, with
before/after hashes and patch bytes retained alongside exact application identity.

Generated HTML's existing reporter is changed to console.error before bootstrap;
it still records panic/exception diagnostics and still fails capture. Automatic
/$report_error transmission is disabled for packages produced by this pipeline.
The dependency web.js reporter delegates to this installed supported override.
This does not authorize live-account qualification or production deployment.
