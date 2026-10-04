# Linux Robrix development candidate

The optional `robrix-preview` feature connects the ordinary `hepta-native`
configured launch to the shared Rust Robrix `App`. It adapts the existing
`HeptaNativeApp`, task controller, readiness witness, runtime and update owner.
It does not create another runtime, credential store or chat writer.

This feature is a development candidate. The default build and installed
packages still use the existing renderer. Configuration errors and retry still
use the existing startup recovery UI. The following Console controls have not
yet been composed into Robrix: operation binding, final-use actions, operation
history/reconciliation, update staging/activation, file selection, notifications,
clipboard and accessibility settings. Chat Send remains disabled without the
separate chat writer capability. This is not completion of the full UI migration.

## Build and test

Use a clean, committed source checkout on Linux with Rust 1.95.0 and the native
system libraries used by the lifecycle workflow. The build requires at least
3 GiB free before compilation and may require more on a cold runner. Run:

```sh
python3 apps/hepta-native/tools/build-robrix-native.py build-preview \
  --source-root "$PWD" --out /absolute/new-preview-output \
  --download-font-source
```

The wrapper resolves the locked native dependency graph, verifies Makepad
revision `337566c8b25d47f7e4fff6a202157b65bf183330`, and creates an independent
source archive checkout. Its platform overlay admits only loaded embedded
resource bytes and publishes the X11 process ID before mapping the window for
process-scoped diagnostics. It never patches the canonical checkout or Cargo cache. Its
generated lock differs only in the platform package's Git-to-local source.
The fixed 28 assets and original notices are checked by size and SHA-256 before
compilation. Asset identities are regenerated from the generated checkout's
manifest paths. Keep `native-preview-build-input.json` and the asset input
records with build evidence.

For an already downloaded original source archive, replace
`--download-font-source` with `--liberation-source /absolute/archive.tar.gz`.
`--offline` disables Cargo network resolution. `prepare-preview` prepares the
same inputs without compiling. `test-preview` runs the repository's `just test`
entry point against the generated overlay and includes the resource conflict,
missing-resource, source export and retained-owner adapter tests. Each prepare,
build or test invocation requires a fresh output directory.

The ordinary source workflow's all-feature Clippy check uses the canonical SDK
and separately verified compile-time assets. It is a source/type check; the
memory-only resource tests and real renderer require the generated overlay.
A passing source job cannot substitute for the Linux preview runtime job.

## Run and observe

Run the generated `hepta-native` binary with the existing absolute `--config`
argument. It uses the same endpoint verification, credentials, private state,
startup recorder and CLI identity. Copying that binary outside its checkout
must not change resource bytes, even if conflicting same-named files exist.
An absent embedded resource fails closed. The explicit `--font-file` override
still reads a bounded local font; the preview's default font set is embedded.

`HEPTA_NATIVE_PREVIEW_OBSERVE=1` enables bounded diagnostic JSON on stderr,
prefixed `HEPTA_NATIVE_PREVIEW `. The events report bounded readiness rejection
codes (only when the reason changes), rejected glyph geometry without text,
the visible status draw list, a later
callback, close requests, confirmed owner drain and GUI-loop
return. They grant no authority. They are not a GPU presentation ACK. External
runtime validation must also retain the real window image, visible status,
startup record, both OS and caption close flows, and successful process exit.
X11 uses the window manager's decorations, so it cannot observe the separate
self-drawn caption action. That path requires a real Wayland client-side
decoration session. A failed startup retains a PID-scoped diagnostic window
image when possible.
Its separate receipt always marks it unqualified; capture failure never replaces
the readiness failure or skips cleanup. It is not successful GUI evidence.
A missing caption rectangle on X11 is not evidence that this separate path passed.
The `gui_loop_returned` event occurs before the unchanged update-helper tail.
The current UI has no update activation control, so an ordinary close can only
qualify the tail's inactive branch. Positive update activation remains untested.

Readiness keeps the exact six-axis view identity, the actual nontruncated
layout's full expected glyph count, an attached and unclipped text draw list,
the later GUI callback, and the existing supervised
owner recheck before writing startup or update readiness. Window-manager close,
caption close and QuitRequested all use the original shutdown owner. The
preview keeps the window alive until that owner confirms close and all workers
are idle. Retry does not reset a deadline or enable an update.
Geometry, focus and lifecycle changes discard the previous draw witness.
Clipped or unsupported text retries at the retained 250 ms owner poll cadence;
it never produces a continuous NextFrame redraw loop. SLUG and separate SSAA
text passes do not qualify this development witness. The status widget reserves
an internal four-pixel inset for raster atlas overhang. Its CPU layout snapshot
replays measured first-glyph bounds at narrow and wide sizes; this is layout
coverage, not a substitute for the actual native raster and screenshot gate.

The Windows SDK process exit prevents preservation of the post-loop helper
contract. Windows and macOS Robrix entry points are not enabled by this feature.
Real native renderer, installed package, accessibility and cross-platform
acceptance must be established separately before any default-entry migration.

## Embedded source and notices

The executable provides the original resource notices and unmodified
Liberation 1.04.93.devel corresponding source without opening a GUI, runtime,
credential store or state directory:

```sh
hepta-native --font-notices
hepta-native --font-source liberation > liberation-fonts-1.04.93.devel.src.tar.gz
```

The source archive is 2,255,959 bytes with SHA-256
`fe3ea5f7a2d3bdea8b8f0d82cdc6c07d14ace67c6e06d7aa33b83fd9e640adae`.
`resources/NATIVE-ASSETS.json` binds every asset and original notice. The
included licenses differ by resource; this is not an all-MIT resource bundle.
Build inputs and CI runtime evidence are not permission to publish a package.
