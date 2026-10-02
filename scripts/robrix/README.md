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
